#!/usr/bin/env bash
set -euo pipefail

readonly TAILSCALE_DEVICE="tailscale0"
readonly TAILSCALE_IP="100.86.10.52"
readonly DEV_ROOT="/opt/tolink/dev"
readonly DEV_COMPOSE="${DEV_ROOT}/docker-compose.yml"
readonly DEV_ENV="${DEV_ROOT}/.env.dev"

log() {
  printf '[tolink-dev-recover] %s\n' "$*"
}

compose() {
  /usr/bin/docker compose --env-file "${DEV_ENV}" -f "${DEV_COMPOSE}" "$@"
}

wait_for_tailscale_ip() {
  local attempt
  for ((attempt = 1; attempt <= 120; attempt++)); do
    if /usr/sbin/ip -4 address show dev "${TAILSCALE_DEVICE}" 2>/dev/null \
      | /usr/bin/grep -Fq "inet ${TAILSCALE_IP}/32"; then
      log "Tailscale IP ${TAILSCALE_IP} is ready"
      return 0
    fi
    /usr/bin/sleep 1
  done
  log "Timed out waiting for ${TAILSCALE_IP} on ${TAILSCALE_DEVICE}"
  return 1
}

wait_for_healthy_container() {
  local container="$1"
  local attempt state health
  for ((attempt = 1; attempt <= 180; attempt++)); do
    state="$(/usr/bin/docker inspect --format '{{.State.Status}}' "${container}" 2>/dev/null || true)"
    health="$(/usr/bin/docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container}" 2>/dev/null || true)"
    if [[ "${state}" == "running" && "${health}" == "healthy" ]]; then
      log "${container} is healthy"
      return 0
    fi
    /usr/bin/sleep 1
  done
  log "${container} did not become healthy: state=${state:-missing} health=${health:-missing}"
  return 1
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempt code
  for ((attempt = 1; attempt <= 180; attempt++)); do
    code="$(/usr/bin/curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "${url}" 2>/dev/null || true)"
    if [[ "${code}" =~ ^2[0-9][0-9]$ ]]; then
      log "${name} is reachable: HTTP ${code}"
      return 0
    fi
    /usr/bin/sleep 1
  done
  log "${name} did not become reachable: HTTP ${code:-000}"
  return 1
}

wait_for_tailscale_ip
/usr/bin/docker info >/dev/null

# These files contain no secrets. Keep them readable by the non-root Loki and
# Promtail processes, and repair labels left by older deployments that did not
# use the Compose :Z mount option.
for config_file in loki-config.yml nginx.conf promtail-config.yml; do
  /usr/bin/chmod 0644 "${DEV_ROOT}/${config_file}"
  /usr/bin/chcon -t container_file_t "${DEV_ROOT}/${config_file}" 2>/dev/null || true
done

log "Recreating stateful middleware bindings without removing data volumes"
compose up -d --no-build --force-recreate mysql redis zookeeper qdrant manticore loki
wait_for_healthy_container tolink-dev-mysql
wait_for_healthy_container tolink-dev-redis
wait_for_healthy_container tolink-dev-zookeeper
wait_for_healthy_container tolink-dev-manticore
wait_for_http qdrant "http://${TAILSCALE_IP}:16333/readyz"
wait_for_http loki "http://${TAILSCALE_IP}:13100/ready"

log "Recreating Kafka after middleware networking is ready"
compose up -d --no-build --no-deps --force-recreate kafka
wait_for_healthy_container tolink-dev-kafka
compose up -d --no-build --no-deps --force-recreate kafka-ui
wait_for_http kafka-ui "http://${TAILSCALE_IP}:19081/"

log "Recreating RAG and Service bindings"
compose --profile apps up -d --no-build --no-deps --force-recreate tolink-rag tolink-service
wait_for_http rag "http://${TAILSCALE_IP}:18000/health"
wait_for_http service "http://${TAILSCALE_IP}:18081/actuator/health"

log "Recreating Web binding after both backends are reachable"
compose --profile apps up -d --no-build --no-deps --force-recreate linkrag-web
wait_for_http web "http://${TAILSCALE_IP}:18080/"
compose --profile apps up -d --no-build --no-deps --force-recreate promtail

if /usr/bin/docker inspect linkcv-dev >/dev/null 2>&1; then
  log "Restarting LinkCV after shared MySQL and Redis are healthy"
  /usr/bin/docker restart linkcv-dev >/dev/null
  wait_for_healthy_container linkcv-dev
fi

log "Development stack recovery completed"
