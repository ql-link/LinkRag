# API Contracts

本文档记录当前项目 HTTP API 约定。实现来源以 `src/api/routes` 和 `src/api/schemas` 为准。

## 1. 通用约定

- API 前缀按模块划分：`/api/v1/parser`、`/api/v1/mq`、`/api/v1/llm`、`/api/v1/internal/llm`、`/api/v1/rag`、`/api/v1/recall`、`/api/v1/wiki`。
- 所有 HTTP 请求可带 `X-Trace-Id` 请求头；未携带时 Python 端生成 UUID。响应会回显本次请求使用的 `X-Trace-Id`，日志上下文同步写入该值。
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
| `md_bucket` | string | 必填 | 历史兼容字段；Python 侧 Markdown 输出 bucket 使用 `MINIO_PRIVATE_BUCKET` |
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
| `POST` | `/send/usage-report` | 发送 LLM 用量上报消息（全链路归属：新增必填 `stage`/`operation`，详见下注） | `SendUsageReportRequest` | `MQResponse` |
| `POST` | `/send/raw` | 向指定 topic/queue 发送原始消息 | `SendRawMessageRequest` | `MQResponse` |
| `GET` | `/vendor/info` | 查询当前 MQ vendor 和可用 vendor | 无 | `MQVendorInfoResponse` |

MQ 发送失败统一返回不含底层连接地址和异常文本的 `500` 通用说明；服务端通过
`mq_http_send_failed` 结构化日志记录 topic、业务锚点、消息字节数、脱敏异常摘要和安全调用栈。
`/send/raw` 不会把 `request.message` 写入日志。

`MQResponse`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `success` | bool | 操作是否成功 |
| `message` | string | 描述信息 |

重要 MQ 名称：

| 消息 | Topic/Name | 说明 |
| --- | --- | --- |
| ParseTask | `tolink.rag.parse_task` | Java/Python 解析任务输入 |
| UsageReport | `tolink.rag.usage_report` | 用量上报 |

> `SendUsageReportRequest`（用量上报全链路归属）：必填 `user_id` / `provider_type` / `model_name` / `stage` / `operation` /
> 正整数全局 `config_id`；token 计数默认 0。可选 `task_id` / `latency_ms` / `status`。字段语义与 MQ 载荷一致。

> parse_result 终态回传 topic（Python→Java 解析终态通知）已下线（LINK-166）：终态只写 DB，前端轮询 Java 查询读取，见下方「解析终态读取」。

### 解析终态读取

parse_result 终态回传 MQ 已下线（LINK-166）。整体任务状态的权威单源是 `document_parse_pipeline.pipeline_status`，前端改由轮询 Java `parse-results` 接口读 DB 获取（LINK-98）。

`SUCCESS` 表示解析+上传、分片、向量化、预分词与 ES 入库均完成；任一阶段失败写 `FAILED`，并在 `failure_reason` 中携带业务化原因。

> **数据库权威单源**：整体任务状态以 `document_parse_pipeline.pipeline_status` 为准；`document_parsed_log.task_status` / `failure_reason` 已下线（migration 0007）。Java 侧直接查表读取：
> - 整体任务是否成功 → `document_parse_pipeline.pipeline_status == SUCCESS`
> - markdown 是否已上传 → `document_parsed_log.parsed_object_key IS NOT NULL`
> - 失败原因 → `document_parse_pipeline.failure_reason`

## 4. LLM API

路由前缀：`/api/v1/llm`

所有接口需要请求头：

| Header | 说明 |
| --- | --- |
| `X-User-Id` | 用户 ID，用于读取用户 LLM 配置 |

配置解析规则：

- 请求体必须携带正整数 `config_id`，精确读取 `llm_model_config.id`。
- 不再接受 `config_source`、`model`、`override_model` 等旧路由/覆盖字段，未知字段返回 `422`。
- resolver 统一校验存在、启用、SYSTEM 或归属 `X-User-Id`，以及 capability 匹配；不读默认指针或环境变量兜底。

