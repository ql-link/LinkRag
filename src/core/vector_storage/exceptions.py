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


class ChunkRepositoryError(VectorStorageError):
    """
        表示底层 MySQL 持久化操作失败时抛出的仓储层异常。

    Args:
        None.

    Returns:
        None.
    """


class QdrantStoreError(VectorStorageError):
    """
        表示 Qdrant collection 或 point 操作失败时抛出的存储异常。

    Args:
        None.

    Returns:
        None.
    """
