# MQ Integration

本文面向**业务方**（通常是 Java 管理端）介绍如何通过 MQ 与 toLink-Rag 协作：投递解析任务、读取解析终态。

权威消息定义见 [src/core/mq/messages](../../src/core/mq/messages)，本文是面向接入方的精简版。

## 协作模式

```
Java 管理端                          toLink-Rag (Python)
    │                                      │
    │  ① 投递解析任务 (ParseTaskMessage)   │
    ├─────────────────────────────────────►│
    │      topic: tolink.rag.parse_task    │
    │                                      │
    │                                      │  ② 异步处理：
    │                                      │     解析 → 分片 → 向量化 → 索引
    │                                      │     终态写入 document_parse_pipeline (DB)
    │                                      │
    │  ③ 前端轮询 Java parse-results 接口读 DB 取终态
    │      （不再有 Python→Java 的 MQ 回传，见下方「终态读取」）
```

> **parse_result 终态回传 MQ 已下线（LINK-166）**：Python 端不再发送解析终态通知消息。解析终态的权威源是 MySQL `document_parse_pipeline`，前端改由轮询 Java `parse-results` 接口读 DB 获取（LINK-98）。Java 端停止消费见 LINK-165。

收发 topic 名由消息类的 `MQ_NAME` 常量固定（见 [src/core/mq/messages](../../src/core/mq/messages)），不随 `.env` 改变；环境变量 `PARSE_TASK_TOPIC` 仅用于 Kafka topic 的自动创建（`topic_admin`），不影响实际投递/订阅的 topic。业务方按下方固定值对接即可。

## 解析任务投递（Java → Python）

### Topic

- 实际收发 topic：`tolink.rag.parse_task`（由 `ParseTaskMessage.MQ_NAME` 固定）
- 环境变量 `PARSE_TASK_TOPIC` 仅用于 Kafka topic 自动创建，默认值同样是 `tolink.rag.parse_task`；改它不会改变 Python 端实际订阅的 topic

### 消息体（ParseTaskPayload）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string | ✅ | 任务唯一 ID（业务方生成的幂等键） |
| `original_file_id` | int | ✅ | 业务方原始文件表主键 |
| `document_parse_file_id` | int | ✅ | 业务方文件解析表主键（`document_parse_file.id`）。这是序列化输出的规范字段名；为兼容历史也接受别名 `document_parse_task_id`（任投递其一即可） |
| `user_id` | int | ✅ | 文件所属用户 |
| `dataset_id` | int | ✅ | 文件所属数据集 |
| `file_type` | string | ✅ | 文件格式：`pdf` / `docx` / `html` / ... |
| `source_bucket` | string | ✅ | 源文件对象存储 bucket |
| `source_object_key` | string | ✅ | 源文件对象存储 key |
| `source_filename` | string | ✅ | 用户上传时的原始文件名 |
| `md_bucket` | string | ✅ | 历史兼容字段；Python 侧非 `md`/`markdown` 解析产物实际写入 `MINIO_PRIVATE_BUCKET` 配置桶，`md`/`markdown` 透传时不使用 |
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
> - 重试请求的 `md_object_key` 是本次 markdown 产物目标 key；bucket 由 Python 侧 `MINIO_PRIVATE_BUCKET` 决定。恢复点晚于 `CLEANING` 时 key 应与上轮一致（Java 直接回填）；从 `CLEANING` 恢复时用于承接重新上传后的 markdown。
> - Python 通过 CAS 第 2 层（`mark_superseded` UPDATE rowcount）仲裁并发重试，失败方仍会建一行 `pipeline_status=FAILED` + `failed_stage=RETRY_VALIDATION` 的审计记录（终态写 DB，前端轮询读取）。

### 消息示例

首次解析：

