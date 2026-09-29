"""管理端安全事件的最小结构化审计字段。"""

import re

from src.observability.logging import logger


def audit_event(
    action: str,
    outcome: str,
    *,
    actor_id: int | None = None,
    target_id: int | None = None,
) -> None:
    """只记录 ID 和动作，不接受令牌、密码、请求体或异常原文。"""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", action):
        raise ValueError("审计动作必须为大写标识")
    if outcome not in {"success", "denied", "failed"}:
        raise ValueError("审计结果不合法")
    logger.bind(
        event="management_audit",
        action=action,
        outcome=outcome,
        actor_id=actor_id,
        target_id=target_id,
    ).info(
        "管理端审计 action={} outcome={} actor_id={} target_id={}",
        action,
        outcome,
        actor_id,
        target_id,
    )
