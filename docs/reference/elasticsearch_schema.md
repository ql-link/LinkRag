# Elasticsearch Schema

ES 索引命名、文档结构与入库结果模型参考。

**代码权威来源**：
- 入库流水线：[src/core/es_index_storage/pipeline.py](../../src/core/es_index_storage/pipeline.py)
- 结果模型：[src/core/es_index_storage/models.py](../../src/core/es_index_storage/models.py)

启用条件：`VECTOR_STORE_TYPE=elasticsearch`，或 Qdrant 与 ES 并行使用（混合检索场景）。

## 索引

### 索引名

| 配置 | 默认值 |
| --- | --- |
| `ES_INDEX_NAME` | `tolink_rag_index` |

当前实现使用**单一索引**承载所有用户的 Chunk（与 Qdrant 的分桶设计不同）。

### 索引创建

`EsIndexingPipeline._ensure_index` 在写入前确保索引存在。**当前实现不显式定义 mapping**——首次写入时由 ES 根据字段值动态生成。

> 如未来需要严格控制 mapping（如 `content` 改用特定分词器、`metadata` 限制 dynamic 等），需在 `_ensure_index` 中显式调用 `client.indices.create(index=..., mappings=...)`。

## 文档结构

每个 Chunk 对应**一份 ES 文档**。

### 文档 ID

```
{task_id}-{chunk_index}
```

来源：`EsIndexingPipeline._item_id`。例如：`task-20260516-001-3`。

### 文档字段

由 `EsIndexingPipeline._build_document` 构造：

| 字段 | 类型（动态推断） | 来源 | 说明 |
| --- | --- | --- | --- |
| `task_id` | keyword | `ParseTaskPayload` | 解析任务 UUID |
| `original_file_id` | long | `ParseTaskPayload` | 原始文件 ID |
| `document_parse_task_id` | long | `ParseTaskPayload` | 业务方文件解析表 ID（历史兼容字段名） |
| `dataset_id` | long | `ParseTaskPayload` | 数据集 ID |
| `user_id` | long | `ParseTaskPayload` | 用户 ID |
| `source_filename` | text | `ParseTaskPayload` | 原始文件名 |
| `chunk_index` | long | 写入时计算 | Chunk 在文档内顺序号（从 0 开始） |
| `content` | text | `Chunk.content` | Chunk 可检索文本 |
| `start_line` | long | `Chunk.start_line` | 源文档起始行 |
| `end_line` | long | `Chunk.end_line` | 源文档结束行 |
| `metadata` | object | `Chunk.metadata` | Chunk 元数据（标题路径、类型等） |

> ES 文档**不持有 `chunk_id`** —— ES 用 `{task_id}-{chunk_index}` 作为 doc id，而 MySQL/Qdrant 使用独立的 `chunk_id`。两者之间需要通过 `task_id + chunk_index` join。

## 入库结果模型

### `EsIndexingResult`

定义见 [src/core/es_index_storage/models.py](../../src/core/es_index_storage/models.py)。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total_items` | int | 本次任务的 Chunk 总数 |
| `indexed_items` | int | 实际写入成功数 |
| `failed_item_ids` | list[str] | 失败的 ES doc id 列表 |
| `failure_reason` | str \| None | 失败摘要，全部成功时为 None |

派生属性：

```python
is_success = (not failed_item_ids) and (indexed_items == total_items)
```

任一失败 Chunk 都会导致 `is_success=False`，触发上层 `document_parse_pipeline.es_indexing_status=FAILED`。

## 写入策略

- **逐条写入**：当前实现遍历 chunks 调用 `client.index(...)`，**未启用 bulk API**。如需提高吞吐应在 pipeline 层引入 `helpers.async_bulk`。
- **错误隔离**：单条 chunk 写失败不中断整批，记录到 `failed_item_ids`，对应 chunk 标 `es_status=FAILED`，`failure_reason` 以 `ES_INDEXING_FAILED:` 前缀。
- **基础设施故障文件级处理**：`_ensure_index` 失败（ES 不可达 / 建索引失败）属文件级故障，**不标任何 chunk es_status**，返回 `failed_item_ids=[]` 且 `failure_reason` 以 `ensure_index:` 前缀，`is_success=False`（`indexed != total`）。
- **文件级粒度上报**：Pipeline 只返回文件级结果，Chunk 级 ES 详情不下发到上层。

## 一致性约束

- **MySQL 为真值**：`kb_document_chunk.es_status` 是 ES 侧的状态权威。ES 实际数据可能因为重试/失败而暂时不一致，以 MySQL 状态决定补偿动作。
- **重建链路**：`kb_document_chunk` → `EsIndexingPipeline.index_for_parse_task` 可全量重建 ES。
- **删除一致性**：Chunk 删除时需同时清理 MySQL、Qdrant、ES 三处。当前实现见 `kb_document_chunk.dense_vector_status=DELETING/DELETED`。

## 连接配置

| 环境变量 | 说明 |
| --- | --- |
| `ES_HOST` | ES 地址，含 schema，如 `http://127.0.0.1:9200` |
| `ES_USER` / `ES_PASSWORD` | 鉴权（启用了 xpack.security 时必填） |
| `ES_INDEX_NAME` | 索引名，默认 `tolink_rag_index` |

## 相关文档

- 关系数据：[mysql_schema.md](mysql_schema.md)
- 向量索引：[qdrant_schema.md](qdrant_schema.md)
- 向量化模块架构：[../architecture/vectorization_module.md](../architecture/vectorization_module.md)
- 解析流水线：[../architecture/parse_task_pipeline_module.md](../architecture/parse_task_pipeline_module.md)
