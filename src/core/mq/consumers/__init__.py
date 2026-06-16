"""MQ 业务消费者集合。

只暴露 handler 与 topic/group 常量；订阅装配在组合根（src/main.py）完成。
"""
from .parse_task_consumer import PARSE_TASK_GROUP, PARSE_TASK_TOPIC, handle_parse_task

__all__ = ["handle_parse_task", "PARSE_TASK_TOPIC", "PARSE_TASK_GROUP"]
