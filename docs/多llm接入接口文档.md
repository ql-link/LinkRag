# toLink-Rag: API 接口文档

本文档概述了 toLink-Rag 多模型计算引擎当前所有对外暴露的 REST API 接口。默认情况下，所有接口均接收并返回 `application/json` 数据格式（流式接口除外）。

---

## 1. 核心 LLM 能力接口 `/api/v1/llm`

这些接口是 RAG 管道处理的核心，将对话生成、向量化、重排和 OCR 提取等能力以原子化的形式暴露给业务管道或外部调用方。

### 1.1 文本生成（非流式）
**端点 (Endpoint):** `POST /api/v1/llm/generate`

使用用户的默认 `CHAT` 模型配置或指定的配置 ID 进行文本生成。如果在数据库中未查到对应用户的配置，系统会自动降级（Fallback）调用系统兜底模型配置。

**请求头 (Headers):**
- `X-User-Id` (字符串, 必填): 调用 API 的用户 ID。

**请求体 (`GenerateRequest`):**
```json
{
  "config_id": "string", // 选填：指定强制使用某一个设定的配置 ID
  "prompt": "string", // 必填：用户的提问/提示词
  "model": "string", // 选填：覆盖配置中的模型名称
  "temperature": 0.7, // 选填：采样温度 (0.0 到 2.0 之间)
  "max_tokens": 1000, // 选填：最大生成 token 数
  "system_prompt": "string", // 选填：系统级设定提示词 (System Prompt)
  "tools": [] // 选填：可选的外部函数/工具调用定义 
}
```

**响应 (`APIResponse[GenerateResult]`):**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "content": "string", // 生成的文本内容
    "model": "string", // 实际使用的模型
    "provider_type": "string", // 模型提供商
    "latency_ms": 1500, // 消耗时长(毫秒)
    "usage": { // token 用量统计
      "prompt_tokens": 15,
      "completion_tokens": 100,
      "total_tokens": 115
    }
  }
}
```

---

### 1.2 文本生成（流式 / SSE）
**端点 (Endpoint):** `POST /api/v1/llm/generate/stream`

以打字机模式 (HTTP Server-Sent Events, SSE) 逐步返回生成的 Token 序列。

**请求头 (Headers):**
- `X-User-Id` (字符串, 必填): 调用 API 的用户 ID。

**请求体 (`GenerateRequest`):** (结构等同于非流式请求)

**响应:**
标准 Server-Sent Events (`text/event-stream`) 协议。每一片返回的数据都按照 `StreamChunk` 数据契约进行序列化。

---

### 1.3 文本向量化 (Embedding)
**端点 (Endpoint):** `POST /api/v1/llm/embed`

调用用户专属配置的 `EMBEDDING` 能力模型，将传入的源字符串转化为高维浮点数向量，以供诸如 Milvus 或 Qdrant 等数据库检索使用。

**请求头 (Headers):**
- `X-User-Id` (字符串, 必填): 调用 API 的用户 ID。

**请求体 (`EmbedRequest`):**
```json
{
  "config_id": "string", // 选填：指定配置 ID
  "input": "string or []string", // 必填：需要向量化的目标文本或文本数组 
  "model": "string" // 选填：覆盖模型名称
}
```

**响应 (`APIResponse[EmbeddingResult]`):**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "model": "string",
    "embeddings": [
      [0.012, 0.045, ...] // 每个请求文本对应的高维空间浮点数列表
    ],
    "usage": {
      "prompt_tokens": 10,
      "completion_tokens": 0,
      "total_tokens": 10
    }
  }
}
```

---

### 1.4 文档语义重排 (Reranking)
**端点 (Endpoint):** `POST /api/v1/llm/rerank`

基于给出的查询语句 (`query`)，使用用户设置的 `RERANK` 交叉编码器模型对一组文档（预先被粗排召回的结果）进行打分并精细排序。

**请求头 (Headers):**
- `X-User-Id` (字符串, 必填): 调用 API 的用户 ID。

