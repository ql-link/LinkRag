#!/usr/bin/env bash

set -euo pipefail

BOOTSTRAP_SERVER="${BOOTSTRAP_SERVER:-127.0.0.1:9092}"
KAFKA_TOPICS_BIN="${KAFKA_TOPICS_BIN:-kafka-topics.sh}"
COMMAND_CONFIG="${COMMAND_CONFIG:-}"

PARSE_TASK_TOPIC="${PARSE_TASK_TOPIC:-tolink.rag.parse_task}"
PARSE_RESULT_TOPIC="${PARSE_RESULT_TOPIC:-tolink.rag.parse_result}"
CACHE_SYNC_TOPIC="${CACHE_SYNC_TOPIC:-tolink.rag.cache_sync}"
USAGE_REPORT_TOPIC="${USAGE_REPORT_TOPIC:-tolink.rag.usage_report}"

PARSE_TASK_PARTITIONS="${PARSE_TASK_PARTITIONS:-1}"
PARSE_RESULT_PARTITIONS="${PARSE_RESULT_PARTITIONS:-1}"
CACHE_SYNC_PARTITIONS="${CACHE_SYNC_PARTITIONS:-1}"
USAGE_REPORT_PARTITIONS="${USAGE_REPORT_PARTITIONS:-1}"

REPLICATION_FACTOR="${REPLICATION_FACTOR:-1}"
MIN_INSYNC_REPLICAS="${MIN_INSYNC_REPLICAS:-1}"
RETENTION_MS_PARSE_TASK="${RETENTION_MS_PARSE_TASK:-604800000}"
RETENTION_MS_PARSE_RESULT="${RETENTION_MS_PARSE_RESULT:-604800000}"
RETENTION_MS_CACHE_SYNC="${RETENTION_MS_CACHE_SYNC:-172800000}"
RETENTION_MS_USAGE_REPORT="${RETENTION_MS_USAGE_REPORT:-604800000}"
MAX_MESSAGE_BYTES="${MAX_MESSAGE_BYTES:-1048576}"

TOPIC_CMD=("${KAFKA_TOPICS_BIN}" "--bootstrap-server" "${BOOTSTRAP_SERVER}")
if [[ -n "${COMMAND_CONFIG}" ]]; then
  TOPIC_CMD+=("--command-config" "${COMMAND_CONFIG}")
fi

topic_exists() {
  local topic="$1"
  "${TOPIC_CMD[@]}" --list | grep -Fxq "${topic}"
}

create_topic() {
  local topic="$1"
  local partitions="$2"
  local retention_ms="$3"

  if topic_exists "${topic}"; then
    echo "[skip] topic already exists: ${topic}"
    return 0
  fi

  echo "[create] topic=${topic} partitions=${partitions} replication-factor=${REPLICATION_FACTOR}"
  "${TOPIC_CMD[@]}" \
    --create \
    --if-not-exists \
    --topic "${topic}" \
    --partitions "${partitions}" \
    --replication-factor "${REPLICATION_FACTOR}" \
    --config cleanup.policy=delete \
    --config min.insync.replicas="${MIN_INSYNC_REPLICAS}" \
    --config retention.ms="${retention_ms}" \
    --config max.message.bytes="${MAX_MESSAGE_BYTES}"
}

describe_topic() {
  local topic="$1"
  echo "[describe] ${topic}"
  "${TOPIC_CMD[@]}" --describe --topic "${topic}"
}

create_topic "${PARSE_TASK_TOPIC}" "${PARSE_TASK_PARTITIONS}" "${RETENTION_MS_PARSE_TASK}"
create_topic "${PARSE_RESULT_TOPIC}" "${PARSE_RESULT_PARTITIONS}" "${RETENTION_MS_PARSE_RESULT}"
create_topic "${CACHE_SYNC_TOPIC}" "${CACHE_SYNC_PARTITIONS}" "${RETENTION_MS_CACHE_SYNC}"
create_topic "${USAGE_REPORT_TOPIC}" "${USAGE_REPORT_PARTITIONS}" "${RETENTION_MS_USAGE_REPORT}"

describe_topic "${PARSE_TASK_TOPIC}"
describe_topic "${PARSE_RESULT_TOPIC}"
describe_topic "${CACHE_SYNC_TOPIC}"
describe_topic "${USAGE_REPORT_TOPIC}"
