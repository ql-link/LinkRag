# MySQL Schema

toLink-Rag 业务表模式参考。**权威来源**：[scripts/db/init.sql](../../scripts/db/init.sql)，本文是按业务域分组的摘要视图。

ORM 与 DDL 不一致时，以 DDL 为准并修正 ORM。

## 表清单

按业务域共 12 张表：

| 业务域 | 表 | 主键 ID 起始 |
| --- | --- | --- |
| [用户](#1-用户) | `sys_user` | 10000 |
| [LLM 配置与用量](#2-llm-配置与用量) | `llm_system_provider`, `llm_user_config`, `llm_usage_log` | 10000 |
| [数据集与对话](#3-数据集与对话) | `dataset`, `chat_conversation`, `chat_message` | 10000 |
| [文档解析](#4-文档解析) | `document_original_file`, `document_parse_file`, `document_parsed_log`, `document_post_process_pipeline` | 10000 |
| [知识索引](#5-知识索引) | `kb_document_chunk` | 10000 |

所有表统一：`InnoDB` / `utf8mb4_unicode_ci`，主键自增从 `10000` 起。

---

## 1. 用户

### `sys_user` — 系统用户表

ORM：（未在 `src/models/` 中映射，由业务侧管理）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 用户唯一标识 |
| `username` | VARCHAR(64) UNIQUE | 登录账号 |
| `password_hash` | VARCHAR(255) | 加密后密码 |
| `nickname` | VARCHAR(64) | 用户昵称 |
| `email` | VARCHAR(128) UNIQUE | 邮箱 |
| `phone` | VARCHAR(20) | 手机号 |
| `avatar_url` | VARCHAR(512) | 头像地址 |
| `role` | ENUM(`ADMIN`,`USER`) | 角色，默认 `USER` |
| `status` | TINYINT | 1=正常，0=禁用 |
| `last_login_at` | DATETIME | 最后登录时间 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：`uk_username`, `uk_email`。

---

## 2. LLM 配置与用量

### `llm_system_provider` — LLM 系统级厂商配置

ORM：[`SystemProviderDB`](../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 厂商唯一标识 |
| `provider_type` | VARCHAR(32) UNIQUE | `openai` / `claude` / `glm` / `deepseek` 等 |
| `provider_name` | VARCHAR(64) | 厂商展示名 |
| `api_base_url` | VARCHAR(512) | 官方默认 API 地址 |
| `supported_models` | JSON | 支持模型与能力映射 |
| `config_schema` | JSON | 配置参数 Schema |
| `is_active` | BOOLEAN | 是否启用 |
| `priority` | INT | 厂商优先级（1-100），默认 50 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：`uk_provider_type`。

### `llm_user_config` — 用户级 LLM 配置

ORM：[`UserLLMConfigDB`](../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 配置唯一标识 |
| `user_id` | BIGINT UNSIGNED | 所属用户 |
| `provider_id` | BIGINT UNSIGNED | 关联 `llm_system_provider.id` |
| `provider_type` | VARCHAR(32) | 厂商类型快照 |
| `provider_name` | VARCHAR(64) | 厂商名快照 |
| `config_name` | VARCHAR(64) | 用户自定义配置名 |
| `api_key` | VARCHAR(512) | **加密存储**，由 `API_KEY_ENCRYPTION_SECRET` 解密 |
| `custom_api_base_url` | VARCHAR(512) | 自定义 API 地址 |
| `model_name` | VARCHAR(128) | 具体模型名 |
| `priority` | INT | 优先级 1-100 |
| `is_active` | BOOLEAN | 是否启用 |
| `is_default` | BOOLEAN | 是否默认配置 |
| `timeout_ms` | INT | 超时（毫秒），默认 60000 |
| `max_retries` | INT | 最大重试次数，默认 3 |
| `stream_enabled` | BOOLEAN | 是否支持流式输出 |
| `capability` | VARCHAR(32) | `CHAT` / `EMBEDDING` / `RERANK` / `OCR`，默认 `CHAT` |
| `extra_config` | JSON | 扩展配置 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_user_provider_model(user_id, provider_id, model_name)`
- `idx_user_active_default(user_id, is_active, is_default)`
- `idx_user_provider_cap(user_id, provider_type, capability)`

### `llm_usage_log` — LLM 调用用量日志

ORM：[`UsageLogDB`](../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 记录唯一标识 |
| `user_id` | BIGINT UNSIGNED | 用户 ID |
| `config_id` | BIGINT UNSIGNED | 用户配置 ID |
| `provider_type` | VARCHAR(32) | 厂商类型 |
| `model_name` | VARCHAR(128) | 模型名称 |
| `prompt_tokens` | INT | 输入 Token 数 |
| `completion_tokens` | INT | 输出 Token 数 |
| `total_tokens` | INT | 总 Token 数 |
| `latency_ms` | INT | 响应延迟（毫秒） |
| `status` | VARCHAR(16) | `success` / `failed` / `partial` |
| `error_message` | VARCHAR(512) | 错误信息 |
| `fallback_config_id` | BIGINT UNSIGNED | 触发 Fallback 时记录原配置 ID |
| `conversation_id` | BIGINT UNSIGNED | 关联对话 ID |
| `created_at` | DATETIME | 创建时间 |

索引：`idx_user_date`, `idx_config_date`, `idx_conversation_id`。

---

## 3. 数据集与对话

### `dataset` — 数据集表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 数据集唯一标识 |
| `user_id` | BIGINT UNSIGNED | 所属用户 |
| `name` | VARCHAR(128) | 数据集名称 |
| `description` | VARCHAR(512) | 数据集描述 |
| `status` | VARCHAR(16) | 状态，默认 `ACTIVE` |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_dataset_user_name(user_id, name)`
- `idx_dataset_user_updated(user_id, updated_at)`

### `chat_conversation` — 对话表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 对话唯一标识 |
| `user_id` | BIGINT UNSIGNED | 所属用户 |
| `dataset_id` | BIGINT UNSIGNED | 所属数据集 |
| `last_config_id` | BIGINT UNSIGNED | 最后使用的 LLM 配置 |
| `last_model_name` | VARCHAR(128) | 最后使用的模型名快照 |
| `title` | VARCHAR(255) | 对话标题 |
| `is_pinned` | BOOLEAN | 是否置顶 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `idx_chat_conversation_user_pinned_updated(user_id, is_pinned, updated_at)`
- `idx_chat_conversation_dataset_updated(dataset_id, updated_at)`

### `chat_message` — 对话消息表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 消息唯一标识 |
| `conversation_id` | BIGINT UNSIGNED | 所属对话 |
| `config_id` | BIGINT UNSIGNED | 产生该消息所使用的 LLM 配置 |
| `model_name` | VARCHAR(128) | 模型名快照 |
| `role` | VARCHAR(16) | `user` / `assistant` / `system` |
| `content` | MEDIUMTEXT | 消息内容 |
| `token_count` | INT | 该条消息消耗的 Token 数 |
| `created_at` | DATETIME | 创建时间 |

索引：`idx_conversation_created(conversation_id, created_at)`。

---

## 4. 文档解析

四张表覆盖完整链路：**原始文件 → 解析任务表 → 解析日志 → 后处理流程**。

```
document_original_file (1)──(N) document_parse_file (1)──(N) document_parsed_log (1)──(0/1) document_post_process_pipeline
        原始文件                  最新解析任务关系                 单次解析任务记录                 单次后处理流程状态
```

### `document_original_file` — 原始文档上传表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 原始文档唯一标识 |
| `dataset_id` | BIGINT UNSIGNED | 所属数据集 |
| `user_id` | BIGINT UNSIGNED | 上传用户 |
| `original_filename` | VARCHAR(255) | 用户上传时的原始文件名 |
| `file_suffix` | VARCHAR(32) | 标准化小写后缀 |
| `file_size` | BIGINT UNSIGNED | 文件大小（字节） |
| `content_type` | VARCHAR(128) | Content-Type |
| `bucket_name` | VARCHAR(64) | 原文件私有存储桶，默认 `rag-raw` |
| `object_key` | VARCHAR(512) | 对象 Key |
| `file_url` | VARCHAR(1024) | 内部下载 URL |
| `upload_status` | VARCHAR(20) | `uploading` / `success` / `failed` |
| `is_upload_success` | TINYINT(1) | 是否上传成功 |
| `failure_reason` | VARCHAR(512) | 上传失败原因 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_dataset_user_name_suffix(dataset_id, user_id, original_filename, file_suffix)`
- `idx_document_original_dataset_created`
- `idx_document_original_user_created`
- `idx_document_original_upload_status`

### `document_parse_file` — 文件解析任务表

记录一个原始文件**当前**的解析任务关系。一文件一行（`document_original_file_id` 唯一）。

ORM：[`DocumentParseTask`](../../src/models/parse_task.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 主键 |
| `document_original_file_id` | BIGINT UNSIGNED UNIQUE | 原文件 ID |
| `dataset_id` | BIGINT UNSIGNED | 数据集 ID |
| `user_id` | BIGINT UNSIGNED | 用户 ID |
| `latest_parse_task_id` | VARCHAR(36) | 最新解析 task_id |
| `original_filename` | VARCHAR(255) | 原文件名快照 |
| `parse_count` | INT | 累计解析次数 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_parse_task_original_file(document_original_file_id)`
- `idx_parse_task_dataset_user(dataset_id, user_id, updated_at)`
- `idx_parse_task_latest_task(latest_parse_task_id)`

### `document_parsed_log` — 单次解析任务日志

每次触发解析产生一条。

ORM：[`DocumentParsedLog`](../../src/models/parse_task.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 主键 |
| `task_id` | VARCHAR(36) UNIQUE | 解析任务 UUID |
| `document_original_file_id` | BIGINT UNSIGNED | 原文件 ID |
| `document_parse_file_id` | BIGINT UNSIGNED | 文件解析表 ID |
| `trigger_mode` | VARCHAR(20) | `upload_auto` / `manual_retry` |
| `task_status` | VARCHAR(16) | `created` / `success` / `failed` |
| `failure_reason` | VARCHAR(512) | 失败原因 |
| `parsed_filename` | VARCHAR(255) | 解析后文件名 |
| `parsed_bucket_name` | VARCHAR(64) | 解析结果桶 |
| `parsed_object_key` | VARCHAR(512) | 解析结果对象 Key |
| `parsed_file_url` | VARCHAR(1024) | 解析结果内部 URL |
| `parsed_at` | DATETIME | 解析时间 |
| `parse_started_at` / `parse_finished_at` | DATETIME | Python 解析开始 / 结束时间 |
| `parse_duration_ms` | BIGINT | 解析耗时 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_parse_task_id(task_id)`
- `idx_parsed_log_original_status(document_original_file_id, task_status, updated_at)`
- `idx_parsed_log_parse_task_status(document_parse_file_id, task_status, updated_at)`

> **历史兼容字段名**：代码与 API 中 `document_parse_task_id` 与本表的 `document_parse_file_id` 等价（同一字段）。

### `document_post_process_pipeline` — 文件级后处理流程状态

记录 Markdown 上传成功后的**分片 → 向量化 → 预分词 → ES 入库**四段状态。

ORM：[`DocumentPostProcessPipeline`](../../src/models/parse_task.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 主键 |
| `document_parsed_log_id` | BIGINT UNSIGNED UNIQUE | 解析日志主键 |
| `task_id` | VARCHAR(36) | 解析任务 ID |
| `document_original_file_id` | BIGINT UNSIGNED | 原文件 ID |
| `document_parse_file_id` | BIGINT UNSIGNED | 文件解析表 ID |
| `pipeline_status` | VARCHAR(20) | `PENDING` / `PROCESSING` / `SUCCESS` / `FAILED` |
| `chunking_status` | VARCHAR(20) | `PENDING` / `SUCCESS` / `FAILED` |
| `vectorizing_status` | VARCHAR(20) | `PENDING` / `SUCCESS` / `FAILED` |
| `pretokenize_status` | VARCHAR(20) | 预分词状态：`PENDING` / `SUCCESS` / `FAILED`（COMMENT 由迁移 0003 补齐） |
| `es_indexing_status` | VARCHAR(20) | `PENDING` / `SUCCESS` / `FAILED` |
| `failed_stage` | VARCHAR(20) | `CHUNKING` / `VECTORIZING` / `PRETOKENIZE` / `ES_INDEXING` |
| `recover_from_stage` | VARCHAR(20) | 下次恢复阶段（首个非 SUCCESS 阶段，同上枚举） |
| `failure_reason` | VARCHAR(512) | 最近一次失败原因（前缀 `pretokenize:` / `ensure_index:` / `ES_INDEXING_FAILED:`） |
| `chunk_count` | INT | 本次分片数量 |
| `retry_count` | INT | **用户侧重试次数**：用户前端触发重试时由 `claim_failed_for_retry` +1；模块/失败处不写 |
| `last_retry_at` | DATETIME | 用户侧最近一次重试时间 |
| `chunking_duration_ms` | BIGINT | 分片耗时 |
| `vectorizing_duration_ms` | BIGINT | 向量化耗时 |
| `pretokenize_duration_ms` | BIGINT | 预分词耗时，单位毫秒（COMMENT 由迁移 0003 补齐） |
| `es_indexing_duration_ms` | BIGINT | ES 入库耗时 |
| `total_duration_ms` | BIGINT | 总耗时 |
| `started_at` / `finished_at` | DATETIME | 开始 / 结束时间 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_post_pipeline_parsed_log(document_parsed_log_id)`
- `idx_post_pipeline_task_id(task_id)`
- `idx_post_pipeline_parse_file(document_parse_file_id, updated_at)`
- `idx_post_pipeline_status(pipeline_status, updated_at)`
- `idx_post_pipeline_retry(pipeline_status, recover_from_stage, updated_at)`

---

## 5. 知识索引

### `kb_document_chunk` — 文档 Chunk 真值记录表

向量库与 ES 的**可重建来源**。每个 Chunk 一行，`chunk_id` 与 Qdrant Point ID 一一对应。

ORM：[`ChunkRecordDB`](../../src/models/chunk_record.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 物理主键 |
| `chunk_id` | VARCHAR(128) UNIQUE | Chunk 业务唯一键，对应 Qdrant Point ID |
| `doc_id` | BIGINT UNSIGNED | 文档 ID（对应原始文件） |
| `set_id` | BIGINT UNSIGNED | 知识集 / 数据集 ID |
| `user_id` | BIGINT UNSIGNED | 用户 ID |
| `bucket_id` | INT | 路由后的 Qdrant 物理桶编号 |
| `content` | TEXT | Splitter 最终产出的可检索 Chunk 原文 |
| `content_hash` | VARCHAR(64) | 内容 SHA-256 |
| `chunk_type` | VARCHAR(32) | `paragraph` / `image` / `table` / `code_block` / `heading` / `mixed` / `text` |
| `start_line` / `end_line` | INT | 源文档起止行号 |
| `chunk_index` | INT | 文档内顺序编号 |
| `dense_vector_status` | VARCHAR(16) | 稠密向量生命周期：`PENDING` / `INDEXING` / `INDEXED` / `FAILED` / `DELETING` / `DELETED` / `DELETE_FAILED` |
| `dense_vector_error_msg` | VARCHAR(512) | 稠密向量最近一次写入或补偿失败原因 |
| `dense_vector_retry_count` | INT | 稠密向量已执行的补偿重试次数 |
| `dense_vector_last_retry_at` | DATETIME | 稠密向量最近一次补偿重试时间 |
| `dense_vector_model` | VARCHAR(128) | 实际使用的稠密向量模型 |
| `sparse_vector_status` | VARCHAR(16) | 稀疏向量生命周期：`PENDING` / `INDEXING` / `INDEXED` / `FAILED` / `DELETING` / `DELETED` / `DELETE_FAILED` |
| `sparse_vector_model` | VARCHAR(128) | 实际使用的稀疏向量模型 |
| `sparse_vector_nonzero_count` | INT | 稀疏向量非零维度数量 |
| `sparse_vector_error_msg` | VARCHAR(512) | 稀疏向量失败原因 |
| `sparse_vector_retry_count` | INT | 稀疏向量重试次数 |
| `sparse_vector_last_retry_at` | DATETIME | 稀疏向量最近一次重试时间 |
| `es_status` | VARCHAR(16) | `PENDING` / `SUCCESS` / `FAILED` |
| `es_error_msg` | VARCHAR(512) | ES 索引失败原因 |
| `create_time` / `update_time` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_chunk_id(chunk_id)`
- `idx_user_set(user_id, set_id)`
- `idx_bucket_dense_vector_status(bucket_id, dense_vector_status)`
- `idx_bucket_sparse_status(bucket_id, sparse_vector_status)`
- `idx_doc_sparse_status(doc_id, sparse_vector_status)`
- `idx_bucket_es_status(bucket_id, es_status)`
- `idx_doc_id(doc_id)`
- `idx_chunk_type(chunk_type)`
- `idx_content_hash(content_hash)`

---

## 字段命名约定

- 时间戳：`created_at` / `updated_at`（对 `kb_document_chunk` 历史命名为 `create_time` / `update_time`，新增表应使用 `_at` 版本）。
- 状态字段：上游业务用 lowercase（`upload_status` 用 `uploading/success/failed`）；后处理流程用 UPPER（`PENDING/PROCESSING/SUCCESS/FAILED`）。
- 加密字段：在字段注释中显式标注 "加密存储" 并说明解密 Secret 来源。
- 外键字段：`<table>_id` 命名，注释中显式给出 "对应 X.Y" 引用。

详见 [docs/conventions/naming_conventions.md](../conventions/naming_conventions.md)。

## 相关文档

- 向量索引模式：[qdrant_schema.md](qdrant_schema.md)
- 全文索引模式：[elasticsearch_schema.md](elasticsearch_schema.md)
- API 契约：[api_contracts.md](api_contracts.md)
- 解析流水线架构：[../architecture/parse_task_pipeline_module.md](../architecture/parse_task_pipeline_module.md)