| Method | Path | 用途 | 请求 |
| --- | --- | --- | --- |
| `POST` | `/generate` | 非流式文本生成 | `GenerateRequest` |
| `POST` | `/generate/stream` | SSE 流式文本生成 | `GenerateRequest` |
| `POST` | `/embed` | 文本向量化 | `EmbedRequest` |
| `POST` | `/rerank` | 文档重排 | `RerankRequest` |
| `POST` | `/ocr` | 图片文字提取（兼容旧 endpoint）。OCR 不再是独立能力，内部统一走 VISION（`analyze_image`）：读 `VISION` 配置、按 base64 嗅探的真实 mime 传图、未带 `prompt` 时用默认文字提取提示词；返回 `content/model/usage`，与原结构一致 | `OcrRequest` |

`GenerateRequest`：

- `config_id`: 必填正整数，全局配置 ID。
- `prompt`: 必填提示词。
- `temperature`: 默认 `0.7`，范围 `0-2`。
- `max_tokens`: 可选，最小 `1`。
- `system_prompt`: 可选系统提示词。
- `tools`: 可选工具定义。

`EmbedRequest`：

- `config_id`: 必填正整数，全局配置 ID。
- `input`: string 或 string 列表。

`RerankRequest`：

- `config_id`: 必填正整数，全局配置 ID。
- `query`: 检索查询。
- `documents`: 待重排文档列表。
- `top_n`: 可选。

`OcrRequest`：

- `config_id`: 必填正整数，全局配置 ID。
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

`GET /providers` 兼容保留 `models: { [model_name]: capability[] }`。新管理端展示模型时优先使用
`model_options[]`：每项包含 `model_name`（真实调用 ID）、`display_name`（短展示名）、
`capabilities`、`protocol`、`api_base_url`；提交配置仍应使用 `model_name`。

## 6. RAG / Recall API（对外）

**面向浏览器前端**：前端凭 Java 签发的**短期 session token** 直连，绕过 Java 中转。
两个端点拆分语义（LINK-131）——`/api/v1/rag/stream` 承接「召回 + LLM 流式生成」的完整 RAG
问答（SSE），`/api/v1/recall` 是纯召回 JSON（一次性返回 hits，不生成）。运行时与会话鉴权细节见
[docs/internals/recall_http_api.md](../internals/recall_http_api.md)。

> 历史背景：早期 `/api/v1/recall/stream` 曾以 `recall` 之名承载完整 RAG 问答（SSE），语义已超出
> 召回；LINK-131 拆为 `/api/v1/rag/stream`（RAG 问答流）与 `/api/v1/recall`（纯召回 JSON），旧
> `/api/v1/recall/stream` 删除、不留兼容。更早还存在一条 Java Recall Gateway → Python 内部端点
> `/api/v1/internal/recall/stream` 的网关链路（纯召回、无生成），已随直连方案废弃清理（LINK-122）。

