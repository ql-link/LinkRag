#!/usr/bin/env bash
set -euo pipefail

dev_root=${1:-/opt/tolink/dev}
middleware_env="$dev_root/.env.dev"
secrets_dir="$dev_root/secrets"
rag_secrets="$secrets_dir/rag.env"
rag_config_dir="$dev_root/config/rag"
access_jwt_dir="$dev_root/config/auth"
access_jwt_private_key="$access_jwt_dir/java-access-jwt-private.pem"
access_jwt_public_key="$access_jwt_dir/java-access-jwt-public.pem"
rag_local_config="$rag_config_dir/.env.development.local"
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
if [[ -z "$rabbitmq_url" ]]; then
  echo "RabbitMQ app env must define RABBITMQ_URL" >&2
  exit 2
fi

api_key_secret=$(existing_or_random_hex "$rag_secrets" API_KEY_ENCRYPTION_SECRET "$legacy_rag_env")
recall_session_secret=$(existing_or_random_hex "$rag_secrets" RECALL_SESSION_JWT_SECRET "$legacy_rag_env")
# B5 上传执行器通过内部文件接口读取原始文件，令牌只在 Python 容器内使用
internal_file_token=$(existing_or_random_hex "$rag_secrets" B5_INTERNAL_FILE_SERVICE_TOKEN)

mineru_api_key=$(read_env_value "$rag_secrets" MINERU_API_KEY)
[[ -n "$mineru_api_key" ]] || mineru_api_key=$(read_env_value "$legacy_rag_env" MINERU_API_KEY)

install -d -m 700 "$secrets_dir"
install -d -m 700 "$rag_config_dir" "$access_jwt_dir"
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
  printf 'B5_INTERNAL_FILE_SERVICE_TOKEN=%s\n' "$internal_file_token"
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

chmod 600 "$rag_secrets" "$rag_local_config" "$middleware_env"
echo "dev secret layers configured"
