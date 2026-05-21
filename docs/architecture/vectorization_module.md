# Vectorization Module

本文说明 Chunk 向量化、向量存储、文件级 ES 入库和后处理状态模块的架构、使用方式，以及新增或修改索引逻辑的方法。

## 1. 模块框架

```text
src/core/splitter/
└── embedding_pipeline.py          # Chunk 批量 embedding 与缓存

src/core/vector_storage/
├── factory.py                     # 装配向量存储 Facade
├── facade.py                      # 对外统一入口
├── pipeline.py                    # 新增写入闭环
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
├── qdrant_store.py                # Qdrant 访问层
└── models.py                      # IndexedPoint
```

新增写入链路：

```text
ParseTaskPipeline
  -> ParseTaskService.aprocess()
  -> upload markdown
  -> document_post_process_pipeline: PROCESSING
  -> _run_chunking()
  -> document_post_process_pipeline.chunking_status = SUCCESS
  -> _store_chunk_vectors()
    -> VectorStorageFacade.store_chunks()
      -> VectorStoragePipeline.store_chunks()
        -> ChunkDraftFactory
        -> ChunkRepository.bulk_insert_pending()
        -> 按 chunk_index 顺序处理每个 chunk
          -> ChunkRepository.mark_indexing()
          -> ChunkEmbeddingPipeline.aembed_chunks([chunk])
          -> SparseVectorService.vectorize_chunk([chunk 原文])（开启时）
          -> QdrantIndexStore.ensure_collection()
          -> QdrantIndexStore.upsert_points()
          -> QdrantIndexStore.ensure_sparse_vector_schema()（开启时）
          -> QdrantIndexStore.upsert_sparse_vectors()（开启时）
          -> ChunkRepository.mark_sparse_indexed()（开启时）
          -> ChunkRepository.mark_indexed()
  -> document_post_process_pipeline.vectorizing_status = SUCCESS
  -> EsIndexingPipeline.index_for_parse_task()
  -> document_post_process_pipeline.es_indexing_status = SUCCESS
  -> parse_result success notification
```

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `ChunkEmbeddingPipeline` | `splitter/embedding_pipeline.py` | 批量生成 Chunk embedding，支持缓存和统计 |
| `SparseVectorService` | `sparse_vector/pipeline.py` | 使用 BGE-M3 对 chunk 原文生成稀疏向量 |
| `VectorStorageFacade` | `vector_storage/facade.py` | 向上游暴露统一入口 |
| `VectorStoragePipeline` | `vector_storage/pipeline.py` | 新增 Chunk 的 MySQL + Qdrant 写入闭环 |
| `VectorStorageManagementPipeline` | `vector_storage/management_pipeline.py` | Chunk 修改、删除 |
| `VectorStorageCompensationPipeline` | `vector_storage/compensation_pipeline.py` | 删除失败、INDEXING 卡住、FAILED 重建 |
| `ChunkDraftFactory` | `vector_storage/draft_factory.py` | 生成 chunk_id、content_hash、bucket_id、chunk_type |
| `ChunkRepository` | `chunk_fact_storage/repository.py` | MySQL Chunk 真值表读写和状态机 |
| `BucketRouter` | `qdrant_vector_storage/bucket_router.py` | 按 `user_id` 路由到 Qdrant collection |
| `QdrantIndexStore` | `qdrant_vector_storage/qdrant_store.py` | Qdrant collection、point 写入、删除、查询 |
| `EsIndexingPipeline` | `es_index_storage/pipeline.py` | 将文件级 Chunk 内容写入 Elasticsearch |
| `PostProcessPipelineRepository` | `pipeline/parse_task/post_process/repository.py` | 维护 `document_post_process_pipeline` 文件级阶段状态 |

## 3. 数据模型

### 3.1 输入模型

`VectorStorageFacade.store_chunks` 接收：

```python
user_id: int
set_id: int
doc_id: int
chunks: Sequence[Chunk]
```

`ChunkDraftFactory` 会把每个 `Chunk` 转成 `StoredChunkDraft`：

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
| `INDEXING` | 正在写入向量索引 |
| `INDEXED` | Qdrant point 已写入，MySQL 已确认 |
| `FAILED` | 向量化或索引失败 |
| `DELETING` | 正在删除 Qdrant point |
| `DELETED` | 删除完成 |
| `DELETE_FAILED` | 删除失败，等待补偿 |

MySQL 是 Chunk 真值源，Qdrant 是向量索引副本。启用稀疏向量后，文件级向量化成功要求每个有效 chunk 同时满足 `dense_vector_status=INDEXED` 与 `sparse_vector_status=INDEXED`。

稀疏向量子状态：

