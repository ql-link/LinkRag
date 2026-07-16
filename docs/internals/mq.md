# MQ Module

本文说明 `src/core/mq` 消息中台模块的架构、使用方式，以及新增或修改 MQ 消息和厂商适配的方法。

## 1. 模块框架

```text
src/core/mq/
├── interfaces.py              # IMQSender / IMQReceiver 抽象接口
├── factory.py                 # MQFactory 注册式厂商工厂；装配 RetryPolicy / DLQ publisher
├── message.py                 # AbstractMessage / MessagePayload 基类
├── observability.py           # 发送日志字段格式化、耗时与消息大小计算
├── topic_admin.py             # Kafka Topic 初始化（含死信 *.DLT 同规格幂等创建）
├── exceptions.py              # MQ 异常类型（含 RetriableError 可重试基类）
├── retry.py                   # 厂商中立失败兜底编排：有限退避重试 + 死信投递
├── consumers/
│   ├── parse_task_consumer.py      # 解析任务消费 handler（订阅装配在组合根 src/main.py）
│   └── document_delete_consumer.py # 删除通知消费 handler（LINK-55；委托 DocumentDeletePurger）
├── messages/
│   ├── parse_task.py          # Java -> Python 解析任务消息
│   ├── document_delete.py     # Java -> Python 删除通知（LINK-55，扁平裸 JSON 无信封）
│   ├── token_usage.py         # 统一 Token 用量上报（全部模型调用）
│   └── chat_turn.py           # 对话内容持久化上报（Python -> Java 落库，不含 token）
│   # parse_result.py 已删除（LINK-166：终态回传 MQ 下线，终态只写 DB）
└── vendors/
    ├── rabbitmq_adapter.py    # 启动声明 DLX/DLT；手动 ack/reject 走 retry 编排
    └── kafka/
        ├── kafka_adapter.py   # 精确 TopicPartition 提交；失败走 retry 编排
        └── topic_admin.py
```

服务层入口：

```text
BusinessCode
  -> MQService
    -> MQFactory
      -> KafkaSender / KafkaReceiver / RabbitMQSender / RabbitMQReceiver
```

消费链路：

```text
FastAPI lifespan（src/main.py 组合根装配 _start_mq_consumers）
  -> MQService.subscribe(parse_task, group, handle_parse_task)
    -> ParseTaskMessage.parse_msg() -> ParseTaskPipeline.execute()
  -> MQService.subscribe(document_delete, group, handle_document_delete)
    -> DocumentDeleteMessage.parse_msg() -> DocumentDeletePurger.purge()
```

> 删除消费 `document_delete`：删除幂等可重试，`handle_document_delete` 把 purge 执行异常统一包成 `RetriableError` 交框架退避重试；坏消息在 `parse_msg` 抛 `MQSerializationError`（终态）直进死信。删除编排见 `src/core/pipeline/document_delete/`（先删 Qdrant/ES/OSS，最后删 DB 行；不碰原文件）。

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `IMQSender` / `IMQReceiver` | `interfaces.py` | MQ 厂商必须实现的发送和接收抽象 |
| `MQFactory` | `factory.py` | 根据 `MQ_VENDOR` 懒加载并缓存厂商适配器 |
| `MQService` | `src/services/mq_service.py` | 业务侧统一发送、订阅和关闭入口 |
| `AbstractMessage` | `message.py` | 业务消息基类，定义序列化、MQ 名称和路由键 |
| `ParseTaskMessage` | `messages/parse_task.py` | Java 投递的解析任务消息 |
| `KafkaSender` / `KafkaReceiver` | `vendors/kafka/kafka_adapter.py` | Kafka 厂商适配 |
| `RabbitMQSender` / `RabbitMQReceiver` | `vendors/rabbitmq_adapter.py` | RabbitMQ 厂商适配 |

## 3. 当前消息类型

