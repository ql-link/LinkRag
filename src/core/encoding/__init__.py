"""编码命名空间：文本到向量的编码器，不含索引/存储职责。

- ``sparse``  BGE-M3 稀疏向量编码（本地/HTTP/远程三种 encoder 与服务装配）

索引侧（``SparseIndexingPipeline`` / ``SparseRetriever``）位于
``src.core.storage.vector``；本命名空间只产出向量，不接触存储底座，
因此与 ``src.core.storage`` 之间是单向依赖（storage → encoding）。
"""
