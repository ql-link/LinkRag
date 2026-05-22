# MQ Module

本文说明 `src/core/mq` 消息中台模块的架构、使用方式，以及新增或修改 MQ 消息和厂商适配的方法。

## 1. 模块框架

```text
src/core/mq/
├── interfaces.py              # IMQSender / IMQReceiver 抽象接口
├── factory.py                 # MQFactory 注册式厂商工厂；装配 RetryPolicy / DLQ publisher
├── message.py                 # AbstractMessage / MessagePayload 基类
├── topic_admin.py             # Kafka Topic 初始化（含死信 *.DLT 同规格幂等创建）
├── exceptions.py              # MQ 异常类型（含 RetriableError 可重试基类）
├── retry.py                   # 厂商中立失败兜底编排：有限退避重试 + 死信投递
├── consumers/
│   └── parse_task_consumer.py # 解析任务消费者启动入口
├── messages/
│   ├── parse_task.py          # Java -> Python 解析任务消息
│   ├── parse_result.py        # Python -> Java 解析终态通知
│   ├── cache_sync.py          # 用户 LLM 配置缓存同步
│   └── usage_report.py        # LLM 用量上报
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
FastAPI lifespan
  -> start_parse_consumer()
    -> MQService.subscribe()
      -> ParseTaskMessage.parse_msg()
      -> ParseTaskPipeline.execute()
```

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `IMQSender` / `IMQReceiver` | `interfaces.py` | MQ 厂商必须实现的发送和接收抽象 |
| `MQFactory` | `factory.py` | 根据 `MQ_VENDOR` 懒加载并缓存厂商适配器 |
| `MQService` | `src/services/mq_service.py` | 业务侧统一发送、订阅和关闭入口 |
| `AbstractMessage` | `message.py` | 业务消息基类，定义序列化、MQ 名称和路由键 |
| `ParseTaskMessage` | `messages/parse_task.py` | Java 投递的解析任务消息 |
| `ParseResultMessage` | `messages/parse_result.py` | Python 回传 Java 的整体终态通知 |
| `KafkaSender` / `KafkaReceiver` | `vendors/kafka/kafka_adapter.py` | Kafka 厂商适配 |
| `RabbitMQSender` / `RabbitMQReceiver` | `vendors/rabbitmq_adapter.py` | RabbitMQ 厂商适配 |

## 3. 当前消息类型

| 消息 | 默认 Topic/Queue | 方向 | 说明 |
| --- | --- | --- | --- |
| `ParseTaskMessage` | `tolink-document-pares` | Java -> Python | 触发文档解析任务 |
| `ParseResultMessage` | `tolink.rag.parse_result` | Python -> Java | 回传解析整体终态 |
| `CacheSyncMessage` | `tolink.rag.cache_sync` | Java -> Python | 失效或刷新用户 LLM 配置缓存 |
| `UsageReportMessage` | `tolink.rag.usage_report` | Python -> Java/统计侧 | 上报 LLM 调用用量 |

`ParseResultMessage.serialize()` 输出的是 Java 约定的业务 payload，不包含 `mq_type`、`mq_name`、`payload` 信封。

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
- `PARSE_RESULT_TOPIC`
- `CACHE_SYNC_TOPIC`
- `USAGE_REPORT_TOPIC`
- `REPLICATION_FACTOR`
- `MIN_INSYNC_REPLICAS`
- `MAX_MESSAGE_BYTES`

## 4.1 失败兜底（重试 + 死信）

消费框架对业务回调异常做有限退避重试 + 死信兜底，业务消费者无需感知。设计与配置：

- 异常分类：抛出 `src.core.mq.exceptions.RetriableError` 的子类（如
  `ParseResultNotificationError`）表示"暂时性、值得重试"；其它从 Pipeline 兜底之外
  逃出的异常视为终态，不重试直接进死信。
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

## 5. 新增消息类型

1. 在 `src/core/mq/messages/` 下新增消息文件。
2. 定义 `MessagePayload` 子类，使用 Pydantic 字段校验业务 payload。
3. 定义 `AbstractMessage` 子类，实现 `MQ_NAME`、`MQ_TYPE`、`get_payload()` 和必要的 `parse_msg()`。
4. 在 `src/core/mq/messages/__init__.py` 暴露新类型。
5. 若需要 HTTP 调试入口，同步更新 `src/api/routes/mq.py`、`src/api/schemas/mq.py` 和 `docs/reference/api_contracts.md`。
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
.venv/bin/pytest tests/unit/services/test_mq_service.py -q
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
