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


# ============================================================================
# 召回侧公共异常族（本次新增）
#
# 设计意图：facade 召回入口抛出的所有异常都继承自 VectorRetrievalError；
# 调用方一处 catch 即可处理所有召回失败模式，**不需要 import 任何
# qdrant_vector_storage / sparse_vector 子包的异常类**。
#
# 底层 SparseVectorEncodingError / QdrantStoreError /
# QdrantVectorStorageConfigurationError 等仍然存在（写入路径用），但只在
# facade 内部出现；facade 通过 raise NewError(...) from exc 翻译并保留 traceback。
# ============================================================================


class VectorRetrievalError(VectorStorageError):
    """召回侧公共异常基类。

    所有由 ``VectorStorageFacade.search_sparse_chunks``（含未来的
    ``search_dense_chunks`` / ``search_hybrid_chunks``）抛出的异常都继承自本类。
    调用方用 ``except VectorRetrievalError`` 一处捕获即可。
    """


class VectorRetrievalConfigurationError(VectorRetrievalError):
    """配置错误：依赖缺失、Qdrant URL 无效、SPARSE_VECTOR_ENABLED=False 等。

    由 facade 把底层 ``SparseVectorConfigurationError`` /
    ``QdrantVectorStorageConfigurationError`` 翻译而来。这类错误对应"部署侧
    配置问题"，**不应**静默返空，避免掩盖运维问题。
    """


class VectorRetrievalBackendError(VectorRetrievalError):
    """底层存储故障：Qdrant 网络 / 超时 / 服务不可用。

    由 facade 把底层 ``QdrantStoreError`` 翻译而来。调用方决定降级或重试。
    """


class VectorRetrievalEncodingError(VectorRetrievalError):
    """查询编码失败：BGE-M3 推理异常等。

    由 facade 把底层 ``SparseVectorEncodingError`` /
    ``SparseVectorOutputError`` 翻译而来。
    """


class VectorRetrievalUserConfigMissingError(VectorRetrievalError):
    """召回 dense 路：发起用户缺少默认 EMBEDDING 配置。

    dense 召回 query 编码改为按发起用户的 EMBEDDING 配置解析（与写入侧同源）。用户无默认
    EMBEDDING 配置时，facade 把统一解析层的 ``UserModelConfigMissingError`` /
    ``DenseEmbeddingConfigMissingError`` 翻译为本异常。区别于一般召回失败：这是**必配缺失**，
    上层（``DenseRetriever`` → recall pipeline）据此走硬失败、不做宽松降级。
    """
