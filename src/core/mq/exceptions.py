"""
MQ 异常体系

层级：MQException → 具体异常类型
保持与 core.llm.exceptions 风格一致
"""


class MQException(Exception):
    """MQ 模块基础异常"""

    def __init__(self, message: str, vendor: str | None = None):
        self.vendor = vendor
        super().__init__(message)


class MQConnectionError(MQException):
    """MQ 连接失败（Broker 不可达、认证失败等）"""
    pass


class MQSendError(MQException):
    """消息发送失败（序列化异常、Broker 拒绝等）"""
    pass


class MQConsumeError(MQException):
    """消息消费失败（反序列化异常、业务回调异常等）"""
    pass


class MQConfigError(MQException):
    """MQ 配置错误（缺少必要参数、Vendor 不存在等）"""
    pass


class MQSerializationError(MQException):
    """消息序列化/反序列化异常"""
    pass
