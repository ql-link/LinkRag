# Qdrant Schema

Qdrant 向量库的 collection 命名、分桶规则、point 结构与 payload 索引参考。

**代码权威来源**：
- 路由：[src/core/storage/qdrant/bucket_router.py](../../../src/core/storage/qdrant/bucket_router.py)
- 常量：[src/core/storage/qdrant/constants.py](../../../src/core/storage/qdrant/constants.py)
- Collection 管理：[src/core/storage/qdrant/qdrant_store.py](../../../src/core/storage/qdrant/qdrant_store.py)
- Point 构造：[src/core/storage/qdrant/point_factory.py](../../../src/core/storage/qdrant/point_factory.py)
- BM25 独立存储：[src/core/storage/qdrant_bm25/store.py](../../../src/core/storage/qdrant_bm25/store.py)

当前向量存储固定使用 Qdrant，`VECTOR_STORE_TYPE=qdrant` 同时控制 readiness 的 Qdrant 探测。

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
| `QDRANT_HOST` / `QDRANT_PORT` / `QDRANT_GRPC_PORT` | 连接信息 |
| `QDRANT_API_KEY` | 鉴权 token |
| `QDRANT_HTTPS` | 是否使用 HTTPS；与 API key 独立配置 |
| `QDRANT_TIMEOUT_SECONDS` | 操作超时，默认 20 秒 |

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
| `vector` | named dense / named sparse vector | 稠密向量默认名称 `dense`；稀疏向量默认名称 `sparse_text`。两者通过 `update_vectors` 独立写入 |
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

启用稀疏向量后，`QdrantIndexStore.ensure_sparse_vector_schema` 会在既有 bucket collection 上确认 named sparse vector schema，默认 vector name 为 `sparse_text`。

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

**写读不变量**：bucket 路由、vector name、payload 字段、稀疏 encoder 实例写入与召回共用同一套，不允许分叉。

### Dense 召回

召回链路通过 `VectorStorageFacade.search_dense_chunks` 发起稠密向量搜索，底层同样由 `QdrantIndexStore._search_chunks` 执行（与 sparse 共用底座，spec dispatch 区分 `SparseQueryVectorSpec` / `DenseQueryVectorSpec`）。

**关键差异（与旧 schema 对比）**：dense 现在是 **named vector**，默认名称来自 `DENSE_VECTOR_QDRANT_VECTOR_NAME=dense`。写入侧 `ensure_collection` 使用 `vectors_config={"dense": VectorParams(size=1024, distance=COSINE)}`，并通过 `update_vectors({"dense": [...]})` 写入；召回侧 `query_points` 调用时 `using="dense"`、`query` 直接给 `list[float]`。

**SDK 调用形态**（qdrant-client 1.17.1）：

