# Data Models

本文档记录当前项目关键数据模型。数据库结构的最终来源是 `scripts/db/init.sql`，代码模型来自 `src/models`、`src/api/schemas`、`src/core/*/models.py`。

## 1. Database Source Of Truth

当前数据库结构以以下文件为准：

```text
scripts/db/init.sql
```

该文件定义表、字段、索引、自增起始值和字段注释。ORM 模型如与 DDL 不一致，应优先核对并修正到同一契约。

## 2. Document Parse Tables

### document_parse_file

用途：Java 侧文件解析任务表，记录一个原始文件当前解析任务关系。

ORM：`src/models/parse_task.py::DocumentParseTask`

关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED | 主键 |
| `document_original_file_id` | BIGINT UNSIGNED | 原始文件 ID，唯一 |
| `dataset_id` | BIGINT UNSIGNED | 数据集 ID |
| `user_id` | BIGINT UNSIGNED | 用户 ID |
| `latest_parse_task_id` | VARCHAR(36) | 最新解析 task_id |
| `original_filename` | VARCHAR(255) | 原始文件名 |
| `parse_count` | INT | 解析次数 |
| `created_at` / `updated_at` | DATETIME | 创建和更新时间 |

索引：

- `uk_parse_task_original_file(document_original_file_id)`
- `idx_parse_task_dataset_user(dataset_id, user_id, updated_at)`
- `idx_parse_task_latest_task(latest_parse_task_id)`

### document_parsed_log

用途：Python 解析日志和终态表。

ORM：`src/models/parse_task.py::DocumentParsedLog`

关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED | 主键 |
| `task_id` | VARCHAR(36) | 解析任务唯一 ID |
| `document_original_file_id` | BIGINT UNSIGNED | 原始文件 ID |
| `document_parse_file_id` | BIGINT UNSIGNED | 文件解析表 ID |
| `trigger_mode` | VARCHAR(20) | 触发方式 |
| `task_status` | VARCHAR(16) | `created/success/failed` 等 |
| `failure_reason` | VARCHAR(512) | 失败原因 |
| `parsed_filename` | VARCHAR(255) | Markdown 文件名 |
| `parsed_bucket_name` | VARCHAR(64) | Markdown bucket |
| `parsed_object_key` | VARCHAR(512) | Markdown object key |
| `parsed_file_url` | VARCHAR(1024) | Markdown 访问 URL |
| `parsed_at` | DATETIME | 解析时间 |
| `parse_started_at` / `parse_finished_at` | DATETIME | 开始和结束时间 |
| `parse_duration_ms` | BIGINT | 解析耗时 |
| `created_at` / `updated_at` | DATETIME | 创建和更新时间 |

索引：

- `uk_parse_task_id(task_id)`
- `idx_parsed_log_original_status(document_original_file_id, task_status, updated_at)`
- `idx_parsed_log_parse_task_status(document_parse_file_id, task_status, updated_at)`

代码和 API 中仍保留 `document_parse_task_id` 字段名作为历史兼容别名；数据库字段名和 ORM column 映射以 `document_parse_file_id` 为准。

### document_post_process_pipeline

用途：文件级解析后处理流程状态表，记录 Markdown 解析上传成功后的分片、向量化和 ES 入库状态。

ORM：`src/models/parse_task.py::DocumentPostProcessPipeline`

关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED | 主键 |
| `document_parsed_log_id` | BIGINT UNSIGNED | 解析日志主键，唯一 |
| `task_id` | VARCHAR(36) | 解析任务 ID |
| `document_original_file_id` | BIGINT UNSIGNED | 原始文件 ID |
| `document_parse_file_id` | BIGINT UNSIGNED | 文件解析表 ID |
| `pipeline_status` | VARCHAR(20) | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `chunking_status` | VARCHAR(20) | `PENDING/SUCCESS/FAILED` |
| `vectorizing_status` | VARCHAR(20) | `PENDING/SUCCESS/FAILED` |
| `es_indexing_status` | VARCHAR(20) | `PENDING/SUCCESS/FAILED` |
| `failed_stage` | VARCHAR(20) | `CHUNKING/VECTORIZING/ES_INDEXING` |
| `recover_from_stage` | VARCHAR(20) | 下次恢复阶段 |
| `failure_reason` | VARCHAR(512) | 最近一次失败原因 |
| `chunk_count` | INT | 本次分片数量 |
| `retry_count` / `last_retry_at` | INT / DATETIME | 重试次数和最近重试时间 |
| `chunking_duration_ms` | BIGINT | 分片耗时 |
| `vectorizing_duration_ms` | BIGINT | 向量化耗时 |
| `es_indexing_duration_ms` | BIGINT | ES 入库耗时 |
| `total_duration_ms` | BIGINT | 后处理总耗时 |
| `started_at` / `finished_at` | DATETIME | 后处理开始和结束时间 |
| `created_at` / `updated_at` | DATETIME | 创建和更新时间 |

索引：

- `uk_post_pipeline_parsed_log(document_parsed_log_id)`
- `idx_post_pipeline_task_id(task_id)`
- `idx_post_pipeline_parse_file(document_parse_file_id, updated_at)`
- `idx_post_pipeline_status(pipeline_status, updated_at)`
- `idx_post_pipeline_retry(pipeline_status, recover_from_stage, updated_at)`

## 3. Chunk Tables

### kb_document_chunk

用途：Chunk 真值表，是向量索引的可重建来源。

ORM：`src/models/chunk_record.py::ChunkRecordDB`

