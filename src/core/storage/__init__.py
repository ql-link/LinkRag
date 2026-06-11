"""存储命名空间：索引与持久化的统一入口。

子包按存储介质/职责划分：

- ``chunks``  Chunk SQL 事实存储（真值源/状态机，MySQL）
- ``qdrant``  Qdrant 向量索引底座（collection 路由/Point 读写）
- ``es``      ES 索引入库 + BM25 召回
- ``vector``  向量存储编排层（dense/sparse 索引流水线、召回 facade）

依赖方向：``vector`` 编排层组合 ``chunks``/``qdrant``，并调用
``src.core.encoding`` 完成向量编码；编码模块不反向依赖本命名空间。
"""