| Method | Path | 用途 | 返回 | 鉴权 |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/rag/stream` | 召回 + LLM 流式生成的完整 RAG 问答 | `text/event-stream` | Header `Authorization: Bearer <session-token>` |
| `POST` | `/api/v1/recall` | 纯召回，一次性返回融合候选（预留实现） | `application/json` | Header `Authorization: Bearer <session-token>` |

### POST /api/v1/rag/stream

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
| `config_id` | int (>0) | 是 | 本次生成所用 CHAT 全局配置 ID。缺失/非正数 `422`；非 CHAT、已停用、不存在或 USER 配置不属本用户时在召回前失败 |
| `conversation_id` | int | 是 | 本轮所属对话 id（Java 预先创建），作为对话落库挂载锚点。缺失 `422`，不进入召回生成、不发对话轮次消息 |
| `turn_id` | string | 是 | 本轮落库幂等键：前端每轮生成的稳定 UUID（断连重连不变）。缺失 `422`。Java 据此 upsert 同一行，断连续跑/重连不重复落库 |
| `is_first_turn` | bool | 否 | 是否会话首条用户消息，默认 `false`。为 `true` 时触发服务端基于 `query` 生成会话标题（SSE `conversation_title` 即时回前端 + `chat_turn.title` 落库），见下文 |
| `dataset_ids` | list[int] | 否 | 本次查询的数据集**子集选择**，必须 ⊆ token 授权范围（超出 `403`）；省略/空 = 用 token 全量授权范围 |

> 生成跑在**独立后台任务**（断连不取消）：任务起点发一条 `tolink.rag.chat_turn`（`status=GENERATING`），终态再发 `COMPLETED`/`FAILED`，同 `turn_id`，供 Java upsert 落库对话内容（空召回也发 `COMPLETED` 占位）。客户端断连只停 SSE 转发、生成续跑到落库；本轮 generate 的 token 用量另走 `tolink.rag.usage_report`（LINK-191）。契约见 [mq_contracts.md §对话轮次上报](mq_contracts.md#对话轮次上报pythonjava)。

**身份只取 token claims**——body 不含 `user_id`，前端自报一律不信任。融合候选池窗口 / 三路执行期 top_k / 召回分数阈值 /
召回路 / 融合策略与权重 / 容错模式 / rerank 条数均由服务端**按数据集配置**控制（`dataset_parse_config.recall_config`：
`recall_result_limit` / `bm25_top_k` / `sparse_top_k` / `dense_top_k` / `sparse_score_threshold` / `dense_score_threshold` / `recall_enabled_sources` /
`recall_fusion_strategy` / `rrf_k` / `fusion_bm25_weight` / `fusion_sparse_weight` / `fusion_dense_weight` /
`recall_strict` / `rerank_top_n`；多数据集混合取首个 dataset，无数据集配置回退
`RECALL_RESULT_LIMIT` / `RECALL_BM25_TOP_K` / `RECALL_SPARSE_TOP_K` / `RECALL_DENSE_TOP_K` /
`SPARSE_RETRIEVAL_SCORE_THRESHOLD` / `DENSE_RETRIEVAL_SCORE_THRESHOLD` / `RECALL_ENABLED_SOURCES` /
`RECALL_FUSION_STRATEGY` / `RECALL_RRF_K` / `RECALL_FUSION_*_WEIGHT` /
`RECALL_STRICT_DEFAULT` / `RERANK_DEFAULT_TOP_N` 等系统默认）；均不接受
请求覆盖。其中 `recall_enabled_sources` **只能在系统已装配的召回路集合内收窄**（不能启用系统未
装配的路）。模型按 `(user_id, capability, config_id)` 精确解析，SYSTEM / USER 配置使用同一 ID 空间。

并发：按 `user_id` 限并发流数（`RECALL_SESSION_MAX_CONCURRENT`），超限返回 `429`。

**召回即包含 rerank 精排 + LLM 答案生成**：召回前置先校验模型，召回融合命中后做
**rerank 精排**，再回填片段正文、按 token 预算（数据集 `recall_config.recall_context_token_budget`，
无数据集配置回退 `RECALL_GENERATION_CONTEXT_TOKEN_BUDGET`）拼装上下文，用所选模型
流式生成答案。SSE 事件：

```
event: stream_started
data: {"conversation_id": 123, "request_id": "<本次请求 ID>"}

event: answer_delta
data: {"text": "<增量 token>"}