**请求体 (`RerankRequest`):**
```json
{
  "config_id": "string", 
  "query": "string", // 必填：用户查询的句子
  "documents": ["string", "string"], // 必填：需要被打分和重排的候选片段集
  "model": "string", // 选填
  "top_n": 5 // 选填：仅返回打分最高的前 N 个片段
}
```

**响应 (`APIResponse[RerankResult]`):**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "model": "string",
    "results": [
      {
         "index": 0, // 该片段在原始请求数组中的下标
         "score": 0.99, // 匹配绝对分数 (相似度)
         "text": "string" // 原始文本内容
      }
    ],
    "usage": { ... }
  }
}
```

---

### 1.5 视觉理解与 OCR 提取
**端点 (Endpoint):** `POST /api/v1/llm/ocr`

使用系统 `VISION` 或 `OCR` 级模型能力来读取并分析传入的图片（例如复杂的扫描件/表格分析）。

**请求头 (Headers):**
- `X-User-Id` (字符串, 必填): 调用 API 的用户 ID。

**请求体 (`OcrRequest`):**
```json
{
  "config_id": "string",
  "image_base64": "string", // 必填：编码好的图像字符串 (不带 data:image 头)
  "prompt": "string" // 选填：提取侧重点指引 (如：请只返回图表数据)
}
```

**响应 (`APIResponse[OcrResult]`):**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "content": "string", // 系统理解或提取出来的文本描述
    "model": "string",
    "usage": { ... }
  }
}
```


---

## 2. 内部管控级接口 `/api/v1/internal/llm`

这部分接口受到网络隔离控制，仅作为我们项目本身不同微服务（如 Java 后台管理控制面板）的通信所用。它们绝对不应该通过网关对外暴露。

### 2.1 获取平台厂商列表
**端点 (Endpoint):** `GET /api/v1/internal/llm/providers`

获取引擎底层注册的所有合法提供商常量、兼容协议和特性字典集。

**查询参数 (Query):**
- `provider_type` (字符串, 选填): 如果填写，可以基于该代码做单体过滤查询。

**响应 (`APIResponse`):**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "provider_type": "string", // 例如 "openai" 或 "qwen"
        "provider_name": "string", 
        "api_base_url": "string",
        "supported_models": { "gpt-4": ["CHAT", "VISION"] },
        "config_schema": { ... },
        "is_active": true
      }
    ]
  }
}
```

---

### 2.2 读取某用户的已存配置脱敏列表
**端点 (Endpoint):** `GET /api/v1/internal/llm/configs`

为 Java 管理端读取出某个用户的模型配额清单，这常用于在前台渲染其拥有的额度和渠道设置，自动规避真实的秘钥数据以防泄漏。

**请求头 (Headers):**
- `X-User-Id` (字符串, 必填): 目标租户/用户的 ID。

**响应 (`APIResponse`):**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "integer",
        "config_name": "string",
        "provider_type": "string",
        "provider_name": "string",
        "model_name": "string",
        "api_key_masked": "sk-****7890", // API 密钥的安全脱敏显示
        "custom_api_base_url": "string",
        "priority": 50,
        "is_active": true,
        "is_default": true,
        "stream_enabled": true,
        "extra_config": {}
      }
    ]
  }
}
```

---

### 2.3 获取用户算力/额度使用账单
**端点 (Endpoint):** `GET /api/v1/internal/llm/usage`

按照不同的时间纬度累加某名特定用户，在其使用的每个生成器模型上耗费的整体 Token 与响应消耗开销报表。

**请求头 (Headers):**
- `X-User-Id` (字符串, 必填): 目标用户的 ID。

**查询参数 (Query):**
- `start_date` (字符串, 选填): 格式规范 `YYYY-MM-DD`
- `end_date` (字符串, 选填): 格式规范 `YYYY-MM-DD`

**响应 (`APIResponse`):**
输出由 `UsageLogService` 日报任务所生成聚合账单。 
