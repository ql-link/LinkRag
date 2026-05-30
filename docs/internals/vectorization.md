# Vectorization Module

本文说明 Chunk 向量化、向量存储、文件级 ES 入库和后处理状态模块的架构、使用方式，以及新增或修改索引逻辑的方法。

## 1. 模块框架

```text
src/core/splitter/
└── embedding_pipeline.py          # Chunk 批量 embedding 与缓存

src/core/vector_storage/
├── factory.py                     # 装配向量存储 Facade
├── facade.py                      # 对外统一入口
├── pipeline.py                    # 已落库 chunk 的向量索引闭环
├── management_pipeline.py         # 修改、删除管理
├── compensation_pipeline.py       # 失败和卡住状态补偿
├── draft_factory.py               # Chunk -> StoredChunkDraft
├── models.py                      # 请求和结果模型
└── repair_policy.py               # 补偿决策

src/core/es_index_storage/
├── models.py                      # ES 入库结果模型
└── pipeline.py                    # 文件级 Elasticsearch 入库阶段

src/core/chunk_fact_storage/
├── constants.py                   # Chunk 状态常量
├── models.py                      # Chunk 真值草稿模型
└── repository.py                  # MySQL 真值表仓储

src/core/qdrant_vector_storage/
├── bucket_router.py               # user_id 分桶和 collection 命名
├── point_factory.py               # draft/record -> Qdrant point
├── qdrant_store.py                # Qdrant 访问层（含召回底座 _search_chunks）
└── models.py                      # IndexedPoint / SparseIndexedPoint / SparseQueryVectorSpec
```

解析后向量化链路：

```text
ParseTaskPipeline
  -> StagePipeline
    -> CleaningStage
      -> StageServices.parse_file()
      -> upload markdown
    -> ChunkingStage
      -> StageServices.run_chunking()
      -> ChunkDraftFactory
      -> ChunkRepository.bulk_insert_pending()
    -> VectorizingStage
      -> StageServices.store_chunk_vectors()  # 现场过滤 dense_vector_status != SUCCESS
        -> VectorStorageFacade.index_chunks(chunks=...)
          -> VectorStoragePipeline.index_chunks(chunks=...)  # 接收已过滤 chunks，不自查 SQL
            -> 按 batch 处理（chunk_index 顺序）
              -> ChunkRepository.mark_indexing(allowed_statuses=(PENDING, FAILED))  # 多值 CAS
              -> ChunkEmbeddingPipeline.aembed_chunks(batch)
              -> QdrantIndexStore.ensure_collection()
              -> QdrantIndexStore.upsert_points()
              -> ChunkRepository.mark_indexed()
    -> PretokenizeStage
      -> StageServices.build_pretokenize_plan()
    -> EsIndexingStage
      -> StageServices.run_es_indexing()
    -> SparseVectorizingStage
      -> StageServices.run_sparse_vectorizing()
  -> document_parse_pipeline.sparse_vectorizing_status = SUCCESS（开启时）
  -> parse_result success notification
```

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `ChunkEmbeddingPipeline` | `splitter/embedding_pipeline.py` | 批量生成 Chunk embedding，支持缓存和统计 |
| `SparseVectorService` | `sparse_vector/pipeline.py` | 使用 BGE-M3 对 chunk 原文生成稀疏向量；`vectorize_query` 供召回侧使用 |
| `VectorStorageFacade` | `vector_storage/facade.py` | 向上游暴露统一入口；含写入、管理、补偿与**召回**（`search_sparse_chunks`） |
| `VectorStoragePipeline` | `vector_storage/pipeline.py` | 消费 SQL chunk 真值，写 dense Qdrant 索引副本并回写状态 |
| `VectorStorageManagementPipeline` | `vector_storage/management_pipeline.py` | Chunk 修改、删除 |
| `VectorStorageCompensationPipeline` | `vector_storage/compensation_pipeline.py` | 删除失败、INDEXING 卡住、FAILED 重建 |
| `ChunkDraftFactory` | `vector_storage/draft_factory.py` | 生成 chunk_id、content_hash、bucket_id、chunk_type |
| `ChunkRepository` | `chunk_fact_storage/repository.py` | MySQL Chunk 真值表读写和状态机 |
| `BucketRouter` | `qdrant_vector_storage/bucket_router.py` | 按 `user_id` 路由到 Qdrant collection；写入与召回共用 |
| `QdrantIndexStore` | `qdrant_vector_storage/qdrant_store.py` | Qdrant collection、point 写入、删除、查询；`_search_chunks` 为向量类型无关召回底座 |
| `EsIndexingPipeline` | `es_index_storage/pipeline.py` | 将文件级 Chunk 内容写入 Elasticsearch |
| `ParsePipelineRepository` | `pipeline/post_process_repository.py` | 维护 `document_parse_pipeline` 文件级阶段状态 |

