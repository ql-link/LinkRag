"""定义向量存储模块的自定义异常类型。"""


class VectorStorageError(Exception):
    """
        定义向量存储模块的基础异常类型，统一承载模块级业务错误。

    Args:
        None.

    Returns:
        None.
    """


class VectorStorageConfigurationError(VectorStorageError):
    """
        表示向量存储配置不完整、依赖缺失或运行参数非法等初始化错误。

    Args:
        None.

    Returns:
        None.
    """