event: answer_done
data: {"answer": "<完整答案>", "hits": [...], "rerank_applied": true, "failed_sources": [], "recall_diagnostics": {...}}
```

- `stream_started`：建流后的**首个事件**，在模型校验、召回、rerank 与生成之前发出；前端收到后将
  `conversation_id` 对应的会话标记为“回复中”，`request_id` 用于链路关联；
- `answer_delta`：流式增量 token，可 0 到多帧；
- `answer_done`：生成结束终态，`hits` 为 **rerank 精排后**的最终候选（含正文 `content`），发送后关闭流；
- **空命中 / 全部片段缺正文**：不生成，发 `recall_done`（`hits` 可空，同带 `rerank_applied`；全部缺正文时各 hit `content` 为空串）；
- **生成阶段失败**：整请求失败，发 `error` `RECALL_GENERATION_FAILED`，不返回部分召回片段。

事件顺序为 `stream_started` → 零到多个中间事件（`answer_delta` / `conversation_title`）→ 恰好一个
终态（`answer_done` / `recall_done` / `error`）。终态是最后一个业务事件；客户端收到任一终态或检测到
连接关闭时，必须清除该 `conversation_id` 的“回复中”状态。新增事件遵循增量兼容：消费者应忽略未知
事件，旧的 `answer_delta` / `answer_done` / `recall_done` / `error` payload 保持不变。

**会话标题事件 `conversation_title`**（仅 `is_first_turn=true` 的会话首轮）：

```
event: conversation_title
data: {"title": "<会话标题>"}
```

服务端用本轮对话模型基于 `query` 生成短标题，标题任务**与召回 + 答案生成并行**，不串行增加问答耗时；一旦算好即在 `answer_delta` 间隙插发本事件（LLM 比答案慢时在本轮终态前补发），前端据此即时刷新侧栏/会话头标题，无需轮询。同一标题随首轮终态的 `chat_turn.title` 上报落库（标题为空/默认「新对话」时由 Java 写入 `chat_conversation.title`，不覆盖用户手改）。标题生成失败/超时回落首问截断兜底（首轮一定命名会话），不影响答案与落库；**生成失败（FAILED）的首轮**仅落库截断标题、不发本事件。非首轮无本事件。

终态 `hits` 单项在融合字段基础上补 rerank 字段与 chunk 正文 `content`：

```json
{"chunk_id": "...", "doc_id": 10, "dataset_id": 1, "fused_score": 0.033,
 "scores": {"bm25": 10.16, "sparse": 0.05}, "rerank_score": 0.87, "rerank_rank": 1,
 "content": "<chunk 正文，供前端展示召回片段>"}