| 状态 | 含义 |
| --- | --- |
| `PENDING` | 等待稀疏向量处理 |
| `INDEXING` | 正在生成或写入 BGE-M3 稀疏向量 |
| `INDEXED` | 稀疏向量已写入 Qdrant，MySQL 已确认 |
| `FAILED` | 稀疏模型调用、Qdrant 写入或状态回写失败 |

### 3.3 文件级后处理状态

`document_post_process_pipeline` 记录一次解析成功落 Markdown 后的后处理阶段状态：

| 字段 | 含义 |
| --- | --- |
| `pipeline_status` | 整体状态：`PENDING/PROCESSING/SUCCESS/FAILED` |
| `chunking_status` | 分片阶段状态：`PENDING/SUCCESS/FAILED` |
| `vectorizing_status` | 向量化/Qdrant 阶段状态：`PENDING/SUCCESS/FAILED` |
| `pretokenize_status` | ES 预分词阶段状态：`PENDING/SUCCESS/FAILED` |
| `es_indexing_status` | Elasticsearch 入库阶段状态：`PENDING/SUCCESS/FAILED` |
| `failed_stage` | 失败阶段：`CHUNKING/VECTORIZING/PRETOKENIZE/ES_INDEXING` |
| `recover_from_stage` | 用户手动重试时可恢复的阶段 |
| `chunk_count` | 本次解析生成的 Chunk 数量 |
| `*_duration_ms` | 各阶段耗时与总耗时 |

解析日志 `document_parsed_log` 会先记录 Markdown 解析和上传成功；只有分片、向量化、预分词和 ES 入库都成功后，Python 才发送 parse_result `success` 通知给 Java。任一后处理阶段失败都会把 `document_post_process_pipeline` 标记为 `FAILED`，并发送 parse_result `failed`。

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

解析流水线先分片，再进入向量化和 ES 入库。`ParseTaskPipeline._store_chunk_vectors` 会解析 owner：

```text
user_id = payload.user_id
set_id = payload.dataset_id
doc_id = payload.original_file_id
```

然后调用：

```python
result = await vector_storage.store_chunks(
    user_id=user_id,
    set_id=set_id,
    doc_id=doc_id,
    chunks=chunks,
)
```

返回 `ChunkIndexingResult`，包含：

- `total_chunks`
- `indexed_chunks`
- `failed_chunk_ids`
- `dense_vector_model`

部分 Chunk 失败不会直接抛到解析主流程，而是通过结果汇总表达。当前文件级语义下，只要向量化存在失败 Chunk，整体 parse_result 会以 `failed` 通知 Java；全部 Chunk 向量化成功后才进入 ES 入库阶段。

### 4.2 文件级 ES 入库

`ParseTaskPipeline` 在向量化全部成功后调用：

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
result = await facade.store_chunks(
    user_id=10002,
    set_id=10003,
    doc_id=10001,
    chunks=chunks,
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

- MySQL 先标记 `DELETING`。
- 按 `bucket_id` 分组删除 Qdrant points。
- 成功后标记 `DELETED`。
- 失败时标记 `DELETE_FAILED`。

### 4.6 补偿

Facade 暴露补偿入口：

```python
await facade.retry_delete_failed(limit=100)
await facade.repair_stale_indexing(limit=100)
await facade.reindex_failed_chunks(chunk_ids)
```

补偿用于恢复 MySQL 和 Qdrant 的最终一致性。

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
- `document_post_process_pipeline` 是文件级后处理阶段状态源。
- 新增写入采用 `PENDING -> INDEXING -> INDEXED`。
- 删除采用 `DELETING -> DELETED`，失败进入 `DELETE_FAILED`。
- Qdrant 写入成功但 MySQL 回写失败时，通过补偿流程修复。
- 解析结果成功通知只在 Markdown、分片、向量化和 ES 入库均成功后发送。
- 自动补偿不应无限重试所有失败；显式重建由 `reindex_failed_chunks` 控制。

## 8. 测试建议

常用测试范围：

```bash
.venv/bin/pytest tests/unit/core/vector_storage -q
.venv/bin/pytest tests/unit/core/qdrant_vector_storage -q
.venv/bin/pytest tests/unit/core/chunk_fact_storage -q
.venv/bin/pytest tests/unit/core/es_index_storage -q
.venv/bin/pytest tests/unit/core/pipeline/test_post_process_repository.py -q
.venv/bin/pytest tests/integration/core/vector_storage -q
```

建议覆盖：

- MySQL 状态流转。
- embedding 批处理和缓存命中。
- Qdrant collection 自动创建和 upsert。
- ES 文件级索引创建和逐 Chunk 写入。
- `document_post_process_pipeline` 阶段状态流转。
- 部分失败时的 `failed_chunk_ids`。
- 删除失败补偿和 INDEXING 卡住修复。
