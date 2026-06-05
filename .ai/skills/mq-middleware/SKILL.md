---
name: mq-middleware
description: 指导 LLM 如何使用 toLink-Rag 项目的 MQ 消息中台进行消息收发、定义新消息类型以及处理多厂商适配逻辑。
when_to_use: "当用户要求接入 Kafka/RabbitMQ、发送或订阅消息、新增 MQ 消息类型、实现消息消费者或处理多消息队列厂商适配时激活。触发示例：'接入Kafka'、'发送一条消息'、'写个MQ消费者'、'新增消息类型'、'对接RabbitMQ'"
---

# MQ 消息中台 Skill (LLM 调用指南)

## 1. 架构定位
该模块通过 `MQFactory` 实现多厂商（Kafka/RabbitMQ）切换。LLM 应优先使用 `MQService` 进行操作，而不是直接实例化 Vendor 适配器。

强制同步要求：
- 只要任务涉及 MQ 模块相关操作，必须在完成代码修改后同步检查并更新本 Skill 的“架构定位”。
- MQ 模块相关操作包括但不限于：新增/修改/删除消息对象、Payload、消费者、Topic 初始化逻辑、厂商适配器、`MQFactory`、`MQService`、MQ 配置项。
- 如果新增 MQ 业务消息，必须把新消息文件同步补充到“当前已落地的 MQ 业务消息”清单。
- 如果新增或调整 MQ 目录职责、入口文件、脚本、Topic 或厂商适配边界，必须同步更新“当前项目的职责边界”。
- 如果本次修改没有改变架构定位中的清单或职责边界，应在交付说明中明确说明“已检查 mq-middleware Skill，无需更新架构定位”，避免遗漏维护动作。

当前项目的职责边界如下：
- `src/core/mq/message.py`：MQ 消息抽象层，定义 `MessagePayload`、`AbstractMessage`、统一消息信封序列化和 `get_routing_key()` 扩展点。
- `src/core/mq/interfaces.py`：MQ 厂商能力接口层，定义 `IMQSender`、`IMQReceiver`、`MQVendorType`，业务代码不直接依赖具体 SDK。
- `src/core/mq/exceptions.py`：MQ 异常体系，包含连接、发送、消费、配置、序列化异常。
- `src/core/mq/messages/`：只放真正的 MQ 业务消息定义，不放 HTTP 请求/响应 DTO。
- `src/core/mq/messages/__init__.py`：统一导出当前 MQ 业务消息和 Payload。
- `src/api/schemas/`：放 FastAPI 路由使用的请求/响应模型。
- `src/services/mq_service.py`：业务侧统一发送/订阅入口，封装 `MQFactory -> Sender/Receiver` 调用链，支持 `send()`、`send_raw()`、`subscribe()`、`start_consuming()`、`stop_consuming()`、`close()`。
- `src/core/mq/factory.py`：注册式单例工厂，根据 `MQ_VENDOR` 选择 Kafka / RabbitMQ 适配器，缓存 Sender/Receiver，并支持测试场景 `reset()`。
- `src/core/mq/vendors/kafka/kafka_adapter.py`：Kafka 厂商适配器，底层封装 `aiokafka`，保持 Topic、ConsumerGroup、Offset 语义，消费成功后手动提交 offset。
- `src/core/mq/vendors/kafka/topic_admin.py`：Kafka Topic Admin 实现，供 Kafka Topic 管理流程使用。
- `src/core/mq/vendors/rabbitmq_adapter.py`：RabbitMQ 厂商适配器，底层封装 `aio-pika`，保持 Exchange、Queue、Binding、RoutingKey、手动 ACK 语义。
- `src/core/mq/consumers/`：消息消费回调实现；当前文档解析消费者位于 `src/core/mq/consumers/parse_task_consumer.py`，启动入口为 `start_parse_consumer()`。
- `src/core/mq/topic_admin.py`：应用启动阶段可调用的 Kafka Topic Admin 逻辑，当前由 `src/main.py` 在 `MQ_VENDOR=kafka` 且 `INIT_KAFKA_TOPICS_ON_STARTUP=true` 时调用。

当前已落地的 MQ 业务消息有 4 类：
- `src/core/mq/messages/parse_task.py`：`ParseTaskMessage` / `ParseTaskPayload`，Topic 为 `tolink.rag.parse_task`，用于文档解析任务投递。
- `src/core/mq/messages/parse_result.py`：`ParseResultMessage` / `ParseResultPayload`，Topic 为 `tolink.rag.parse_result`，用于文档解析终态通知。
- `src/core/mq/messages/cache_sync.py`：`CacheSyncMessage` / `CacheSyncPayload`，Topic 为 `tolink.rag.cache_sync`，用于缓存刷新、失效、预热。
- `src/core/mq/messages/usage_report.py`：`UsageReportMessage` / `UsageReportPayload`，Topic 为 `tolink.rag.usage_report`，用于 LLM 用量上报。

当前应用启动流程中的 MQ 行为：
- `src/main.py` lifespan 中会初始化 Redis、数据库后进入 MQ 初始化逻辑。
- 当 `settings.MQ_VENDOR.lower() == "kafka"` 且 `settings.INIT_KAFKA_TOPICS_ON_STARTUP` 为 `true` 时，调用 `src/core/mq/topic_admin.py::ensure_topics()`。
- 当前会调用 `start_parse_consumer()` 启动文档解析消费者。

