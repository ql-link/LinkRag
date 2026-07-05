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

## 公共消息头

所有 MQ 消息可选携带 `X-Trace-Id` header，用于和 HTTP 请求、Java 服务日志、Python 服务日志串联。Python 端发送消息时会把当前日志上下文中的 trace id 写入 `X-Trace-Id`；消费消息时会读取 `X-Trace-Id`、`x-trace-id`、`trace_id` 或 `trace-id` header 并绑定到当前处理协程的日志上下文。

该字段是消息头，不属于业务 payload；缺失时不影响消费兼容性。

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
  "source_bucket": "tolink-rag-raw",
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
  "source_bucket": "tolink-rag-raw",
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

## 删除通知（Java → Python，LINK-55）

数据集 / 文件删除采用「Java 隐性软删 + Python 清产物」两段式：Java 在删除事务里软删原文件行（`document_original_file.is_deleted=1`，保留 OSS 原文件对象）、物理删会话消息，提交后（afterCommit）发本通知；Python 据此删除**解析域衍生产物**（解析三表 + `kb_document_chunk` + Qdrant 向量点 + ES 索引 + OSS `parsed/.../{taskId}/` 下的 Markdown 与图片），**不碰原文件**。

### Topic

- 实际收发 topic：`tolink.rag.document_delete`（由 `DocumentDeleteMessage.MQ_NAME` 固定）。
- 环境变量 `DOCUMENT_DELETE_TOPIC` 仅用于 Kafka topic 自动创建，默认同名；不改变 Python 实际订阅 topic。
- 语义 `QUEUE`（点对点），消费组 `tolink.rag.document_delete`。

### 消息体（DocumentDeletePayload）

扁平裸 JSON + snake_case，**无信封**（与 parse_task 一致，区别于 chat_turn / usage_report 的 `{mq_type,mq_name,payload}` 信封）；Java 侧 `JSON.toJSONString` 直发，消费端 `json.loads` 即得下表。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `delete_type` | string | ✅ | 删除范围：`dataset` / `file` |
| `dataset_id` | int (BIGINT) | ✅ | 所属数据集 id |
| `user_id` | int (BIGINT) | ✅ | 操作用户 id（归属维度，删除时兜底校验防越权） |
| `original_file_id` | int (BIGINT) | 仅 `file` 必填 | 被软删的原文件 id；`dataset` 范围不下发（Java 端为 null，fastjson 省略） |

### 消息示例

删数据集（按 dataset 级联删名下全部衍生产物，不下发文件清单）：

```json
{"delete_type": "dataset", "dataset_id": 10, "user_id": 100}
```

删单文件（按 original_file_id 删该文件衍生产物）：

```json
{"delete_type": "file", "dataset_id": 200, "user_id": 100, "original_file_id": 1}
```

### 幂等、顺序与可靠性

- **幂等**：按 id / filter 删，重复消费 no-op；删不存在产物按成功处理。
- **删除次序（Python 侧）**：先删外部存储（Qdrant/ES/OSS），最后删 DB 行——DB 行是定位外部产物的账本，留到最后删保证崩溃/重试安全。
- **无顺序保证**：Java 发送不带 key，分区轮询；删除通知之间、与 parse_task 之间均无时序约束。
- **可靠性**：Java 尽力发（afterCommit 失败仅告警吞掉，无对账）；Python 坏消息进死信跳过，暂时性失败退避重试（≤3 次）耗尽进 `.DLT`。

### 边界

- 不删原文件：`document_original_file` 行（Java 软删保留）与 OSS 原文件对象（Java 保留）。透传 md（`file_type∈{md,markdown}`）的 `parsed_object_key` 指向原文件对象，Python 按「非 `parsed/` 前缀跳过」护栏排除。
- 不删账务/用户态：`llm_usage_log`、`chat_*`（会话消息由 Java 物理删）。

## 终态读取（Python → DB → 前端轮询）

> **parse_result 终态回传 MQ 已下线（LINK-166）**。Python 端解析完成后**只写 DB 终态**，不再向 Java 发送 MQ 通知；`ParseResultMessage` 消息体与生产侧代码、`PARSE_RESULT_TOPIC` 配置项均已删除。Java 端停止消费见 LINK-165。

### 终态权威源

解析终态的权威源是 MySQL `document_parse_pipeline`（`pipeline_status` = `SUCCESS` / `FAILED`，附 `failed_stage` / `recover_from_stage` / `failure_reason` / 各阶段耗时）。前端改由轮询 Java 的 `parse-results` 接口读 DB 获取状态（LINK-98），不再依赖 Python 的回传消息。

### 终态语义