| 消息 | 默认 Topic/Queue | 方向 | 说明 |
| --- | --- | --- | --- |
| `ParseTaskMessage` | `tolink.rag.parse_task` | Java -> Python | 触发文档解析任务（含首次解析与重试，由 `is_retry` + `previous_task_id` 区分；详见 [mq_integration.md §ParseTaskPayload](../api/mq_contracts.md)） |
| `DocumentDeleteMessage` | `tolink.rag.document_delete` | Java -> Python | 删除通知：按 `delete_type`（dataset/file）清理解析域衍生产物，不碰原文件（详见 [mq_contracts.md §删除通知](../api/mq_contracts.md)） |
| `TokenUsageMessage` | `tolink.rag.usage_report` | Python -> Java/统计侧 | 统一上报**全部**模型调用用量（对话 generate、解析 embed/sparse/vision/table、召回 embed/sparse/rerank），含 `stage`/`operation` 归属。topic/mq_type 沿用历史值，Java 无需重绑 queue（详见 [mq_contracts.md §用量上报](../api/mq_contracts.md#用量上报pythonjava统计侧)） |
| `ChatTurnMessage` | `tolink.rag.chat_turn` | Python -> Java | 上报一轮 RAG 问答的**对话内容**（query/answer/references/`turn_id`/三态 `status`/error/首轮 `title`，**不含 token**），起点 `GENERATING` + 终态 `COMPLETED`/`FAILED` 同 `turn_id`，供 Java upsert 落库 `chat_message` + 更新 `chat_conversation`（token 改走 `TokenUsageMessage`；首轮 `title` 在标题空/默认时落 `chat_conversation.title`，详见 [mq_contracts.md](../api/mq_contracts.md)） |

`ParseTaskMessage` 中的 `md_bucket` 为历史兼容字段；不论 `file_type`（含 `md`/`markdown`），解析产物实际都写入 `MINIO_PRIVATE_BUCKET` 配置桶，`md_object_key` 仍来自消息。`md`/`markdown` 透传只跳过解析引擎转换，不跳过落盘。

> 当前 `consumers/` 下有 `parse_task_consumer.py` 与 `document_delete_consumer.py` 两个消费入口。`TokenUsageMessage` / `ChatTurnMessage` 在本服务侧生产、由 Java 消费。`ChatTurnMessage` 由 RAG 生成的**后台任务**生产（`recall_stream_runtime`）：起点发 `GENERATING`、终态发 `COMPLETED`/`FAILED`，客户端断连不取消任务；`TokenUsageMessage` 由全链路埋点经 `src/services/usage_reporter.py` 生产，发送失败仅告警不阻断主链路。
>
> 收发 topic 名由各消息类的 `MQ_NAME` 常量固定，`PARSE_TASK_TOPIC` 等环境变量仅用于 §4.1 的 Kafka topic 自动创建，不改变实际收发 topic。

> **parse_result 终态回传 MQ 已下线（LINK-166）**：Python 端解析完成后**只写 DB 终态**（`document_parse_pipeline`），不再向 Java 发送 `ParseResultMessage`。`messages/parse_result.py` 与生产侧 `ParseResultNotifier`、`PARSE_RESULT_TOPIC` 配置项均已删除。前端改由轮询 Java `parse-results` 接口读 DB 获取终态（LINK-98）；Java 端停止消费见 LINK-165。

### Trace ID 透传

`MQService` 在服务层处理 trace id，不要求各业务消息重复声明字段：

- 发送：当前协程已有 trace id 时，`MQService.send()` / `send_raw()` 自动把它写入 `X-Trace-Id` 消息头；调用方显式传入的同名 header 优先。
- 消费：`MQService.subscribe()` 会包装业务 callback，从 metadata headers 中读取 `X-Trace-Id` / `x-trace-id` / `trace_id` / `trace-id`，并在 callback 执行期间绑定到日志上下文。
- 业务 payload 不变；缺少 trace header 时按普通消息消费，日志里的 `trace_id` 为空。

### 消费者层异常兜底

`consumers/parse_task_consumer.py::handle_parse_task` 在 `ParseTaskPipeline.execute()` 之外再包一层 catch-all：

- **反序列化失败**（`ParseTaskMessage.parse_msg` 抛错）：无 payload / 无解析日志行，直接抛出交由 §4.1 死信兜底（Java 端 stuck scanner 最终收敛文件状态）。
- **`execute` 逃逸异常**（pipeline 内部兜底之外的未预期错误，如 DB/会话故障）：记录日志后直接 `raise`，交由 §4.1 死信兜底。终态权威源是 DB，前端轮询读取，无需 Python 回发任何通知。

## 4. 配置

MQ 配置统一来自 `src/config.py::Settings` 和 `.env`：

- `MQ_VENDOR`: `kafka` 或 `rabbitmq`
- `KAFKA_BOOTSTRAP_SERVERS`
- `KAFKA_SASL_MECHANISM`
- `KAFKA_SASL_USERNAME`
- `KAFKA_SASL_PASSWORD`
- `KAFKA_SECURITY_PROTOCOL`
- `KAFKA_MAX_POLL_INTERVAL_MS`
- `INIT_KAFKA_TOPICS_ON_STARTUP`
- `RABBITMQ_URL`
- `RABBITMQ_EXCHANGE_NAME`
- `RABBITMQ_EXCHANGE_TYPE`
- `RABBITMQ_PREFETCH_COUNT`

Kafka Topic 初始化还会读取：

- `PARSE_TASK_TOPIC`
- `USAGE_REPORT_TOPIC`
- `CHAT_TURN_TOPIC`
- `DOCUMENT_DELETE_TOPIC`
- `REPLICATION_FACTOR`
- `MIN_INSYNC_REPLICAS`
- `MAX_MESSAGE_BYTES`

## 4.1 失败兜底（重试 + 死信）

消费框架对业务回调异常做有限退避重试 + 死信兜底，业务消费者无需感知。设计与配置：

- 异常分类：抛出 `src.core.mq.exceptions.RetriableError` 的子类表示"暂时性、值得重试"；
  其它从 Pipeline 兜底之外逃出的异常视为终态，不重试直接进死信。
- 编排：`src.core.mq.retry.dispatch_with_retry` 是厂商中立的核心；Kafka / RabbitMQ
  receiver 失败路径都走它。
- 死信目标命名：`<原 topic / queue> + MQ_DLQ_SUFFIX`（默认 `.DLT`）。
  - Kafka：`topic_admin.build_default_topic_specs()` 为每个业务 topic 同规格创建 `.DLT`，
    启动时随 `ensure_topics()` 幂等装配。
  - RabbitMQ：`RabbitMQReceiver.start()` 期声明 `<queue>.DLX` 交换器 + 死信队列，
    原队列声明附 `x-dead-letter-exchange` 参数。
- 死信消息头携带 `x-original-topic` / `x-exception-class` / `x-exception-message` /
  `x-retry-count` / `x-original-key` / `x-failed-at`，body 沿用原始字节不重新序列化。
- Kafka 位点提交按 `{TopicPartition: offset + 1}` 精确提交（不再使用无参 commit，
  避免坏消息被后续成功消息"静默跳过"导致丢数据）。
- 重试计数仅存进程内存（不持久化）；进程重启后重新从 0 起算一轮上限内重试。
- 配置项（来自 `Settings`，无开关项——死信兜底恒启用）：
  - `MQ_MAX_RETRIES`（默认 3）
  - `MQ_RETRY_BACKOFF_SECONDS`（默认 1.0）
  - `MQ_DLQ_SUFFIX`（默认 `.DLT`）

## 4.2 发送侧日志

所有业务消息通过 `MQService.send()` 发送，统一记录：

- `mq_send_started`（DEBUG）
- `mq_send_succeeded`（INFO）
- `mq_send_failed`（ERROR，包含 traceback）

通用字段包括 `type`、`topic`、`routing_key`、`duration_ms`、`message_bytes`。
消息类通过 `AbstractMessage.get_log_fields()` 返回白名单业务摘要：

| 消息 | 日志摘要字段 |
| --- | --- |
| `ParseTaskMessage` | `message_id`、`task_id`、`doc_id`、`parse_file_id`、`user_id`、`dataset_id`、`file_type`、重试字段 |
| `TokenUsageMessage` | `message_id`、`user_id`、厂商/模型、`stage`、`operation`、三类 token、`config_id`、`task_id`、耗时和状态 |
| `ChatTurnMessage` | `message_id`、`conversation_id`、`request_id`、`turn_id`、`user_id`、模型、状态、引用数量、错误码；不记录 query/answer/title/error_message |
| `DocumentDeleteMessage` | `message_id`、`delete_type`、`dataset_id`、`user_id`、`original_file_id` |

`MQService.send_raw()` 使用 `mq_raw_send_*` 事件，只记录 topic、routing key、消息
字节数和 header 名称，不记录 raw body 或 header 值。死信发送绕过 `MQService`，由
`MQFactory.get_dlq_publisher()` 记录 `mq_dlq_send_*`，同样不打印消息正文和死信
header 值。

发送日志严禁直接输出完整 payload。新增消息类型时应覆写 `get_log_fields()`，只返回
排障必需且确认允许记录的字段。trace id 仍按上文约定通过消息 header 透传。

## 5. 新增消息类型

1. 在 `src/core/mq/messages/` 下新增消息文件。
2. 定义 `MessagePayload` 子类，使用 Pydantic 字段校验业务 payload。
3. 定义 `AbstractMessage` 子类，实现 `MQ_NAME`、`MQ_TYPE`、`get_payload()` 和必要的 `parse_msg()`；覆写 `get_log_fields()` 声明安全日志摘要。
4. 在 `src/core/mq/messages/__init__.py` 暴露新类型。
5. 若需要 HTTP 调试入口，同步更新 `src/api/routes/mq.py`、`src/api/schemas/mq.py` 和 `docs/api/http_contracts.md`。
6. 增加 `tests/unit/core/mq` 单元测试。

## 6. 新增 MQ 厂商

1. 实现 `IMQSender` 和 `IMQReceiver`。
2. 在 `MQFactory._register_defaults()` 或启动初始化逻辑中注册厂商。
3. 在 `Settings` 和 `.env.example` 增加厂商配置。
4. 补齐发送、订阅、异常和关闭资源的测试。

业务代码只依赖 `MQService` 和 `AbstractMessage`，不要直接操作 Kafka/RabbitMQ SDK。

## 7. 测试建议

```bash
.venv/bin/pytest tests/unit/core/mq -q
.venv/bin/pytest tests/integration/core/mq -q
```

建议覆盖：

- 消息序列化和反序列化。
- 缺字段、非法 JSON、非对象消息的错误。
- `MQFactory` 按配置选择厂商；retry policy / DLQ publisher 注入。
- `MQService` 发送和订阅调用链。
- Kafka Topic 初始化参数（含 `.DLT` 同规格）。
- `retry.dispatch_with_retry`：可重试退避、终态直进死信、死信投递失败保留消息。
- `KafkaReceiver._commit_partition_offset` 精确提交、跨分区隔离。
- `RabbitMQReceiver.start()` 声明 DLX/DLT；`_on_message` 手动 ack/reject。
- 验收套件：`tests/acceptance/test_mq_dlq_poison_pill.py`。
