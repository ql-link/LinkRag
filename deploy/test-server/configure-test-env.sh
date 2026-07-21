#!/usr/bin/env bash
set -euo pipefail

test_root=${1:-/opt/tolink/test}
middleware_env="$test_root/.env.test"
secrets_dir="$test_root/secrets"
rag_secrets="$secrets_dir/rag.env"
app_secrets="$secrets_dir/app.env"
legacy_rag_env="$test_root/toLink-Rag/.env.test"

if [[ ! -f "$middleware_env" ]]; then
  echo "missing required file: $middleware_env" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$middleware_env"
set +a

read_env_value() {
  local file=$1
  local key=$2
  [[ -f "$file" ]] || return 0
  sed -n "s/^${key}=//p" "$file" | tail -1
}

existing_or_random_hex() {
  local file=$1
  local key=$2
  local fallback_file=${3:-}
  local value
  value=$(read_env_value "$file" "$key")
  if [[ -z "$value" && -n "$fallback_file" ]]; then
    value=$(read_env_value "$fallback_file" "$key")
  fi
  if [[ -z "$value" ]]; then
    value=$(openssl rand -hex 32)
  fi
  printf '%s' "$value"
}

api_key_secret=$(existing_or_random_hex "$rag_secrets" API_KEY_ENCRYPTION_SECRET "$legacy_rag_env")
recall_session_secret=$(existing_or_random_hex "$rag_secrets" RECALL_SESSION_JWT_SECRET "$legacy_rag_env")
llm_migration_auth_secret=$(existing_or_random_hex "$rag_secrets" TOLINK_LLM_MIGRATION_AUTH_SECRET)
recall_internal_secret=$(existing_or_random_hex "$app_secrets" RECALL_INTERNAL_JWT_SECRET)

system_llm_api_key=$(read_env_value "$rag_secrets" SYSTEM_LLM_API_KEY)
[[ -n "$system_llm_api_key" ]] || system_llm_api_key=$(read_env_value "$legacy_rag_env" SYSTEM_LLM_API_KEY)
mineru_api_key=$(read_env_value "$rag_secrets" MINERU_API_KEY)
[[ -n "$mineru_api_key" ]] || mineru_api_key=$(read_env_value "$legacy_rag_env" MINERU_API_KEY)

install -d -m 700 "$secrets_dir"
umask 077

rag_tmp=$(mktemp "$secrets_dir/rag.env.XXXXXX")
{
  printf 'DB_PASSWORD=%s\n' "$TEST_MYSQL_PASSWORD"
  printf 'DATABASE_URL=mysql+pymysql://%s:%s@tolink-test-mysql:3306/%s\n' "$TEST_MYSQL_USER" "$TEST_MYSQL_PASSWORD" "$TEST_MYSQL_DATABASE"
  printf 'ALEMBIC_DATABASE_URL=mysql+pymysql://%s:%s@tolink-test-mysql:3306/%s\n' "$TEST_MYSQL_USER" "$TEST_MYSQL_PASSWORD" "$TEST_MYSQL_DATABASE"
  printf 'TOLINK_LLM_MIGRATION_AUTH_SECRET=%s\n' "$llm_migration_auth_secret"
  printf 'REDIS_PASSWORD=%s\n' "$TEST_REDIS_PASSWORD"
  printf 'REDIS_URL=redis://:%s@tolink-test-redis:6379/0\n' "$TEST_REDIS_PASSWORD"
  printf 'QDRANT_API_KEY=%s\n' "$TEST_QDRANT_API_KEY"
  printf 'MINIO_SECRET_KEY=%s\n' "$TEST_MINIO_SECRET_KEY"
  printf 'KAFKA_SASL_PASSWORD=%s\n' "$TEST_KAFKA_PASSWORD"
  printf 'API_KEY_ENCRYPTION_SECRET=%s\n' "$api_key_secret"
  printf 'RECALL_SESSION_JWT_SECRET=%s\n' "$recall_session_secret"
  [[ -z "$system_llm_api_key" ]] || printf 'SYSTEM_LLM_API_KEY=%s\n' "$system_llm_api_key"
  [[ -z "$mineru_api_key" ]] || printf 'MINERU_API_KEY=%s\n' "$mineru_api_key"
} >"$rag_tmp"
mv "$rag_tmp" "$rag_secrets"

app_tmp=$(mktemp "$secrets_dir/app.env.XXXXXX")
{
  printf 'SPRING_DATASOURCE_PASSWORD=%s\n' "$TEST_MYSQL_PASSWORD"
  printf 'SPRING_REDIS_PASSWORD=%s\n' "$TEST_REDIS_PASSWORD"
  printf 'SPRING_KAFKA_PROPERTIES_SASL_JAAS_CONFIG=org.apache.kafka.common.security.plain.PlainLoginModule required username="%s" password="%s";\n' "$TEST_KAFKA_USER" "$TEST_KAFKA_PASSWORD"
  printf 'TOLINK_OSS_MINIO_SECRET_KEY=%s\n' "$TEST_MINIO_SECRET_KEY"
  printf 'RECALL_INTERNAL_JWT_SECRET=%s\n' "$recall_internal_secret"
  printf 'TOLINK_RECALL_SESSION_JWT_SECRET=%s\n' "$recall_session_secret"
  printf 'TOLINK_LLM_API_KEY_SECRET=%s\n' "$api_key_secret"
} >"$app_tmp"
mv "$app_tmp" "$app_secrets"

chmod 600 "$rag_secrets" "$app_secrets" "$middleware_env"
echo "test secret layers configured"
