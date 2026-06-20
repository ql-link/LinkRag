# LLM Module

本文说明 `src/core/llm` LLM 能力模块的架构、协议化分发、配置来源、调用链，以及新增 adapter 的方法。

## 1. 模块框架

```text
src/core/llm/
├── interfaces.py          # 能力接口：文本、向量化、稀疏向量化、重排、视觉
├── base_provider.py       # Provider(adapter) 基类
├── factory.py             # ModelFactory —— 协议分发中台
├── response.py            # APIResponse 和模型结果对象
├── encryption.py          # API Key 加解密辅助
├── circuit_breaker.py     # Provider 熔断
├── tokenizer.py           # token 估算
├── exceptions.py          # LLM 异常类型（含 ProtocolRequiredError / UnsupportedProtocolCapabilityError）
├── user_model_resolver.py # 统一解析：查配置 → protocol 必填校验 → 分发 → 能力门禁
└── providers/
    ├── _rerank.py          # 平铺 /rerank 契约的共享调用与解析助手（standard_rerank）
    ├── _sse.py             # SSE 解析助手（openai/anthropic/google 流式共用）
    ├── openai.py           # OpenAICompatibleProvider（protocol=openai）
    ├── anthropic.py        # AnthropicProvider（protocol=anthropic）
    ├── google.py           # GoogleProvider（protocol=google，Gemini 原生）
    ├── jina.py             # JinaProvider（protocol=jina，平铺 rerank+embedding）
    ├── dashscope.py        # DashScopeProvider（protocol=dashscope，千问原生 rerank）
    ├── doubao_vision.py    # DoubaoVisionProvider（protocol=doubao_vision，火山多模态稀疏）
    └── bge_m3.py           # BgeM3ServiceProvider（protocol=bge_m3，自部署 bge-m3-service 稀疏）
```

## 2. 协议化分发（核心）

LLM 调用拆成两个正交维度：

- **`protocol`（API 家族）**：决定怎么拼 HTTP 请求体、鉴权、解析响应。7 个枚举（小写、大小写敏感）：`openai` / `anthropic` / `google` / `jina` / `dashscope` / `doubao_vision` / `bge_m3`（后两个为稀疏向量专用）。
- **`capability`（用途）**：`CHAT` / `EMBEDDING` / `SPARSE_EMBEDDING` / `RERANK` / `VISION`，决定调哪个能力分支。`OCR` 不再作为独立 LLM capability。
  > 命名口径：对外字符串用 `"CHAT"`，内部枚举为 `CapabilityType.TEXT`（值 `"text"`），二者经 `user_model_resolver` 映射对应（`"CHAT" → CapabilityType.TEXT`）；下表 `TEXT(CHAT)` 即此意。

**分发中台 = `ModelFactory.create_client(protocol=...)`**：所有要 LLM 的路径都经此一个口子按 `protocol` 选 adapter。**分发不依据 `provider_type`**——`provider_type` 仅作厂商身份 / 展示 / 日志。同一厂商不同能力可落不同协议（典型：千问 chat=`openai`、rerank=`dashscope`，落到两个 adapter）。

### 2.1 (protocol, capability) → adapter 矩阵（本期）

| protocol | adapter | 本期能力 | URL 策略 |
| --- | --- | --- | --- |
| `openai` | `OpenAICompatibleProvider` | `TEXT`(CHAT) / `EMBEDDING` / `SPARSE_EMBEDDING` / `VISION` | 直打 `api_base_url` |
| `anthropic` | `AnthropicProvider` | `TEXT`(CHAT) / `VISION` | 直打 `api_base_url`（`/v1/messages`） |
| `google` | `GoogleProvider` | `TEXT`(CHAT) / `VISION` | Python 补全（见 §2.3） |
| `jina` | `JinaProvider` | `RERANK` / `EMBEDDING` / `SPARSE_EMBEDDING` | 直打 `api_base_url`（平铺 `/rerank` 或 `/embeddings`） |
| `dashscope` | `DashScopeProvider` | `RERANK` | 直打 `api_base_url`（原生嵌套 `/services/rerank/text-rerank/text-rerank`） |
| `doubao_vision` | `DoubaoVisionProvider` | `SPARSE_EMBEDDING` | 直打 `api_base_url`（火山多模态 `/embeddings/multimodal`，逐条编码） |
| `bge_m3` | `BgeM3ServiceProvider` | `SPARSE_EMBEDDING` | 直打 `api_base_url`（自部署 `bge-m3-service` 编码端点） |