```json
{
  "task_id": "task-20260516-001",
  "original_file_id": 12345,
  "document_parse_file_id": 67890,
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
  "document_parse_file_id": 67890,
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

> **`md` / `markdown` 透传**：源文件本身即目标 Markdown，cleaning 阶段跳过解析引擎转换，也**不再把 markdown 重复写入输出桶**——markdown 产物坐标直接取上传位置（`source_bucket` / `source_object_key`）。因此对 md/markdown 文件，业务方读取解析产物（预览/下载）须以 `document_parsed_log.parsed_bucket_name` / `parsed_object_key`（即上传位置）为准，不可硬取请求里的 `md_object_key`。其余格式（pdf/docx/html/…）仍把转换后的 markdown 写入 Python 侧 `MINIO_PRIVATE_BUCKET` / `md_object_key`。

### 路由键

消息以 `file_type` 作为 routing key，便于按文件类型做消费侧分流。

## 终态读取（Python → DB → 前端轮询）

> **parse_result 终态回传 MQ 已下线（LINK-166）**。Python 端解析完成后**只写 DB 终态**，不再向 Java 发送 MQ 通知；`ParseResultMessage` 消息体与生产侧代码、`PARSE_RESULT_TOPIC` 配置项均已删除。Java 端停止消费见 LINK-165。

### 终态权威源

解析终态的权威源是 MySQL `document_parse_pipeline`（`pipeline_status` = `SUCCESS` / `FAILED`，附 `failed_stage` / `recover_from_stage` / `failure_reason` / 各阶段耗时）。前端改由轮询 Java 的 `parse-results` 接口读 DB 获取状态（LINK-98），不再依赖 Python 的回传消息。

### 终态语义

- `SUCCESS`：Markdown 转换 + 分片 + 向量化 + 索引入库**全部完成**。
- `FAILED`：上述任一环节失败，具体原因见 `failure_reason`。

不存在 "部分成功" 状态。中间步骤的细节状态由 toLink-Rag 写入 `document_parse_pipeline`，前端通过 Java 查询接口读取。

## 对话轮次上报（Python→Java）

RAG 问答在 Python 端（`/api/v1/rag/stream`）流式生成结束后，发送一条 `ChatTurnMessage`，由 **Java 消费并落库**：在单事务里写入 `chat_message` 一行（一行一轮：query + answer 同行）、`llm_usage_log` 一行，并更新 `chat_conversation` 的 `last_config_id` / `last_model_name` / `updated_at`。Python 侧不写这三张表。

### Topic

- 实际收发 topic：`tolink.rag.chat_turn`（由 `ChatTurnMessage.MQ_NAME` 固定）。

### 消息体（ChatTurnPayload）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | int | ✅ | 所属对话 ID（前端请求 `/rag/stream` 时传入，由 Java 预先创建） |
| `request_id` | string | ✅ | 请求追踪 ID / 幂等键；Java 据此去重，写入 `chat_message.request_id` 与 `llm_usage_log.request_id` |
| `user_id` | int | ✅ | 用户 ID |
| `query` | string | ✅ | 用户提问 → `chat_message.query` |
| `answer` | string | ✅ | LLM 回答 → `chat_message.answer`（`partial` 为半截，`failed` 可空串） |
| `config_id` | int | ✅ | 本轮所用 LLM 配置 ID |
| `provider_type` | string | ✅ | LLM 厂商类型 |
| `model_name` | string | ✅ | 模型名快照（可空时为空串） |
| `prompt_tokens` | int | ✅ | 输入 Token 数（流式未返回 usage 时为 0） |
| `completion_tokens` | int | ✅ | 输出 Token 数 |
| `total_tokens` | int | ✅ | 总 Token 数 |
| `references` | string[] | ⬜ | 召回片段 `chunk_id` 列表（仅标识，不含正文）→ `chat_message.references` |
| `latency_ms` | int | ⬜ | 生成延迟（毫秒） |
| `status` | string | ✅ | `success`（正常结束）/ `partial`（客户端断连，保留半截）/ `failed`（生成异常） |

> 公共信封字段 `message_id` / `timestamp` 由消息基类自动附带（见 [§协议要点](#协议要点)）。

### 路由键与语义

- 路由键：`conversation_id`，保证同一对话的轮次有序投递。
- **空召回不发消息**：0 命中或全部片段缺正文时只回 `recall_done`，不产生对话轮次。
- **缺 `conversation_id` 不发消息**：`/rag/stream` 缺该字段直接 422，不进入召回生成。
- **最终一致**：Python 端发送失败仅告警、不影响已返回答案；建议 Java 侧以 `request_id` 幂等去重，配合对账补偿。
- **归属校验（Java 必做）**：`conversation_id` 来自前端请求体，`user_id` 取自 session token claims，Python 仅透传、不校验二者归属关系。Java 落库前**必须**校验 `conversation_id` 属于该 `user_id`（不匹配则丢弃/告警），否则存在跨用户写入他人对话的风险。

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