```python
response = await client.query_points(
    collection_name="kb_bucket_42",
    query=[0.1, 0.2, ...],            # list[float]，长度 = 数据集绑定 EMBEDDING 模型输出维度（当前要求 1024）
    using="dense",                     # named dense vector，与写入侧同源
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
| named dense vector 未配置 | 返空 hits，不抛；warn 日志带 `bucket_id` + vector name（通常表示旧匿名 dense collection 尚未迁移） |
| Qdrant 网络故障 / 超时 | 抛 `QdrantStoreError`，由 facade 翻译为 `VectorRetrievalBackendError`（与 sparse 一致） |
| 数据集绑定 embedding HTTP 推理失败 | facade 翻译为 `VectorRetrievalEncodingError` |

**写读不变量**：bucket 路由、payload 字段、dense vector name、`embedding_model` 字符串、`embedder` 实例写入与召回共用同一套。dense vector name 由 `DENSE_VECTOR_QDRANT_VECTOR_NAME` 统一控制，默认 `dense`。

**Embedding 模型升级**：详见 [docs/internals/vectorization.md §9.7](../../internals/vectorization.md)。当前锁定 Qwen `text-embedding-v4`（对称模型，dim=1024）。

### 补偿时的 named-vector 精确操作

dense 与 sparse 共用一个 point，但补偿状态彼此独立，不能用“point 是否存在”代替某一路向量是否存在：解析 DAG 会先创建只有 payload 的空 point，这类 point 对 dense、sparse 都应判为缺失。

- `get_named_vector_presence(bucket_id, chunk_ids, vector_name)` retrieve 时只请求目标 named vector，并检查返回 vector map 中是否包含该 key。collection、schema、point 不存在均返回 `False`。
- `delete_named_vectors(...)` 调用 Qdrant `delete_vectors`，只删除目标 named vector；payload 与 sibling vector 保留。collection、point 或目标 vector 已不存在时视为幂等成功。
- `delete_points(...)` 会删除完整 point，只允许用于业务文档删除等明确需要同时清理 dense/sparse 的路径，不得用于单路补偿。

正常 dense / sparse 写分别持有自己的 MySQL `(doc_id, branch)` 锁；repair 即使只清理一个 named vector，也因共用 point 固定同时取得 `DENSE → SPARSE`，文档删除则继续按 `DENSE → SPARSE → BM25` 取锁。锁内 current-task SELECT 使用共享行锁且事务保持到 mutation guard 退出，从而阻止 Java 在外部 mutation 中途切换 `latest_parse_task_id`。

正常写入失败时，写入链路使用当前 chunk 的 `bucket_id` 和 `chunk_id` 同步删除对应 named vector；不会持久化补偿任务或自动 rebuild。

### Qdrant BM25 补偿边界

Qdrant BM25 使用独立 sparse-only collection，不与上述 dense/sparse bucket point 共用物理载体。它与 Elasticsearch 采用相同的文档级一致性语义：按 `user_id + dataset_id + doc_id` filter 清理整篇，再从 MySQL ACTIVE chunk 全量重建。repair 的 inspect、cleanup 与 rebuild 都使用 job 创建时保存的 `artifact_name` 作为 collection 名，不能在执行时跟随当前配置切到另一个 collection。`point_exists(chunk_id)` 只用于核对和指标，不用于回填 MySQL `es_status=SUCCESS`。

## 一致性约束

- **MySQL 为真值**：`kb_document_chunk` 是 Chunk 真值表，可从中重建 Qdrant 数据。
- **id 一致**：`chunk_id` 同时作为 MySQL UK 与 Qdrant Point ID。
- **bucket_id 同步**：MySQL 的 `bucket_id` 字段必须与 Qdrant 实际 collection 一致，由统一的 `BucketRouter` 计算。
- **状态分离**：`kb_document_chunk.dense_vector_status`、`sparse_vector_status` 是向量侧粗粒度产物状态（`PENDING/SUCCESS/FAILED`），`es_status` 是 BM25 侧产物状态，`lifecycle_status` 是 chunk 是否有效的生命周期权威。三路状态用于诊断与补偿，不是文档可见性聚合字段。
- **MySQL 单向权威**：Qdrant 实际存在只作诊断，不能反向把 MySQL 状态标为成功。外部存在但 MySQL 未确认时必须精确 cleanup，再从 MySQL rebuild；payload-only point 不能证明 dense 或 sparse 成功。
- **稀疏向量一致性**：同一 chunk 的 dense 和 sparse 使用相同 Point ID；单路 cleanup 只能删除自己的 named vector，不影响 sibling。
- **当前任务与门禁**：补偿扫描只处理 `latest_parse_task_id` 对应且明确失败的 current pipeline，不凭 chunk 共享 `update_time` 推断写入结束。防御性缺失重建期间仅由 `source_task_id` 等于当前 `latest_parse_task_id` 的 `visibility_hold` 阻断召回，旧 task 的 hold 不隐藏新 current task。

## 常见操作

| 操作 | 实现位置 |
| --- | --- |
| 写入 Chunk 向量 | `QdrantStore.upsert_points` |
| 写入 Chunk 稀疏向量 | `QdrantStore.upsert_sparse_vectors` |
| 确认稀疏向量 schema | `QdrantStore.ensure_sparse_vector_schema` |
| 检查目标 named vector 是否存在 | `QdrantStore.get_named_vector_presence` |
| 精确删除单路 named vector | `QdrantStore.delete_named_vectors` |
| 检查完整 Point 是否存在 | `QdrantStore.point_exists`（不能证明任一路向量成功） |
| 删除 Chunk | `QdrantStore.delete_points` |
| Qdrant BM25 文档级删除 | `QdrantBm25Store.delete_by_document` |
| Qdrant BM25 point 核对 | `QdrantBm25Store.point_exists` |
| **稀疏向量召回** | **`QdrantStore._search_chunks`（私有底座，由 `VectorStorageFacade.search_sparse_chunks` 调用）** |
| **稠密向量召回** | **`QdrantStore._search_chunks`（同一底座，由 `VectorStorageFacade.search_dense_chunks` 调用，`using=DENSE_VECTOR_QDRANT_VECTOR_NAME`）** |
| 用户路由 | `BucketRouter.route_user(user_id)` |
| 按 bucket 取 collection 名 | `BucketRouter.collection_name(bucket_id)` |

## 相关文档

- 关系数据：[mysql_schema.md](mysql.md)
- BM25 评测：[bm25_eval.md](../../internals/bm25_eval.md)
- 向量化模块架构：[../internals/vectorization.md](../../internals/vectorization.md)
- 配置项详解：[../ops/configure.md](../../ops/configure.md)
