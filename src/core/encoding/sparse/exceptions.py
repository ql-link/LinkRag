"""定义稀疏向量模块的业务异常。"""


class SparseVectorError(Exception):
    """稀疏向量模块的基础异常。"""


class SparseVectorConfigurationError(SparseVectorError):
    """配置缺失、本地模型不可用或推理设备不可用时抛出。"""


class SparseVectorEncodingError(SparseVectorError):
    """BGE-M3 编码调用失败或返回结构不符合预期时抛出。"""


class SparseVectorOutputError(SparseVectorEncodingError):
    """BGE-M3 返回空向量、非法权重或无法写入 Qdrant 的稀疏结果时抛出。"""
