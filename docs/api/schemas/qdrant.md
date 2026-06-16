# Qdrant Schema

Qdrant 向量库的 collection 命名、分桶规则、point 结构与 payload 索引参考。

**代码权威来源**：
- 路由：[src/core/storage/qdrant/bucket_router.py](../../../src/core/storage/qdrant/bucket_router.py)
- 常量：[src/core/storage/qdrant/constants.py](../../../src/core/storage/qdrant/constants.py)
- Collection 管理：[src/core/storage/qdrant/qdrant_store.py](../../../src/core/storage/qdrant/qdrant_store.py)
- Point 构造：[src/core/storage/qdrant/point_factory.py](../../../src/core/storage/qdrant/point_factory.py)

启用条件：`VECTOR_STORE_TYPE=qdrant`。

## Collection 命名与分桶

Qdrant 不使用单一 collection，而是按用户 ID **哈希分桶**到多个 collection。

### 路由规则

```python
bucket_id = zlib.crc32(str(user_id).encode("utf-8")) % bucket_count
collection_name = f"{prefix}_{bucket_id}"
```

### 默认参数

| 参数 | 默认值 | 来源 |
| --- | --- | --- |
| `bucket_count` | **128** | `DEFAULT_BUCKET_COUNT` |
| `prefix` | `kb_bucket` | `DEFAULT_COLLECTION_PREFIX` / `CHUNK_INDEX_COLLECTION_PREFIX` |

Collection 名称示例：`kb_bucket_0`, `kb_bucket_1`, ..., `kb_bucket_127`。

### 配置覆盖

| 环境变量 | 用途 |
| --- | --- |
| `CHUNK_INDEX_BUCKET_COUNT` | 覆盖 bucket 总数 |
| `CHUNK_INDEX_COLLECTION_PREFIX` | 覆盖 collection 前缀 |
| `QDRANT_COLLECTION_NAME` | 全局兜底 collection 名（非分桶场景） |
| `QDRANT_HOST` / `QDRANT_PORT` / `QDRANT_GRPC_PORT` | 连接信息 |
| `QDRANT_API_KEY` | 鉴权 token |
| `QDRANT_TIMEOUT_SECONDS` | 操作超时，默认 5 秒 |

### 分桶的设计目的

- **同一用户的所有 Chunk** 落在**同一 collection**（路由键是 `user_id`）。
- 同 collection 内可按 `set_id` / `doc_id` 进一步过滤（payload 索引支持）。
- 避免单一 collection 数据量过大导致查询性能下降。
- bucket 数量 **不可在线修改**——一旦改动，已存数据的路由位置会偏移。

## Collection 配置

每个 collection 由首次写入时按需创建（见 `qdrant_store.ensure_collection`）：

| 参数 | 值 |
| --- | --- |
| Vector size | 由 `vector_size` 入参指定（来自 embedding 模型，无硬编码默认） |
| Distance | `Cosine` |

## Point 结构

每个 Chunk 在 Qdrant 中是一个 **Point**，结构定义见 [IndexedPoint](../../../src/core/storage/qdrant/models.py)：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | Point ID = `chunk_id`，与 MySQL `kb_document_chunk.chunk_id` 一致 |
| `vector` | float[] / named sparse vector | 稠密 embedding 向量；启用稀疏向量后，同一 point 还会写入 named sparse vector，默认名称 `sparse_text` |
| `payload` | object | 业务标识，见下表 |

### Payload 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_id` | string | 与 Point ID 重复，便于跨库 join |
| `user_id` | int | 数据隔离主键 |
| `set_id` | int | 数据集 / 知识集 ID |
| `doc_id` | int | 文档 ID（原始文件） |

> **不下放业务内容到 payload**：`content` / `chunk_type` / `start_line` / `metadata` 等都留在 MySQL，Qdrant 仅承担"向量检索 + 业务过滤"。

### Payload 索引

写入前自动创建以下 payload 索引（INTEGER 类型），用于过滤查询：

```
user_id, set_id, doc_id
```

来源：`QDRANT_PAYLOAD_INDEX_FIELDS` 常量。

### 索引创建幂等性

`QdrantStore` 内部维护 `_payload_index_ready_collections` 集合，确保 payload index 在进程生命周期内只为每个 collection 创建一次。重启进程后会再次创建，Qdrant 端已存在时不影响。

### Sparse Vector

启用 BGE-M3 稀疏向量后，`QdrantIndexStore.ensure_sparse_vector_schema` 会在既有 bucket collection 上确认 named sparse vector schema，默认 vector name 为 `sparse_text`。

写入时使用 `QdrantIndexStore.upsert_sparse_vectors`，通过 Qdrant `update_vectors` 对同一 `point_id=chunk_id` 追加或覆盖 sparse vector，不覆盖已存在的 dense vector 与 payload。

### Sparse 召回

召回链路通过 `VectorStorageFacade.search_sparse_chunks` 发起稀疏向量搜索，底层由 `QdrantIndexStore._search_chunks` 执行（私有方法，向量类型无关底座，未来 dense / hybrid 召回复用同一底座）。

**SDK 调用形态**（qdrant-client 1.17.1，旧版 `search` 已移除）：

```python
response = await client.query_points(
    collection_name="kb_bucket_42",
    query=models.SparseVector(indices=[...], values=[...]),
    using="sparse_text",          # named sparse vector，与写入侧同源
    query_filter=models.Filter(
        must=[
            models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
            models.FieldCondition(key="set_id",  match=models.MatchValue(value=set_id)),
            # doc_id 可选，非空时用 MatchAny
        ]
    ),
    limit=top_k,
    score_threshold=score_threshold,
    with_payload=True,
    with_vectors=False,
)
```

