"""召回 pipeline 自定义异常。"""


class RecallError(Exception):
    """召回流程失败。

    触发条件：
    - 严格模式下任一路抛异常；
    - 宽松模式下"已装配的全部路"都抛异常。
    """


class RecallValidationError(Exception):
    """召回入参校验失败。

    触发条件：
    - query 为空或纯空白。
    """


class RecallFatalError(RecallError):
    """致命召回失败：必须让整个召回请求失败，**绕过宽松降级**。

    与普通单路失败的区别：普通失败在宽松模式下只把该路计入 ``failed_sources`` 并继续融合
    其余路；``RecallFatalError`` 表示前置必备条件缺失（当前唯一来源：发起用户无默认 EMBEDDING
    配置，dense 路无法编码 query），即便宽松模式 ``_check_failures`` 也立即重抛，由路由映射为
    明确错误码返回。由 ``DenseRetriever`` 在捕获 ``VectorRetrievalUserConfigMissingError`` 后抛出。
    """