```

- `rerank_applied`（顶层 bool）：rerank 是否实际生效。**未配置 RERANK 模型 / 调用失败 / 返回不可用
  一律降级**为当前融合顺序候选（best-effort：rag/stream 不因 rerank 不可用而整条失败），此时该字段为
  `false`，每个 hit 的 `rerank_score` / `rerank_rank` 为 `null`；
- rerank **生效**时（`rerank_applied=true`）：`hits` 按 `rerank_rank` 升序（即 rerank 相关性降序），
  长度 ≤ `rerank_top_n`（数据集 `recall_config.rerank_top_n`，无数据集配置回退 `RERANK_DEFAULT_TOP_N`）；
  个别未被模型打分的候选 `rerank_score` / `rerank_rank` 可为 `null`，排在已打分候选之后；
- rerank **降级**时（`rerank_applied=false`）：`hits` 为当前融合顺序（按 `fused_score` 降序），
  截断到 `rerank_top_n`；
- `fused_score` / `scores` 为当前融合策略解释信息，原样保留；`scores` 键集合等于本次生效的召回路
  （即数据集 `recall_enabled_sources` 在已装配路集合内收窄后的结果）。
- `content` 为该 chunk 的正文（与生成阶段上下文同源、一次性回填，无需另起反查）；某候选正文缺失
  时为空串。仅 rag/stream 终态 `hits` 含此字段，纯召回 JSON 端点（下文 `/api/v1/recall`）不含。

`failed_sources` 表达「降级成功」（如 bm25 成功、sparse 失败），空列表表示无失败路。失败终态
`error` 发送后关闭流，`message` 不含内部堆栈。错误码见
[error_codes.md §5](error_codes.md#5-recall-错误码对外-rag-流--纯召回-json)。

`recall_diagnostics` 是召回来源结构诊断（LINK-195），在三路 `bm25` / `sparse` / `dense`
均启用且结果可归入四态时返回：

```json
{
  "source_mode": "bm25_only",
  "degraded": true,
  "active_sources": ["bm25", "sparse", "dense"],
  "per_source_counts": {"bm25": 12, "sparse": 0, "dense": 0},
  "empty_sources": ["sparse", "dense"],
  "failed_sources": []
}
```

`source_mode` 取值为 `hybrid` / `bm25_only` / `missing_sparse` / `missing_dense`。
`empty_sources` 表示成功执行但 0 命中的路；`failed_sources` 仍只表示异常失败路。BM25-only
不是错误，不改变 rerank、prompt 或生成策略。首版不返回 `reason` 字段。

> CORS：本端点暴露给浏览器，生产环境必须把 `CORS_ORIGINS` 收敛为前端可信域名清单
> （不可用 `*`）。

### POST /api/v1/recall

纯召回 JSON：一次性返回融合候选，**不调 CHAT 模型、不回填正文、不建立 SSE、不做并发限流**。
当前阶段为接口预留实现，前端暂不真正接入。请求头：`Authorization: Bearer <session-token>`、
`Content-Type: application/json`、可选 `Origin`（CORS）、`X-Request-Id`。

会话鉴权与 `dataset_ids` scope 校验同 `/api/v1/rag/stream`。请求体（仅以下字段；出现 `config_id` /
`user_id` / `top_k` / `sources` / `strict` / `doc_ids` / `fusion_strategy` / `fusion_weights` /
`recall_fusion_strategy` / `rrf_k` / `fusion_*_weight` 等任何未知字段返回 `422`）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | string | 是 | 检索词，不能为空或纯空白 |
| `dataset_ids` | list[int] | 否 | 数据集**子集选择**，必须 ⊆ token 授权范围（超出 `403`）；省略/空 = 用 token 全量授权范围 |

**不要求 `config_id`**（纯召回不生成）。成功返回 `200`。**纯召回不经 rerank**，`hits` 为当前融合策略
融合候选、**不含** `rerank_score` / `rerank_rank` 字段，也无顶层 `rerank_applied`（与 RAG 流的
终态 `hits` 区别在此）：

```json
{ "hits": [ {"chunk_id": "...", "doc_id": 10, "dataset_id": 1, "fused_score": 0.92, "scores": {"bm25": 8.7, "sparse": 0.76}} ], "failed_sources": [], "recall_diagnostics": {...} }
```

`hits` 按 `fused_score` 降序、不含正文，长度 ≤ 数据集 `recall_config.recall_result_limit`（无数据集
配置回退 `RECALL_RESULT_LIMIT`）；`failed_sources` 表达异常失败路；`recall_diagnostics` 与
RAG SSE 成功终态同构。三路执行期 top_k / 分数阈值 / 融合策略的数据集级
解析与 `/api/v1/rag/stream` 完全一致（LINK-148）。
执行期错误走 **HTTP 状态码**（区别于 SSE error 帧）：无默认 EMBEDDING 配置 `422`、全路失败 `500`、
召回超时 `504`、未预期异常 `500`，错误体为 `{code, message, data}`，`message` 不含内部堆栈。错误码见
[error_codes.md §5](error_codes.md#5-recall-错误码对外-rag-流--纯召回-json)。

## 7. Wiki API（对外）

四个端点均使用 `/api/v1/wiki` 前缀和 `Authorization: Bearer <session-token>`，鉴权 claims 与 §6 相同。成功响应为 JSON，并回显/生成 `X-Request-Id`；两个 POST 请求体中的未知字段一律 422，ID 必须为正整数。身份只取 token claims。

| Method | Path | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/wiki/search` | exact 标题或 prefix + BM25 混合搜索 |
| `GET` | `/api/v1/wiki/documents/{doc_id}/headings/{heading_key}/chunks` | 分页展开一个标题的直属 Chunk |
| `POST` | `/api/v1/wiki/chunk-locations` | 批量定位 Chunk 的全部直接标题路径 |
| `GET` | `/api/v1/wiki/documents/{doc_id}/tree` | 读取授权且就绪文档的完整标题树 |

### POST /api/v1/wiki/search

请求：

```json
{"query":"快速 开始","dataset_ids":[10,20],"doc_ids":[10001],"cursor":"optional"}
```

`query` 必填；`dataset_ids`、`doc_ids`、`cursor` 可省略。ID 数组去重后排序。客户端不能提交 `page_size`、`top_k`、`strict` 或 sources。续页必须重复同一 query 和范围；无状态 HMAC 游标绑定用户、规范 query、有效 scope 和 exact/mixed 分支，10 分钟过期。

