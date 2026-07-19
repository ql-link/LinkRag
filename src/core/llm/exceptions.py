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


class LLMConfigResolutionError(ConfigurationException):
    """精确 config_id 解析失败基类。"""

    code = "LLM_CONFIG_ERROR"
    http_status = 400

    def __init__(self, config_id: int, message: str) -> None:
        self.config_id = config_id
        super().__init__(message)


class LLMConfigNotFoundError(LLMConfigResolutionError):
    code = "LLM_CONFIG_NOT_FOUND"
    http_status = 404

    def __init__(self, config_id: int) -> None:
        super().__init__(config_id, f"LLM config {config_id} does not exist")


class LLMConfigInactiveError(LLMConfigResolutionError):
    code = "LLM_CONFIG_INACTIVE"
    http_status = 409

    def __init__(self, config_id: int) -> None:
        super().__init__(config_id, f"LLM config {config_id} is inactive")


class LLMConfigForbiddenError(LLMConfigResolutionError):
    code = "LLM_CONFIG_FORBIDDEN"
    http_status = 403

    def __init__(self, config_id: int) -> None:
        super().__init__(config_id, f"LLM config {config_id} is not accessible by this user")


class LLMConfigCapabilityMismatchError(LLMConfigResolutionError):
    code = "LLM_CONFIG_CAPABILITY_MISMATCH"
    http_status = 400

    def __init__(self, config_id: int, expected: str, actual: str) -> None:
        self.expected_capability = expected
        self.actual_capability = actual
        super().__init__(
            config_id,
            f"LLM config {config_id} capability mismatch: expected {expected}, got {actual}",
        )


class DatasetModelBindingRequiredError(ConfigurationException):
    """Dataset 在当前用途下缺少必要的精确配置绑定。"""

    code = "DATASET_MODEL_BINDING_REQUIRED"
    http_status = 409

    def __init__(self, dataset_id: int, missing_bindings: list[str]) -> None:
        self.dataset_id = dataset_id
        self.missing_bindings = missing_bindings
        super().__init__(
            f"Dataset {dataset_id} is missing required model bindings: "
            + ",".join(missing_bindings)
        )


class UnsupportedProtocolCapabilityError(ConfigurationException):
    """(protocol, capability) 组合本期未实现。

    执行端按 ``protocol`` 选 adapter、按 ``capability`` 选能力分支；请求的 capability
    不在该 protocol 的能力集合内时抛出，不静默降级、不回退猜测。对应 acceptance 的
    ``UNSUPPORTED_PROTOCOL_CAPABILITY``。
    """

    def __init__(
        self,
        protocol: str,
        capability: str,
        *,
        model_name: str | None = None,
        config_id: int | str | None = None,
        supported_combinations: list[str] | None = None,
    ) -> None:
        self.protocol = protocol
        self.capability = capability
        self.model_name = model_name
        self.config_id = config_id
        self.supported_combinations = supported_combinations or []

        details = [
            f"protocol='{protocol}'",
            f"capability='{capability}'",
        ]
        if model_name is not None:
            details.append(f"model_name='{model_name}'")
        if config_id is not None:
            details.append(f"config_id='{config_id}'")
        if self.supported_combinations:
            details.append("supported=" + ",".join(self.supported_combinations))
        super().__init__("Unsupported LLM protocol/capability combination: " + "; ".join(details))


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
