#!/usr/bin/env bash
set -euo pipefail

dev_root=${1:-/opt/tolink/dev}
middleware_env="$dev_root/.env.dev"
secrets_dir="$dev_root/secrets"
rag_secrets="$secrets_dir/rag.env"
app_secrets="$secrets_dir/app.env"
rag_config_dir="$dev_root/config/rag"
service_config_dir="$dev_root/config/service"
access_jwt_dir="$dev_root/config/auth"
access_jwt_private_key="$access_jwt_dir/java-access-jwt-private.pem"
access_jwt_public_key="$access_jwt_dir/java-access-jwt-public.pem"
rag_local_config="$rag_config_dir/.env.development.local"
service_local_config="$service_config_dir/application-dev-local.yml"
rabbitmq_app_env="$dev_root/config/rabbitmq/app.env"
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

if [[ ! -f "$rabbitmq_app_env" ]]; then
  echo "missing required file: $rabbitmq_app_env" >&2
  exit 2
fi

rabbitmq_url=$(read_env_value "$rabbitmq_app_env" RABBITMQ_URL)
rabbitmq_username=$(read_env_value "$rabbitmq_app_env" RABBITMQ_USERNAME)
rabbitmq_password=$(read_env_value "$rabbitmq_app_env" RABBITMQ_PASSWORD)
if [[ -z "$rabbitmq_url" || -z "$rabbitmq_username" || -z "$rabbitmq_password" ]]; then
  echo "RabbitMQ app env must define URL, username and password" >&2
  exit 2
fi

api_key_secret=$(existing_or_random_hex "$rag_secrets" API_KEY_ENCRYPTION_SECRET "$legacy_rag_env")
recall_session_secret=$(existing_or_random_hex "$rag_secrets" RECALL_SESSION_JWT_SECRET "$legacy_rag_env")
recall_internal_secret=$(existing_or_random_hex "$app_secrets" RECALL_INTERNAL_JWT_SECRET)

mineru_api_key=$(read_env_value "$rag_secrets" MINERU_API_KEY)
[[ -n "$mineru_api_key" ]] || mineru_api_key=$(read_env_value "$legacy_rag_env" MINERU_API_KEY)

install -d -m 700 "$secrets_dir"
install -d -m 700 "$rag_config_dir" "$service_config_dir" "$access_jwt_dir"
umask 077

if [[ ! -s "$access_jwt_private_key" ]]; then
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
    -out "$access_jwt_private_key"
fi
openssl pkey -in "$access_jwt_private_key" -pubout -out "$access_jwt_public_key"
chmod 600 "$access_jwt_private_key"
chmod 644 "$access_jwt_public_key"

rag_tmp=$(mktemp "$secrets_dir/rag.env.XXXXXX")
{
  printf 'DB_PASSWORD=%s\n' "$DEV_MYSQL_PASSWORD"
  printf 'DATABASE_URL=mysql+pymysql://%s:%s@tolink-dev-mysql:3306/%s\n' "$DEV_MYSQL_USER" "$DEV_MYSQL_PASSWORD" "$DEV_MYSQL_DATABASE"
  printf 'ALEMBIC_DATABASE_URL=mysql+pymysql://%s:%s@tolink-dev-mysql:3306/%s\n' "$DEV_MYSQL_USER" "$DEV_MYSQL_PASSWORD" "$DEV_MYSQL_DATABASE"
  printf 'REDIS_PASSWORD=%s\n' "$DEV_REDIS_PASSWORD"
  printf 'REDIS_URL=redis://:%s@tolink-dev-redis:6379/0\n' "$DEV_REDIS_PASSWORD"
  printf 'QDRANT_API_KEY=%s\n' "$DEV_QDRANT_API_KEY"
  printf 'MINIO_SECRET_KEY=%s\n' "$DEV_MINIO_SECRET_KEY"
  printf 'API_KEY_ENCRYPTION_SECRET=%s\n' "$api_key_secret"
  printf 'RECALL_SESSION_JWT_SECRET=%s\n' "$recall_session_secret"
  [[ -z "$mineru_api_key" ]] || printf 'MINERU_API_KEY=%s\n' "$mineru_api_key"
} >"$rag_tmp"
mv "$rag_tmp" "$rag_secrets"

rag_local_tmp=$(mktemp "$rag_config_dir/.env.development.local.XXXXXX")
{
  printf 'DB_USER=%s\n' "$DEV_MYSQL_USER"
  printf 'MINIO_ACCESS_KEY=%s\n' "$DEV_MINIO_ACCESS_KEY"
  printf 'RABBITMQ_URL=%s\n' "$rabbitmq_url"
  printf 'JAVA_ACCESS_JWT_ENABLED=true\n'
  printf 'JAVA_ACCESS_JWT_PUBLIC_KEY_PATH=/run/secrets/java-access-jwt-public.pem\n'
  printf 'JAVA_ACCESS_JWT_ISSUER=tolink-java\n'
  printf 'JAVA_ACCESS_JWT_AUDIENCE=tolink-rag-api\n'
  printf 'JAVA_ACCESS_JWT_TOKEN_USE=access\n'
  cat "$rag_secrets"
} >"$rag_local_tmp"
mv "$rag_local_tmp" "$rag_local_config"

app_tmp=$(mktemp "$secrets_dir/app.env.XXXXXX")
{
  printf 'SPRING_DATASOURCE_PASSWORD=%s\n' "$DEV_MYSQL_PASSWORD"
  printf 'SPRING_REDIS_PASSWORD=%s\n' "$DEV_REDIS_PASSWORD"
  printf 'TOLINK_OSS_MINIO_SECRET_KEY=%s\n' "$DEV_MINIO_SECRET_KEY"
  printf 'RECALL_INTERNAL_JWT_SECRET=%s\n' "$recall_internal_secret"
  printf 'TOLINK_RECALL_SESSION_JWT_SECRET=%s\n' "$recall_session_secret"
  printf 'TOLINK_LLM_API_KEY_SECRET=%s\n' "$api_key_secret"
} >"$app_tmp"
mv "$app_tmp" "$app_secrets"

API_KEY_SECRET="$api_key_secret" RECALL_SESSION_SECRET="$recall_session_secret" \
RABBITMQ_USERNAME="$rabbitmq_username" RABBITMQ_PASSWORD="$rabbitmq_password" \
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
    "rabbitmq_username": os.environ["RABBITMQ_USERNAME"],
    "rabbitmq_password": os.environ["RABBITMQ_PASSWORD"],
    "minio_user": os.environ["DEV_MINIO_ACCESS_KEY"],
    "minio_password": os.environ["DEV_MINIO_SECRET_KEY"],
    "recall_secret": os.environ["RECALL_SESSION_SECRET"],
    "llm_secret": os.environ["API_KEY_SECRET"],
}
content = f"""# dev 账号、密码与密钥。禁止提交到 Git。
spring:
  datasource:
    username: {quoted(values['db_user'])}
    password: {quoted(values['db_password'])}
  redis:
    password: {quoted(values['redis_password'])}
  rabbitmq:
    username: {quoted(values['rabbitmq_username'])}
    password: {quoted(values['rabbitmq_password'])}
tolink:
  auth:
    access-token:
      enabled: true
      private-key-path: /run/secrets/java-access-jwt-private.pem
      issuer: tolink-java
      audiences:
        - tolink-java-api
        - tolink-rag-api
      ttl-seconds: 7200
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
