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
