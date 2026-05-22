"""topic_admin DLT 同规格装配单测。"""

from __future__ import annotations

from src.core.mq.topic_admin import build_default_topic_specs


def test_build_default_topic_specs_emits_dlt_siblings() -> None:
    """Scenario: 死信目标在启动时被幂等创建（Kafka 侧 spec 装配）。"""
    specs = build_default_topic_specs()

    business = [s for s in specs if not s.name.endswith(".DLT")]
    dlt = [s for s in specs if s.name.endswith(".DLT")]

    # 业务 topic 与 DLT 同长度（每个业务 topic 对应一个 DLT）
    assert len(business) == 4
    assert len(dlt) == 4

    biz_by_name = {s.name: s for s in business}
    for d in dlt:
        original = d.name[:-len(".DLT")]
        assert original in biz_by_name, f"DLT {d.name} 没有对应业务 topic"
        b = biz_by_name[original]
        # 同规格：partition / replication / retention / 副本约束 / 单消息大小一致
        assert d.partitions == b.partitions
        assert d.replication_factor == b.replication_factor
        assert d.retention_ms == b.retention_ms
        assert d.min_insync_replicas == b.min_insync_replicas
        assert d.max_message_bytes == b.max_message_bytes


def test_dlt_includes_parse_task_topic() -> None:
    """parse_task DLT 命名必须为 <原 topic>.DLT 形式（acceptance 契约）。"""
    names = {s.name for s in build_default_topic_specs()}
    assert "tolink.rag.parse_task" in names
    assert "tolink.rag.parse_task.DLT" in names
