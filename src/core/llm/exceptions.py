"""
自定义异常体系
"""


class LLMException(Exception):
    """LLM 模块异常基类"""

    def __init__(self, message: str = "", **kwargs):
        self.message = message
        self.provider_type = kwargs.get("provider_type")
        self.provider_name = kwargs.get("provider_name")
        super().__init__(self.message)

    def __str__(self):
        parts = [self.message]
        if self.provider_type:
            parts.append(f"(provider={self.provider_type})")
        return " ".join(parts)


class ProviderException(LLMException):
    """Provider 相关异常"""
    pass


class AuthenticationError(ProviderException):
    """认证失败（API Key 无效等）"""
    pass


class RateLimitError(ProviderException):
    """限流异常"""
    pass


class ProviderConnectionError(ProviderException):
    """Provider 连接异常"""
    pass


class InvalidResponseError(ProviderException):
    """无效响应异常"""
    pass


class ConfigurationException(LLMException):
    """配置相关异常"""
    pass


class ConfigNotFoundError(ConfigurationException):
    """配置未找到"""
    pass


class UserModelConfigMissingError(ConfigurationException):
    """发起用户缺少指定能力的默认 LLM 配置。

    统一用户模型解析（``user_model_resolver``）在「未启用系统兜底且用户无该能力默认配置」时
    抛出。各领域调用点可在边界捕获后重抛自己的领域异常（如 ``DenseEmbeddingConfigMissingError`` /
    ``LLMConfigMissingError``）以保留既有失败码映射。``capability`` 为配置表能力字符串
    （CHAT / EMBEDDING / RERANK / VISION / OCR）。
    """

    def __init__(self, capability: str, user_id: int) -> None:
        self.capability = capability
        self.user_id = user_id
        super().__init__(
            f"User {user_id} has no default {capability} config",
        )


class ProtocolRequiredError(ConfigurationException):
    """用户配置缺少必填的 protocol 字段。

    协议化分发以 ``protocol`` 为必填事实列：运行期读到空 / NULL 直接 fail fast，
    **不按 provider_type 兜底推导**（与三层语义"绝不 fallback"一致）。存量缺
    protocol 的行应由运维上线前清理 / 回填。对应 acceptance 的 ``PROTOCOL_REQUIRED``。
    """

    def __init__(self, capability: str | None = None, user_id: int | None = None) -> None:
        self.capability = capability
        self.user_id = user_id
        super().__init__("LLM config missing required 'protocol'")


class UnsupportedProtocolCapabilityError(ConfigurationException):
    """(protocol, capability) 组合本期未实现。

    执行端按 ``protocol`` 选 adapter、按 ``capability`` 选能力分支；请求的 capability
    不在该 protocol 的能力集合内时抛出，不静默降级、不回退猜测。对应 acceptance 的
    ``UNSUPPORTED_PROTOCOL_CAPABILITY``。
    """

    def __init__(self, protocol: str, capability: str) -> None:
        self.protocol = protocol
        self.capability = capability
        super().__init__(
            f"protocol '{protocol}' does not support capability '{capability}'"
        )


class InvalidConfigError(ConfigurationException):
    """无效配置"""
    pass


class CircuitBreakerOpenError(LLMException):
    """熔断器开启异常"""
    pass


class AllProvidersFailedError(LLMException):
    """所有 Provider 都失败"""
    pass


class TokenLimitExceededError(LLMException):
    """Token 超出限制"""
    pass
