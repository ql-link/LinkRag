"""
MQFactory 单元测试

测试工厂模式的注册、实例创建、缓存、配置读取。
Mock 外部依赖（Settings），不连接真实 Broker。
"""
import pytest
from unittest.mock import patch, MagicMock

from src.core.mq.factory import MQFactory
from src.core.mq.interfaces import IMQSender, IMQReceiver, MQVendorType
from src.core.mq.exceptions import MQConfigError


@pytest.fixture(autouse=True)
def reset_factory():
    """每个测试前重置单例"""
    MQFactory.reset()
    yield
    MQFactory.reset()


class TestFactoryRegistration:
    """注册机制测试"""

    def test_default_vendors_registered(self):
        factory = MQFactory()
        vendors = factory.list_vendors()
        assert MQVendorType.KAFKA in vendors
        assert MQVendorType.RABBITMQ in vendors

    def test_register_custom_vendor(self):
        factory = MQFactory()

        class FakeSender(IMQSender):
            async def send(self, topic, message, **kw): pass
            async def send_batch(self, topic, messages, **kw): pass
            async def close(self): pass

        class FakeReceiver(IMQReceiver):
            async def subscribe(self, topic, group_id, callback, **kw): pass
            async def start(self): pass
            async def stop(self): pass
            def is_running(self): return False

        factory.register_vendor("rocketmq", FakeSender, FakeReceiver)
        assert "rocketmq" in factory.list_vendors()


class TestFactoryGetSender:
    """Sender 获取测试"""

    @patch("src.core.mq.factory.MQFactory._resolve_config")
    def test_get_kafka_sender(self, mock_config):
        mock_config.return_value = {
            "vendor": MQVendorType.KAFKA,
            "bootstrap_servers": "localhost:9092",
            "security_protocol": "PLAINTEXT",
        }
        factory = MQFactory()
        sender = factory.get_sender()
        # 验证返回的是 KafkaSender 实例
        from src.core.mq.vendors.kafka_adapter import KafkaSender
        assert isinstance(sender, KafkaSender)

    @patch("src.core.mq.factory.MQFactory._resolve_config")
    def test_get_rabbitmq_sender(self, mock_config):
        mock_config.return_value = {
            "vendor": MQVendorType.RABBITMQ,
            "url": "amqp://guest:guest@localhost:5672/",
            "exchange_name": "",
            "exchange_type": "direct",
        }
        factory = MQFactory()
        sender = factory.get_sender()
        from src.core.mq.vendors.rabbitmq_adapter import RabbitMQSender
        assert isinstance(sender, RabbitMQSender)

    @patch("src.core.mq.factory.MQFactory._resolve_config")
    def test_sender_caching(self, mock_config):
        """同一 vendor 的 sender 应复用实例"""
        mock_config.return_value = {
            "vendor": MQVendorType.KAFKA,
            "bootstrap_servers": "localhost:9092",
            "security_protocol": "PLAINTEXT",
        }
        factory = MQFactory()
        s1 = factory.get_sender()
        s2 = factory.get_sender()
        assert s1 is s2

    @patch("src.core.mq.factory.MQFactory._resolve_config")
    def test_unknown_vendor_raises(self, mock_config):
        mock_config.return_value = {"vendor": "unknown_mq"}
        factory = MQFactory()
        with pytest.raises(MQConfigError):
            factory.get_sender()


class TestFactoryGetReceiver:
    """Receiver 获取测试"""

    @patch("src.core.mq.factory.MQFactory._resolve_config")
    def test_get_kafka_receiver(self, mock_config):
        mock_config.return_value = {
            "vendor": MQVendorType.KAFKA,
            "bootstrap_servers": "localhost:9092",
            "security_protocol": "PLAINTEXT",
        }
        factory = MQFactory()
        receiver = factory.get_receiver()
        from src.core.mq.vendors.kafka_adapter import KafkaReceiver
        assert isinstance(receiver, KafkaReceiver)

    @patch("src.core.mq.factory.MQFactory._resolve_config")
    def test_get_rabbitmq_receiver(self, mock_config):
        mock_config.return_value = {
            "vendor": MQVendorType.RABBITMQ,
            "url": "amqp://guest:guest@localhost:5672/",
            "prefetch_count": 10,
        }
        factory = MQFactory()
        receiver = factory.get_receiver()
        from src.core.mq.vendors.rabbitmq_adapter import RabbitMQReceiver
        assert isinstance(receiver, RabbitMQReceiver)


class TestFactorySingleton:
    """单例模式测试"""

    def test_singleton(self):
        f1 = MQFactory()
        f2 = MQFactory()
        assert f1 is f2

    def test_reset_creates_new_instance(self):
        f1 = MQFactory()
        MQFactory.reset()
        f2 = MQFactory()
        assert f1 is not f2
