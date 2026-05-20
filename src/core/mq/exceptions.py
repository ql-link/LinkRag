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


class RetriableError(MQException):
    """可重试异常基类（业务回调可抛出此基类的子类以触发有限退避重试）。

    设计动机：消费框架需要在"暂时性失败、值得有限次重试"与"终态失败、重试无意义"
    之间分流。框架层只识别 ``RetriableError``——业务侧（如 ParseResultNotifier）
    把"通知发送失败但解析终态已确定"归入此基类，其余从 Pipeline 兜底之外逃出的异常
    一律视为终态，直接进入死信兜底而不再重试。
    """
    pass
