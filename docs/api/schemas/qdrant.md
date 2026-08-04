# Qdrant Schema

Qdrant 只承载业务 chunk 的稠密向量与 learned sparse 向量。BM25 固定由 Manticore 承载，不再写入或查询 Qdrant。

权威实现：

- [qdrant_store.py](../../../src/core/storage/qdrant/qdrant_store.py)
- [models.py](../../../src/core/storage/qdrant/models.py)
- [point_factory.py](../../../src/core/storage/qdrant/point_factory.py)

## Collection

所有知识库、数据集和用户统一写入一个 collection，名称由 `CHUNK_INDEX_COLLECTION_NAME` 指定，默认 `tolink_rag_chunks`。不再按 `user_id` 或知识库计算 bucket，也不存在运行时 collection 路由。

collection 使用两个 named vector：

| 名称 | 类型 | 配置 |
| --- | --- | --- |
| `dense` | dense cosine vector | `DENSE_VECTOR_QDRANT_VECTOR_NAME`、`DENSE_VECTOR_DIMENSION` |
| `sparse_text` | learned sparse vector | `SPARSE_VECTOR_QDRANT_VECTOR_NAME` |

dense 与 sparse 共用相同 point id，二者可以独立写入。写入使用 `update_vectors`，不会覆盖另一个 named vector。

## Point 与 payload

point id 等于 `chunk_id`。payload 至少包含：

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `chunk_id` | string | chunk 标识 |
| `user_id` | integer | 租户过滤 |
| `set_id` | integer | 数据集过滤 |
| `doc_id` | integer | 文档过滤和删除 |
| `chunk_type` | string | 类型过滤或重排 |
| `chunk_index` | integer | 文档内顺序 |
| `content_hash` | string | 内容一致性核对 |

单 collection 下的数据隔离完全依赖 payload filter。dense 与 sparse 查询都必须至少带 `user_id` 和 `set_id` 的 `must` 条件；按文档操作时再附加 `doc_id`。

## 写入与删除语义

- `ensure_collection` 创建固定业务 collection，并校验 dense named vector schema。
- `ensure_points` 只保证 point 与 payload 存在。
- `upsert_points` 写入 dense named vector。
- `upsert_sparse_vectors` 写入 learned sparse named vector。
- `delete_named_vectors` 只移除目标 named vector，保留 sibling vector 和 payload。
- `delete_points` 按 chunk id 删除整个 point；collection 不存在按幂等成功处理。

collection、named vector 或 point 不存在时，召回返回空 hits；Qdrant 连接、鉴权或协议错误才转换为后端异常。

## 变更约束

- 修改 `CHUNK_INDEX_COLLECTION_NAME` 等价于切换物理索引，必须先完成数据迁移和对账。
- 修改 dense 维度或距离度量必须重建 collection。
- 不允许恢复按用户或知识库动态创建 collection 的逻辑。
- MySQL 不保存 Qdrant collection/bucket 路由字段；MySQL 是 chunk 真值源，Qdrant 是可重建索引。