不要把消息模型拆成 `payload.py` / `message.py` 两个文件，也不要把 HTTP DTO 放进 `src/core/mq/messages/`。

## 2. 常用操作指令

### 发送消息
当用户要求“发送某某通知”或“触发某项异步任务”时：
1. 检查 `src/core/mq/messages/` 下是否已有对应的消息模型。
2. 如果有，使用 `MQService().send(YourMessage.build(...))`。
3. 如果没有，新增一个“按业务聚合”的消息文件，例如 `src/core/mq/messages/your_event.py`。
4. 不要在路由里直接拼 JSON 字符串，也不要直接实例化 Kafka / RabbitMQ vendor。

### 订阅消息
当用户要求“监听消息”或“处理 MQ 任务”时：
1. 使用 `MQService().subscribe(topic, group_id, callback)`。
2. 确保 `callback` 是一个 `async` 函数。
3. 必须调用 `MQService().start_consuming()` 才会开始拉取消息。
4. 消费者实现优先放在 `src/core/mq/consumers/`。
5. 当前文档解析消费者入口为 `src/core/mq/consumers/parse_task_consumer.py`。

## 3. 当前消息目录约定
新增 MQ 消息时，按“一个业务消息一个文件”组织。例如：

```text
src/core/mq/messages/
  parse_task.py
  parse_result.py
  cache_sync.py
  usage_report.py
  your_event.py
```

每个文件内部同时定义：
- `YourPayload`
- `YourMessage`
- 可选 `MQReceiver` Protocol

不要新增以下结构：
- `your_payload.py`
- `your_message.py`
- `http_models.py`

## 4. 定义新消息模板
如果需要新增业务消息，请按以下结构生成代码：

```python
from src.core.mq.message import AbstractMessage, MessagePayload
from pydantic import Field
from typing import Protocol

class YourPayload(MessagePayload):
    # 定义具体字段
    biz_id: str = Field(..., title="业务ID")

class YourMessage(AbstractMessage):
    MQ_NAME = "your.topic.name"
    MQ_TYPE = "YOUR_TYPE"
    
    def __init__(self, payload: YourPayload):
        self._payload = payload
        
    @classmethod
    def get_mq_name(cls): return cls.MQ_NAME
    
    @classmethod
    def get_mq_type(cls): return cls.MQ_TYPE
    
    def get_payload(self): return self._payload

    @classmethod
    def build(cls, **kwargs):
        return cls(payload=YourPayload(**kwargs))

    @classmethod
    def parse_msg(cls, raw: str) -> YourPayload:
        envelope = cls.deserialize_envelope(raw)
        return YourPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_your_event(self, payload: "YourPayload") -> None: ...
```

补充要求：
- `MQ_NAME` 使用稳定 topic 名称，例如 `tolink.rag.your_event`
- `MQ_TYPE` 使用稳定枚举式字符串，例如 `YOUR_EVENT`
- 如果需要 Kafka key，覆写 `get_routing_key()`
- Payload 只放业务最小必要字段，不塞大对象、不塞文件二进制内容

## 5. Topic 初始化
当前项目支持在应用启动时可选初始化 Kafka Topics：
- 启动时可选初始化：`src/main.py` 的 lifespan 中调用 `src/core/mq/topic_admin.py`

相关约定：
- 默认不开启启动时自动初始化
- 开关配置：`.env` / `settings` 中的 `INIT_KAFKA_TOPICS_ON_STARTUP`
- 仅当 `MQ_VENDOR=kafka` 且开关为 `true` 时才执行初始化

当前默认 Topic：
- `tolink.rag.parse_task`
- `tolink.rag.parse_result`
- `tolink.rag.cache_sync`
- `tolink.rag.usage_report`

## 6. 配置与维护
- 厂商切换在 `.env` 的 `MQ_VENDOR` 字段。
- Kafka 收发依赖：`aiokafka`
- Kafka Topic Admin 依赖：`confluent-kafka`
- RabbitMQ 依赖：`aio-pika`
- Topic 初始化相关配置：
  - `KAFKA_BOOTSTRAP_SERVERS`
  - `KAFKA_SECURITY_PROTOCOL`
  - `KAFKA_SASL_MECHANISM`
  - `KAFKA_SASL_USERNAME`
  - `KAFKA_SASL_PASSWORD`
  - `KAFKA_MAX_POLL_INTERVAL_MS`
  - `INIT_KAFKA_TOPICS_ON_STARTUP`
  - `RABBITMQ_URL`
  - `RABBITMQ_EXCHANGE_NAME`
  - `RABBITMQ_EXCHANGE_TYPE`
  - `RABBITMQ_PREFETCH_COUNT`

调试时优先检查：
- `MQService` log
- `src/core/mq/vendors/kafka/kafka_adapter.py`
- `src/core/mq/vendors/rabbitmq_adapter.py`
- `src/core/mq/topic_admin.py`
- `src/core/mq/vendors/kafka/topic_admin.py`
