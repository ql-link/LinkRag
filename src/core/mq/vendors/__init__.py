"""
MQ Vendor Adapters

按 SKILL.md 设计：厂商特定代码置于 vendor 包下，通过配置激活。
"""
from src.core.mq.vendors.kafka.kafka_adapter import KafkaSender, KafkaReceiver
from src.core.mq.vendors.rabbitmq_adapter import RabbitMQSender, RabbitMQReceiver

__all__ = [
    "KafkaSender",
    "KafkaReceiver",
    "RabbitMQSender",
    "RabbitMQReceiver",
]