## 3. 数据模型

### 3.1 输入模型

解析流水线使用 `VectorStorageFacade.index_chunks(chunks=...)`，接收 pipeline 已现场过滤好的 chunk 真值行：

```python
user_id: int            # 业务归属（日志可读用途）
set_id: int
doc_id: int
chunks: Sequence[ChunkRecordDB]   # pipeline 现场过滤：dense_vector_status != SUCCESS
```

该入口不接收 splitter `list[Chunk]`、不重新分片、不生成新 `chunk_id`、不执行 chunk 真值 INSERT，**也不再按 `doc_id` 自查 SQL**——待处理 chunk 由 `StageServices.store_chunk_vectors` 现场过滤后透传。每个 `ChunkRecordDB` 行携带：

- `content`：dense 和 sparse 的文本输入。
- `chunk_id`：Qdrant point id，重试时覆盖同一个索引副本。
- `user_id` / `set_id` / `doc_id` / `bucket_id`：Qdrant payload 与 collection/bucket 路由。
- `chunk_index` / `chunk_type` / `start_line` / `end_line`：还原 splitter 兼容 `Chunk`。
- `dense_vector_status` / `sparse_vector_status`：现场过滤口径。
- `lifecycle_status`：`_reload_chunks_from_db` 只反查 `ACTIVE` 行，删除态不进入向量化。

首次与人工重试共用同一入口：`store_chunk_vectors` 都过滤 `dense_vector_status != SUCCESS`
（首次为 `PENDING`，重试覆盖 `PENDING` + `FAILED`），dense 模块不感知场景类型。多值 CAS
`mark_indexing(allowed_statuses=(PENDING, FAILED))` 在 SQL 层兜底：若过滤口径错误把已
`SUCCESS` chunk 混入，UPDATE rowcount 不达预期进失败路径，不会把 SUCCESS chunk 拉回 INDEXING。
`FAILED` chunk 仍可由 `VectorStorageCompensationPipeline` 在补偿路径独立重建。

chunking 阶段复用 `ChunkDraftFactory`，把每个 `Chunk` 转成 `StoredChunkDraft`：

- `chunk_id`：新生成的 UUID。
- `user_id` / `set_id` / `doc_id`：业务归属。
- `bucket_id`：由 `BucketRouter.route_user(user_id)` 计算。
- `content_hash`：基于内容的 SHA-256。
- `chunk_type`：来自 `Chunk.metadata["element_types"]` 或默认 `text`。
- `chunk_index`：来自 `Chunk.metadata["chunk_index"]`。

### 3.2 MySQL 状态

主要状态来自 `src/core/chunk_fact_storage/constants.py`：

| 状态 | 含义 |
| --- | --- |
| `PENDING` | 真值记录已创建，等待进入索引 |
| `SUCCESS` | Qdrant point 已写入，MySQL 已确认 |
| `FAILED` | 向量化或索引失败 |

MySQL 是 Chunk 真值源，Qdrant 是向量索引副本。chunk 表中的稠密和稀疏向量状态使用 `PENDING/SUCCESS/FAILED` 粗粒度终态；代码中的 `INDEXED` 常量映射为数据库值 `SUCCESS`。`vectorizing_status` 只代表 dense/Qdrant 阶段成功；启用稀疏向量后，文件级整体成功还要求后续 `sparse_vectorizing_status=SUCCESS`，且每个有效 chunk 的 `sparse_vector_status=SUCCESS`。

