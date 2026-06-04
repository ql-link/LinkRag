# MQ Integration

本文面向**业务方**（通常是 Java 管理端）介绍如何通过 MQ 与 toLink-Rag 协作：投递解析任务、接收终态通知。

权威消息定义见 [src/core/mq/messages](../../src/core/mq/messages)，本文是面向接入方的精简版。

## 协作模式

```
Java 管理端                          toLink-Rag (Python)
    │                                      │
    │  ① 投递解析任务 (ParseTaskMessage)   │
    ├─────────────────────────────────────►│
    │      topic: PARSE_TASK_TOPIC         │
    │      默认 tolink-document-pares      │
    │                                      │
    │                                      │  ② 异步处理：
    │                                      │     解析 → 分片 → 向量化 → 索引
    │                                      │
    │  ③ 终态回调 (ParseResultMessage)     │
    │◄─────────────────────────────────────┤
    │      topic: PARSE_RESULT_TOPIC       │
    │      默认 tolink.rag.parse_result    │
```

Topic 名称由 toLink-Rag 的 `.env` 配置决定，业务方对接前需要从 toLink-Rag 部署侧获取实际值。

## 解析任务投递（Java → Python）

### Topic

- 配置项：`PARSE_TASK_TOPIC`
- 默认值：`tolink-document-pares`（注意是 `pares`，历史遗留拼写）

### 消息体（ParseTaskPayload）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string | ✅ | 任务唯一 ID（业务方生成的幂等键） |
| `original_file_id` | int | ✅ | 业务方原始文件表主键 |
| `document_parse_task_id` | int | ✅ | 业务方文件解析表主键（`document_parse_file.id`） |
| `user_id` | int | ✅ | 文件所属用户 |
| `dataset_id` | int | ✅ | 文件所属数据集 |
| `file_type` | string | ✅ | 文件格式：`pdf` / `docx` / `html` / ... |
| `source_bucket` | string | ✅ | 源文件对象存储 bucket |
| `source_object_key` | string | ✅ | 源文件对象存储 key |
| `source_filename` | string | ✅ | 用户上传时的原始文件名 |
| `md_bucket` | string | ✅ | 解析后 Markdown 输出 bucket（`md`/`markdown` 透传时不使用，见下方说明） |
| `md_object_key` | string | ✅ | 解析后 Markdown 输出 key（`md`/`markdown` 透传时不使用，见下方说明） |
| `trigger_mode` | string | ⬜ | `upload_auto`（默认） / `manual_retry` |
| `pdf_parser_backend` | string | ⬜ | `mineru`（默认） / `opendataloader` / `naive` / `auto` |
| `docling_force_ocr` | bool | ⬜ | 仅 Docling 后端生效 |
| `image_bucket` | string | ⬜ | PDF 图片输出 bucket |
| `image_prefix` | string | ⬜ | PDF 图片输出 key 前缀 |
| `is_retry` | bool | ⬜ | `false`（默认）表示首次解析；`true` 表示用户触发的重试任务。老消息缺省默认 `false`，与首次解析路径完全等价（migration 0009 新增） |
| `previous_task_id` | string | ⬜ | `is_retry=true` 时必填，指向上一轮失败任务的 `task_id`；Python 端 `ParseTaskGuard.validate_retry_context` 会严格校验上一轮记录存在、pipeline 失败且可恢复。若恢复点晚于 `CLEANING`，还会要求上一轮 markdown 已成功上传 |

> **重试链路约束**（与 [parse_task_pipeline.md §4 重试分支](../internals/parse_task_pipeline.md) 配套）：
> - 重试请求由 Java 端在判定旧任务 `pipeline_status=FAILED` 后发起；Python 端不计数、不限次。若旧任务 `recover_from_stage=CLEANING`，允许旧 log 没有 `parsed_object_key`，Python 会重新下载源文件、解析并上传 markdown。
> - 重试请求的 `md_bucket` / `md_object_key` 是本次 markdown 产物目标坐标。恢复点晚于 `CLEANING` 时应与上轮一致（Java 直接回填）；从 `CLEANING` 恢复时用于承接重新上传后的 markdown。
> - Python 通过 CAS 第 2 层（`mark_superseded` UPDATE rowcount）仲裁并发重试，失败方仍会建一行 `pipeline_status=FAILED` + `failed_stage=RETRY_VALIDATION` 的审计记录，并通过 parse_result 主题通知 Java FAILED。

### 消息示例

首次解析：

```json
{
  "task_id": "task-20260516-001",
  "original_file_id": 12345,
  "document_parse_task_id": 67890,
  "user_id": 1001,
  "dataset_id": 2001,
  "file_type": "pdf",
  "source_bucket": "tolink-rag-docs",
  "source_object_key": "raw/2026/05/16/doc-001.pdf",
  "source_filename": "技术规范.pdf",
  "md_bucket": "tolink-rag-docs",
  "md_object_key": "parsed/2026/05/16/doc-001.md",
  "trigger_mode": "upload_auto",
  "pdf_parser_backend": "mineru",
  "image_bucket": "tolink-rag-docs",
  "image_prefix": "images/2026/05/16/doc-001/"
}
```

重试任务（后处理阶段恢复时 Java 直接回填上轮 markdown 坐标；`CLEANING` 恢复时作为本次重新上传目标坐标）：

