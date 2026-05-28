# Elasticsearch Schema

ES 索引命名、mapping、文档结构与入库结果模型参考。

**代码权威来源**：
- 入库流水线：[src/core/es_index_storage/pipeline.py](../../../src/core/es_index_storage/pipeline.py)
- 文档构造：[src/core/es_index_storage/document_factory.py](../../../src/core/es_index_storage/document_factory.py)
- Mapping 定义：[src/core/es_index_storage/mapping.py](../../../src/core/es_index_storage/mapping.py)
- 批次构造：[src/core/es_index_storage/batcher.py](../../../src/core/es_index_storage/batcher.py)
- 结果模型：[src/core/es_index_storage/models.py](../../../src/core/es_index_storage/models.py)

ES 负责存储预分词后的 Chunk token 索引副本，用于后续 BM25 / lexical 召回。原文内容、分块元数据与索引状态真值仍以 MySQL `kb_document_chunk` 为准。

## 索引

### 索引名

| 配置 | 默认值 |
| --- | --- |
| `ES_INDEX_NAME` | `tolink_rag_index` |

当前实现使用**单一索引**承载所有用户的 Chunk（与 Qdrant 的分桶设计不同）。

写入时使用 `dataset_id` 作为 routing：

```python
routing = str(file_meta.dataset_id)
```

后续查询同一数据集时也应携带相同 routing，减少跨 shard fan-out。

### 索引创建

`EsIndexingPipeline._ensure_index` 在写入前确保索引存在。索引不存在时调用 `client.indices.create(...)`，body 来自 `build_es_index_body(...)`，显式指定 settings 与 mappings。

### Analyzer

当前 ES 文档存的是预分词后的 token 字符串，因此索引与查询 analyzer 都使用 whitespace tokenizer + lowercase filter：

| Analyzer | 用途 |
| --- | --- |
| `chunk_index_analyzer` | 写入 `coarse_tokens` / `fine_tokens` |
| `chunk_search_analyzer` | 查询 `coarse_tokens` / `fine_tokens` |

### Mapping

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_id` | keyword | Chunk 业务唯一键，与 MySQL `kb_document_chunk.chunk_id` / Qdrant point id 一致 |
| `user_id` | long | 用户 ID，召回必须过滤 |
| `dataset_id` | long | 数据集 / 知识集 ID，召回必须过滤，并作为 ES routing |
| `doc_id` | long | 文档 ID（原始文件） |
| `task_id` | keyword | 解析任务 ID，可为空 |
| `chunk_index` | integer | Chunk 在文档内顺序号（从 0 开始） |
| `coarse_tokens` | text | 粗粒度 token 文本，使用 `chunk_index_analyzer` / `chunk_search_analyzer` |
| `fine_tokens` | text | 细粒度 token 文本，使用 `chunk_index_analyzer` / `chunk_search_analyzer` |

`_source` 排除 `coarse_tokens` 与 `fine_tokens`，避免查询结果携带大 token 文本：

```json
{
  "_source": {
    "excludes": ["coarse_tokens", "fine_tokens"]
  }
}
```

## 文档结构

每个 Chunk 对应**一份 ES 文档**。ES 文档只保留召回所需 token 与定位字段，不保存 Chunk 原文内容。

### 文档 ID

```
{user_id}-{dataset_id}-{doc_id}-{chunk_id}
```

来源：`EsDocumentFactory.build_action(...)`。例如：`20-30-10-chunk-001`。

### 文档字段

由 `EsDocumentFactory.build_action(...)` 构造：

| 字段 | 类型 | 来源 | 说明 |
| --- | --- | --- | --- |
| `chunk_id` | keyword | `ChunkWithTokens.chunk_id` | Chunk 业务唯一键 |
| `user_id` | long | `FileIndexMeta.user_id` | 用户 ID |
| `dataset_id` | long | `FileIndexMeta.dataset_id` | 数据集 ID |
| `doc_id` | long | `FileIndexMeta.doc_id` | 文档 ID |
| `task_id` | keyword | `FileIndexMeta.task_id` | 解析任务 ID，可为空 |
| `chunk_index` | integer | `ChunkWithTokens.chunk_index` | 文档内顺序号 |
| `coarse_tokens` | text | `ChunkWithTokens.coarse_tokens` | 粗粒度分词结果 |
| `fine_tokens` | text | `ChunkWithTokens.fine_tokens` | 细粒度分词结果 |

ES 文档不包含 `content`、`source_filename`、`start_line`、`end_line`、`metadata` 等原文或展示字段。检索命中后应通过 `chunk_id` 回 MySQL 读取 Chunk 真值与展示信息。

### 写入前置输入

ES 入库不直接消费 splitter 输出，而是消费预分词阶段产出的 `FilePostIndexPlan`：

| 模型 | 说明 |
| --- | --- |
| `FileIndexMeta` | 文件级归属字段：`user_id`、`dataset_id`、`doc_id`、`task_id` |
| `ChunkWithTokens` | 单个 Chunk 的 `chunk_id`、`chunk_index`、`coarse_tokens`、`fine_tokens` |
| `FilePostIndexPlan` | 一个文件的完整 ES 入库计划 |

分词职责属于 pretokenize 阶段；ES 入库只校验并写入 token 计划。

## 入库结果模型

### `EsIndexingResult`

定义见 [src/core/es_index_storage/models.py](../../../src/core/es_index_storage/models.py)。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total_items` | int | 本次任务的 Chunk 总数 |
| `indexed_items` | int | 实际写入成功数 |
| `failed_item_ids` | list[str] | 失败的 `chunk_id` 列表 |
| `failure_reason` | str \| None | 失败摘要，全部成功时为 None |
| `succeeded_item_ids` | list[str] | 写入成功的 `chunk_id` 列表 |
| `skipped_item_ids` | list[str] | 预留字段，当前默认空列表 |

