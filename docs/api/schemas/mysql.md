# MySQL Schema

toLink-Rag 业务表模式参考。**权威来源**：ORM 模型 (`src/models/**.py`) + Alembic migrations (`migrations/versions/*.py`)。

- 冷启动 baseline：[migrations/db.sql](../../../migrations/db.sql)（0001，已冻结）
- 当前完整结构快照（baseline + 已应用 migration）：[scripts/db/init.sql](../../../scripts/db/init.sql)
- 本文是按业务域分组的人读摘要视图

ORM 与 migration 不一致时，以 migration 为准并修正 ORM；scripts/db/init.sql 需在每条 schema 演进的 migration 落库时一并同步。

## 表清单

按业务域共 20 张表：

| 业务域 | 表 | 主键 ID 起始 |
| --- | --- | --- |
| [用户](#1-用户) | `sys_user` | 10000 |
| [LLM 配置与用量](#2-llm-配置与用量) | `llm_system_provider`, `llm_provider_model`, `llm_system_preset`, `llm_user_config`, `llm_usage_log` | 10000 |
| [数据集与对话](#3-数据集与对话) | `dataset`, `dataset_parse_config`, `chat_conversation`, `chat_message` | 10000 |
| [文档解析](#4-文档解析) | `document_original_file`, `document_parse_file`, `document_parsed_log`, `document_parse_pipeline` | 10000 |
| [博客](#5-博客) | `blog_post`, `blog_asset` | 10000 |
| [用户反馈](#6-用户反馈) | `user_feedback` | 10000 |
| [知识索引](#7-知识索引) | `kb_document_chunk` | 10000 |
| [Workflow 运行记录](#8-workflow-运行记录) | `workflow_run`, `workflow_node_run` | 10000 |

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

> **协议（protocol）与入口（api_base_url）三层语义**（LINK-123）：LLM 调用拆成两个正交维度——`protocol`（API 家族，决定 HTTP 怎么拼）× `capability`（用途，决定调哪个端点）。`protocol` 枚举：`openai` / `anthropic` / `google` / `jina` / `dashscope` / `doubao_vision` / `bge_m3`（小写、大小写敏感；后两个为稀疏向量专用）。同一厂商不同能力可走不同协议（如千问 chat 走 `openai`、rerank 走 `dashscope`），故 `protocol` ≠ `provider_type`。
>
> 三层定位：**厂商层**（`llm_system_provider`）= 默认模板，不参与运行决策；**模型能力层**（`llm_provider_model`）= 协议与入口的事实来源；**用户配置层**（`llm_user_config`）= 运行快照，从模型能力层复制，Python 下游按 `(protocol, capability)` 选 adapter，绝不 fallback 厂商默认。`api_base_url` 在厂商层保存协议基地址，仅用于管理端预填；在模型能力层和用户配置层保存**完整端点 URL**，Python adapter 直接请求该 URL，不再拼 capability 后缀。`google` 协议例外，保存到 `/v1beta` 为止，由 Python 按模型和流式模式补全 Gemini 原生路径。

### `llm_system_provider` — LLM 系统级厂商配置

ORM：[`SystemProviderDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 厂商唯一标识 |
| `provider_type` | VARCHAR(32) UNIQUE | `openai` / `claude` / `glm` / `deepseek` 等 |
| `provider_name` | VARCHAR(64) | 厂商展示名 |
| `api_base_url` | VARCHAR(512) | 默认 API 地址（模板值，不参与运行决策） |
| `default_protocol` | VARCHAR(32) | 默认协议（模板值，新增模型能力预填用），默认 `openai` |
| `is_active` | BOOLEAN | 是否启用 |
| `priority` | INT | 厂商优先级（1-100），默认 50 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：`uk_provider_type`。

### `llm_provider_model` — 厂商模型能力目录

ORM：[`ProviderModelDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 主键 |
| `provider_id` | BIGINT UNSIGNED | 关联 `llm_system_provider.id` |
| `model_name` | VARCHAR(128) | 模型名 |
| `capability` | VARCHAR(32) | 单能力；一模型多能力拆成多行 |
| `protocol` | VARCHAR(32) | 调用协议（**事实来源**）；当前 nullable，由 Java 服务层保证非空，待回填后收紧 |
| `api_base_url` | VARCHAR(512) | 调用入口完整端点 URL（**事实来源**；`google` 例外保存 `/v1beta` base） |
| `is_active` | BOOLEAN | 该模型能力是否上架 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_provider_model_cap(provider_id, model_name, capability)`
- `idx_provider_cap(provider_id, capability)`

### `llm_system_preset` — 系统预设模板

ORM：[`SystemPresetDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 主键 |
| `provider_id` | BIGINT UNSIGNED | 关联 `llm_system_provider.id` |
| `model_name` | VARCHAR(128) | 模型名 |
| `capability` | VARCHAR(32) | 能力标识 |
| `provider_type` | VARCHAR(32) | 厂商类型（与用户配置对齐，镜像免 join） |
| `protocol` | VARCHAR(32) | 调用协议（创建预设时复制自模型能力层） |
| `api_base_url` | VARCHAR(512) | 调用入口完整端点 URL（复制自模型能力层） |
| `api_key` | VARCHAR(512) | 平台 Key，**加密存储** |
| `is_active` | BOOLEAN | 是否对新用户下发 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：`uk_preset_provider_model_cap(provider_id, model_name, capability)`。

说明：Python 运行时不直接读取本表决定生效配置；Java 注册时会将 active 预设复制进 `llm_user_config`。

### `llm_user_config` — 用户级 LLM 配置

ORM：[`UserLLMConfigDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 配置唯一标识 |
| `user_id` | BIGINT UNSIGNED | 所属用户 |
| `provider_id` | BIGINT UNSIGNED | 关联 `llm_system_provider.id` |
| `provider_type` | VARCHAR(32) | 厂商类型快照，用于下游路由到对应 SDK |
| `api_key` | VARCHAR(512) | **加密存储**，由 `API_KEY_ENCRYPTION_SECRET` 解密 |
| `api_base_url` | VARCHAR(512) | 实际生效地址：完整端点 URL，复制自模型能力层事实（不 fallback 厂商默认） |
| `protocol` | VARCHAR(32) | 调用协议快照：复制自模型能力层，下游按 `protocol`+`capability` 选 adapter |
| `model_name` | VARCHAR(128) | 具体模型名 |
| `capability` | VARCHAR(32) | `CHAT` / `EMBEDDING` / `SPARSE_EMBEDDING` / `RERANK` / `VISION` 等，默认 `CHAT`；`OCR` 不再作为独立 LLM capability |
| `is_active` | BOOLEAN | 模型启停 + 生效过滤 |
| `is_default` | BOOLEAN | 该能力是否生效 |
| `is_system_preset` | BOOLEAN | 是否系统预设行 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_user_provider_model_capability(user_id, provider_id, model_name, capability, is_system_preset)`
- `idx_user_active_default(user_id, is_active, is_default)`
- `idx_user_provider_cap(user_id, provider_type, capability)`

运行时读取生效配置：

```sql
SELECT *
FROM llm_user_config
WHERE user_id = :user_id
  AND capability = :capability
  AND is_default = TRUE
  AND is_active = TRUE
LIMIT 1;
```

### `llm_usage_log` — LLM 调用用量日志

ORM：[`UsageLogDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 记录唯一标识 |
| `user_id` | BIGINT UNSIGNED | 用户 ID |
| `config_id` | BIGINT UNSIGNED NULL | 用户配置 ID；走系统配置的调用（如召回 query 编码）无 per-user 配置，可空 |
| `provider_type` | VARCHAR(32) | 厂商类型 |
| `model_name` | VARCHAR(128) | 模型名称 |
| `prompt_tokens` | INT | 输入 Token 数；向量类调用（embed/sparse/rerank）即此列 |
| `completion_tokens` | INT | 输出 Token 数；向量类调用恒为 0 |
| `total_tokens` | INT | 总 Token 数 |
| `latency_ms` | INT | 响应延迟（毫秒） |
| `status` | VARCHAR(16) | `success` / `failed` / `partial` |
| `error_message` | VARCHAR(512) | 错误信息 |
| `fallback_config_id` | BIGINT UNSIGNED | 触发 Fallback 时记录原配置 ID |
| `conversation_id` | BIGINT UNSIGNED | 关联对话 ID（由 Java 消费 `chat_turn` 消息时写入） |
| `message_id` | BIGINT UNSIGNED | 关联产生该用量的 `chat_message` 行 |
| `request_id` | VARCHAR(64) | 与 `chat_message` 同一把 key，串联一轮问答 |
| `stage` | VARCHAR(16) NULL | 阶段：`parse` / `recall` / `chat`；归属一条用量出自哪个阶段 |
| `operation` | VARCHAR(16) NULL | 操作：`embed` / `sparse` / `rerank` / `vision` / `table` / `generate`；`sparse` 本期预留不写入 |
| `created_at` | DATETIME | 创建时间 |

索引：`idx_user_date`, `idx_config_date`, `idx_conversation_id`, `idx_usage_message_id`, `idx_user_stage_date`。

> 全链路归属（0022）：本表从「对话账本」升级为「全链路模型调用账本」。对话最终 `generate` 的行仍由 Java 消费 `chat_turn` 落库（Java 补 `stage='chat'`、`operation='generate'`）；解析侧 embed/vision/table、召回侧 embed/rerank 的行由 Python 通过 `tolink.rag.usage_report` 上报、Java 消费落库。token 一律由模型返回（不自算），向量类 `completion_tokens=0`。`sparse` 因模型不返回 token 本期预留不上报，仅在 `operation` 枚举占位。详见 [mq_contracts.md](../mq_contracts.md#用量上报pythonjava统计侧)。

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
| `is_deleted` | BOOLEAN | 逻辑删除标记，默认 `FALSE` |
| `deleted_seq` | BIGINT UNSIGNED | 删除判别列：活行为 `0`，软删后为自身 `id`，支持删后同名重建 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_dataset_user_name_seq(user_id, name, deleted_seq)`
- `idx_dataset_user_updated(user_id, updated_at)`

### `dataset_parse_config` — 数据集解析/检索参数配置表

按数据集独立设置解析/检索参数。四个 JSON 列分别承载分块、Markdown 增强、PDF 解析、召回检索四类配置；未配置或缺字段时由 Python 侧回退系统默认值。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 配置唯一标识 |
| `user_id` | BIGINT UNSIGNED | 所属用户 ID |
| `dataset_id` | BIGINT UNSIGNED | 所属数据集 ID，对应 `dataset.id` |
| `chunking_config` | JSON | 分块配置（3 项：heading_break_level / min_candidate_chunk_tokens / overlap_tokens；旧 percentile 语义切片参数已随 splitter 重写移除） |
| `enhancement_config` | JSON | Markdown 增强配置（2 项：enable_table_enhancement / enable_image_enhancement）。仅控制是否开启表格/图片增强；增强模型不在此选择，统一用发起用户对应能力（CHAT/VISION）的默认模型。历史数据残留的 table_model / vision_model 键被忽略 |
| `pdf_config` | JSON | PDF 解析配置（1 项：pdf_parser_backend，null 表示用系统默认） |
| `recall_config` | JSON | 召回检索配置（9 项：recall_result_limit / recall_context_token_budget / sparse_top_k / sparse_score_threshold / dense_top_k / dense_score_threshold / recall_enabled_sources / rerank_top_n / recall_strict）。其中 recall_enabled_sources 为启用的召回路数组（bm25/sparse/dense，**仅能在系统已装配的召回路集合内收窄**，列出的未装配路被忽略、交集为空时回退全部已装配路）；rerank_top_n 为重排返回条数上限；recall_strict 为召回容错模式（true=任一路失败即整体失败，false=允许单路失败降级） |
| `is_active` | BOOLEAN | 是否启用，默认 `TRUE` |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_user_dataset(user_id, dataset_id)`
- `idx_dataset_parse_config_dataset(dataset_id)`

> 所有权：表结构由 Python 侧 Alembic 迁移管理；**行数据的增删改由 Java 侧负责**，Python 侧只读，无配置行时使用内存默认。

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

### `chat_message` — 对话消息表（一行一轮）

一行同时承载用户提问与 LLM 回答（RAG 单轮严格一问一答），不再用 role 区分的逐消息两行模型。

ORM：[`ChatMessageDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 消息唯一标识 |
| `conversation_id` | BIGINT UNSIGNED | 所属对话 |
| `config_id` | BIGINT UNSIGNED | 产生该消息所使用的 LLM 配置 |
| `model_name` | VARCHAR(128) | 模型名快照 |
| `query` | MEDIUMTEXT | 用户提问 |
| `answer` | MEDIUMTEXT | LLM 回答（`GENERATING`/`FAILED` 可空或半截） |
| `references` | JSON | 召回片段 `chunk_id` 列表（仅标识，不含正文） |
| `request_id` | VARCHAR(64) | 请求追踪 ID（每 HTTP 请求级，不再作幂等键） |
| `turn_id` | VARCHAR(64) | 轮次幂等键：前端每轮稳定 UUID，Java 据此 upsert 同一行（唯一索引，既有行为 NULL）（migration 0023 新增） |
| `status` | VARCHAR(16) | `GENERATING` / `COMPLETED` / `FAILED`（旧 `success`/`partial`/`failed` 退役） |
| `error_code` | VARCHAR(64) | 失败码 `RECALL_*`/`GENERATION_TIMEOUT`，仅 `FAILED`（migration 0023 新增） |
| `error_message` | VARCHAR(512) | 失败原因，不含堆栈，仅 `FAILED`（migration 0023 新增） |
| `created_at` | DATETIME | 创建时间 |

索引：`idx_conversation_created(conversation_id, created_at)`、`uk_chat_message_turn_id(turn_id) UNIQUE`（migration 0023）。

> 所有权：表结构由 Python 侧 Alembic 迁移管理（含 `chat_conversation`）；**行数据的增删改由 Java 侧负责**——Java 消费 Python 发出的 `tolink.rag.chat_turn` 消息后，单事务写入 `chat_message` 行、`llm_usage_log` 行并更新 `chat_conversation`。Python 侧不写这三张表的行数据。详见 [mq_contracts.md](../mq_contracts.md#对话轮次上报pythonjava)。

---

## 4. 文档解析

四张表覆盖完整链路：**原始文件 → 解析任务表 → 解析日志 → 后处理流程**。

```
document_original_file (1)──(N) document_parse_file (1)──(N) document_parsed_log (1)──(0/1) document_parse_pipeline
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
| `is_deleted` | BOOLEAN | 逻辑删除标记，默认 `FALSE`；软删保留原文件和 OSS 对象 |
| `deleted_seq` | BIGINT UNSIGNED | 删除判别列：活行为 `0`，软删后为自身 `id`，支持删后同名重传 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_dof_name_suffix_seq(dataset_id, user_id, original_filename, file_suffix, deleted_seq)`
- `idx_document_original_dataset_created`
- `idx_document_original_user_created`
- `idx_document_original_upload_status`

### `document_parse_file` — 文件解析任务表

记录一个原始文件**当前**的解析任务关系。一文件一行（`document_original_file_id` 唯一）。

ORM：[`DocumentParseTask`](../../../src/models/parse_task.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 主键 |
| `document_original_file_id` | BIGINT UNSIGNED UNIQUE | 原文件 ID |
| `dataset_id` | BIGINT UNSIGNED | 数据集 ID |
| `user_id` | BIGINT UNSIGNED | 用户 ID |
| `latest_parse_task_id` | VARCHAR(36) NULL | 最新解析 task_id |
| `original_filename` | VARCHAR(255) | 原文件名快照 |
| `parse_count` | INT | 累计解析次数 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_parse_task_original_file(document_original_file_id)`
- `idx_parse_task_dataset_user(dataset_id, user_id, updated_at)`
- `idx_parse_task_latest_task(latest_parse_task_id)`

### `document_parsed_log` — 文件解析产物快照表

每次触发解析产生一条，承担解析产物（Markdown 文件位置、解析起止时间）与触发上下文的快照。**整体任务状态的权威单源是 `document_parse_pipeline`**；本表不再保存 `task_status` / `failure_reason`（migration 0007 已下线）。重试链路通过 `retry_of_task_id` 串接（migration 0009 新增）。

ORM：[`DocumentParsedLog`](../../../src/models/parse_task.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 主键 |
| `task_id` | VARCHAR(36) UNIQUE | 解析任务 UUID |
| `document_original_file_id` | BIGINT UNSIGNED | 原文件 ID |
| `document_parse_file_id` | BIGINT UNSIGNED NULL | 文件解析表 ID |
| `trigger_mode` | VARCHAR(20) | `upload_auto` / `manual_retry` |
| `parsed_filename` | VARCHAR(255) | 解析后文件名 |
| `parsed_bucket_name` | VARCHAR(64) | 解析结果桶 |
| `parsed_object_key` | VARCHAR(512) | 解析结果对象 Key（Java 侧判定"markdown 是否已上传"的依据） |
| `parsed_file_url` | VARCHAR(1024) | 解析结果内部 URL |
| `parsed_at` | DATETIME | 解析时间 |
| `parse_started_at` / `parse_finished_at` | DATETIME | Python 解析开始 / 结束时间 |
| `parse_duration_ms` | BIGINT | 解析耗时 |
| `retry_of_task_id` | VARCHAR(36) NULL | 重试链路上一轮 `task_id`；首次解析为 `NULL` |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_parse_task_id(task_id)`
- `idx_parsed_log_original_file(document_original_file_id, updated_at)`
- `idx_parsed_log_parse_file(document_parse_file_id, updated_at)`
- `idx_parsed_log_retry_of(retry_of_task_id)`

> **历史兼容字段名**：代码与 API 中 `document_parse_task_id` 与本表的 `document_parse_file_id` 等价（同一字段）。

### `document_parse_pipeline` — 文件解析流程状态表

整体任务状态的**权威单源**，覆盖**文档清洗 → 分片 → 向量化 → 预分词 → ES 入库 → 稀疏向量化**六段状态机。

> **术语映射**：brief / acceptance 中的 `parsing_status` 与 `parsing_duration_ms` 在代码与 schema 中实际为 `cleaning_status` 与 `cleaning_duration_ms`（migration 0007 落地时选择 cleaning 词根）。统一重命名由 issue [#48](https://github.com/ql-link/LinkRag/issues/48) 跟踪。

ORM：[`DocumentParsePipeline`](../../../src/models/parse_task.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 主键 |
| `document_parsed_log_id` | BIGINT UNSIGNED UNIQUE | 解析日志主键 |
| `task_id` | VARCHAR(36) | 解析任务 ID |
| `document_original_file_id` | BIGINT UNSIGNED | 原文件 ID |
| `document_parse_file_id` | BIGINT UNSIGNED NULL | 文件解析表 ID |
| `pipeline_status` | VARCHAR(20) | 整体任务状态：`PENDING` / `PROCESSING` / `SUCCESS` / `FAILED`（Java 侧判定"上次任务是否整体成功"的唯一字段；`SUCCESS` 翻转点为 sparse 阶段成功） |
| `cleaning_status` | VARCHAR(20) | 文档清洗（=解析+上传 markdown）阶段状态：`PENDING` / `PROCESSING` / `SUCCESS` / `FAILED`（brief 称 `parsing_status`） |
| `chunking_status` | VARCHAR(20) | `PENDING` / `PROCESSING` / `SUCCESS` / `FAILED` |
| `vectorizing_status` | VARCHAR(20) | `PENDING` / `PROCESSING` / `SUCCESS` / `FAILED` |
| `pretokenize_status` | VARCHAR(20) | 预分词状态：`PENDING` / `PROCESSING` / `SUCCESS` / `FAILED` |
| `es_indexing_status` | VARCHAR(20) | `PENDING` / `PROCESSING` / `SUCCESS` / `FAILED` |
| `sparse_vectorizing_status` | VARCHAR(20) | 稀疏向量阶段状态：`PENDING` / `PROCESSING` / `SUCCESS` / `FAILED`（migration 0009 新增） |
| `failed_stage` | VARCHAR(20) | `CLEANING(PARSING)` / `CHUNKING` / `VECTORIZING` / `PRETOKENIZE` / `ES_INDEXING` / `SPARSE_VECTORIZING` / `RETRY_VALIDATION` |
| `recover_from_stage` | VARCHAR(20) | 下次恢复阶段（首个非 SUCCESS 阶段，6 阶段顺序；`RETRY_VALIDATION` 不进入该序列） |
| `failure_reason` | VARCHAR(512) | 整体失败原因摘要（含前缀 `PARSING_FAILED:` / `VECTORIZING_FAILED:` / `pretokenize:` / `ES_INDEXING_FAILED:` / `SPARSE_VECTORIZING_FAILED:` / `RETRY_VALIDATION_FAILED:` 等） |
| `cleaning_duration_ms` | BIGINT | 文档清洗阶段耗时（brief 称 `parsing_duration_ms`） |
| `chunking_duration_ms` | BIGINT | 分片耗时 |
| `vectorizing_duration_ms` | BIGINT | 向量化耗时 |
| `pretokenize_duration_ms` | BIGINT | 预分词耗时 |
| `es_indexing_duration_ms` | BIGINT | ES 入库耗时 |
| `sparse_vectorizing_duration_ms` | BIGINT | 稀疏向量阶段耗时（migration 0009 新增） |
| `total_duration_ms` | BIGINT | 总耗时 |
| `superseded_by_task_id` | VARCHAR(36) NULL | 被哪个新 `task_id` 接班（重试 CAS 第 2 层目标列；migration 0009 新增；`NULL` 表示未被接班） |
| `started_at` / `finished_at` | DATETIME | 开始 / 结束时间 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_parse_pipeline_parsed_log(document_parsed_log_id)`
- `idx_parse_pipeline_task_id(task_id)`
- `idx_parse_pipeline_parse_file(document_parse_file_id, updated_at)`
- `idx_parse_pipeline_status(pipeline_status, updated_at)`
- `idx_parse_pipeline_superseded(superseded_by_task_id)`

> **重试治理已下线**（migration 0007）：`chunk_count` / `retry_count` / `last_retry_at` 移除。chunk 数量由真值表 `kb_document_chunk` 为 source of truth；重试由 Java 端负责，重试链通过 `document_parsed_log.retry_of_task_id` 与 `document_parse_pipeline.superseded_by_task_id` 双向追溯（migration 0009）。
>
> **`pipeline_status=SUCCESS` 翻转点**：6 阶段全部 `*_status=SUCCESS` 后由 `mark_sparse_vectorizing_success` 唯一翻转；`mark_es_success` 不再触碰 `pipeline_status`。
>
> **重试 CAS 两层保护**：第 1 层（快速失败）在 `ParseTaskGuard.validate_retry_context` 通过 `SELECT superseded_by_task_id IS NULL` 校验；第 2 层（真正原子）在 `ParsePipelineRepository.mark_superseded` 通过 `UPDATE ... WHERE superseded_by_task_id IS NULL` 的 rowcount 仲裁。

---

## 5. 博客

### `blog_post` — 博客文章表

ORM：[`BlogPostDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 博客文章唯一标识 |
| `title` | VARCHAR(255) | 文章标题 |
| `slug` | VARCHAR(255) | 公开访问标识，由 Java 侧生成 |
| `summary` | VARCHAR(1000) | 文章摘要 |
| `content_object_key` | VARCHAR(512) | Markdown 正文对象 Key |
| `cover_asset_id` | BIGINT UNSIGNED | 封面资源 ID，对应 `blog_asset.id` |
| `status` | VARCHAR(20) | `DRAFT` / `PUBLISHED`，默认 `DRAFT` |
| `published_at` | DATETIME | 首次发布时间 |
| `created_by` | BIGINT UNSIGNED | 创建管理员用户 ID，仅用于审计 |
| `is_deleted` | BOOLEAN | 逻辑删除标记 |
| `deleted_seq` | BIGINT UNSIGNED | 删除判别列：活行为 `0`，软删后为自身 `id` |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_blog_post_slug_seq(slug, deleted_seq)`
- `idx_blog_post_public_list(status, published_at, id)`
- `idx_blog_post_admin_list(is_deleted, updated_at, id)`

### `blog_asset` — 博客文章资源表

ORM：[`BlogAssetDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 博客资源唯一标识 |
| `post_id` | BIGINT UNSIGNED | 所属博客文章 ID |
| `asset_type` | VARCHAR(20) | `COVER` / `CONTENT_IMAGE` |
| `original_filename` | VARCHAR(255) | 上传时的原始文件名 |
| `content_type` | VARCHAR(128) | 文件 MIME 类型 |
| `file_size` | BIGINT UNSIGNED | 文件大小，单位字节 |
| `object_key` | VARCHAR(512) | MinIO 对象 Key |
| `public_url` | VARCHAR(1024) | 资源公开访问 URL |
| `created_by` | BIGINT UNSIGNED | 上传管理员用户 ID |
| `is_deleted` | BOOLEAN | 逻辑删除标记 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_blog_asset_object_key(object_key)`
- `idx_blog_asset_post_type(post_id, asset_type, is_deleted, created_at)`

说明：博客 HTTP 工作流由 Java 侧负责；Python 侧迁移链负责创建共享库表。博客资源与反馈附件统一存入公开桶 `MINIO_PUBLIC_BUCKET`（默认 `tolink-public`，需由部署环境配置公开读策略）；原博客专用桶 `tolink-blog` 已并入该公开桶。

---

## 6. 用户反馈

### `user_feedback` — 匿名用户反馈表

ORM：[`UserFeedbackDB`](../../../src/models/db_models.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 反馈唯一标识 |
| `type` | VARCHAR(32) | 反馈类型：`BUG` / `FEATURE` / `EXPERIENCE` / `OTHER`，默认 `OTHER` |
| `title` | VARCHAR(128) | 反馈标题 |
| `content` | TEXT | 反馈详细内容 |
| `attachment_object_key` | VARCHAR(512) | 附件 MinIO object key，由 Java 上传后写入 |
| `status` | VARCHAR(32) | 处理状态：`PENDING` / `PROCESSING` / `RESOLVED` / `CLOSED`，默认 `PENDING` |
| `priority` | TINYINT | 处理优先级：1=高，2=中，3=低，默认 3 |
| `admin_id` | BIGINT UNSIGNED | 处理该反馈的管理员用户 ID |
| `admin_reply` | TEXT | 管理员处理回复或处理结论 |
| `processed_at` | DATETIME | 管理员处理完成或最后一次处理该反馈的时间 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `idx_feedback_created(created_at)`
- `idx_feedback_status_priority(status, priority, created_at)`
- `idx_feedback_type_created(type, created_at)`

说明：反馈提交、附件上传和管理员处理 HTTP 工作流由 Java 侧负责；Python 侧仅通过 migration 创建共享库表。`attachment_object_key` 只保存 MinIO object key，不保存文件流、bucket 配置或派生路径。

---

## 7. 知识索引

### `kb_document_chunk` — 文档 Chunk 真值记录表

向量库与 ES 的**可重建来源**。每个 Chunk 一行，`chunk_id` 与 Qdrant Point ID 一一对应。

ORM：[`ChunkRecordDB`](../../../src/models/chunk_record.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 物理主键 |
| `chunk_id` | VARCHAR(128) UNIQUE | Chunk 业务唯一键，对应 Qdrant Point ID |
| `doc_id` | BIGINT UNSIGNED | 文档 ID（对应原始文件） |
| `set_id` | BIGINT UNSIGNED | 知识集 / 数据集 ID |
| `user_id` | BIGINT UNSIGNED | 用户 ID |
| `bucket_id` | INT NULL | 路由后的 Qdrant 物理桶编号（路由前为空） |
| `content` | TEXT | Splitter 最终产出的可检索 Chunk 原文 |
| `content_hash` | VARCHAR(64) | 内容 SHA-256 |
| `chunk_type` | VARCHAR(32) | `paragraph` / `image` / `table` / `code_block` / `heading` / `mixed` / `text` |
| `start_line` / `end_line` | INT | 源文档起止行号 |
| `chunk_index` | INT | 文档内顺序编号 |
| `dense_vector_status` | VARCHAR(16) | 稠密向量状态：`PENDING` / `SUCCESS` / `FAILED` |
| `dense_vector_model` | VARCHAR(128) | 实际使用的稠密向量模型 |
| `sparse_vector_status` | VARCHAR(16) | 稀疏向量状态：`PENDING` / `SUCCESS` / `FAILED` |
| `sparse_vector_model` | VARCHAR(128) | 实际使用的稀疏向量模型 |
| `es_status` | VARCHAR(16) | `PENDING` / `SUCCESS` / `FAILED` |
| `lifecycle_status` | VARCHAR(16) | Chunk 业务生命周期状态：`ACTIVE`=业务有效，可参与解析 / 索引 / 检索；`REMOVED`=已从业务视图移除，不再参与解析 / 索引 / 检索，外部索引清理由异步任务处理 |
| `create_time` / `update_time` | DATETIME | 创建 / 更新时间 |

> 重试治理 (`*_retry_count` / `*_last_retry_at`) 与失败原因 (`*_error_msg`) 已从本表移除（migration 0006）：文件级状态机由 `document_parse_pipeline` 承担，失败原因从 `document_parse_pipeline.failure_reason` 读取；chunk 表仅保留断点续传必需的产物状态反查谓词、业务生命周期状态与产物元数据。`dense_vector_status` / `sparse_vector_status` / `es_status` 只表示产物状态；业务有效性统一由 `lifecycle_status` 表达。

索引：
- `uk_chunk_id(chunk_id)`
- `idx_user_set(user_id, set_id)`
- `idx_doc_dense_status(doc_id, dense_vector_status)`
- `idx_doc_sparse_status(doc_id, sparse_vector_status)`
- `idx_doc_es_status(doc_id, es_status)`
- `idx_doc_lifecycle_status(doc_id, lifecycle_status)`
- `idx_lifecycle_update_time(lifecycle_status, update_time)`

---

## 8. Workflow 运行记录

通用 workflow engine 的运行记录表。它们只记录 demo / 后续显式接入的 workflow run 与 node run，不替代现有 `document_parse_pipeline`、`document_parsed_log` 或 `kb_document_chunk`。

### `workflow_run` — Workflow Run 记录表

ORM：[`WorkflowRunDB`](../../../src/models/workflow.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 物理主键 |
| `run_id` | VARCHAR(36) UNIQUE | workflow run UUID |
| `definition_name` | VARCHAR(64) | workflow 定义名，例如 `parse_task_demo` |
| `biz_key` | VARCHAR(128) NULL | 业务关联键；parse demo 可使用 `task_id` |
| `previous_run_id` | VARCHAR(36) NULL | 断点续跑时指向上一轮 run |
| `status` | VARCHAR(16) | `CREATED` / `RUNNING` / `SUCCESS` / `FAILED` |
| `failure_phase` | VARCHAR(16) NULL | `RUN` / `RESTORE` / `SCHEDULE` |
| `failure_reason` | VARCHAR(512) NULL | run 级失败原因摘要 |
| `started_at` / `finished_at` | DATETIME | 开始 / 结束时间 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_workflow_run_id(run_id)`
- `idx_workflow_run_biz_key(biz_key)`
- `idx_workflow_run_previous(previous_run_id)`
- `idx_workflow_run_definition_status(definition_name, status, updated_at)`

### `workflow_node_run` — Workflow Node Run 记录表

ORM：[`WorkflowNodeRunDB`](../../../src/models/workflow.py)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT UNSIGNED PK | 物理主键 |
| `run_id` | VARCHAR(36) | workflow run UUID |
| `node_key` | VARCHAR(64) | 节点 key |
| `status` | VARCHAR(16) | `PENDING` / `RUNNING` / `SUCCESS` / `SKIPPED` / `FAILED` |
| `requires` | JSON | 节点声明的输入产物 key 列表 |
| `provides` | JSON | 节点声明的输出产物 key 列表 |
| `output_ref` | JSON NULL | 节点可恢复产物引用；框架不解释其结构 |
| `allow_failure` | BOOLEAN | 失败是否可容忍 |
| `tolerated` | BOOLEAN | 本次失败是否已按可容忍处理 |
| `failure_phase` | VARCHAR(16) NULL | `RUN` / `RESTORE` / `SCHEDULE` |
| `failure_reason` | VARCHAR(512) NULL | node 级失败原因摘要 |
| `inherited_from_run_id` | VARCHAR(36) NULL | 断点续跑跳过节点时继承自哪一轮 run |
| `started_at` / `finished_at` | DATETIME | 开始 / 结束时间 |
| `created_at` / `updated_at` | DATETIME | 创建 / 更新时间 |

索引：
- `uk_workflow_node_run(run_id, node_key)`
- `idx_workflow_node_run_run(run_id)`
- `idx_workflow_node_run_status(status, updated_at)`
- `idx_workflow_node_run_inherited(inherited_from_run_id)`

---

## 字段命名约定

- 时间戳：`created_at` / `updated_at`（对 `kb_document_chunk` 历史命名为 `create_time` / `update_time`，新增表应使用 `_at` 版本）。
- 状态字段：上游业务用 lowercase（`upload_status` 用 `uploading/success/failed`）；后处理流程用 UPPER（`PENDING/PROCESSING/SUCCESS/FAILED`）。
- 加密字段：在字段注释中显式标注 "加密存储" 并说明解密 Secret 来源。
- 外键字段：`<table>_id` 命名，注释中显式给出 "对应 X.Y" 引用。

详见 [docs/internals/naming_conventions.md](../../internals/naming_conventions.md)。

## 相关文档

- 向量索引模式：[qdrant_schema.md](qdrant.md)
- 全文索引模式：[elasticsearch_schema.md](elasticsearch.md)
- API 契约：[api_contracts.md](../http_contracts.md)
- 解析流水线架构：[../internals/parse_task_pipeline.md](../../internals/parse_task_pipeline.md)
