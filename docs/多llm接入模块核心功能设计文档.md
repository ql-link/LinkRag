# 多 LLM 接入模块核心功能设计文档

## 一、 文档说明

本文档旨在详细阐述 toLink-Rag 项目中多 LLM 接入模块的核心架构与业务功能机制。该模块作为 RAG 执行端的“推理引擎网络底座”，主要职责是屏蔽不同 LLM 厂商（如 OpenAI、通义千问、DeepSeek 等）的 API 差异，并为上层业务提供标准化的原子能力接口（对话、向量化、重排等）。

当前文档将持续更新迭代，记录该模块在演进过程中沉淀的所有关键特性设计。

---

## 二、 核心功能

### 2.1 多 LLM 厂商与能力隔离架构

#### 2.1.1 设计背景

在实际的 RAG (检索增强生成) 系统中，通常需要同时且交叉地调用多种不同提供商的 AI 模型来协同工作：
- **Chat**: 用于最终的回答生成和意图理解（例如配置推理能力强的 DeepSeek）。
- **Embedding**: 用于将文档和问题向量化（例如配置便宜量大的 OpenAI 早期模型）。
- **Rerank**: 用于对检索结果进行精细化排序（例如配置专项重排模型 BGE）。
- **OCR/Vision**: 用于解析图片或复杂文档（例如配置多模态视觉大模型）。

为了实现灵活的模型切换、厂商解耦以及“专款专用”的精细化配置，本系统采用了 **“基于接口的能力隔离 + 动态工厂映射”** 的架构设计。

#### 2.1.2 核心隔离机制

**1. 基于接口的能力抽象 (Capability-Based Abstraction)**
系统在 `src/core/llm/interfaces.py` 中定义了原子化的能力接口。这些接口基于 `typing.Protocol` 实现，提供了静态类型检查：
- `ITextGenerator`: 定义 `generate()` 和 `stream()`。
- `IEmbedder`: 定义 `embed_text()` 和 `embed_documents()`。
- `IReranker`: 定义 `rerank()`。
- `IOcrProcessor`: 定义 `extract_text()`。

*隔离意义*：业务逻辑（如 RAG Pipeline）只依赖于标准契约接口，而不直接感知具体各个 SDK 的参数细节。

**2. 厂商适配层 (Provider Adapter Layer)**
每个底层厂商在 `src/core/llm/providers/` 下有独立的适配器实现（如 `openai.py` 等）。
- 一个厂商子类可以**同时实现多个能力接口**。例如：`OpenAIProvider` 既继承了 `ITextGenerator` 也继承了 `IEmbedder`。
- *自省机制*：`BaseProvider` 提供了 `has_capability(type)` 方法。系统在运行时通过 `isinstance(instance, interface)` 动态识别该实例具备哪些能力。

**3. 数据库能力路由 (Capability Routing)**
在数据库层面，`llm_user_config` 表严格通过 `capability` 字段来标识配置记录的“首要能力”：
- *路由规则*：当系统需要做向量化任务时，它会查询 `where capability = 'EMBEDDING' AND is_default = 1`。这确保了即便用户创建了一万个聊天模型记录，系统也能精准捞取指定的向量化专用大模型。

#### 2.1.3 核心使用场景

**跨厂商混合编排 (Mixed-Provider Workflow)**
在同一个 RAG 流程中，你可以配置如下路由，它们将互不干扰地并行流转工作：

| 任务类型 | 绑定的能力 (Capability) | 实际模型配置 | 物理链路 |
| :--- | :--- | :--- | :--- |
| **查询向量化** | `EMBEDDING` | `text-embedding-3-small` | 走 OpenAI 渠道 |
| **精排打分** | `RERANK` | `bge-reranker-v2-m3` | 走 阿里云/Qwen 渠道 |
| **智能对话** | `CHAT` | `deepseek-chat` | 走 DeepSeek 渠道 |

**动态降级与 Fallback**
如果用户未配置自己的模型或当前首选模型服务波动失效，系统能够穿透业务代码，直接自动降级回退（Fallback）至 `.env` 系统级预配置好的全局大盘兜底 Provider。

#### 2.1.4 使用指南 (Usage Guide)

作为同项目的后端研发人员，我们在编写 RAG 算子管道流水线时，推荐使用如下注入调用的手法：

```python
# 1. 注入数据库 Session
config_service = ConfigReaderService(db_session)

# 2. 按需获取目标能力的模型配置实体
emb_config = await config_service.get_user_default_config_by_capability(user_id, "EMBEDDING")

# 3. 通过实例化工厂获取执行态客户端
client = model_factory.get_client_by_config(emb_config)

# 4. 面向接口编程，执行业务
vectors = await client.embed_documents(["Hello RAG architecture."])
```

#### 2.1.5 后续扩展规范

如果是未来迭代加入了诸如**语音播报能力**（例如添加 `SPEECH_TO_TEXT` 录音切分特性），需要遵循如下步骤：
1. 抽象契约：在 `interfaces.py` 定义 `ISpeechProcessor`。
2. 厂商实现：在对应的厂商 `provider` 中（如通义千问）编写逻辑 `def speech_to_text(self, audio): ...` 来支持实现该接口。
3. 枚举落库：在数据库 `llm_user_config.capability` 及 Pydantic 数据验证中加入 `STT` (Speech to text) 枚举常量支撑。