- `SUCCESS`：Markdown 转换 + 分片 + 向量化 + 索引入库**全部完成**。
- `FAILED`：上述任一环节失败，具体原因见 `failure_reason`。

不存在 "部分成功" 状态。中间步骤的细节状态由 toLink-Rag 写入 `document_parse_pipeline`，前端通过 Java 查询接口读取。

## 对话轮次上报（Python→Java）

RAG 问答在 Python 端（`/api/v1/rag/stream`）以**后台任务**执行，生成起点与终态各发一条 `ChatTurnMessage`，由 **Java 消费并落库**：在单事务里 upsert `chat_message` 一行（一行一轮：query + answer 同行），并更新 `chat_conversation` 的 `last_config_id` / `last_model_name` / `updated_at`。Python 侧不写这两张表。

> 职责拆分（LINK-191）：本消息**只负责对话内容持久化，不再携带 token**；本轮 `generate` 的 token 用量随统一的[用量上报消息](#用量上报pythonjava统计侧)单独上报（`stage='chat'`、`operation='generate'`），不再由 `chat_turn` 触发 `llm_usage_log` 落库。动机：token 统计链路不应依赖携带大文本（query/answer）的消息。

落库时序（chat-stream-resilient-persist）：生成任务**起点**先发 `status=GENERATING`（`answer` 空），**终态**再发 `COMPLETED`/`FAILED`，两条消息携带同一 `turn_id`，Java 据 `turn_id` **upsert 同一行**（起点插「生成中」行，终态更新该行）。客户端断连不取消任务，生成续跑到终态并落库。

会话标题（LINK-209）：标题**生成职责完全在 Python**——首轮（前端在 `/rag/stream` 传 `is_first_turn=true`）基于 `query` 调用本轮对话模型生成短标题，随终态 `chat_turn.title` 上报，并通过 SSE `conversation_title` 事件即时回前端。Java 不再发起任何标题 LLM 调用、也不再用首问截断造临时标题，仅作条件落库：当 `chat_conversation.title` 为空或仍为默认「新对话」时写入上游 `title`，否则跳过（不覆盖用户手改）。

### Topic

- 实际收发 topic：`tolink.rag.chat_turn`（由 `ChatTurnMessage.MQ_NAME` 固定）。

### 消息体（ChatTurnPayload）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | int | ✅ | 所属对话 ID（前端请求 `/rag/stream` 时传入，由 Java 预先创建） |
| `request_id` | string | ✅ | 请求追踪 ID（每 HTTP 请求级，**不再充当幂等键**；幂等键改用 `turn_id`） |
| `turn_id` | string | ✅ | 轮次幂等键：前端每轮生成的稳定 UUID（断连重连不变），Java 据此 **upsert 同一行** → `chat_message.turn_id`（唯一） |
| `user_id` | int | ✅ | 用户 ID |
| `query` | string | ✅ | 用户提问 → `chat_message.query` |
| `answer` | string | ✅ | LLM 回答 → `chat_message.answer`（`GENERATING`/`FAILED` 可空或半截串） |
| `config_id` | int | ✅ | 本轮所用 LLM 配置 ID |
| `provider_type` | string | ⬜ | LLM 厂商类型（`GENERATING` 起点与模型未解析的前置失败时为空串，终态补齐） |
| `model_name` | string | ⬜ | 模型名快照（可空时为空串） |
| `references` | string[] | ⬜ | 召回片段 `chunk_id` 列表（仅标识，不含正文）→ `chat_message.references` |
| `latency_ms` | int | ⬜ | 生成延迟（毫秒） |
| `status` | string | ✅ | `GENERATING`（生成起点占位）/ `COMPLETED`（成功或空命中占位）/ `FAILED`（任意失败，含生成超时） |
| `error_code` | string | ⬜ | 失败码（仅 `FAILED`）：`RECALL_*`（前置/生成失败）或 `GENERATION_TIMEOUT`（生成超时）→ `chat_message.error_code` |
| `error_message` | string | ⬜ | 失败原因（仅 `FAILED`），不含堆栈 → `chat_message.error_message` |
| `title` | string | ⬜ | 会话标题，**仅会话首轮终态携带**（Python 基于 `query` 生成，LLM 不可用/失败时回落首问截断）→ `chat_conversation.title`。Java 仅在当前标题为空或仍为默认「新对话」时写入并按列宽（255）截断，**不覆盖用户手动改过的标题**；`GENERATING` 起点与非首轮一律为 `null` |

> `prompt_tokens` / `completion_tokens` / `total_tokens` 已从本消息**移除**（LINK-191），改由统一用量消息承载；`provider_type` / `latency_ms` 仍保留供 Java 落库快照。

> 公共信封字段 `message_id` / `timestamp` 由消息基类自动附带（见 [§协议要点](#协议要点)）。
> 旧值 `success`/`partial`/`failed` 已退役；`partial` 取消——断连不再产生半截终态（任务续跑到 `COMPLETED`），唯一半截场景为生成超时 → `FAILED` + `GENERATION_TIMEOUT`（保留已生成文本）。

### 路由键与语义

- 路由键：`conversation_id`，保证同一对话的起点与终态有序投递；Java upsert 以 `turn_id` 为准、按 `status` 不回退。
- **每轮至少两条**：起点 `GENERATING` + 终态（`COMPLETED`/`FAILED`），同 `turn_id`。
- **空召回也落库**：0 命中或全部片段缺正文时回 `recall_done`，并发 `COMPLETED`（`answer` 空占位），不再「不产生对话轮次」。
- **缺 `conversation_id` / `turn_id` 不发消息**：`/rag/stream` 缺任一直接 422，不进入召回生成。
- **最终一致**：Python 端发送失败仅告警、不影响已返回答案；Java 侧以 `turn_id` 幂等 upsert，配合对账补偿。
- **归属校验（Java 必做）**：`conversation_id` 来自前端请求体，`user_id` 取自 session token claims，Python 仅透传、不校验二者归属关系。Java 落库前**必须**校验 `conversation_id` 属于该 `user_id`（不匹配则丢弃/告警），否则存在跨用户写入他人对话的风险。

## 用量上报（Python→Java/统计侧）

**全部模型调用**的 token 用量经统一的 `TokenUsageMessage` 上报，由 Java 消费后落 `llm_usage_log` 一行：对话 `generate`（stage=`chat`）、解析侧 dense embed / 图片增强(vision) / 表格增强(table)、召回侧 query embed / rerank。对话内容持久化另走 [`chat_turn`](#对话轮次上报pythonjava)，与本用量解耦（LINK-191）。

### Topic

- 实际收发 topic：`tolink.rag.usage_report`（由 `TokenUsageMessage.MQ_NAME` 固定）。
- **topic / mq_type 沿用历史值**（`tolink.rag.usage_report` / `USAGE_REPORT`）：Java 现有 usage_report 消费者无需重新绑定 queue，本次对 Java 是纯增量——该消费者现在也会收到 `generate` 行。

### 消息体（TokenUsagePayload）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `user_id` | string | ✅ | 用户 ID |
| `provider_type` | string | ✅ | LLM 厂商类型 |
| `model_name` | string | ✅ | 模型名称 |
| `stage` | string | ✅ | 阶段：`parse` / `recall` / `chat` |
| `operation` | string | ✅ | 操作：`embed` / `sparse` / `rerank` / `vision` / `table` / `generate`（`generate` 即对话 stage=`chat`） |
| `prompt_tokens` | int | ✅ | 输入 Token；向量类调用即此列 |
| `completion_tokens` | int | ✅ | 输出 Token；向量类（embed/rerank）恒为 0，vision/table 为真实生成 token |
| `total_tokens` | int | ✅ | 总 Token |
| `config_id` | int | ⬜ | 用户配置 ID；系统配置调用缺省 → 落 NULL |
| `task_id` | string | ⬜ | 解析任务锚点（parse·embed 带；vision/table 暂不带） |
| `latency_ms` | int | ⬜ | 调用耗时（毫秒） |
| `status` | string | ⬜ | `success` / `partial` / `failed`，默认 `success` |

> 公共信封字段 `message_id` / `timestamp` 由消息基类自动附带。

### 路由键与语义

- 路由键：`user_id`，按用户分区。
- **口径**：token 一律由模型返回，Python 不自算；向量类 `completion_tokens=0`。
- **token 由模型返回的取舍**：`sparse` 向量模型若返回 `usage`，Python 会按 `operation='sparse'` 上报并带实际绑定的 `config_id`；未返回 token 时跳过上报。
- **解析侧粒度**：task 级聚合——每个解析任务每 operation 上报一条（token 在任务内累加），不落 chunk 级明细。全缓存命中（token=0）不上报。
- **旁路、最终一致**：用量是事后算账的旁路记录。Python 上报失败仅告警、不阻断解析/召回主链路，丢一条用量可接受。
- **Java 落库**：字段直映射 `llm_usage_log`；可空字段缺失落 NULL。对话 `generate` 的行也经本消息上报（`stage='chat'`、`operation='generate'`），不再由 `chat_turn` 落 `llm_usage_log`，使本表口径全链路一致（LINK-191）。

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