成功体：

```json
{
  "results":[
    {"result_type":"HEADING","source":"title_prefix","heading":{
      "heading_key":"<64-hex>","doc_id":10001,"dataset_id":10,"title":"快速开始",
      "heading_level":2,"path":[{"heading_key":"<64-hex>","title":"指南","heading_level":1}],
      "direct_chunk_count":2,"direct_chunk_preview_id":"C1","direct_chunks_has_more":true,
      "next_direct_chunk_cursor":"<signed>"
    },"chunk_id":null,"bm25_score":null},
    {"result_type":"CHUNK","source":"bm25","heading":null,"chunk_id":"C2","bm25_score":8.31}
  ],
  "chunks":[{"chunk_id":"C1","doc_id":10001,"dataset_id":10,"content":"完整 Chunk 正文",
    "chunk_type":"paragraph","start_line":10,"end_line":20,
    "positions":[{"path":[{"heading_key":"<64-hex>","title":"快速开始","heading_level":2}]}],
    "position_count":1,"positions_truncated":false}],
  "failed_sources":[],"page_size":15,"has_more":true,"next_cursor":"<signed>"
}
```

`results` 是以 `result_type` 为判别字段的严格联合类型，也是分页与顺序的权威数组：`HEADING` 只允许 `source=exact_title|title_prefix`、非空 `heading` 及空 `chunk_id/bm25_score`；`CHUNK` 只允许 `source=bm25`、空 `heading` 及非空 `chunk_id/bm25_score`。其他来源或交叉字段组合不属于响应契约，并会被服务端 Schema 拒绝。HEADING 以物理节点唯一，CHUNK 以 `chunk_id` 唯一。`chunks` 是按 `chunk_id` 去重的正文展开区。每个标题最多预览一个直属 Chunk；每个搜索 Chunk 最多内嵌前 10 个稳定标题位置。exact 结果的全部续页不调用 prefix/BM25；mixed 默认目标配额 5/10，任一路不足由另一条补位。`has_more=false` 时省略 `next_cursor`。

### GET /api/v1/wiki/documents/{doc_id}/headings/{heading_key}/chunks

`heading_key` 是 64 位小写十六进制。查询参数 `cursor` 可选：不传时从首个直属 Chunk 开始；提交搜索结果的 `next_direct_chunk_cursor` 时从预览后的第二个开始。响应字段为 `doc_id`、`heading_key`、去重后的完整 `chunks`、`page_size`、`direct_chunks_has_more` 及可选 `next_direct_chunk_cursor`。只读取当前标题的直属 CHUNK_REF，不进入子标题或其他搜索结果。每个返回 Chunk 的 `positions` 最多内嵌前 10 个稳定标题位置，并以 `position_count/positions_truncated` 表示完整数量和是否截断；需要全部位置时调用 Chunk 定位端点。

### POST /api/v1/wiki/chunk-locations

请求 `{"chunk_ids":["C1","C2"],"dataset_ids":[10,20]}`。`chunk_ids` 为 1～100 个，去重后保持首次出现顺序；`dataset_ids` 可省略。响应 `locations[]` 逐项包含 `chunk_id`、`doc_id`、`dataset_id`、`positions[]`，每个 position 含从文档根标题到直接标题的完整 `path`。本端点不截断位置；任一 Chunk 缺失、越权、非 ACTIVE 或文档未就绪时整体 403。

### GET /api/v1/wiki/documents/{doc_id}/tree

响应包含 `doc_id`、`dataset_id`、`original_filename`、递归 `headings`、`root_chunk_ids` 与去重后的完整 `chunks`。每个 heading 含 `heading_key/title/heading_level/direct_chunk_ids/children`；同父 HEADING 与直属 CHUNK_REF 分别按各自 `sort_order` 排序，不声明两类节点间的混合顺序。文档越权或当前 pipeline 非 SUCCESS 时返回 403。

Wiki 错误码见 [error_codes.md §5.1](error_codes.md#51-wiki-端点错误映射)，实现与最终一致性游标语义见 [wiki_heading_tree.md](../internals/wiki_heading_tree.md)。