**容错语义**（与写入侧一致）：

| 场景 | 处理 |
| --- | --- |
| collection 不存在 | 返空 hits，不抛；warn 日志带 `bucket_id` |
| named sparse vector 未配置 | 返空 hits，不抛；warn 日志带 `bucket_id` + `vector_name` |
| Qdrant 网络故障 / 超时 | 抛 `QdrantStoreError`，由 facade 翻译为 `VectorRetrievalBackendError` |

**写读不变量**：bucket 路由、vector name、payload 字段、BGE-M3 encoder 实例写入与召回共用同一套，不允许分叉。

### Dense 召回

召回链路通过 `VectorStorageFacade.search_dense_chunks` 发起稠密向量搜索，底层同样由 `QdrantIndexStore._search_chunks` 执行（与 sparse 共用底座，spec dispatch 区分 `SparseQueryVectorSpec` / `DenseQueryVectorSpec`）。

**关键差异（与 sparse 对比）**：dense 是 **unnamed** vector——写入侧 `ensure_collection` 用 `vectors_config=VectorParams(size=1024, distance=COSINE)`（不是 `{name: VectorParams}` dict），`PointStruct(vector=[...])` 裸传；召回侧 `query_points` 调用时 `using=None`、`query` 直接给 `list[float]`。

**SDK 调用形态**（qdrant-client 1.17.1）：

```python
response = await client.query_points(
    collection_name="kb_bucket_42",
    query=[0.1, 0.2, ...],            # list[float]，长度 = SYSTEM_LLM_MODEL_EMBEDDING 输出维度（1024）
    using=None,                        # dense 是 unnamed vector，**不传 vector name**
    query_filter=models.Filter(
        must=[
            models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
            models.FieldCondition(key="set_id",  match=models.MatchValue(value=set_id)),
            # doc_id 可选，非空时用 MatchAny
        ]
    ),
    limit=top_k,
    score_threshold=score_threshold,   # cosine 上界 [0, 1]
    with_payload=True,
    with_vectors=False,
)
```

**容错语义**（与 sparse 共用，仅以下一项不同）：

| 场景 | 处理 |
| --- | --- |
| collection 不存在 | 返空 hits，不抛；warn 日志带 `bucket_id`（与 sparse 一致） |
| named vector 未配置 | **不会触发**——dense 是 collection 创建时配齐的 unnamed vector，无中间状态 |
| Qdrant 网络故障 / 超时 | 抛 `QdrantStoreError`，由 facade 翻译为 `VectorRetrievalBackendError`（与 sparse 一致） |
| system embedding HTTP 推理失败 | facade 翻译为 `VectorRetrievalEncodingError` |

**写读不变量**：bucket 路由、payload 字段、`embedding_model` 字符串、`embedder` 实例写入与召回共用同一套；**不引入 `DENSE_RETRIEVAL_VECTOR_NAME` 配置**——dense 永远 unnamed，避免分叉风险。

**Embedding 模型升级**：详见 [docs/internals/vectorization.md §9.7](../../internals/vectorization.md)。当前锁定 Qwen `text-embedding-v4`（对称模型，dim=1024）。

## 一致性约束

- **MySQL 为真值**：`kb_document_chunk` 是 Chunk 真值表，可从中重建 Qdrant 数据。
- **id 一致**：`chunk_id` 同时作为 MySQL UK 与 Qdrant Point ID。
- **bucket_id 同步**：MySQL 的 `bucket_id` 字段必须与 Qdrant 实际 collection 一致，由统一的 `BucketRouter` 计算。
- **状态分离**：`kb_document_chunk.dense_vector_status`、`sparse_vector_status` 是向量侧粗粒度产物状态（`PENDING/SUCCESS/FAILED`），`es_status` 是 ES 侧产物状态，`lifecycle_status` 是 chunk 是否有效的生命周期权威。Qdrant 实际存在状态不直接作为业务真值；失败重试和召回回表以 MySQL 状态决定是否重做或返回。
- **稀疏向量一致性**：同一 chunk 的 dense 和 sparse 使用相同 Point ID；Qdrant 写入成功但 MySQL 回写失败时，以 MySQL 状态阻断文件级成功和后续检索返回。

## 常见操作

| 操作 | 实现位置 |
| --- | --- |
| 写入 Chunk 向量 | `QdrantStore.upsert_points` |
| 写入 Chunk 稀疏向量 | `QdrantStore.upsert_sparse_vectors` |
| 确认稀疏向量 schema | `QdrantStore.ensure_sparse_vector_schema` |
| 检查 Chunk 是否存在 | `QdrantStore.point_exists` |
| 删除 Chunk | `QdrantStore.delete_points` |
| **稀疏向量召回** | **`QdrantStore._search_chunks`（私有底座，由 `VectorStorageFacade.search_sparse_chunks` 调用）** |
| **稠密向量召回** | **`QdrantStore._search_chunks`（同一底座，由 `VectorStorageFacade.search_dense_chunks` 调用，`using=None`）** |
| 用户路由 | `BucketRouter.route_user(user_id)` |
| 按 bucket 取 collection 名 | `BucketRouter.collection_name(bucket_id)` |

## 相关文档

- 关系数据：[mysql_schema.md](mysql.md)
- 全文索引：[elasticsearch_schema.md](elasticsearch.md)
- 向量化模块架构：[../internals/vectorization.md](../../internals/vectorization.md)
- 配置项详解：[../ops/configure.md](../../ops/configure.md)
