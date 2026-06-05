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