每个 adapter 的 `_capabilities` 集合即"本期 (protocol, capability) 矩阵"的唯一真源。`openai` 吃掉全部 OpenAI 兼容厂商（openai/千问 chat/glm/deepseek/硅基流动…）。**`VISION` 已接入 `openai` / `anthropic` / `google` 三协议**：复用各自 CHAT 通路（chat_completions / messages / generateContent），仅请求体多拼一个图片块，响应解析与 CHAT 一致；其余协议不支持 `VISION`，返回 `UnsupportedProtocolCapabilityError`。`OCR` 仍不作为独立能力，图片文字提取 = `VISION` + prompt（`/ocr` 兼容 endpoint 读 `VISION` 配置）。**ASR 本期不做。**

`SPARSE_EMBEDDING` 已接入 RAG sparse 写入/召回链路：按发起用户的默认 `SPARSE_EMBEDDING` 配置经 `aresolve_user_model` 解析到稀疏 adapter（当前 `doubao_vision` / `bge_m3`），产出框架中性的 `SparseEmbeddingResult`，再由 encoding 层 `AdapterSparseVectorEncoder` 统一清洗成 `SparseVector` 写入 Qdrant named sparse vector（详见 [sparse_vector.md](sparse_vector.md)）。`openai` / `jina` 仍声明 `SPARSE_EMBEDDING`（可解析到 embedding 端点），但 RAG 稀疏链路当前由 `doubao_vision` / `bge_m3` 承载；`google` / `dashscope` / `anthropic` 不支持该能力，返回 `UnsupportedProtocolCapabilityError`。

### 2.2 URL 接缝：完整 URL 直打

`api_base_url` 由配置下发**完整端点 URL**（含 capability 后缀），adapter 直接 POST，**不在代码里维护 `(protocol,capability)→后缀` 映射**。端点知识全部数据化，改端点只动配置不动代码。`google` 协议是唯一例外，配置保存到 `/v1beta` 为止，由 Python 按模型和流式模式补全 Gemini 原生路径。

### 2.3 Google 流式特例（唯一例外）

Gemini 原生把"是否流式"编码在 URL（而非请求体 `stream` 开关），无法用单条静态 URL 表达。故 `google` 协议由 Python 补全：

- 非流式：`{base}/models/{model}:generateContent`
- 流式：`{base}/models/{model}:streamGenerateContent?alt=sse`（**必须加 `alt=sse`**，否则 Gemini 返回 JSON 数组而非标准 SSE）
- 鉴权用 `x-goog-api-key` 头（非 Bearer）

`google` 协议的 `api_base_url` 由配置下发到 `/v1beta` 为止（base 而非完整 URL）。

### 2.4 protocol 必填、不兜底

`protocol` 是必填事实列（三层语义见 [docs/api/schemas/mysql.md](../api/schemas/mysql.md) 「协议与入口三层语义」：厂商默认模板 / 模型能力事实 / 用户配置快照，运行层**绝不 fallback 厂商默认**）。

- 运行期读到空 / NULL → `ProtocolRequiredError`（fail fast，**不按 provider_type 兜底推导**）。存量缺 protocol 的行由运维上线前清理 / 回填。
- 请求的 `(protocol, capability)` 不在该 adapter 能力集合内 → `UnsupportedProtocolCapabilityError`（不静默降级、不回退猜测）。

### 2.5 RERANK 说明

- `jina` 协议：平铺 `/rerank`（jina / cohere / 硅基流动 同构契约：请求 `{model, query, documents, top_n?, return_documents}`，响应 `{results:[{index, relevance_score, document}], tokens|usage}`），复用 `_rerank.standard_rerank()`，`endpoint=""` 直打 `api_base_url`。现网推荐路径（如硅基流动 `BAAI/bge-reranker-v2-m3`）。
- `dashscope` 协议：千问原生**嵌套**体（`{model, input:{query,documents}, parameters:{top_n,return_documents}}`），解析 `output.results[*]`，与平铺不同，单独实现。
- rerank 模型由调用方 `model` 指定，缺省回退 adapter 构造时的 `model_name`；`top_n=None` 不在 provider 侧截断。
- **RERANK 不走系统兜底**：`SYSTEM_LLM_MODEL_RERANK` 留空，必须由用户在 RERANK 配置里显式指定。

