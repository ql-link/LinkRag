"""MQ 业务消费者集合。"""
from .parse_task_consumer import handle_parse_task, start_parse_consumer

__all__ = ["handle_parse_task", "start_parse_consumer"]