稀疏向量子状态：

| 状态 | 含义 |
| --- | --- |
| `PENDING` | 等待稀疏向量处理 |
| `SUCCESS` | 稀疏向量已写入 Qdrant，MySQL 已确认 |
| `FAILED` | 稀疏模型调用、Qdrant 写入或状态回写失败 |

### 3.3 文件级后处理状态

`document_parse_pipeline` 记录一次解析成功落 Markdown 后的后处理阶段状态：

| 字段 | 含义 |
| --- | --- |
| `pipeline_status` | 整体状态：`PENDING/PROCESSING/SUCCESS/FAILED` |
| `chunking_status` | 分片阶段状态：`PENDING/PROCESSING/SUCCESS/FAILED` |
| `vectorizing_status` | 向量化/Qdrant 阶段状态：`PENDING/PROCESSING/SUCCESS/FAILED` |
| `es_indexing_status` | Elasticsearch 入库阶段状态：`PENDING/PROCESSING/SUCCESS/FAILED` |
| `failed_stage` | 失败阶段：`CHUNKING/VECTORIZING/ES_INDEXING` |
| `recover_from_stage` | 重投或补偿时可恢复的阶段 |
| `chunk_count` | 本次解析生成的 Chunk 数量 |
| `*_duration_ms` | 各阶段耗时与总耗时 |

解析日志 `document_parsed_log` 会先记录 Markdown 解析和上传成功；只有分片、向量化和 ES 入库都成功后，Python 才发送 parse_result `success` 通知给 Java。任一后处理阶段失败都会把 `document_parse_pipeline` 标记为 `FAILED`，并发送 parse_result `failed`。

### 3.4 Qdrant Point

`IndexedPoint` 包含：

```python
chunk_id: str
bucket_id: int
vector: list[float]
payload: {
    "chunk_id": str,
    "user_id": int,
    "set_id": int,
    "doc_id": int,
}
```

collection 名称由 `BucketRouter.collection_name(bucket_id)` 生成。

启用稀疏向量时，`SparseIndexedPoint` 使用同一 `chunk_id` 作为 Point ID，并通过 named sparse vector（默认 `sparse_text`）写入 BGE-M3 lexical weights。稀疏向量写入使用局部 vector update，不覆盖 dense vector。

### 3.5 Elasticsearch Document

`EsIndexingPipeline` 使用 `ES_INDEX_NAME` 指定索引名，按 `task_id` 和 Chunk 顺序生成文档 ID：

```text
{task_id}-{chunk_index}
```

写入文档包含：

- `task_id`
- `original_file_id`
- `document_parse_task_id`
- `dataset_id`
- `user_id`
- `source_filename`
- `chunk_index`
- `content`
- `start_line`
- `end_line`
- `metadata`

## 4. 使用方式

### 4.1 解析流水线中的使用

解析流水线先分片，再进入 dense 向量化、预分词、ES 入库和 sparse 向量化。`VectorizingStage` 通过 `StageServices.store_chunk_vectors()` 解析 owner：

```text
user_id = payload.user_id
set_id = payload.dataset_id
doc_id = payload.original_file_id
```

然后**现场过滤** `dense_vector_status != SUCCESS` 后调用：

```python
dense_chunks = [c for c in chunks if c.dense_vector_status != CHUNK_STATUS_INDEXED]
result = await vector_storage.index_chunks(
    user_id=user_id,
    set_id=set_id,
    doc_id=doc_id,
    chunks=dense_chunks,
)
```

`chunks` 是 `list[ChunkRecordDB]`（`run_chunking` 反查或 retry 的 `load_all_chunks_from_db` 反查，形态一致）。全部已 SUCCESS 时 `store_chunk_vectors` 短路返回幂等成功，不调 `index_chunks`。

