#!/usr/bin/env bash
set -euo pipefail

component=${1:-}
build_number=${2:-}
dev_root=${DEV_ROOT:-/opt/tolink/dev}
jenkins_root="$dev_root/jenkins"
workspace_root="$jenkins_root/workspaces"
lock_file="$jenkins_root/build.lock"

if [[ ! "$build_number" =~ ^[0-9]+$ ]]; then
  echo "build number must be numeric" >&2
  exit 2
fi

case "$component" in
  rag)
    github_repo=LinkRag
    workspace_name=toLink-Rag
    image_name=tolink-rag
    tag_key=RAG_TAG
    compose_service=tolink-rag
    ;;
  web)
    # 前端与后端同仓：拉取 LinkRag 仓库，在 web/ 子目录构建
    github_repo=LinkRag
    workspace_name=LinkRag-Web
    image_name=linkrag-web
    tag_key=WEB_TAG
    compose_service=linkrag-web
    ;;
  *)
    echo "usage: $0 {rag|web} BUILD_NUMBER" >&2
    exit 2
    ;;
esac

install -d -m 700 "$jenkins_root" "$workspace_root"
exec 9>"$lock_file"
flock 9

source_dir="$workspace_root/$workspace_name"
next_dir="$workspace_root/.${workspace_name}.next"
archive=$(mktemp "$jenkins_root/${workspace_name}.XXXXXX.tgz")
trap 'rm -f "$archive"; rm -rf "$next_dir"' EXIT
source_ref_file="$dev_root/source-refs/$component"
source_ref=dev
if [[ -f "$source_ref_file" ]]; then
  source_ref=$(tr -d '[:space:]' <"$source_ref_file")
