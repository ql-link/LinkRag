"""文档删除链路（LINK-55）。

消费 Java 的删除通知（``tolink.rag.document_delete``），清理解析域全部衍生产物：
解析表 + chunk 真值行 + Qdrant 向量点 + ES 索引 + OSS 解析产物（Markdown / 图片）。
不触碰原文件（行由 Java 软删保留、OSS 原文件对象由 Java 保留）。
"""

from src.core.pipeline.document_delete.purger import DocumentDeletePurger

__all__ = ["DocumentDeletePurger"]
