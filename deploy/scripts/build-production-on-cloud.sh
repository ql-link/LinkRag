#!/usr/bin/env bash
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

image="tolink-rag"
tag="${commit_short}"
prod_root="/opt/tolink/toLink-Rag"
work_root="${prod_root}/jenkins/workspaces"
build_dir="${work_root}/rag-${build_number}"
base_env="${prod_root}/.env.production"
secret_env="${prod_root}/.env.production.local"
rabbitmq_env="/opt/tolink/rabbitmq/app.env"
compose_file="${prod_root}/deploy/docker-compose.yml"
backup_root="${prod_root}/backups/production-deploy"
docker_network="tolink-app-net"
compose_project="linkrag-production"
http_port="8000"
cutover_started="false"

cleanup() {
  if [[ "${build_dir}" == "${work_root}/rag-${build_number}" ]]; then
    rm -rf -- "${build_dir}"
  fi
}

finish() {
  exit_status=$?
  if [[ "${exit_status}" -ne 0 && "${cutover_started}" == "true" ]] && \
    declare -F rollback_old_application >/dev/null; then
    rollback_old_application || true
  fi
  cleanup
  return "${exit_status}"
}
trap finish EXIT

if [[ ! -f "${secret_env}" ]]; then
  echo "Missing Production secret env file: ${secret_env}" >&2
  exit 10
fi
if [[ "$(stat -c '%a' "${secret_env}")" != "600" ]]; then
  echo "Production secret env file must use mode 600" >&2
  exit 11
fi
if [[ ! -f "${rabbitmq_env}" ]]; then
  echo "Missing RabbitMQ application env file: ${rabbitmq_env}" >&2
  exit 12
fi
if [[ "$(stat -c '%a' "${rabbitmq_env}")" != "600" ]]; then
  echo "RabbitMQ application env file must use mode 600" >&2
  exit 13
fi

docker network inspect "${docker_network}" >/dev/null

port_owners="$(docker ps --filter "publish=${http_port}" --format '{{.Names}}')"
if [[ -n "${port_owners}" && "${port_owners}" != "tolink-rag" ]]; then
  echo "Production port ${http_port} is owned by another container: ${port_owners}" >&2
  exit 14
fi

available_kb="$(df -Pk "${prod_root}" | awk 'NR == 2 {print $4}')"
if [[ ! "${available_kb}" =~ ^[0-9]+$ || "${available_kb}" -lt 2097152 ]]; then
  echo "Production host requires at least 2 GiB free disk space" >&2
  exit 15
fi

rm -rf -- "${build_dir}"
mkdir -p "${build_dir}" "${prod_root}/deploy" "${prod_root}/logs" "${backup_root}"
tar -xzf "${source_archive}" -C "${build_dir}"

candidate_base_env="${build_dir}/.env.production"
candidate_compose_file="${build_dir}/deploy/docker-compose.yml"
if [[ ! -f "${candidate_base_env}" || ! -f "${candidate_compose_file}" ]]; then
  echo "Source archive is missing Production deployment files" >&2
  exit 16
fi

TAG="${tag}" \
RAG_ENV_FILE="${candidate_base_env}" \
RAG_SECRET_ENV_FILE="${secret_env}" \
RABBITMQ_APP_ENV_FILE="${rabbitmq_env}" \
  docker compose \
    -p "${compose_project}" \
    -f "${candidate_compose_file}" \
    config >/dev/null

DOCKER_BUILDKIT=1 docker build \
  --label "org.opencontainers.image.revision=${commit_short}" \
  -t "${image}:${tag}" \
  "${build_dir}"

backup_dir="${backup_root}/build-${build_number}"
mkdir -m 0700 -p "${backup_dir}"
if [[ -f "${base_env}" ]]; then
  cp -p "${base_env}" "${backup_dir}/.env.production"
fi
if [[ -f "${compose_file}" ]]; then
  cp -p "${compose_file}" "${backup_dir}/docker-compose.yml"
fi

old_image="$(docker inspect --format='{{.Config.Image}}' tolink-rag 2>/dev/null || true)"
printf '%s\n' "${old_image}" >"${backup_dir}/previous-image.txt"

docker run --rm \
  --network "${docker_network}" \
  --env-file "${candidate_base_env}" \
  --env-file "${secret_env}" \
  -e PYTHONPATH=/app \
  "${image}:${tag}" \
  python scripts/release/run_alembic.py \
    --expected-app-env production \
    --expected-host tolink-mysql \
    --expected-port 3306 \
    --expected-database tolink_rag_db

rollback_old_application() {
  if [[ "${old_image}" != tolink-rag:* ]]; then
    echo "Automatic application rollback is unavailable" >&2
    return 1
  fi
  if [[ ! -f "${backup_dir}/.env.production" || ! -f "${backup_dir}/docker-compose.yml" ]]; then
    echo "Previous Production configuration is unavailable for rollback" >&2
    return 1
  fi

  install -m 0644 "${backup_dir}/.env.production" "${base_env}"
  install -m 0644 "${backup_dir}/docker-compose.yml" "${compose_file}"
  old_tag="${old_image#tolink-rag:}"
  TAG="${old_tag}" \
  RAG_ENV_FILE="${base_env}" \
  RAG_SECRET_ENV_FILE="${secret_env}" \
  RABBITMQ_APP_ENV_FILE="${rabbitmq_env}" \
    docker compose \
      -p "${compose_project}" \
      -f "${compose_file}" \
      up -d --no-deps tolink-rag

  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${http_port}/health" >/dev/null && \
      curl -fsS "http://127.0.0.1:${http_port}/ready" >/dev/null; then
      echo "Previous Production application restored: ${old_image}"
      return 0
    fi
    sleep 2
  done
  echo "Previous Production application rollback health check failed" >&2
  return 1
}

install -m 0644 "${candidate_base_env}" "${base_env}"
install -m 0644 "${candidate_compose_file}" "${compose_file}"
cutover_started="true"

TAG="${tag}" \
RAG_ENV_FILE="${base_env}" \
RAG_SECRET_ENV_FILE="${secret_env}" \
RABBITMQ_APP_ENV_FILE="${rabbitmq_env}" \
  docker compose \
    -p "${compose_project}" \
    -f "${compose_file}" \
    up -d --no-deps tolink-rag

for _ in $(seq 1 30); do
  running_image="$(docker inspect --format='{{.Config.Image}}' tolink-rag 2>/dev/null || true)"
  running_status="$(docker inspect --format='{{.State.Status}}' tolink-rag 2>/dev/null || true)"
  if [[ "${running_image}" == "${image}:${tag}" && "${running_status}" == "running" ]] && \
    curl -fsS "http://127.0.0.1:${http_port}/health" >/dev/null && \
    curl -fsS "http://127.0.0.1:${http_port}/ready" >/dev/null; then
    echo "Container status: ${running_status}"
    echo "Production deployed: ${image}:${tag}"
    docker tag "${image}:${tag}" "${image}:latest"
    docker image prune -f >/dev/null
    cutover_started="false"
    exit 0
  fi
  sleep 2
done

TAG="${tag}" \
RAG_ENV_FILE="${base_env}" \
RAG_SECRET_ENV_FILE="${secret_env}" \
RABBITMQ_APP_ENV_FILE="${rabbitmq_env}" \
  docker compose \
    -p "${compose_project}" \
    -f "${compose_file}" \
    logs --tail=100 tolink-rag || true
echo "Production health check timed out; restoring previous application" >&2
exit 17