## 3. 调用链

```text
/api/v1/llm/*  或  系统链路（ChunkEmbeddingPipeline / MarkdownEnhancement / 召回 rerank）
  -> ConfigReaderService           # 读 llm_user_config（含 protocol）
  -> user_model_resolver           # protocol 必填校验 + 能力门禁
  -> ModelFactory.create_client    # 协议分发中台：按 protocol 选 adapter
    -> Provider(adapter)
      -> generate / stream / embed / rerank
```

## 4. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `CapabilityType` | `interfaces.py` | `TEXT/EMBEDDING/SPARSE_EMBEDDING/RERANK/VISION/TOOL_CALLING` |
| `BaseProvider` | `base_provider.py` | adapter 公共属性、`_capabilities` 与能力判断 |
| `ModelFactory` | `factory.py` | **协议分发中台**：按 `protocol` 注册 / 查找 / 创建 adapter |
| `build_provider_from_config` / `aresolve_user_model` | `user_model_resolver.py` | 查配置 → protocol 必填 → 分发 → 能力门禁 |
| `ConfigReaderService` | `src/services/config_reader_service.py` | 读用户配置 / 系统兜底配置（含 `protocol`）并管缓存 |
| adapter 实现 | `providers/*.py` | 各 protocol 的请求构造 / 鉴权 / 响应解析 |

## 5. 配置来源

运行时配置权威源为 **DB 三层 + Redis 缓存**（`llm_provider_model` 事实源 / `llm_user_config` 运行快照 / `llm_system_preset` 预设），均带 `protocol` / `api_base_url`。

`src/config.py::Settings` 另有一套**系统级 env 配置** `SYSTEM_LLM_*`（embedding / markdown 增强 / `/llm` 兜底用）。它是平行于 DB 的遗留第二事实源，且 env 无 `protocol` 字段——当前由系统三处调用点**写死 `protocol="openai"`** 桥接（系统级只做 embedding+chat，固定 openai 兼容）。收口到 DB 单一事实源见 **issue #191**。

API Key 不写入文档 / 测试 / 提交；用户密钥库内密文保存，读取后 `decrypt_api_key()` 解密。

## 6. 能力映射

| API/链路 | 能力 | 协议（典型） |
| --- | --- | --- |
| `/api/v1/llm/generate(/stream)` | `CHAT` | openai / anthropic / google |
| `/api/v1/llm/embed` | `EMBEDDING` | openai / jina |
| 用户配置解析 | `SPARSE_EMBEDDING` | doubao_vision / bge_m3（已接入 RAG 稀疏写入/召回）；openai / jina 仅声明能力 |
| `/api/v1/llm/rerank` | `RERANK` | jina（平铺）/ dashscope（千问原生） |
| Markdown 表格增强 | `CHAT` | 系统级 openai |
| Chunk 向量化 | `EMBEDDING` | 系统级 openai |
| Markdown 图片增强 / `/ocr` | `VISION` | openai / anthropic / google；`/ocr` 为兼容旧 endpoint，读 `VISION` 配置（不再读 `OCR` 默认模型）。图片增强按发起用户 `VISION` 默认配置解析，未配则抛 `EnhancementModelMissingError`（不静默跳过） |

## 7. 新增 adapter（新增 protocol）

1. 在 `src/core/llm/providers/` 下新增 adapter 文件，继承 `BaseProvider`，按协议实现 `generate/stream/embed/rerank`，声明 `_capabilities`。
2. 在 `ModelFactory._register_default_providers()` 按 `protocol` 注册（key 为协议名）。
3. 若协议有特殊 URL 规则（如 google），在 adapter 内封装，不要外泄到分发层。
4. DB 侧由 Java 管理端维护 `protocol` / `api_base_url` 事实列。
5. 在 `tests/unit/core/llm` 补单测（分发、能力矩阵、URL、未知组合）。

## 8. 测试建议

```bash
uv run pytest tests/unit/core/llm -q
uv run pytest tests/integration/core/llm -q
```

建议覆盖：按 protocol 分发与默认注册恢复、(protocol,capability) 能力矩阵、protocol 必填 fail-fast、未实现组合报错、google URL（含流式 `alt=sse`）、平铺 vs 原生 rerank、API Key 解密、Provider 异常映射与熔断。
