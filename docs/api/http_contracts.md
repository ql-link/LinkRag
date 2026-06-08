# API Contracts

本文档记录当前项目 HTTP API 约定。实现来源以 `src/api/routes` 和 `src/api/schemas` 为准。

## 1. 通用约定

- API 前缀按模块划分：`/api/v1/parser`、`/api/v1/mq`、`/api/v1/llm`、`/api/v1/internal/llm`、`/api/v1/recall`。
- 普通 JSON 响应通常使用 `{code, message, data}` 或模块自定义响应模型。
- 解析和 MQ 路由异常通常返回 HTTP `500`，`detail` 为异常文本。
- LLM 路由在业务异常中多返回 `APIResponse(code=500, message=..., data=null)`。
- LLM 用户级接口要求请求头 `X-User-Id`。
- 内部 LLM 配置和用量接口为 Java 管理端内部使用，不应直接暴露给公网。

## 2. Parser API

路由前缀：`/api/v1/parser`

| Method | Path | 用途 | 请求 | 响应 |
| --- | --- | --- | --- | --- |
| `POST` | `/extract_sync` | 上传文件并同步解析为 Markdown，仅用于测试或联调 | `multipart/form-data` | `code/message/data/time_cost_ms` |
| `POST` | `/task/submit` | 提交异步解析任务，经 MQ 投递后台消费 | `TaskSubmitRequest` | `TaskSubmitResponse` |

### POST /api/v1/parser/extract_sync

表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | file | 是 | 待解析文件 |
| `file_type` | string | 是 | `pdf/docx/doc/html/htm` 等 |
| `parser_backend` | string | 否 | PDF 解析器，默认 `mineru` |
| `docling_force_ocr` | bool | 否 | 仅兼容旧 PDF 参数 |
| `image_bucket` | string | 否 | PDF 图片输出 bucket |
| `image_prefix` | string | 否 | PDF 图片输出 key 前缀 |
| `source_file_url` | string | 否 | MinerU 精准解析 API 使用的源文件 URL；选择 `parser_backend=mineru` 时必须可被 MinerU 云端访问 |
| `mineru_model_version` | string | 否 | MinerU 精准解析模型，默认 `vlm` |

响应 `data`：

- `file_type`
- `pdf_parser_backend`
- `markdown`
- `metadata`
- `warning`

### POST /api/v1/parser/task/submit

请求模型：`TaskSubmitRequest`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string | 必填 | 文档解析任务唯一标识 |
| `original_file_id` | int | 必填 | 原始文件表主键 |
| `document_parse_task_id` | int | 必填 | 历史兼容字段名，对应 `document_parse_file.id` |
| `user_id` | int | 必填 | 文件所属用户 |
| `dataset_id` | int | 必填 | 文件所属数据集 |
| `file_type` | string | 必填 | 文件格式 |
| `source_bucket` | string | 必填 | 原始文件 bucket |
| `source_object_key` | string | 必填 | 原始文件对象 key |
| `source_filename` | string | 必填 | 原始文件名 |
| `md_bucket` | string | 必填 | Markdown 输出 bucket |
| `md_object_key` | string | 必填 | Markdown 输出对象 key |
| `trigger_mode` | string | `upload_auto` | 触发方式 |
| `pdf_parser_backend` | string | `mineru` | PDF 解析器 |
| `docling_force_ocr` | bool | `false` | 兼容旧参数；当前内置 PDF 后端不使用 Docling |
| `image_bucket` | string/null | `null` | 图片输出 bucket |
| `image_prefix` | string/null | `null` | 图片输出前缀 |

响应：

```json
{
  "code": 200,
  "message": "Task accepted and queued via MQ",
  "data": {
    "task_id": "...",
    "status": "created"
  }
}
```

## 3. MQ API

路由前缀：`/api/v1/mq`

