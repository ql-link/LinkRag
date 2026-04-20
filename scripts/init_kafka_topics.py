#!/usr/bin/env python3
"""使用 Kafka Admin API 初始化项目所需 Topics。"""
from __future__ import annotations

import sys

try:
    from src.core.mq.vendors.kafka.topic_admin import ensure_topics, describe_topics
except ImportError as exc:
    raise SystemExit(
        "无法导入 Topic Admin 组件，请确认依赖和项目路径正确。"
    ) from exc

def main() -> int:
    try:
        created_topics = ensure_topics()
        topic_partitions = describe_topics()
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    created_set = set(created_topics)
    for topic, partitions in topic_partitions.items():
        status = "create" if topic in created_set else "skip"
        print(f"[{status}] topic={topic} partitions={partitions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