返回 `ChunkIndexingResult`，包含：

- `total_chunks`
- `indexed_chunks`
- `failed_chunk_ids`
- `embedding_model`
- `sparse_model`
- `compensation_entry`

部分 Chunk 失败不会直接抛到解析主流程，而是通过结果汇总表达。当前文件级语义下，只要向量化存在失败 Chunk，整体 parse_result 会以 `failed` 通知 Java；全部 Chunk 向量化成功后才进入 ES 入库阶段。

### 4.2 文件级 ES 入库

`EsIndexingStage` 在预分词成功后通过 `StageServices.run_es_indexing()` 调用 ES 入库：

```python
es_result = await EsIndexingPipeline().index_for_parse_task(
    payload=payload,
    chunks=chunks,
)
```

`EsIndexingResult` 包含：

- `total_items`
- `indexed_items`
- `failed_item_ids`
- `failure_reason`

`failed_item_ids` 为空且 `indexed_items == total_items` 时视为 ES 阶段成功。

### 4.3 直接创建 Facade

```python
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.vector_storage.factory import create_vector_storage_facade

facade = create_vector_storage_facade(embedding_pipeline=embedding_pipeline)
result = await facade.index_chunks(
    user_id=10002,
    set_id=10003,
    doc_id=10001,
    chunks=dense_chunks,  # list[ChunkRecordDB]，调用方需先过滤 dense_vector_status != SUCCESS
)
```

实际业务通常由 `ParseTaskPipeline._build_vector_storage()` 负责装配。

### 4.4 修改 Chunk

```python
result = await facade.update_chunk(
    chunk_id="...",
    content="updated content",
)
```

行为：

- 内容未变化时只更新必要元数据或跳过。
- 内容变化时重新 embedding。
- 使用原 `chunk_id` 覆盖 Qdrant point。
- 成功后回写 `INDEXED`。

### 4.5 删除 Chunk

```python
result = await facade.delete_chunks(["chunk-id-1", "chunk-id-2"])
```

行为：

- MySQL 先把 `lifecycle_status` 标记为 `REMOVED`，使 chunk 立即退出解析 / 索引 / 检索视图。
- 后续删除流程按 `doc_id` / `chunk_id` 幂等清理 Qdrant points、ES 文档与 sparse 向量。
- 任一步失败时不回写 chunk 生命周期失败态；重试继续扫描 `REMOVED` 记录并重复执行清理。
- `dense_vector_status` / `sparse_vector_status` / `es_status` 保留原产物状态，不再承载删除生命周期。

### 4.6 补偿

Facade 暴露补偿入口：

```python
await facade.repair_stale_indexing(limit=100)
await facade.reindex_failed_chunks(chunk_ids)
```

补偿用于恢复 MySQL 和 Qdrant 的最终一致性。删除补偿状态机当前未启用；后续删除流程会基于 `REMOVED` chunk 记录做幂等重试。

### 4.7 稀疏向量召回

召回链路通过 `VectorStorageFacade.search_sparse_chunks` 发起稀疏向量搜索。这是**唯一对外召回入口**，调用方只需 import `vector_storage` 包。

```python
from src.core.vector_storage import (
    VectorStorageFacade,
    VectorSearchHit, VectorSearchResult,
    VectorRetrievalError,
    VectorRetrievalConfigurationError,
    VectorRetrievalBackendError,
    VectorRetrievalEncodingError,
)

result: VectorSearchResult = await facade.search_sparse_chunks(
    query="数据治理流程",
    user_id=10002,
    set_id=10003,
    doc_id=[42, 43],          # 可选；None 或 [] 不加 doc_id filter
    top_k=20,                 # 可选；不传走 settings.SPARSE_RETRIEVAL_TOP_K（默认 10）
    score_threshold=0.3,      # 可选；不传走 settings.SPARSE_RETRIEVAL_SCORE_THRESHOLD（默认 0.0）
)

for hit in result.hits:
    # hit 含 chunk_id / doc_id / set_id / score / vector_kind
    # 不含 content——调用方自行查 MySQL 回填真值
    record = await chunk_repository.get_by_chunk_ids(db, [hit.chunk_id])
```