| Method | Path | 用途 | 请求 | 响应 |
| --- | --- | --- | --- | --- |
| `POST` | `/send/parse-task` | 发送文档解析任务 MQ 消息 | `SendParseTaskRequest` | `MQResponse` |
| `POST` | `/send/cache-sync` | 发送用户 LLM 配置缓存同步消息 | `SendCacheSyncRequest` | `MQResponse` |
| `POST` | `/send/usage-report` | 发送 LLM 用量上报消息 | `SendUsageReportRequest` | `MQResponse` |
| `POST` | `/send/raw` | 向指定 topic/queue 发送原始消息 | `SendRawMessageRequest` | `MQResponse` |
| `GET` | `/vendor/info` | 查询当前 MQ vendor 和可用 vendor | 无 | `MQVendorInfoResponse` |

`MQResponse`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `success` | bool | 操作是否成功 |
| `message` | string | 描述信息 |

重要 MQ 名称：

| 消息 | Topic/Name | 说明 |
| --- | --- | --- |
| ParseTask | `tolink-document-pares` | Java/Python 解析任务输入 |
| ParseResult | `tolink.rag.parse_result` | Python 解析终态通知 Java |
| CacheSync | `tolink.rag.cache_sync` | 缓存同步 |
| UsageReport | `tolink.rag.usage_report` | 用量上报 |

### ParseResult 通知语义

Python 发往 Java 的 `tolink.rag.parse_result` 消息不带 MQ 信封，消息体就是业务 payload。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 解析任务 ID |
| `original_file_id` | int | 原始文件 ID |
| `document_parse_task_id` | int | 历史兼容字段名，对应 `document_parse_file.id` |
| `dataset_id` | int | 数据集 ID |
| `user_id` | int | 用户 ID |
| `task_status` | string | `success/failed` |
| `failure_reason` | string/null | 失败原因；成功时为空 |
| `parse_finished_at` | string | 整体终态时间，ISO 8601 |
| `user_message` | string/null | 可选用户提示 |

`success` 表示解析+上传、分片、向量化、预分词与 ES 入库均完成。任一阶段失败都会发送 `failed`，并在 `failure_reason` 中携带业务化原因。

> **数据库权威单源**：整体任务状态以 `document_parse_pipeline.pipeline_status` 为准；`document_parsed_log.task_status` / `failure_reason` 已下线（migration 0007）。Java 侧若需直接查表，应读取：
> - 整体任务是否成功 → `document_parse_pipeline.pipeline_status == SUCCESS`
> - markdown 是否已上传 → `document_parsed_log.parsed_object_key IS NOT NULL`
> - 失败原因 → `document_parse_pipeline.failure_reason`

## 4. LLM API

路由前缀：`/api/v1/llm`

所有接口需要请求头：

| Header | 说明 |
| --- | --- |
| `X-User-Id` | 用户 ID，用于读取用户 LLM 配置 |

| Method | Path | 用途 | 请求 |
| --- | --- | --- | --- |
| `POST` | `/generate` | 非流式文本生成 | `GenerateRequest` |
| `POST` | `/generate/stream` | SSE 流式文本生成 | `GenerateRequest` |
| `POST` | `/embed` | 文本向量化 | `EmbedRequest` |
| `POST` | `/rerank` | 文档重排 | `RerankRequest` |
| `POST` | `/ocr` | 图片 OCR | `OcrRequest` |

`GenerateRequest`：

- `config_id`: 可选用户配置 ID。
- `prompt`: 必填提示词。
- `model`: 可选模型覆盖。
- `temperature`: 默认 `0.7`，范围 `0-2`。
- `max_tokens`: 可选，最小 `1`。
- `system_prompt`: 可选系统提示词。
- `tools`: 可选工具定义。

`EmbedRequest`：

- `config_id`: 可选。
- `input`: string 或 string 列表。
- `model`: 可选。

`RerankRequest`：

- `config_id`: 可选。
- `query`: 检索查询。
- `documents`: 待重排文档列表。
- `model`: 可选。
- `top_n`: 可选。

`OcrRequest`：

- `config_id`: 可选。
- `image_base64`: 图片 base64。
- `prompt`: 可选提示词。

## 5. Internal LLM API

路由前缀：`/api/v1/internal/llm`

| Method | Path | 用途 | 参数 |
| --- | --- | --- | --- |
| `GET` | `/providers` | 查询系统级 LLM 厂商 | `provider_type` 可选 |
| `GET` | `/configs` | 查询用户 LLM 配置 | Header `X-User-Id` |
| `GET` | `/usage` | 查询用户用量统计 | Header `X-User-Id`，`start_date/end_date` 可选 |

