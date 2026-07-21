#!/usr/bin/env bash
set -euo pipefail

component=${1:-}
build_number=${2:-}
test_root=${TEST_ROOT:-/opt/tolink/test}
jenkins_root="$test_root/jenkins"
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
  service)
    github_repo=LinkRag-Service
    workspace_name=toLink-Service
    image_name=tolink-service
    tag_key=SERVICE_TAG
    compose_service=tolink-service
    ;;
  web)
    github_repo=LinkRag-Web
    workspace_name=LinkRag-Web
    image_name=linkrag-web
    tag_key=WEB_TAG
    compose_service=linkrag-web
    ;;
  *)
    echo "usage: $0 {rag|service|web} BUILD_NUMBER" >&2
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

echo "[$component] fetch ql-link/$github_repo dev on Primary"
rm -rf "$next_dir"
mkdir -p "$next_dir"
archive_url="https://codeload.github.com/ql-link/${github_repo}/tar.gz/refs/heads/dev"
if ! curl -fsSL --retry 3 --retry-all-errors --retry-delay 3 \
  --connect-timeout 15 --max-time 300 \
  "https://gh-proxy.com/${archive_url}" -o "$archive"; then
  echo "[$component] GitHub proxy unavailable, fallback to codeload"
  curl -fsSL --retry 8 --retry-all-errors --retry-delay 5 \
    --connect-timeout 15 --max-time 1200 "$archive_url" -o "$archive"
fi
tar -xzf "$archive" --strip-components=1 -C "$next_dir"
rm -f "$archive"
rm -rf "$source_dir"
mv "$next_dir" "$source_dir"

image_tag="test-dev-b${build_number}"
echo "[$component] build $image_name:$image_tag on Primary"
case "$component" in
  rag|service)
    DOCKER_BUILDKIT=1 docker build -t "$image_name:$image_tag" "$source_dir"
    ;;
  web)
    docker run --rm -u 0:0 \
      -v "$source_dir:/workspace" -w /workspace node:20-alpine sh -lc '
        HUSKY=0 npm ci --prefer-offline --no-audit --registry=https://registry.npmmirror.com
        npm run typecheck
        npm run test
        VITE_GITHUB_URL=https://github.com/ql-link/LinkRag npm run build
      '
    docker build -t "$image_name:$image_tag" "$source_dir"
    ;;
esac

update_tag() {
  local key=$1
  local value=$2
  local env_file="$test_root/.env.test"
  if grep -q "^${key}=" "$env_file"; then
    sed -i "s/^${key}=.*/${key}=${value}/" "$env_file"
  else
    printf '%s=%s\n' "$key" "$value" >>"$env_file"
  fi
}

if [[ "$component" == rag ]]; then
  config_source="$source_dir/deploy/test-server"
  for name in docker-compose.yml loki-config.yml promtail-config.yml nginx.conf \
    rag.env.test app.env.test configure-test-env.sh build-component-on-primary.sh \
    generate-test-llm-migration-inputs.py; do
    install -m 600 "$config_source/$name" "$test_root/$name"
  done
  chmod 700 "$test_root/configure-test-env.sh" "$test_root/build-component-on-primary.sh"
  "$test_root/configure-test-env.sh"
elif [[ "$component" == service ]]; then
  install -d -m 700 "$test_root/toLink-Service/config"
  install -m 600 \
    "$source_dir/link-api/src/main/resources/application-dev.yml" \
    "$test_root/toLink-Service/config/application-test.yml"
  "$test_root/configure-test-env.sh"
fi

update_tag "$tag_key" "$image_tag"

cd "$test_root"
if [[ "$component" == rag ]]; then
  llm_migration_dir="$test_root/secrets/llm-migration"
  install -d -m 700 "$llm_migration_dir"
  docker run --rm \
    --env-file "$test_root/rag.env.test" \
    --env-file "$test_root/secrets/rag.env" \
    -e PYTHONPATH=/app \
    -v "$test_root/generate-test-llm-migration-inputs.py:/run/generate-test-llm-migration-inputs.py:ro" \
    -v "$llm_migration_dir:/run/llm-migration" \
    "$image_name:$image_tag" \
    python /run/generate-test-llm-migration-inputs.py /run/llm-migration
  docker run --rm \
    --network tolink-test-net \
    --env-file "$test_root/rag.env.test" \
    --env-file "$test_root/secrets/rag.env" \
    -e PYTHONPATH=/app \
    -e TOLINK_LLM_SEED_CIPHERTEXT_FILE=/run/llm-migration/ciphertexts.json \
    -v "$llm_migration_dir:/run/llm-migration" \
    -v "$test_root/toLink-Rag/logs:/app/logs" \
    "$image_name:$image_tag" \
    python scripts/release/llm_config_migration_preflight.py \
      --evidence /run/llm-migration/evidence.json \
      --ciphertexts /run/llm-migration/ciphertexts.json \
      --authorization-file /run/llm-migration/authorization.json \
      --run-migration
fi

docker compose --env-file .env.test --profile apps up -d "$compose_service"

case "$component" in
  rag)
    health_url=http://100.86.10.52:18000/health
    ;;
  service)
    health_url=http://100.86.10.52:18081/
    ;;
  web)
    health_url=http://100.86.10.52:18080/
    ;;
esac

for _ in $(seq 1 60); do
  if [[ "$component" == service ]]; then
    http_code=$(curl -sS -o /dev/null -w '%{http_code}' "$health_url" || true)
    [[ "$http_code" != 000 ]] && break
  elif curl -fsS "$health_url" >/dev/null; then
    break
  fi
  sleep 5
done

container_name="tolink-test-$component"
[[ "$component" == service ]] && container_name=tolink-test-service
if ! docker inspect -f '{{.State.Running}}' "$container_name" 2>/dev/null | grep -qx true; then
  docker logs --tail 150 "$container_name" || true
  exit 1
fi

if [[ "$component" == service ]]; then
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' "$health_url" || true)
  [[ "$http_code" != 000 ]] || exit 1
else
  curl -fsS "$health_url" >/dev/null
fi

echo "[$component] deployed $image_name:$image_tag on Primary"
