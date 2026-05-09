"""
Kafka Topic 管理工具。

提供给部署脚本或应用启动阶段调用，不直接耦合到路由层。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.config import settings

try:
    from confluent_kafka.admin import AdminClient, NewTopic
except ImportError as exc:
    raise RuntimeError("缺少依赖 confluent-kafka，请先安装后再使用 Topic Admin。") from exc


@dataclass(frozen=True)
class TopicSpec:
    name: str
    partitions: int
    replication_factor: int
    retention_ms: int
    min_insync_replicas: int
    max_message_bytes: int

    def as_new_topic(self) -> NewTopic:
        return NewTopic(
            topic=self.name,
            num_partitions=self.partitions,
            replication_factor=self.replication_factor,
            config={
                "cleanup.policy": "delete",
                "retention.ms": str(self.retention_ms),
                "min.insync.replicas": str(self.min_insync_replicas),
                "max.message.bytes": str(self.max_message_bytes),
            },
        )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def build_admin_client() -> AdminClient:
    config = {
        "bootstrap.servers": os.getenv("BOOTSTRAP_SERVER", settings.KAFKA_BOOTSTRAP_SERVERS),
        "security.protocol": os.getenv("KAFKA_SECURITY_PROTOCOL", settings.KAFKA_SECURITY_PROTOCOL),
    }

    sasl_mechanism = os.getenv("KAFKA_SASL_MECHANISM", settings.KAFKA_SASL_MECHANISM or "")
    if sasl_mechanism:
        config["sasl.mechanism"] = sasl_mechanism
        config["sasl.username"] = os.getenv(
            "KAFKA_SASL_USERNAME", settings.KAFKA_SASL_USERNAME or ""
        )
        config["sasl.password"] = os.getenv(
            "KAFKA_SASL_PASSWORD", settings.KAFKA_SASL_PASSWORD or ""
        )

    return AdminClient(config)


def build_default_topic_specs() -> list[TopicSpec]:
    replication_factor = _env_int("REPLICATION_FACTOR", 1)
    min_insync_replicas = _env_int("MIN_INSYNC_REPLICAS", 1)
    max_message_bytes = _env_int("MAX_MESSAGE_BYTES", 1048576)

    return [
        TopicSpec(
            name=os.getenv("PARSE_TASK_TOPIC", "tolink-document-pares"),
            partitions=_env_int("PARSE_TASK_PARTITIONS", 1),
            replication_factor=replication_factor,
            retention_ms=_env_int("RETENTION_MS_PARSE_TASK", 604800000),
            min_insync_replicas=min_insync_replicas,
            max_message_bytes=max_message_bytes,
        ),
        TopicSpec(
            name=os.getenv("PARSE_RESULT_TOPIC", "tolink.rag.parse_result"),
            partitions=_env_int("PARSE_RESULT_PARTITIONS", 1),
            replication_factor=replication_factor,
            retention_ms=_env_int("RETENTION_MS_PARSE_RESULT", 604800000),
            min_insync_replicas=min_insync_replicas,
            max_message_bytes=max_message_bytes,
        ),
        TopicSpec(
            name=os.getenv("CACHE_SYNC_TOPIC", "tolink.rag.cache_sync"),
            partitions=_env_int("CACHE_SYNC_PARTITIONS", 1),
            replication_factor=replication_factor,
            retention_ms=_env_int("RETENTION_MS_CACHE_SYNC", 172800000),
            min_insync_replicas=min_insync_replicas,
            max_message_bytes=max_message_bytes,
        ),
        TopicSpec(
            name=os.getenv("USAGE_REPORT_TOPIC", "tolink.rag.usage_report"),
            partitions=_env_int("USAGE_REPORT_PARTITIONS", 1),
            replication_factor=replication_factor,
            retention_ms=_env_int("RETENTION_MS_USAGE_REPORT", 604800000),
            min_insync_replicas=min_insync_replicas,
            max_message_bytes=max_message_bytes,
        ),
    ]


def ensure_topics() -> list[str]:
    admin = build_admin_client()
    specs = build_default_topic_specs()

    metadata = admin.list_topics(timeout=10)
    existing_topics = set(metadata.topics.keys())
    to_create = [spec for spec in specs if spec.name not in existing_topics]
    created: list[str] = []

    if to_create:
        futures = admin.create_topics([spec.as_new_topic() for spec in to_create])
        for spec in to_create:
            futures[spec.name].result()
            created.append(spec.name)

    return created


def describe_topics() -> dict[str, int]:
    admin = build_admin_client()
    specs = build_default_topic_specs()
    metadata = admin.list_topics(timeout=10)

    return {
        spec.name: len(metadata.topics[spec.name].partitions)
        for spec in specs
        if spec.name in metadata.topics
    }