关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT | 主键 |
| `chunk_id` | VARCHAR(128) | Chunk 全局唯一 ID |
| `doc_id` | BIGINT | 文档 ID，对应原始文件 |
| `set_id` | BIGINT | 知识集/数据集 ID |
| `user_id` | BIGINT | 用户 ID |
| `bucket_id` | INT | Qdrant 分桶 |
| `content` | TEXT | Chunk 文本 |
| `content_hash` | VARCHAR(64) | 内容 SHA-256 |
| `chunk_type` | VARCHAR(32) | text/table/image/code/mixed 等 |
| `start_line` / `end_line` | INT | 源 Markdown 行号 |
| `chunk_index` | INT | 文档内顺序 |
| `status` | VARCHAR(16) | Chunk 主状态 |
| `error_msg` | VARCHAR(512) | 主状态失败原因 |
| `retry_count` | INT | 重试次数 |
| `last_retry_at` | DATETIME | 最近重试时间 |
| `embedding_model` | VARCHAR(128) | embedding 模型 |
| `vector_status` | VARCHAR(16) | 向量侧状态 |
| `vector_error_msg` | VARCHAR(512) | 向量错误 |
| `es_status` | VARCHAR(16) | ES 侧状态 |
| `es_error_msg` | VARCHAR(512) | ES 错误 |
| `create_time` / `update_time` | DATETIME | 创建和更新时间 |

索引：

- `idx_user_set(user_id, set_id)`
- `idx_bucket_status(bucket_id, status)`
- `idx_bucket_vector_status(bucket_id, vector_status)`
- `idx_bucket_es_status(bucket_id, es_status)`
- `idx_doc_id(doc_id)`
- `idx_chunk_type(chunk_type)`
- `idx_content_hash(content_hash)`

## 4. LLM Tables

### llm_system_provider

ORM：`src/models/db_models.py::SystemProviderDB`

字段：

- `id`
- `provider_type`
- `provider_name`
- `api_base_url`
- `supported_models`
- `config_schema`
- `is_active`
- `priority`
- `created_at`
- `updated_at`

### llm_user_config

ORM：`src/models/db_models.py::UserLLMConfigDB`

字段：

- `id`
- `user_id`
- `provider_id`
- `provider_type`
- `provider_name`
- `config_name`
- `api_key`
- `custom_api_base_url`
- `model_name`
- `priority`
- `is_active`
- `is_default`
- `timeout_ms`
- `max_retries`
- `stream_enabled`
- `extra_config`
- `capability`
- `created_at`
- `updated_at`

索引：

- `idx_user_provider_cap(user_id, provider_type, capability)`

### llm_usage_log

ORM：`src/models/db_models.py::UsageLogDB`

字段：

- `id`
- `user_id`
- `config_id`
- `provider_type`
- `model_name`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `latency_ms`
- `status`
- `error_message`
- `fallback_config_id`
- `conversation_id`
- `created_at`

索引：

- `idx_user_date(user_id, created_at)`
- `idx_config_date(config_id, created_at)`
- `idx_conversation_id(conversation_id)`

## 5. API Request/Response Models

### Parser

`TaskSubmitRequest` and `SendParseTaskRequest` share the parse-task contract:

- `task_id`
- `original_file_id`
- `document_parse_task_id`：历史兼容字段名，对应数据库 `document_parse_file.id`
- `user_id`
- `dataset_id`
- `file_type`
- `source_bucket`
- `source_object_key`
- `source_filename`
- `md_bucket`
- `md_object_key`
- `trigger_mode`
- `pdf_parser_backend`
- `docling_force_ocr`
- `image_bucket`
- `image_prefix`

`TaskSubmitResponse`:

- `code`
- `message`
- `data`

### MQ

`MQResponse`:

- `success`
- `message`

`MQVendorInfoResponse`:

- `current_vendor`
- `available_vendors`

### LLM

Request models:

- `GenerateRequest`
- `EmbedRequest`
- `RerankRequest`
- `OcrRequest`

Common response model:

- `APIResponse(code, message, data)`

LLM result models:

- `GenerateResult(content, model, usage, provider_type, latency_ms)`
- `EmbeddingResult(model, embeddings, usage)`
- `RerankResult(model, results, usage)`
- `OcrResult(content, model, usage)`
- `UsageInfo(prompt_tokens, completion_tokens, total_tokens)`

## 6. Splitter And Vector Models

### Chunk

Defined in `src/core/splitter/models.py`.

Fields:

- `content`
- `start_line`
- `end_line`
- `metadata`

Derived properties:

- `char_count`
- `line_count`

### EmbeddedChunk

Fields:

- `chunk`
- `embedding`
- `embedding_model`
- `cached`

### Vector Storage Models

Defined in `src/core/vector_storage/models.py`.

Key models:

- `ChunkStorageRequest(user_id, set_id, doc_id, chunks)`
- `ChunkUpdateRequest(chunk_id, content, chunk_type, start_line, end_line, chunk_index)`
- `ChunkDeleteRequest(chunk_ids)`
- `StoredChunkDraft(chunk_id, user_id, set_id, doc_id, bucket_id, content, content_hash, chunk_type, start_line, end_line, chunk_index, status)`
- `ChunkIndexingResult(total_chunks, indexed_chunks, failed_chunk_ids, embedding_model)`
- `ChunkMutationResult(total_chunks, affected_chunks, failed_chunk_ids, skipped_chunk_ids, embedding_model)`

### Qdrant IndexedPoint

Defined in `src/core/qdrant_vector_storage/models.py`.

Fields:

- `chunk_id`
- `bucket_id`
- `vector`
- `payload`

### ES Indexing Result

Defined in `src/core/es_index_storage/models.py`.

Fields:

- `total_items`
- `indexed_items`
- `failed_item_ids`
- `failure_reason`

`is_success` 为 `true` 的条件是 `failed_item_ids` 为空且 `indexed_items == total_items`。