**返回字段**：`VectorSearchHit` 含 `chunk_id` / `doc_id` / `set_id` / `score` / `vector_kind`，**不含 `payload` dict 和 `content`**——facade 层职责边界是"向量检索 + 业务过滤"，chunk 真值由调用方查 MySQL。

**完全只读**：不动 MySQL `sparse_vector_status`，不调 Qdrant `upsert/update_vectors/delete`。

## 5. 配置

常见配置来自 `src/config.py` 和 `.env`：

- `SYSTEM_LLM_PROVIDER`
- `SYSTEM_LLM_API_KEY`
- `SYSTEM_LLM_API_BASE`
- `SYSTEM_LLM_MODEL_EMBEDDING`
- `CHUNK_INDEX_EMBED_BATCH_SIZE`
- `CHUNK_INDEX_BUCKET_COUNT`
- `CHUNK_INDEX_COLLECTION_PREFIX`
- `CHUNK_INDEX_INDEXING_STALE_SECONDS`
- `QDRANT_HOST`
- `QDRANT_PORT`
- `QDRANT_API_KEY`
- `QDRANT_TIMEOUT_SECONDS`
- `ES_HOST`
- `ES_USER`
- `ES_PASSWORD`
- `ES_INDEX_NAME`
- `SPARSE_RETRIEVAL_TOP_K`（默认 10；召回默认值，调用方可 per-call 覆盖）
- `SPARSE_RETRIEVAL_SCORE_THRESHOLD`（默认 0.0；默认不过滤，见 §9 调研依据）

Embedding 客户端由 `ModelFactory` 创建，必须支持 `CapabilityType.EMBEDDING`。

## 6. 修改或扩展向量化逻辑

### 6.1 修改 embedding 行为

修改 `ChunkEmbeddingPipeline`，适用于：

- 批大小控制。
- embedding 缓存策略。
- embedding 返回值校验。
- 向量化统计。

不要在这里写 MySQL 或 Qdrant 逻辑。

### 6.2 修改写入闭环

修改 `VectorStoragePipeline`，适用于：

- PENDING、INDEXING、INDEXED 状态流转。
- MySQL 和 Qdrant 写入顺序。
- 失败时标记 `FAILED` 的策略。
- point 构造前后的校验。

### 6.3 修改 Qdrant 适配

修改 `QdrantIndexStore` 或 `point_factory.py`，适用于：

- collection 创建参数。
- payload index 字段。
- point payload 结构。
- 删除和存在性检查。

### 6.4 新增向量存储后端

当前 `VectorStorageFacade` 面向 Qdrant 装配。如果新增后端，建议：

1. 新增后端 store，提供 `ensure_collection`、`upsert_points`、`delete_points`、`point_exists` 等等价能力。
2. 在 `factory.py` 中按配置选择后端。
3. 保持 `VectorStorageFacade` 对上游接口不变。
4. 补齐单元测试和真实基础设施集成测试。

### 6.5 修改 ES 入库阶段

修改 `EsIndexingPipeline`，适用于：

- ES index 创建参数。
- 文件级 document payload。
- 单 Chunk 写入失败的汇总策略。
- ES 客户端认证和生命周期管理。

ES 阶段只返回文件级 `EsIndexingResult`，不直接维护 `kb_document_chunk.es_status`；Chunk 级 ES 状态字段保留给更细粒度索引状态扩展。

## 7. 一致性原则

