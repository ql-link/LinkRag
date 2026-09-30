#!/usr/bin/env bash
# 在云服务器上构建并发布生产前端（linkrag-web）。
# Jenkins 在 RAG 发布成功后调用：上传同一份源码包，本脚本在 node 容器中执行
# npm ci / typecheck / test / build，打包 Nginx 镜像，安装站点配置并切换容器。
# 任一步失败都会还原旧站点配置与旧镜像，保证 80/443 入口（含 LinkResume）不中断。
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <build-number> <commit-short> <source-archive>" >&2
  exit 2
fi

build_number="$1"
commit_short="$2"
source_archive="$3"

if [[ ! "${build_number}" =~ ^[0-9]+$ ]]; then
  echo "build-number must be numeric" >&2
  exit 3
fi
if [[ ! "${commit_short}" =~ ^[0-9a-f]{7,40}$ ]]; then
  echo "commit-short must be a hexadecimal Git revision" >&2
  exit 4
fi
if [[ ! -f "${source_archive}" ]]; then
  echo "source archive does not exist: ${source_archive}" >&2
  exit 5
fi

image="linkrag-web"
tag="${commit_short}"
container="linkrag-web"
web_root="/opt/tolink/LinkRag-Web"
nginx_dir="${web_root}/nginx"
site_conf="${nginx_dir}/default.conf"
npm_cache="${web_root}/npm-cache"
work_root="${web_root}/jenkins/workspaces"
build_dir="${work_root}/web-${build_number}"
backup_root="${web_root}/backups/production-deploy"
compose_file="/opt/tolink/toLink-Rag/deploy/docker-compose.yml"
compose_project="linkrag-production"
docker_network="tolink-app-net"
cutover_started="false"

cleanup() {
  if [[ "${build_dir}" == "${work_root}/web-${build_number}" ]]; then
    rm -rf -- "${build_dir}"
  fi
}

finish() {
  exit_status=$?
  if [[ "${exit_status}" -ne 0 && "${cutover_started}" == "true" ]] && \
    declare -F rollback_old_site >/dev/null; then
    rollback_old_site || true
  fi
  cleanup
  return "${exit_status}"
}
trap finish EXIT

docker network inspect "${docker_network}" >/dev/null
for required in "${nginx_dir}/linkresume.conf" /opt/tolink/letsencrypt/conf /opt/tolink/letsencrypt/www; do
  if [[ ! -e "${required}" ]]; then
    echo "Missing production site dependency: ${required}" >&2
    exit 10
  fi
done
if [[ ! -f "${compose_file}" ]]; then
  echo "Missing production compose file (deploy RAG first): ${compose_file}" >&2
  exit 11
fi

rm -rf -- "${build_dir}"
install -d -m 0700 "${work_root}" "${npm_cache}" "${backup_root}"
mkdir -p "${build_dir}"
tar -xzf "${source_archive}" -C "${build_dir}"

candidate_conf="${build_dir}/deploy/cloud-server/nginx/linkrag.conf"
if [[ ! -f "${build_dir}/web/package.json" || ! -f "${candidate_conf}" ]]; then
  echo "Source archive is missing web/ or the production site config" >&2
  exit 12
fi

docker run --rm -u 0:0 \
  -v "${build_dir}/web:/workspace" \
  -v "${npm_cache}:/root/.npm" \
  -w /workspace node:20-alpine sh -lc '
    set -eu
    for attempt in 1 2 3; do
      if HUSKY=0 npm ci --prefer-offline --no-audit \
        --fetch-retries=5 --fetch-retry-mintimeout=1000 \
        --fetch-retry-maxtimeout=20000 --fetch-timeout=60000 \
        --registry=https://registry.npmmirror.com; then
        break
      fi
      if [ "$attempt" -eq 3 ]; then
        echo "npm ci failed after $attempt attempts" >&2
        exit 1
      fi
      echo "npm ci attempt $attempt failed; retrying with cache" >&2
      sleep 3
    done
    npm run typecheck
    npm run test
    VITE_GITHUB_URL=https://github.com/ql-link/LinkRag npm run build
  '

DOCKER_BUILDKIT=1 docker build \
  --label "org.opencontainers.image.revision=${commit_short}" \
  -t "${image}:${tag}" \
  "${build_dir}/web"

# 用新镜像 + 新配置先做一次语法检查（-t 会解析证书与上游主机名，因此接入生产网络）。
docker run --rm --network "${docker_network}" \
  -v "${candidate_conf}:/etc/nginx/conf.d/default.conf:ro" \
  -v "${nginx_dir}/linkresume.conf:/etc/nginx/conf.d/linkresume.conf:ro" \
  -v /opt/tolink/letsencrypt/www:/var/www/certbot:ro \
  -v /opt/tolink/letsencrypt/conf:/etc/letsencrypt:ro \
  "${image}:${tag}" nginx -t

backup_dir="${backup_root}/build-${build_number}"
mkdir -m 0700 -p "${backup_dir}"
if [[ -f "${site_conf}" ]]; then
  cp -p "${site_conf}" "${backup_dir}/default.conf"
fi
old_image="$(docker inspect --format='{{.Config.Image}}' "${container}" 2>/dev/null || true)"
printf '%s\n' "${old_image}" >"${backup_dir}/previous-image.txt"

rollback_old_site() {
  if [[ -f "${backup_dir}/default.conf" ]]; then
    install -m 0644 "${backup_dir}/default.conf" "${site_conf}"
  fi
  if [[ "${old_image}" != "${image}":* ]]; then
    echo "Automatic web rollback is unavailable" >&2
    return 1
  fi
  WEB_TAG="${old_image#"${image}":}" \
    docker compose -p "${compose_project}" -f "${compose_file}" \
      up -d --no-deps --force-recreate linkrag-web
  echo "Previous production site restored: ${old_image}"
}

install -m 0644 "${candidate_conf}" "${site_conf}"
cutover_started="true"

WEB_TAG="${tag}" \
  docker compose -p "${compose_project}" -f "${compose_file}" \
    up -d --no-deps --force-recreate linkrag-web

for _ in $(seq 1 30); do
  running_image="$(docker inspect --format='{{.Config.Image}}' "${container}" 2>/dev/null || true)"
  running_status="$(docker inspect --format='{{.State.Status}}' "${container}" 2>/dev/null || true)"
  if [[ "${running_image}" == "${image}:${tag}" && "${running_status}" == "running" ]] && \
    curl -fsSk --resolve linkrag.cn:443:127.0.0.1 https://linkrag.cn/ >/dev/null && \
    curl -fsSk --resolve linkrag.cn:443:127.0.0.1 "https://linkrag.cn/api/v1/blog/posts?page=1&pageSize=1" >/dev/null; then
    echo "Production web deployed: ${image}:${tag}"
    docker tag "${image}:${tag}" "${image}:latest"
    docker image prune -f >/dev/null
    cutover_started="false"
    exit 0
  fi
  sleep 2
done

docker logs --tail=100 "${container}" || true
echo "Production web health check timed out; restoring previous site" >&2
exit 17