```json
{
  "task_id": "task-20260527-002",
  "original_file_id": 12345,
  "document_parse_task_id": 67890,
  "user_id": 1001,
  "dataset_id": 2001,
  "file_type": "pdf",
  "source_bucket": "tolink-rag-docs",
  "source_object_key": "raw/2026/05/16/doc-001.pdf",
  "source_filename": "技术规范.pdf",
  "md_bucket": "tolink-rag-docs",
  "md_object_key": "parsed/2026/05/16/doc-001.md",
  "trigger_mode": "manual_retry",
  "is_retry": true,
  "previous_task_id": "task-20260516-001"
}
```

> **`md` / `markdown` 透传**：源文件本身即目标 Markdown，cleaning 阶段跳过解析引擎转换，也**不再把 markdown 重复写入 `md_bucket`**——markdown 产物坐标直接取上传位置（`source_bucket` / `source_object_key`）。因此对 md/markdown 文件，业务方读取解析产物（预览/下载）须以 `document_parsed_log.parsed_bucket_name` / `parsed_object_key`（即上传位置）为准，不可硬取请求里的 `md_object_key`。其余格式（pdf/docx/html/…）仍把转换后的 markdown 写入 `md_bucket`/`md_object_key`，行为不变。

### 路由键

消息以 `file_type` 作为 routing key，便于按文件类型做消费侧分流。

## LLM 配置缓存同步（Java → Python）

### Topic

- 配置项：`CACHE_SYNC_TOPIC`
- 默认值：`tolink.rag.cache_sync`

Java 管理端新增、更新、删除或切换 LLM 配置后投递缓存同步消息。消息使用标准 MQ 信封，payload 字段如下：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `user_id` | string | ✅ | 被修改配置的所属用户。`"0"` 表示系统预设配置 |
| `config_id` | string/null | ⬜ | 具体配置 ID。消息体不携带 capability，Python 按用户维度扩大清理 |
| `action` | string | ⬜ | `refresh` / `invalidate` / `warmup`，默认 `refresh` |

清理规则：

- `user_id!="0"`：清理该用户全部 LLM 配置缓存；如带 `config_id`，同时清理该配置详情缓存；并清理该用户 `ModelFactory` 客户端缓存。
- `user_id="0"`：系统预设变更会影响所有未设置个人默认配置的用户，因此清理所有用户 LLM 配置缓存、系统厂商缓存和全部 `ModelFactory` 客户端缓存。

## 终态通知（Python → Java）

### Topic

- 配置项：`PARSE_RESULT_TOPIC`
- 默认值：`tolink.rag.parse_result`

### 消息体（ParseResultPayload）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string | ✅ | 与请求中的 `task_id` 一致，用于关联 |
| `original_file_id` | int | ✅ | 来自请求 |
| `document_parsed_log_id` | int | ✅ | `document_parsed_log.id`，Java 据此回查解析日志与流水线终态 |
| `dataset_id` | int | ✅ | 来自请求 |
| `user_id` | int | ✅ | 来自请求 |
| `task_status` | string | ✅ | `success` / `failed` |
| `parse_finished_at` | string | ✅ | ISO 8601 格式时间 |
| `failure_reason` | string | ⬜ | `failed` 时的失败原因摘要 |
| `user_message` | string | ⬜ | 可直接展示给用户的提示文案 |

### 终态语义

- `success`：Markdown 转换 + 分片 + 向量化 + 索引入库**全部完成**。
- `failed`：上述任一环节失败，具体原因见 `failure_reason`。

不存在 "部分成功" 状态。中间步骤的细节状态请查询 toLink-Rag 内部的解析任务表，不在 MQ 通知里下发。

### 路由键

消息以 `task_id` 作为 routing key，便于业务方按任务维度关联请求与结果。

## 协议要点

- **传输格式**：JSON。
- **字符集**：UTF-8。
- **幂等键**：`task_id`。toLink-Rag 内部以 `task_id` 做去重，重复投递不会重复处理。
- **MQ 中间件**：默认 Kafka（`MQ_VENDOR=kafka`），可切换为 RabbitMQ（`MQ_VENDOR=rabbitmq`）。
- **认证**：Kafka 默认 SASL_PLAINTEXT + PLAIN 机制，生产环境应改用 SASL_SSL。
- **超时**：toLink-Rag 侧 `KAFKA_MAX_POLL_INTERVAL_MS` 默认 900000（15 分钟），单条任务处理需在该窗口内完成或下一轮 poll 前不会被踢出 group。

## 同步调试接口

业务方在联调阶段可以不经过 MQ，直接调用 HTTP 接口：

| 路径 | 用途 |
| --- | --- |
| `POST /api/v1/parser/extract_sync` | 同步解析，仅测试用 |
| `POST /api/v1/parser/task/submit` | 触发异步任务（内部投递 MQ） |
| `POST /api/v1/mq/send/parse-task` | 直接投递 MQ 消息（管理端用） |

Swagger 文档：`http://<host>:<port>/docs`

## 版本兼容性

- 新增字段必须设计为**可选**，避免历史消息无法反序列化。
- 字段删除或重命名属于**破坏性变更**，需同步 Java 端版本并升级 schema。
- 消息体增删字段需同步更新 [src/core/mq/messages/](../../src/core/mq/messages/) 和 [docs/api/schemas/](schemas/)。

## 相关文档

- 部署与 MQ 启停：[deploy.md](../ops/deploy.md)
- 配置项详解：[configure.md](../ops/configure.md)
- MQ 模块架构：[mq.md](../internals/mq.md)
- 解析任务流水线：[parse_task_pipeline.md](../internals/parse_task_pipeline.md)