派生属性：

```python
is_success = (not failed_item_ids) and (indexed_items == total_items)
```

任一失败 Chunk 都会导致 `is_success=False`，触发上层 `document_parse_pipeline.es_indexing_status=FAILED`。

## 写入策略

- **显式建索引**：写入前通过 `_ensure_index` 创建带 analyzer / mapping 的索引；索引已存在则跳过。
- **批量写入**：`TokenBatcher` 按 `ES_MAX_TOKEN_BATCH_CHUNKS` 与 `ES_MAX_TOKEN_BATCH_BYTES` 拆分批次，`EsIndexingPipeline._bulk_index_batch` 使用 `client.bulk(...)` 写入。
- **稳定顺序**：批次构造前按 `chunk_index` 升序排序。
- **文档校验**：`chunk_id`、`chunk_index`、`coarse_tokens`、`fine_tokens` 必须有效；单个 Chunk 校验失败不会阻断其他 Chunk，失败项会写入 `failed_item_ids` 并标记 `es_status=FAILED`。
- **错误隔离**：单批 bulk 中部分 Chunk 失败不影响同批其他成功项；成功项标 `es_status=SUCCESS`，失败项标 `es_status=FAILED`，`failure_reason` 以 `ES_INDEXING_FAILED:` 前缀。
- **批次提交**：每个 batch 的成功 / 失败状态独立写回 MySQL 并 `commit`，前一批成功不会因为后一批失败回滚。
- **基础设施故障文件级处理**：`_ensure_index` 失败（ES 不可达 / 建索引失败）属文件级故障，**不标任何 chunk es_status**，返回 `failed_item_ids=[]` 且 `failure_reason` 以 `ensure_index:` 前缀，`is_success=False`（`indexed != total`）。
- **空计划短路**：`chunks_with_tokens` 为空时直接返回成功的空结果，不调用 ES。

## 查询约束

后续 BM25 / lexical 召回应只依赖 ES 文档中的 token 与定位字段。查询必须至少包含：

| 约束 | 字段 |
| --- | --- |
| 用户隔离 | `user_id` |
| 数据集隔离 | `dataset_id` |
| 数据路由 | `routing=str(dataset_id)` |

可选按 `doc_id` 收窄到单文档。当前 ES 文档不包含 `chunk_type`、业务状态、原文内容等字段；如召回需要这些条件，应先评估是否由 MySQL 后过滤承接，避免为了读侧过滤轻易扩大 ES 文档结构。

## 一致性约束

- **MySQL 为真值**：`kb_document_chunk.es_status` 是 ES 侧的状态权威。ES 实际数据可能因为重试/失败而暂时不一致，以 MySQL 状态决定补偿动作。
- **重建链路**：`kb_document_chunk` → pretokenize 阶段构建 `FilePostIndexPlan` → `EsIndexingPipeline.write_es_index` 可重建 ES token 索引副本。
- **跨库 join**：ES / MySQL / Qdrant 统一使用 `chunk_id` 作为 Chunk 业务唯一键。
- **删除一致性**：Chunk 删除时需同时清理 MySQL、Qdrant、ES 三处。`kb_document_chunk.dense_vector_status` 只保留 `PENDING/SUCCESS/FAILED` 粗粒度结果。

## 连接配置

| 环境变量 | 说明 |
| --- | --- |
| `ES_HOST` | ES 地址，含 schema，如 `http://127.0.0.1:9200` |
| `ES_USER` / `ES_PASSWORD` | 鉴权（启用了 xpack.security 时必填） |
| `ES_INDEX_NAME` | 索引名，默认 `tolink_rag_index` |
| `ES_INDEX_SHARDS` | 索引 shard 数 |
| `ES_INDEX_REPLICAS` | 索引 replica 数 |
| `ES_MAX_DOCUMENT_BYTES` | 单个 ES 文档最大估算字节数 |
| `ES_MAX_TOKEN_BATCH_BYTES` | 单个 bulk batch 最大估算字节数 |
| `ES_MAX_TOKEN_BATCH_CHUNKS` | 单个 bulk batch 最大 Chunk 数 |
| `ES_BULK_REQUEST_TIMEOUT_SECONDS` | ES client / bulk 请求超时 |

## 相关文档

- 关系数据：[mysql_schema.md](mysql.md)
- 向量索引：[qdrant_schema.md](qdrant.md)
- 向量化模块架构：[../../internals/vectorization.md](../../internals/vectorization.md)
- 解析流水线：[../../internals/parse_task_pipeline.md](../../internals/parse_task_pipeline.md)