- MySQL Chunk 记录是真值源。
- Qdrant point 是可重建索引副本。
- Elasticsearch document 是面向检索的文本索引副本。
- `document_parse_pipeline` 是文件级后处理阶段状态源。
- chunking 阶段负责创建 chunk 真值，向量化阶段不得创建新的 chunk 行。
- dense 写入采用 `PENDING/FAILED -> SUCCESS/FAILED` 的粗粒度 SQL 状态；运行时处理中间态由文件级阶段和 Qdrant 操作边界表达。
- sparse 是独立文件级阶段，在 dense、pretokenize、ES 成功后采用 `PENDING/FAILED -> SUCCESS/FAILED` 的粗粒度 SQL 状态。
- 业务生命周期由 `lifecycle_status` 表达：`ACTIVE -> REMOVED`；产物状态字段只保留 `PENDING/SUCCESS/FAILED`。
- Qdrant 写入成功但 MySQL 回写失败时，仍以 SQL 状态为准；后续进入 vectorizing 时按原 `chunk_id` 覆盖写索引副本。
- 解析结果成功通知只在 Markdown、分片、向量化和 ES 入库均成功后发送。
- 自动补偿不应无限重试所有失败；显式重建由 `reindex_failed_chunks` 控制。

## 8. 测试建议

常用测试范围：

```bash
.venv/bin/pytest tests/unit/core/vector_storage -q
.venv/bin/pytest tests/unit/core/qdrant_vector_storage -q
.venv/bin/pytest tests/unit/core/chunk_fact_storage -q
.venv/bin/pytest tests/unit/core/es_index_storage -q
.venv/bin/pytest tests/unit/core/sparse_vector -q
.venv/bin/pytest tests/unit/core/pipeline/test_post_process_repository.py -q
.venv/bin/pytest tests/acceptance/test_sparse_vector_recall.py -v
.venv/bin/pytest tests/integration/core/vector_storage -q
```

建议覆盖：

- MySQL 状态流转。
- vectorizing 接收 pipeline 现场过滤好的 `list[ChunkRecordDB]`（`index_chunks(chunks=...)`），不自查 SQL、不接收内存 `list[Chunk]`，且只处理 dense。
- 稀疏向量由 `SparseIndexingPipeline.run(chunks=...)` 独立阶段处理：pipeline 在 dense 完成后重新 load 并现场过滤 `dense=SUCCESS AND sparse != SUCCESS` 透传；`bucket_id` 从 chunks 自带字段取，入口前置断言 dense=SUCCESS。
- embedding 批处理和缓存命中。
- Qdrant collection 自动创建和 upsert。
- ES 文件级索引创建和逐 Chunk 写入。
- `document_parse_pipeline` 阶段状态流转。
- 部分失败时的 `failed_chunk_ids`。
- 删除失败补偿和 INDEXING 卡住修复。

## 9. 召回链路

### 9.1 概览

召回链路是写入链路的**只读镜像**：query 走与 chunk 写入完全相同的 BGE-M3 编码路径，到同一 bucket collection 的同一 named sparse vector 上做搜索，命中通过 payload filter 限定到当前 user / set。

```text
调用方
  -> VectorStorageFacade.search_sparse_chunks(query, user_id, set_id, ...)
       -> 参数校验（user_id/set_id 必填正整数；top_k>0；score_threshold>=0）
       -> 空 query 短路：直接返空 VectorSearchResult，不调 encoder / Qdrant
       -> 配置检查：SPARSE_VECTOR_ENABLED=False → 抛 VectorRetrievalConfigurationError
       -> SparseVectorService.vectorize_query(query)
            -> BGEM3SparseVectorEncoder.aencode([query])（与写入侧同一实例）
            -> 返回 SparseVector(indices, values)
       -> BucketRouter.route_user(user_id) → bucket_id（与写入侧共用）
       -> 构造 SparseQueryVectorSpec + payload_filter(must: user_id, set_id, [doc_id MatchAny])
       -> QdrantIndexStore._search_chunks(bucket_id, spec, filter, limit, score_threshold)
            -> collection_exists? 不存在 → 返空 hits + warn 日志
            -> client.query_points(query=SparseVector, using="sparse_text", ...)
            -> named vector 不存在 → 返空 hits + warn 日志
            -> ScoredPoint → VectorSearchHit(chunk_id, doc_id, set_id, score, vector_kind)
       -> 包装为 VectorSearchResult(hits, vector_name, top_k, score_threshold, model_name)
  -> 调用方拿 chunk_id 列表 → ChunkRepository.get_by_chunk_ids → 回填 content
```