日期参数格式：`YYYY-MM-DD`。

## 6. Recall API（对外直连 SSE）

路由前缀：`/api/v1/recall`。**面向浏览器前端**：前端凭 Java 签发的**短期 session token**
直连，绕过 Java 中转。运行时与会话鉴权细节见
[docs/internals/recall_http_api.md](../internals/recall_http_api.md)。

> 历史背景：早期曾存在一条 Java Recall Gateway → Python 内部端点
> `/api/v1/internal/recall/stream` 的网关链路（纯召回、无生成），已随本直连方案废弃清理
> （LINK-122）。

| Method | Path | 用途 | 鉴权 |
| --- | --- | --- | --- |
| `POST` | `/stream` | 前端直连多路召回，SSE 流式返回融合候选 | Header `Authorization: Bearer <session-token>` |

### POST /api/v1/recall/stream

前端以 fetch 流式（`ReadableStream`）建连，**不使用** `EventSource`（无法设鉴权头）。
请求头：`Authorization: Bearer <session-token>`、`Content-Type: application/json`、可选
`Origin`（CORS）、`X-Request-Id`。

session token 由 Java 签发、Python 用**独立专用密钥**验签；claims：
`iss=tolink-java`、`aud=tolink-rag-frontend`、`scope=recall:stream`、`sub`、`dataset_ids`、
`exp`。**token 短期可复用**（只校验 `exp`，不做一次性 / 防重放 / 撤销）。

请求体（仅以下字段；出现 `user_id` / `top_k` / `sources` / `strict` / `doc_ids` 等任何未知
字段返回 `422`）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | string | 是 | 用户问题，不能为空或纯空白 |
| `config_id` | int | 是 | 本次生成所用 CHAT 模型配置 id（前端选中、用户已配置）。缺失 `422`；不属本用户 / 非 CHAT / 已停用 / 不存在 → 召回前置失败 `RECALL_MODEL_CONFIG_MISSING` |
| `dataset_ids` | list[int] | 否 | 本次查询的数据集**子集选择**，必须 ⊆ token 授权范围（超出 `403`）；省略/空 = 用 token 全量授权范围 |

**身份只取 token claims**——body 不含 `user_id`，前端自报一律不信任。`top_k` / `sources` /
`strict` 由服务端配置控制（`RECALL_RESULT_LIMIT` / `RECALL_ENABLED_SOURCES` /
`RECALL_STRICT_DEFAULT`），不接受请求覆盖。模型按 `(user_id, config_id)` 解析、不回退系统配置。

并发：按 `user_id` 限并发流数（`RECALL_SESSION_MAX_CONCURRENT`），超限返回 `429`。

**召回即包含 LLM 答案生成**：召回前置先校验模型，融合命中后
回填片段正文、按 token 预算（`RECALL_GENERATION_CONTEXT_TOKEN_BUDGET`）拼装上下文，用所选模型
流式生成答案。SSE 事件：

```
event: answer_delta
data: {"text": "<增量 token>"}

event: answer_done
data: {"answer": "<完整答案>", "hits": [...], "failed_sources": []}
```

- `answer_delta`：流式增量 token，可 0 到多帧；
- `answer_done`：生成结束终态，`hits` 为 RRF 融合候选（不含正文），发送后关闭流；
- **空命中 / 全部片段缺正文**：不生成，发 `recall_done`（`hits` 可空，不含正文）；
- **生成阶段失败**：整请求失败，发 `error` `RECALL_GENERATION_FAILED`，不返回部分召回片段。

`hits` 按 `fused_score` 降序，长度 ≤ `RECALL_RESULT_LIMIT`，`scores` 键集合等于已装配召回路；
`failed_sources` 表达「降级成功」（如 bm25 成功、sparse 失败），空列表表示无失败路。失败终态
`error` 发送后关闭流，`message` 不含内部堆栈。错误码见
[error_codes.md](error_codes.md#6-对外直连-recall-错误码)。

> CORS：本端点暴露给浏览器，生产环境必须把 `CORS_ORIGINS` 收敛为前端可信域名清单
> （不可用 `*`）。