fi
if [[ ! "$source_ref" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "invalid source ref for $component: $source_ref" >&2
  exit 2
fi
source_ref_slug=${source_ref//\//-}
incoming_archive="$jenkins_root/incoming/${workspace_name}-${source_ref_slug}.tgz"

echo "[$component] fetch ql-link/$github_repo $source_ref on Primary"
rm -rf "$next_dir"
mkdir -p "$next_dir"
archive_url="https://codeload.github.com/ql-link/${github_repo}/tar.gz/refs/heads/${source_ref}"
if [[ -s "$incoming_archive" ]]; then
  echo "[$component] use preloaded dev archive"
  mv "$incoming_archive" "$archive"
else
  if ! curl -fsSL --retry 3 --retry-all-errors --retry-delay 3 \
    --connect-timeout 15 --speed-time 30 --speed-limit 1024 --max-time 300 \
    "https://gh-proxy.com/${archive_url}" -o "$archive"; then
    echo "[$component] GitHub proxy unavailable, fallback to codeload"
    curl -fsSL --retry 8 --retry-all-errors --retry-delay 5 \
      --connect-timeout 15 --speed-time 30 --speed-limit 1024 --max-time 1200 \
      "$archive_url" -o "$archive"
  fi
fi
tar -tzf "$archive" >/dev/null
tar -xzf "$archive" --strip-components=1 -C "$next_dir"
rm -f "$archive"
rm -rf "$source_dir"
mv "$next_dir" "$source_dir"

# 可选的构建代理：仅在服务器存在 /opt/tolink/build-proxy.env（BUILD_PROXY=http://host:port）时启用，
# 且只作用于本次 docker build / npm ci，不修改系统或 Docker daemon 代理。
# 代理端（Clash rule 模式）负责只转发境外流量；NO_PROXY 再显式排除国内镜像与内网地址。
build_proxy_args=()
build_proxy_env=()
if [[ -f /opt/tolink/build-proxy.env ]]; then
  BUILD_PROXY=$(sed -n 's/^BUILD_PROXY=//p' /opt/tolink/build-proxy.env | tail -1)
  if [[ "${BUILD_PROXY}" =~ ^http://[A-Za-z0-9._-]+:[0-9]+$ ]]; then
    build_no_proxy="localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,.aliyun.com,.aliyuncs.com,.npmmirror.com,.tuna.tsinghua.edu.cn,.cn"
    for name in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy; do
      build_proxy_args+=(--build-arg "${name}=${BUILD_PROXY}")
      build_proxy_env+=(-e "${name}=${BUILD_PROXY}")
    done
    for name in NO_PROXY no_proxy; do
      build_proxy_args+=(--build-arg "${name}=${build_no_proxy}")
      build_proxy_env+=(-e "${name}=${build_no_proxy}")
    done
    echo "build proxy enabled for this build: ${BUILD_PROXY}"
  else
    echo "ignore invalid BUILD_PROXY in /opt/tolink/build-proxy.env" >&2
  fi
fi

image_tag="dev-b${build_number}"
echo "[$component] build $image_name:$image_tag on Primary"
case "$component" in
  rag)
    DOCKER_BUILDKIT=1 docker build ${build_proxy_args[@]+"${build_proxy_args[@]}"} -t "$image_name:$image_tag" "$source_dir"
    ;;
  web)
    install -d -m 700 "$jenkins_root/npm-cache"
    docker run --rm -u 0:0 ${build_proxy_env[@]+"${build_proxy_env[@]}"} \
      -v "$source_dir/web:/workspace" \
      -v "$jenkins_root/npm-cache:/root/.npm" \
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
    docker build ${build_proxy_args[@]+"${build_proxy_args[@]}"} -t "$image_name:$image_tag" "$source_dir/web"
    ;;
esac

update_tag() {
  local key=$1
  local value=$2
  local env_file="$dev_root/.env.dev"
  if grep -q "^${key}=" "$env_file"; then
    sed -i "s/^${key}=.*/${key}=${value}/" "$env_file"
  else
    printf '%s=%s\n' "$key" "$value" >>"$env_file"
  fi
}

if [[ "$component" == rag ]]; then
  config_source="$source_dir/deploy/dev-server"
  for name in loki-config.yml promtail-config.yml nginx.conf \
    configure-dev-env.sh \
    generate-dev-llm-migration-inputs.py; do
    install -m 600 "$config_source/$name" "$dev_root/$name"
  done

  # RabbitMQ 切换完成后，旧 dev 分支的 Kafka Compose 不得覆盖服务器现状。
  # 待迁移提交合入 dev 后，符合条件的构建会恢复正常同步这些部署入口。
  if grep -q '^  rabbitmq:' "$config_source/docker-compose.yml" \
    && ! grep -q '^  kafka:' "$config_source/docker-compose.yml"; then
    install -m 600 "$config_source/docker-compose.yml" "$dev_root/docker-compose.yml"
    install -m 600 "$config_source/build-component-on-primary.sh" \
      "$dev_root/build-component-on-primary.sh"
    install -m 0644 "$config_source/rabbitmq.conf" "$dev_root/rabbitmq.conf"
  else
    echo "[$component] preserve deployed RabbitMQ Compose until migration reaches dev"
  fi
  chmod 700 "$dev_root/configure-dev-env.sh" "$dev_root/build-component-on-primary.sh"
  install -d -m 700 "$dev_root/config/rag"
  install -m 0644 "$source_dir/.env.development" "$dev_root/config/rag/.env.development"
  "$dev_root/configure-dev-env.sh"
fi

update_tag "$tag_key" "$image_tag"

cd "$dev_root"
case "$component" in
  rag)
    required_dev_config=${RAG_DEV_ENV_FILE:-$dev_root/config/rag/.env.development}
    required_secret_config=${RAG_DEV_SECRET_ENV_FILE:-$dev_root/config/rag/.env.development.local}
    ;;
  *)
    required_dev_config=
    required_secret_config=
    ;;
esac
if [[ -n "$required_dev_config" && ! -f "$required_dev_config" ]]; then
  echo "missing required dev config: $required_dev_config" >&2
  exit 2
fi
if [[ -n "$required_secret_config" && ! -f "$required_secret_config" ]]; then
  echo "missing required dev secret config: $required_secret_config" >&2
  exit 2
fi

if [[ "$component" == rag ]]; then
  llm_migration_dir="$dev_root/secrets/llm-migration"
  install -d -m 700 "$llm_migration_dir"
  echo "[rag] prepare Alembic seed with development config: $required_dev_config + $required_secret_config"
  docker run --rm \
    --env-file "$dev_root/config/rag/.env.development" \
    --env-file "$dev_root/config/rag/.env.development.local" \
    -e PYTHONPATH=/app \
    -v "$dev_root/generate-dev-llm-migration-inputs.py:/run/generate-dev-llm-migration-inputs.py:ro" \
    -v "$llm_migration_dir:/run/llm-migration" \
    "$image_name:$image_tag" \
    python /run/generate-dev-llm-migration-inputs.py /run/llm-migration
  docker run --rm \
    --network tolink-dev-net \
    --env-file "$dev_root/config/rag/.env.development" \
    --env-file "$dev_root/config/rag/.env.development.local" \
    -e PYTHONPATH=/app \
    -v "$llm_migration_dir:/run/llm-migration" \
    -v "$dev_root/toLink-Rag/logs:/app/logs" \
    "$image_name:$image_tag" \
    python scripts/release/run_alembic.py \
      --expected-app-env development \
      --expected-host tolink-dev-mysql \
      --expected-port 3306 \
      --expected-database tolink_rag_dev \
      --seed-ciphertext-file /run/llm-migration/ciphertexts.json
fi

docker compose --env-file .env.dev --profile apps up -d "$compose_service"

# RAG 重建后容器 IP 可能变化；刷新 Web Nginx，避免其 worker 继续使用旧的
# Docker DNS 解析结果，导致前端通过 /api/ 访问后端时返回 502。
if [[ "$component" == rag ]] && docker inspect tolink-dev-web >/dev/null 2>&1; then
  echo "[$component] refresh web proxy after rag redeploy"
  docker compose --env-file .env.dev --profile apps up -d --force-recreate linkrag-web
fi

case "$component" in
  rag)
    health_url=http://100.86.10.52:18000/health
    ;;
  web)
    health_url=http://100.86.10.52:18080/
    ;;
esac

for _ in $(seq 1 60); do
  if curl -fsS "$health_url" >/dev/null; then
    break
  fi
  sleep 5
done

container_name="tolink-dev-$component"
if ! docker inspect -f '{{.State.Running}}' "$container_name" 2>/dev/null | grep -qx true; then
  docker logs --tail 150 "$container_name" || true
  exit 1
fi

curl -fsS "$health_url" >/dev/null

echo "[$component] deployed $image_name:$image_tag on Primary"