### 9.2 写读不变量

| 不变量 | 同源处 |
| --- | --- |
| bucket 路由 | `BucketRouter.route_user(user_id)`，写入与召回共用同一实例 |
| sparse vector 命名 | `settings.SPARSE_VECTOR_QDRANT_VECTOR_NAME`（默认 `sparse_text`），写入 `upsert_sparse_vectors` 与召回 `_search_chunks` 都从该 setting 读取，不分叉 |
| BGE-M3 编码器实例 | `factory.create_vector_storage_facade` 构造一次 `SparseVectorService` 后，同时下传给写入 pipeline 与 facade 召回入口，全进程一份 |
| payload 字段 | `point_factory._payload()` 写入 `{chunk_id, user_id, set_id, doc_id}`；召回 filter 命中同名字段 |
| `chunk_id` | MySQL UK + Qdrant Point ID + 召回 `hit.chunk_id`，三处一致 |

### 9.3 失败模式判别原则

召回是只读路径，与写入路径的"必须有终态"诉求不同。以下判别原则对 sparse / dense / hybrid 召回**全部适用**，不再重新讨论：

| 场景 | 处理 | 判别 |
| --- | --- | --- |
| bucket collection 不存在 | 返空 hits，不抛；warn 日志带 `bucket_id` | 业务等价于"用户/set 没数据"；与写入侧 `delete_points` 把"collection 不存在"当作合法语义一致 |
| collection 存在但目标 named vector 未配置 | 返空 hits，不抛；warn 日志带 `bucket_id` + `vector_name` | dense-only 等中间状态合法（写入侧 `ensure_*_schema` 由首次写入触发） |
| Qdrant 网络故障 / 超时 / 服务不可用 | 抛 `VectorRetrievalBackendError` | 底层故障，由调用方决定降级或重试 |
| `SPARSE_VECTOR_ENABLED=False` / 依赖缺失 / Qdrant URL 无效 | 抛 `VectorRetrievalConfigurationError` | 部署侧配置错误，不是常态 |
| 编码器（BGE-M3 等）推理失败 | 抛 `VectorRetrievalEncodingError` | 编码失败不是召回的常态 |

**一句话原则**：业务上等价于"没数据"的状况返空；环境 / 配置 / 底层故障一律抛。

### 9.4 默认值依据

| 配置项 | 默认值 | 依据 |
| --- | --- | --- |
| `SPARSE_RETRIEVAL_TOP_K` | 10 | 业界主流 RAG 框架（Dify UI 默认上限 10、Qdrant 官方 hybrid + reranking 教程"先广召回后精排"）；10 在覆盖率与上下文成本之间是常见折中 |
| `SPARSE_RETRIEVAL_SCORE_THRESHOLD` | 0.0（不过滤） | Dify 公开文档明示"score threshold disabled = 0.0"；BGE-M3 sparse score 必须基于自身语料分布手工校准，盲设阈值会让 top_k cutoff 也救不回来；本项目暂无评测 harness，采取保守默认 |

调用方可任意 per-call 覆盖（`top_k=20, score_threshold=0.3`）；运维可改 `.env` 全局收紧。后续 follow-up issue「稀疏向量召回评测 harness」落地后，基于实证数据回头校准默认值。

### 9.5 对外暴露面

召回相关的所有类型 / 异常都从 `src.core.vector_storage` 单点 import，调用方不需要感知 `qdrant_vector_storage` / `sparse_vector` 子包：

```python
from src.core.vector_storage import (
    VectorStorageFacade,
    VectorSearchHit, VectorSearchResult,
    VectorRetrievalError,                  # 基类
    VectorRetrievalConfigurationError,
    VectorRetrievalBackendError,
    VectorRetrievalEncodingError,
)
```

**不在 `__all__` 中**：`SparseVectorSearchRequest`（facade 内部包装）、`QueryVectorSpec` / `SparseQueryVectorSpec`（store 层私有）。
