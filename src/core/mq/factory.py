"""
MQFactory 注册式工厂

对应 SKILL.md 中的 Vendor Selector 层。
根据配置 (MQ_VENDOR) 自动创建对应厂商的 Sender/Receiver 实例。
单例模式，全局共享同一组连接实例。
"""
from typing import Dict, Optional, Type, Any

from loguru import logger

from src.core.mq.interfaces import IMQSender, IMQReceiver, MQVendorType
from src.core.mq.exceptions import MQConfigError


class MQFactory:
    """MQ 厂商注册式工厂

    使用方式：
        factory = MQFactory()
        sender = factory.get_sender()    # 根据配置返回 Kafka/RabbitMQ Sender
        receiver = factory.get_receiver() # 根据配置返回 Kafka/RabbitMQ Receiver

    设计决策：
        - 单例模式：一个进程中只需一组 MQ 连接
        - 懒初始化：只在首次 get_sender/get_receiver 时创建连接
        - 缓存实例：避免重复创建连接
    """

    _instance: Optional["MQFactory"] = None

    # 注册表: vendor_type -> (SenderClass, ReceiverClass)
    _sender_registry: Dict[str, Type[IMQSender]] = {}
    _receiver_registry: Dict[str, Type[IMQReceiver]] = {}

    # 实例缓存
    _sender_cache: Optional[IMQSender] = None
    _receiver_cache: Optional[IMQReceiver] = None
    _current_vendor: Optional[str] = None

    def __new__(cls) -> "MQFactory":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sender_registry = {}
            cls._instance._receiver_registry = {}
            cls._instance._sender_cache = None
            cls._instance._receiver_cache = None
            cls._instance._current_vendor = None
            cls._instance._register_defaults()
        return cls._instance

    def _register_defaults(self) -> None:
        """注册内置的厂商适配器"""
        from src.core.mq.vendors.kafka.kafka_adapter import KafkaSender, KafkaReceiver
        from src.core.mq.vendors.rabbitmq_adapter import RabbitMQSender, RabbitMQReceiver

        self._sender_registry[MQVendorType.KAFKA] = KafkaSender
        self._receiver_registry[MQVendorType.KAFKA] = KafkaReceiver
        self._sender_registry[MQVendorType.RABBITMQ] = RabbitMQSender
        self._receiver_registry[MQVendorType.RABBITMQ] = RabbitMQReceiver

    def register_vendor(
        self,
        vendor_type: str,
        sender_cls: Type[IMQSender],
        receiver_cls: Type[IMQReceiver],
    ) -> None:
        """注册新的 MQ 厂商

        Args:
            vendor_type: 厂商标识
            sender_cls: 发送者类
            receiver_cls: 接收者类
        """
        self._sender_registry[vendor_type] = sender_cls
        self._receiver_registry[vendor_type] = receiver_cls
        logger.info(f"[MQFactory] 注册厂商: {vendor_type}")

    def _resolve_config(self) -> Dict[str, Any]:
        """从 Settings 读取 MQ 配置

        Returns:
            包含 vendor, connection 参数的配置字典
        """
        from src.config import settings

        vendor = getattr(settings, "MQ_VENDOR", "kafka").lower()
        config: Dict[str, Any] = {"vendor": vendor}

        if vendor == MQVendorType.KAFKA:
            config["bootstrap_servers"] = getattr(
                settings, "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
            )
            config["sasl_mechanism"] = getattr(
                settings, "KAFKA_SASL_MECHANISM", None
            )
            config["sasl_plain_username"] = getattr(
                settings, "KAFKA_SASL_USERNAME", None
            )
            config["sasl_plain_password"] = getattr(
                settings, "KAFKA_SASL_PASSWORD", None
            )
            config["security_protocol"] = getattr(
                settings, "KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"
            )
            config["max_poll_interval_ms"] = getattr(
                settings, "KAFKA_MAX_POLL_INTERVAL_MS", 900000
            )
        elif vendor == MQVendorType.RABBITMQ:
            config["url"] = getattr(
                settings, "RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"
            )
            config["exchange_name"] = getattr(
                settings, "RABBITMQ_EXCHANGE_NAME", ""
            )
            config["exchange_type"] = getattr(
                settings, "RABBITMQ_EXCHANGE_TYPE", "direct"
            )
            config["prefetch_count"] = getattr(
                settings, "RABBITMQ_PREFETCH_COUNT", 10
            )
        else:
            raise MQConfigError(
                f"不支持的 MQ 厂商: {vendor}，"
                f"可选: {list(self._sender_registry.keys())}",
                vendor=vendor,
            )

        return config

    def get_sender(self, **overrides: Any) -> IMQSender:
        """获取消息发送者实例（带缓存）

        Args:
            **overrides: 覆盖配置的参数

        Returns:
            IMQSender 实例
        """
        config = self._resolve_config()
        vendor = config["vendor"]

        # 如果 vendor 切换了，清除缓存
        if self._current_vendor and self._current_vendor != vendor:
            self._sender_cache = None
            self._receiver_cache = None

        self._current_vendor = vendor

        if self._sender_cache is not None:
            return self._sender_cache

        sender_cls = self._sender_registry.get(vendor)
        if not sender_cls:
            raise MQConfigError(
                f"厂商 {vendor} 未注册 Sender", vendor=vendor
            )

        # 构建厂商特定参数
        if vendor == MQVendorType.KAFKA:
            kwargs = {
                "bootstrap_servers": config["bootstrap_servers"],
                "sasl_mechanism": config.get("sasl_mechanism"),
                "sasl_plain_username": config.get("sasl_plain_username"),
                "sasl_plain_password": config.get("sasl_plain_password"),
                "security_protocol": config.get("security_protocol", "PLAINTEXT"),
                "max_poll_interval_ms": config.get("max_poll_interval_ms", 900000),
            }
        elif vendor == MQVendorType.RABBITMQ:
            kwargs = {
                "url": config["url"],
                "exchange_name": config.get("exchange_name", ""),
                "exchange_type": config.get("exchange_type", "direct"),
            }
        else:
            kwargs = {}

        kwargs.update(overrides)
        self._sender_cache = sender_cls(**kwargs)
        logger.info(f"[MQFactory] 创建 Sender: vendor={vendor}")
        return self._sender_cache

    def get_receiver(self, **overrides: Any) -> IMQReceiver:
        """获取消息接收者实例（带缓存）

        Args:
            **overrides: 覆盖配置的参数

        Returns:
            IMQReceiver 实例
        """
        config = self._resolve_config()
        vendor = config["vendor"]

        if self._current_vendor and self._current_vendor != vendor:
            self._sender_cache = None
            self._receiver_cache = None

        self._current_vendor = vendor

        if self._receiver_cache is not None:
            return self._receiver_cache

        receiver_cls = self._receiver_registry.get(vendor)
        if not receiver_cls:
            raise MQConfigError(
                f"厂商 {vendor} 未注册 Receiver", vendor=vendor
            )

        if vendor == MQVendorType.KAFKA:
            kwargs = {
                "bootstrap_servers": config["bootstrap_servers"],
                "sasl_mechanism": config.get("sasl_mechanism"),
                "sasl_plain_username": config.get("sasl_plain_username"),
                "sasl_plain_password": config.get("sasl_plain_password"),
                "security_protocol": config.get("security_protocol", "PLAINTEXT"),
            }
        elif vendor == MQVendorType.RABBITMQ:
            kwargs = {
                "url": config["url"],
                "prefetch_count": config.get("prefetch_count", 10),
            }
        else:
            kwargs = {}

        kwargs.update(overrides)
        self._receiver_cache = receiver_cls(**kwargs)
        logger.info(f"[MQFactory] 创建 Receiver: vendor={vendor}")
        return self._receiver_cache

    def list_vendors(self) -> list[str]:
        """列出所有已注册的厂商"""
        return list(self._sender_registry.keys())

    async def close_all(self) -> None:
        """关闭所有连接（应用关闭时调用）"""
        if self._sender_cache:
            await self._sender_cache.close()
            self._sender_cache = None
        if self._receiver_cache:
            await self._receiver_cache.stop()
            self._receiver_cache = None
        self._current_vendor = None
        logger.info("[MQFactory] 所有 MQ 连接已关闭")

    @classmethod
    def reset(cls) -> None:
        """重置单例（仅用于测试）"""
        cls._instance = None
