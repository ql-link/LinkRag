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
| `VectorStorageFacade` | `vector_storage/facade.py` | 向上游暴露统一入口；含写入、管理、补偿与**召回**（`search_sparse_chunks` / `search_dense_chunks`） |
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

### 4.7 向量召回入口

召回链路通过 `VectorStorageFacade` 暴露**两个对仗入口**：

- `search_sparse_chunks`（BGE-M3 稀疏向量召回）
- `search_dense_chunks`（system embedding 稠密向量召回）

两路是**唯一对外召回入口**，调用方只需 import `vector_storage` 包。详细链路 / 失败模式 / 默认值依据 / 鬼影 hit 边界 / 模型升级 SOP 见 [§9 召回链路](#9-召回链路)。

```python
from src.core.vector_storage import (
    VectorStorageFacade,
    VectorSearchHit, VectorSearchResult,
    VectorRetrievalError,
    VectorRetrievalConfigurationError,
    VectorRetrievalBackendError,
    VectorRetrievalEncodingError,
)
from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import CHUNK_LIFECYCLE_ACTIVE

# === sparse 召回 ===
sparse_result: VectorSearchResult = await facade.search_sparse_chunks(
    query="数据治理流程",
    user_id=10002,
    set_id=10003,
    doc_id=[42, 43],          # 可选
    top_k=20,                 # 可选；默认 SPARSE_RETRIEVAL_TOP_K=10
    score_threshold=0.3,      # 可选；默认 SPARSE_RETRIEVAL_SCORE_THRESHOLD=0.0
)

# === dense 召回（与 sparse 字面对仗，差异仅在向量类型）===
dense_result: VectorSearchResult = await facade.search_dense_chunks(
    query="数据治理流程",
    user_id=10002,
    set_id=10003,
    doc_id=[42, 43],
    top_k=20,                 # 默认 DENSE_RETRIEVAL_TOP_K=10
    score_threshold=0.6,      # 默认 DENSE_RETRIEVAL_SCORE_THRESHOLD=0.0；cosine 上界 [0, 1]
)

# === 真值回填 + 鬼影 hit 过滤（强制，详见 §9.6）===
chunk_ids = [hit.chunk_id for hit in dense_result.hits]
records = await chunk_repository.list_by_chunk_ids(db, chunk_ids)
chunk_id_to_content = {
    r.chunk_id: r.content
    for r in records
    if r.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE  # 关键
}
```

**返回字段**：`VectorSearchHit` 含 `chunk_id` / `doc_id` / `set_id` / `score` / `vector_kind`（`"sparse"` / `"dense"`），**不含 `payload` dict 和 `content`**——facade 层职责边界是"向量检索 + 业务过滤"，chunk 真值由调用方查 MySQL。

**完全只读**：两路都不动 MySQL `*_vector_status`，不调 Qdrant `upsert/update_vectors/delete`。

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
- `SPARSE_RETRIEVAL_TOP_K`（默认 10；sparse 召回默认值，调用方可 per-call 覆盖）
- `SPARSE_RETRIEVAL_SCORE_THRESHOLD`（默认 0.0；默认不过滤，见 §9 调研依据）
- `DENSE_RETRIEVAL_TOP_K`（默认 10；dense 召回默认值；pipeline 路径下被 `RECALL_RESULT_LIMIT` 覆盖）
- `DENSE_RETRIEVAL_SCORE_THRESHOLD`（默认 0.0；cosine 上界 [0, 1]，facade 入口校验早死）
- `RECALL_ENABLED_SOURCES`（默认 `bm25,sparse,dense`；运维侧通过 env 显式设置可暂时回退）

稀疏向量推理（dense embedding 与之独立，见下表）：

- `SPARSE_VECTOR_PROVIDER`（默认 `bge_m3`）：选择稀疏向量推理实现，见 §6.6。
  - `bge_m3`：本地进程内加载 BGE-M3 模型。
  - `bge_m3_http`：调用早期 `bge-m3-server` 的 `/encode` 接口（仅 sparse）。
  - `remote_bge_m3`：调用独立部署的 `bge-m3-service`（dense + sparse 同出，带重试）。
- `SPARSE_VECTOR_MODEL_NAME` / `SPARSE_VECTOR_MODEL_CACHE_DIR` / `SPARSE_VECTOR_LOCAL_FILES_ONLY` / `SPARSE_VECTOR_DEVICE` / `SPARSE_VECTOR_BATCH_SIZE`（仅 `bge_m3` 本地推理生效）。
- `SPARSE_VECTOR_HTTP_ENDPOINT` / `SPARSE_VECTOR_HTTP_TIMEOUT` / `SPARSE_VECTOR_HTTP_BATCH_SIZE`（仅 `bge_m3_http` 远程推理生效）。
- `BGE_M3_SERVICE_URL` / `BGE_M3_TIMEOUT_SECONDS` / `BGE_M3_MAX_RETRIES`（仅 `remote_bge_m3` 远程推理生效）。
- `SPARSE_VECTOR_MAX_LENGTH` / `SPARSE_VECTOR_TOP_K` / `SPARSE_VECTOR_MIN_WEIGHT`：三种 provider 共用，保证产出经过同一套清洗规则。

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

### 6.6 切换稀疏向量推理实现（本地 / 远程 HTTP）

稀疏向量推理通过 `SPARSE_VECTOR_PROVIDER` 在两种实现间切换，二者都实现同一
`SparseVectorEncoderProtocol`（`aencode()` + `model_name`），由
`sparse_vector/factory.py::create_sparse_vector_service_from_settings()` 按配置装配，
**上层 `SparseVectorService` 与编排层无感**。

| provider | 编码器 | 位置 | 推理方式 |
| --- | --- | --- | --- |
| `bge_m3`（默认） | `BGEM3SparseVectorEncoder` | `sparse_vector/encoder.py` | 本地进程内 `FlagEmbedding.BGEM3FlagModel` 推理 |
| `bge_m3_http` | `BGEM3HttpSparseVectorEncoder` | `sparse_vector/http_encoder.py` | `POST {endpoint}/encode` 调用早期 `bge-m3-server`（仅 sparse） |
| `remote_bge_m3` | `RemoteBGEM3Encoder` | `sparse_vector/remote_encoder.py` | `POST {BGE_M3_SERVICE_URL}/encode` 调用独立 `bge-m3-service`（dense + sparse，带重试） |

两条路径产出对齐：远程 `/encode` 返回的 `sparse` 列表元素是 `{token_id: weight}`，与本地
`output["lexical_weights"]` 同构，HTTP 编码器复用 `normalize_lexical_weights` 做同一套
`top_k` / `min_weight` 清洗与升序排序，因此切换 provider 不改变 Qdrant 写入与召回口径。

远程服务契约（`bge-m3-server`）：

```text
POST {SPARSE_VECTOR_HTTP_ENDPOINT}/encode
请求: {"texts": [...], "return_dense": false, "return_sparse": true, "return_colbert": false,
       "max_length"?: int, "batch_size"?: int}
响应: {"sparse": [ {"<token_id>": weight, ...}, ... ]}   # 与 texts 一一同序
```

切换到远程只需 `.env`：

```bash
# 早期 bge-m3-server（仅 sparse）
SPARSE_VECTOR_PROVIDER=bge_m3_http
SPARSE_VECTOR_HTTP_ENDPOINT=http://<host>:<port>

# 或：独立 bge-m3-service（dense + sparse 同出，带重试）
SPARSE_VECTOR_PROVIDER=remote_bge_m3
BGE_M3_SERVICE_URL=http://<host>:<port>
BGE_M3_TIMEOUT_SECONDS=30.0
BGE_M3_MAX_RETRIES=3
```

`remote_bge_m3` 服务契约（独立 ``bge-m3-service``）：

```text
POST {BGE_M3_SERVICE_URL}/encode
请求: {"texts": [...], "return_dense": true, "return_sparse": true}
响应: {"dense":  [[float, ...]],          # shape (n, 1024)
       "sparse": [{"<token_id>": weight, ...}, ...]}  # 与 texts 一一同序
```

`RemoteBGEM3Encoder` 的 `aencode()` 走 `return_dense=False` 节省带宽；当
dense 召回侧需要复用同一次推理时，可调 `aencode_with_dense()` 同时返回
`(list[SparseVector], list[list[float]])`。HTTP 失败的处理：

- 4xx：当作永久错误，立即抛 `SparseVectorEncodingError`，不重试。
- 5xx / 网络错误：按 `BGE_M3_MAX_RETRIES` 线性退避重试，耗尽后抛
  `SparseVectorEncodingError`。

新增第三种 provider 时：实现 `SparseVectorEncoderProtocol`，在 `constants.py` 注册 provider
常量，并在 `factory.py` 增加对应 `_build_*_encoder()` 分支即可。

> 注意：切换 provider 只改变“如何计算稀疏向量”，不修复 MySQL 与 Qdrant 的既有不一致。
> 若清空过 Qdrant，仍需按 §7 一致性原则把相关 chunk 的
> `dense_vector_status` / `sparse_vector_status` 重置后重新解析，否则
> `update_vectors` 会因 point 缺失返回 404。

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

召回链路是写入链路的**只读镜像**。本期同时支持两种向量召回：

- **稀疏召回**（`search_sparse_chunks`）：query 走 BGE-M3 编码 → Qdrant **named** sparse vector（默认 `sparse_text`）
- **稠密召回**（`search_dense_chunks`）：query 走 system embedding HTTP（默认 `text-embedding-v4`） → Qdrant **unnamed** dense vector（cosine 距离）

两路共用 bucket 路由、payload filter 构造、`VectorSearchHit` / `VectorSearchResult` 中性 dataclass、召回侧异常族（`VectorRetrievalError` 系列）。差异仅在 query 向量化路径与 Qdrant `query_points` 调用形态。

```text
调用方
  -> VectorStorageFacade.search_{sparse|dense}_chunks(query, user_id, set_id, ...)
       -> 参数校验（user_id/set_id 必填正整数；top_k>0；score_threshold 范围校验）
       -> 空 query 短路：直接返空 VectorSearchResult，不调 encoder / Qdrant
       -> 配置检查：
            - sparse: SPARSE_VECTOR_ENABLED=False → 抛 VectorRetrievalConfigurationError
            - dense: embedding_pipeline 未注入 → 抛 VectorRetrievalConfigurationError
       -> query 向量化
            - sparse: SparseVectorService.vectorize_query(query) → SparseVector(indices, values)
            - dense:  ChunkEmbeddingPipeline.aembed_query(query)  → list[float]
       -> BucketRouter.route_user(user_id) → bucket_id（两路共用）
       -> 构造 query_vector_spec + payload_filter(must: user_id, set_id, [doc_id MatchAny])
            - sparse: SparseQueryVectorSpec(name, indices, values)
            - dense:  DenseQueryVectorSpec(vector=list[float])  ← 不带 vector_name
       -> QdrantIndexStore._search_chunks(bucket_id, spec, filter, limit, score_threshold)
            -> collection_exists? 不存在 → 返空 hits + warn 日志
            -> client.query_points:
                 - sparse: query=SparseVector, using="sparse_text"
                 - dense:  query=list[float],  using=None
            -> named vector 不存在（仅 sparse 触发）→ 返空 hits + warn 日志
            -> ScoredPoint → VectorSearchHit(chunk_id, doc_id, set_id, score, vector_kind)
       -> 包装为 VectorSearchResult
  -> 调用方拿 chunk_id 列表 → ChunkRepository.list_by_chunk_ids 查 MySQL
     ★ 必须按 lifecycle_status == ACTIVE 过滤（消除删除间隙鬼影 hit，详见 §9.6）
  -> 回填 content 给下游 rerank / prompt 拼装
```

### 9.2 写读不变量

| 不变量 | 同源处 |
| --- | --- |
| bucket 路由 | `BucketRouter.route_user(user_id)`，写入 / sparse 召回 / dense 召回共用同一路由算法（按 user_id CRC32 哈希 → bucket_id → collection 名） |
| sparse vector 命名 | `settings.SPARSE_VECTOR_QDRANT_VECTOR_NAME`（默认 `sparse_text`），写入 `upsert_sparse_vectors` 与召回 sparse 分支都从该 setting 读取，不分叉 |
| dense vector 形态 | unnamed vector，写入 `ensure_collection` 用 `vectors_config=VectorParams(size=1024, distance=COSINE)`，`PointStruct(vector=[...])` 裸传；召回 `query_points(using=None)` 与之对齐——不引入 `DENSE_RETRIEVAL_VECTOR_NAME` 配置避免分叉风险 |
| BGE-M3 编码器实例 | `SparseVectorService` 在工厂构造一次后，同时下传给写入 pipeline 与召回入口 |
| system embedding 实例 | `ChunkEmbeddingPipeline` 在工厂构造一次后，`aembed_chunks`（写入）与 `aembed_query`（召回）共用同一个 `self.embedder` + `self.embedding_model` 字段——编译期保证写入 / 召回 model 不分叉 |
| payload 字段 | `point_factory._payload()` 写入 `{chunk_id, user_id, set_id, doc_id}`；两路召回 filter 命中同名字段（`facade._build_payload_filter` 是 staticmethod，sparse / dense 共用） |
| `chunk_id` | MySQL UK + Qdrant Point ID + 召回 `hit.chunk_id`，三处一致 |

### 9.3 失败模式判别原则

召回是只读路径，与写入路径的"必须有终态"诉求不同。以下判别原则对 sparse / dense / hybrid 召回**全部适用**，不再重新讨论：

| 场景 | 处理 | 判别 |
| --- | --- | --- |
| bucket collection 不存在 | 返空 hits，不抛；warn 日志带 `bucket_id` | 业务等价于"用户/set 没数据"；与写入侧 `delete_points` 把"collection 不存在"当作合法语义一致 |
| collection 存在但目标 named vector 未配置 | 返空 hits，不抛；warn 日志带 `bucket_id` + `vector_name`（**仅 sparse 触发**——dense 是 collection 创建时一并配齐的 unnamed vector，无中间状态） | sparse 写入侧 `ensure_sparse_vector_schema` 是首次写入时延迟挂载 |
| Qdrant 网络故障 / 超时 / 服务不可用 | 抛 `VectorRetrievalBackendError` | 底层故障，由调用方决定降级或重试 |
| `SPARSE_VECTOR_ENABLED=False` / dense `embedding_pipeline` 未注入 / 依赖缺失 / Qdrant URL 无效 | 抛 `VectorRetrievalConfigurationError` | 部署侧配置错误，不是常态 |
| 编码器（BGE-M3 / system embedding HTTP）推理失败 | 抛 `VectorRetrievalEncodingError` | 编码失败不是召回的常态 |

**一句话原则**：业务上等价于"没数据"的状况返空；环境 / 配置 / 底层故障一律抛。

### 9.4 默认值依据

| 配置项 | 默认值 | 依据 |
| --- | --- | --- |
| `SPARSE_RETRIEVAL_TOP_K` | 10 | 业界主流 RAG 框架（Dify UI 默认上限 10、Qdrant 官方 hybrid + reranking 教程"先广召回后精排"）；10 在覆盖率与上下文成本之间是常见折中 |
| `SPARSE_RETRIEVAL_SCORE_THRESHOLD` | 0.0（不过滤） | Dify 公开文档明示"score threshold disabled = 0.0"；BGE-M3 sparse score 必须基于自身语料分布手工校准，盲设阈值会让 top_k cutoff 也救不回来；本项目暂无评测 harness，采取保守默认 |
| `DENSE_RETRIEVAL_TOP_K` | 10 | 与 sparse 对仗，hybrid 融合时两路覆盖范围一致；对齐 Dify 主流上界。注意：**pipeline 路径下实际 top_k 由 `RECALL_RESULT_LIMIT` 在执行期透传覆盖**；`DENSE_RETRIEVAL_TOP_K` 仅作 facade 直调（脚本 / 评测 harness）的兜底默认 |
| `DENSE_RETRIEVAL_SCORE_THRESHOLD` | 0.0（不过滤） | 与 sparse 对仗保守策略；cosine 物理范围 [0, 1]，facade 入口加上界校验早死。本项目暂无评测 harness，盲设阈值不可追溯——评测 harness follow-up 落地后基于实证数据回头校准 |
| `RECALL_ENABLED_SOURCES` | `bm25,sparse,dense` | 默认开启三路召回；运维侧通过 env 显式 set `bm25,sparse` 可暂时回退到 dev 旧默认 |

调用方可任意 per-call 覆盖（`top_k=20, score_threshold=0.6`）；运维可改 `.env` 全局收紧。后续 follow-up issue「dense + sparse 召回评测 harness」落地后，基于实证数据回头校准两路阈值。

### 9.5 对外暴露面

召回相关的所有类型 / 异常都从 `src.core.vector_storage` 单点 import，调用方不需要感知 `qdrant_vector_storage` / `sparse_vector` / `splitter` 子包：

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

**不在 `__all__` 中**：
- `SparseVectorSearchRequest` / `DenseVectorSearchRequest`（facade 内部包装）
- `QueryVectorSpec` / `SparseQueryVectorSpec` / `DenseQueryVectorSpec`（store 层私有 union dispatch）
- `DenseRetriever`（被 `recall_pipeline_provider` 内部独占使用）

### 9.6 鬼影 hit 边界（删除一致性）

chunk 删除链路：MySQL `lifecycle_status=REMOVED` 即时翻转 → Qdrant `delete_points` 经 MQ + 删除补偿异步清理（窗口数十秒至分钟级）。窗口内 sparse / dense 召回**会**返回这些已 REMOVED 但 Qdrant 尚未清理的 chunk_id（"鬼影 hit"）。

> 状态值参照 [src/core/chunk_fact_storage/constants.py](../../src/core/chunk_fact_storage/constants.py)：`CHUNK_LIFECYCLE_ACTIVE = "ACTIVE"` / `CHUNK_LIFECYCLE_REMOVED = "REMOVED"`。**注意**：写入路径已天然过滤 REMOVED（`_reload_chunks_from_db` 只反查 `ACTIVE`），所以鬼影 hit 来源**不是"写入了 REMOVED chunk"**，而是"已 INDEXED 的 chunk 被翻转为 REMOVED 但 Qdrant 异步删除尚未到达"。

**facade 边界声明**：

- `search_sparse_chunks` / `search_dense_chunks` 返回的是「**Qdrant 当下视图**」，不保证与 MySQL `lifecycle_status` 强一致。
- 下游消费者必须按 `chunk_id` 反查 MySQL 时过滤 `lifecycle_status == ACTIVE`。

**调用方使用模式（强制）**：

```python
from src.core.vector_storage import VectorStorageFacade
from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import CHUNK_LIFECYCLE_ACTIVE

# === 1. 召回（facade 返回 Qdrant 当下视图）===
result = await facade.search_dense_chunks(query="...", user_id=..., set_id=...)

# === 2. 真值回填 + 鬼影 hit 过滤 ===
chunk_ids = [hit.chunk_id for hit in result.hits]
records = await chunk_repository.list_by_chunk_ids(db, chunk_ids)
chunk_id_to_content = {
    r.chunk_id: r.content
    for r in records
    if r.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE  # 关键：剔除鬼影
}
ordered = [
    (hit, chunk_id_to_content[hit.chunk_id])
    for hit in result.hits
    if hit.chunk_id in chunk_id_to_content
]
# 注意：ordered 长度可能 < result.hits 长度（鬼影 hit 被剔除）
```

**生产路径与内部直调的边界**：

| 调用方 | 鬼影 hit 责任归属 |
| --- | --- |
| SSE API → Java Recall Gateway → chunk-content-fetch | **Java 侧**按 lifecycle_status 过滤；本期 Python 不实现 |
| 内部 Python 直调（调试脚本 / 内部 service / 评测 harness） | **caller 侧**按上面模式自行处理 |
| 未来 hybrid 融合 reranker | hybrid issue 中实现，在 RRF 融合后一次性反查 MySQL + lifecycle 过滤 |

**Follow-up（不在本期）**：单独 issue「dense/sparse 召回鬼影 hit 防御」——可选 utility 工具或 Qdrant payload 同步删除标记（把不一致窗口从分钟级降到毫秒级）。

### 9.7 Embedding 模型升级 SOP

dense 召回正确性建立在「query 与 chunk 走同一份 embedding 接口、同一个模型字符串、同一份 token 化策略」这一前提上。本项目锁定 **Qwen `text-embedding-v4`（对称模型）**、**dense 维度 1024**。模型切换 SOP：

| 升级场景 | Qdrant 行为 | 运维 SOP |
| --- | --- | --- |
| 切换到不同维度的 embedding 模型（如 1024 → 1536） | `client.upsert` 维度不匹配硬报错 | 升级前必须重建所有 bucket collection；写入 + 召回同步切换 |
| 切换到同维度但不同向量空间的模型 | Qdrant 不报错；cosine 分数失真，召回质量静默退化 | **不允许就地切换**；必须重建 collection；staging 环境实测 recall@k 通过后才上生产 |
| 切换到非对称模型（需 `input_type` 参数区分 query / document） | API 调用通过；语义模式不一致 → recall@k 静默退化（10~30%） | 单独 issue 扩 `IEmbedder` 协议；**当前实现假设对称模型** |
| 同一模型字符串但服务端权重漂移（厂商静默更新） | 不报错；分数缓慢漂移 | 评测 harness follow-up 监控 score 分布趋势 |
