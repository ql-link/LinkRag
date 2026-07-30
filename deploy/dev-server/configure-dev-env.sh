#!/usr/bin/env bash
set -euo pipefail

dev_root=${1:-/opt/tolink/dev}
middleware_env="$dev_root/.env.dev"
secrets_dir="$dev_root/secrets"
rag_secrets="$secrets_dir/rag.env"
app_secrets="$secrets_dir/app.env"
rag_config_dir="$dev_root/config/rag"
service_config_dir="$dev_root/config/service"
rag_local_config="$rag_config_dir/.env.development.local"
service_local_config="$service_config_dir/application-dev-local.yml"
legacy_rag_env="$dev_root/toLink-Rag/.env.dev"

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
recall_internal_secret=$(existing_or_random_hex "$app_secrets" RECALL_INTERNAL_JWT_SECRET)

mineru_api_key=$(read_env_value "$rag_secrets" MINERU_API_KEY)
[[ -n "$mineru_api_key" ]] || mineru_api_key=$(read_env_value "$legacy_rag_env" MINERU_API_KEY)

install -d -m 700 "$secrets_dir"
install -d -m 700 "$rag_config_dir" "$service_config_dir"
umask 077

rag_tmp=$(mktemp "$secrets_dir/rag.env.XXXXXX")
{
  printf 'DB_PASSWORD=%s\n' "$DEV_MYSQL_PASSWORD"
  printf 'DATABASE_URL=mysql+pymysql://%s:%s@tolink-dev-mysql:3306/%s\n' "$DEV_MYSQL_USER" "$DEV_MYSQL_PASSWORD" "$DEV_MYSQL_DATABASE"
  printf 'ALEMBIC_DATABASE_URL=mysql+pymysql://%s:%s@tolink-dev-mysql:3306/%s\n' "$DEV_MYSQL_USER" "$DEV_MYSQL_PASSWORD" "$DEV_MYSQL_DATABASE"
  printf 'REDIS_PASSWORD=%s\n' "$DEV_REDIS_PASSWORD"
  printf 'REDIS_URL=redis://:%s@tolink-dev-redis:6379/0\n' "$DEV_REDIS_PASSWORD"
  printf 'QDRANT_API_KEY=%s\n' "$DEV_QDRANT_API_KEY"
  printf 'MINIO_SECRET_KEY=%s\n' "$DEV_MINIO_SECRET_KEY"
  printf 'KAFKA_SASL_PASSWORD=%s\n' "$DEV_KAFKA_PASSWORD"
  printf 'API_KEY_ENCRYPTION_SECRET=%s\n' "$api_key_secret"
  printf 'RECALL_SESSION_JWT_SECRET=%s\n' "$recall_session_secret"
  [[ -z "$mineru_api_key" ]] || printf 'MINERU_API_KEY=%s\n' "$mineru_api_key"
} >"$rag_tmp"
mv "$rag_tmp" "$rag_secrets"

rag_local_tmp=$(mktemp "$rag_config_dir/.env.development.local.XXXXXX")
{
  printf 'DB_USER=%s\n' "$DEV_MYSQL_USER"
  printf 'KAFKA_SASL_USERNAME=%s\n' "$DEV_KAFKA_USER"
  printf 'MINIO_ACCESS_KEY=%s\n' "$DEV_MINIO_ACCESS_KEY"
  cat "$rag_secrets"
} >"$rag_local_tmp"
mv "$rag_local_tmp" "$rag_local_config"

app_tmp=$(mktemp "$secrets_dir/app.env.XXXXXX")
{
  printf 'SPRING_DATASOURCE_PASSWORD=%s\n' "$DEV_MYSQL_PASSWORD"
  printf 'SPRING_REDIS_PASSWORD=%s\n' "$DEV_REDIS_PASSWORD"
  printf 'SPRING_KAFKA_PROPERTIES_SASL_JAAS_CONFIG=org.apache.kafka.common.security.plain.PlainLoginModule required username="%s" password="%s";\n' "$DEV_KAFKA_USER" "$DEV_KAFKA_PASSWORD"
  printf 'TOLINK_OSS_MINIO_SECRET_KEY=%s\n' "$DEV_MINIO_SECRET_KEY"
  printf 'RECALL_INTERNAL_JWT_SECRET=%s\n' "$recall_internal_secret"
  printf 'TOLINK_RECALL_SESSION_JWT_SECRET=%s\n' "$recall_session_secret"
  printf 'TOLINK_LLM_API_KEY_SECRET=%s\n' "$api_key_secret"
} >"$app_tmp"
mv "$app_tmp" "$app_secrets"

API_KEY_SECRET="$api_key_secret" RECALL_SESSION_SECRET="$recall_session_secret" \
python3 - "$service_local_config" <<'PY'
import json
import os
import sys
from pathlib import Path

def quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)

values = {
    "db_user": os.environ["DEV_MYSQL_USER"],
    "db_password": os.environ["DEV_MYSQL_PASSWORD"],
    "redis_password": os.environ["DEV_REDIS_PASSWORD"],
    "kafka_user": os.environ["DEV_KAFKA_USER"],
    "kafka_password": os.environ["DEV_KAFKA_PASSWORD"],
    "minio_user": os.environ["DEV_MINIO_ACCESS_KEY"],
    "minio_password": os.environ["DEV_MINIO_SECRET_KEY"],
    "recall_secret": os.environ["RECALL_SESSION_SECRET"],
    "llm_secret": os.environ["API_KEY_SECRET"],
}
jaas = (
    "org.apache.kafka.common.security.plain.PlainLoginModule required "
    f'username="{values["kafka_user"]}" password="{values["kafka_password"]}";'
)
content = f"""# dev 账号、密码与密钥。禁止提交到 Git。
spring:
  datasource:
    username: {quoted(values['db_user'])}
    password: {quoted(values['db_password'])}
  redis:
    password: {quoted(values['redis_password'])}
  kafka:
    properties:
      sasl.jaas.config: {quoted(jaas)}
tolink:
  oss:
    minio:
      access-key: {quoted(values['minio_user'])}
      secret-key: {quoted(values['minio_password'])}
  recall:
    session-jwt-secret: {quoted(values['recall_secret'])}
  llm:
    api-key:
      secret: {quoted(values['llm_secret'])}
"""
Path(sys.argv[1]).write_text(content, encoding="utf-8")
PY

chmod 600 "$rag_secrets" "$app_secrets" "$rag_local_config" "$service_local_config" "$middleware_env"
echo "dev secret layers configured"
