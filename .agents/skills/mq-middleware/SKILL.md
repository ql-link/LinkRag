---
name: tolink-rag-mq-middleware
description: 指导 LLM 如何使用 toLink-Rag 项目的 MQ 消息中台进行消息收发、定义新消息类型以及处理多厂商适配逻辑。
when_to_use: "当用户要求对接 MQ（Kafka/RabbitMQ）、发送/订阅消息、定义新消息类型、实现消费者或处理多厂商适配逻辑时激活"
---

# MQ 消息中台 Skill (LLM 调用指南)

## 1. 架构定位
该模块通过 `MQFactory` 实现多厂商（Kafka/RabbitMQ）切换。LLM 应优先使用 `MQService` 进行操作，而不是直接实例化 Vendor 适配器。

## 2. 常用操作指令

### 发送消息
当用户要求“发送某某通知”或“触发某项异步任务”时：
1. 检查 `src/core/mq/messages/` 下是否已有对应的消息模型。
2. 如果有，使用 `MQService().send(YourMessage.build(...))`。
3. 如果没有，先引导用户定义新的 `AbstractMessage`。

### 订阅消息
当用户要求“监听消息”或“处理 MQ 任务”时：
1. 使用 `MQService().subscribe(topic, group_id, callback)`。
2. 确保 `callback` 是一个 `async` 函数。
3. 必须调用 `MQService().start_consuming()` 才会开始拉取消息。

## 3. 定义新消息模板
如果需要新增业务消息，请按以下结构生成代码：

```python
from src.core.mq.message import AbstractMessage, MessagePayload
from pydantic import Field

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
```

## 4. 配置与维护
- 厂商切换在 `.env` 的 `MQ_VENDOR` 字段。
- 依赖项：`aiokafka` (Kafka), `aio-pika` (RabbitMQ)。
- 调试：查看 `MQService` 的 log 输出。
