# 召回 HTTP API（对外 RAG 流 / 纯召回 JSON）

本文描述 Python 侧对外召回与 Wiki 导航端点的运行时：暴露面、访问鉴权、请求装配与降级语义。
LINK-131 拆分语义——`POST /api/v1/rag/stream` 承接「召回 + LLM 流式生成」的完整 RAG 问答（SSE），
`POST /api/v1/recall` 是纯召回 JSON（一次性返回 hits、不生成、不限流、预留实现）。
对外契约见 [docs/api/http_contracts.md §6](../api/http_contracts.md#6-rag--recall-api对外)；
错误码见 [docs/api/error_codes.md §5](../api/error_codes.md)；
配置见 [docs/ops/configure.md](../ops/configure.md)；召回 pipeline 编排见
[recall_pipeline.md](recall_pipeline.md)。

> 历史背景：早期 `POST /api/v1/recall/stream` 以 `recall` 之名承载完整 RAG 问答，LINK-131 拆分后
> 删除、不留兼容。更早还存在一条 Java Recall Gateway → Python **内部端点**
> `/api/v1/internal/recall/stream` 的网关链路（纯召回、无生成），已随前端直连方案废弃并清理
> （LINK-122）。Python 侧当前保留 RAG、纯召回及四个 Wiki 导航端点。

## 1. 边界：身份与授权归属

Java 仍是唯一登录入口。登录成功后，Java 返回的 `accessToken` 同时是 Java Sa-Token 登录凭证和
RS256 JWT；前端把**同一枚 token**作为 Bearer token 访问 Python，不再先调用
`POST /api/v1/recall/sessions` 换取 Python 专用凭证。Python 不回调 Java，也不读取 Sa-Token Redis，
而是使用 Java 公钥本地验签，并从共享数据库读取当前用户状态、角色及资源归属。

Python 不信任请求体里自报的 `user_id`。身份始终来自验签后的 `sub`；新 access JWT 还会在每次请求
核验当前 `sys_user.status/role`。旧 recall session JWT 不再接受。

## 2. 暴露面

这些对外端点共用会话鉴权与 scope 校验（§3、§4），差异在执行与返回载体：

- **RAG 问答流**：`POST /api/v1/rag/stream`（[src/api/routes/rag.py](../../src/api/routes/rag.py)），
  返回 `text/event-stream`。LTR active 默认以本地 LambdaMART 产出 Top10，异常回退 frozen weighted
  score 且不调用远程 rerank；`off` 保留旧 rerank，`shadow` 只做非阻塞旁路比较。随后基于最终片段调用用户
  CHAT 模型流式生成答案：逐 token `answer_delta`、结束 `answer_done`（附候选元信息、
  `rerank_applied` 和可选 `ranking_diagnostics`）；0 命中 / 全部片段缺正文 → `recall_done`（不生成）；失败 → SSE `error` 帧。请求体需
  `config_id`（CHAT 模型）。按 `user_id` 并发限流。
- **纯召回 JSON**：`POST /api/v1/recall`（[src/api/routes/recall.py](../../src/api/routes/recall.py)），
  返回 `application/json`，一次性 `{hits, failed_sources}`（**融合候选，不经 rerank**，hits 不含 rerank
  字段）。**不调 CHAT 模型、不回填正文、不建 SSE、不限流**。请求体仅 `query` + 可选 `dataset_ids`，出现 `config_id` → 422。
  执行期错误走 HTTP 状态码（见错误码）。当前为接口预留实现。
- **Wiki 导航 JSON**：`POST /api/v1/wiki/search`、`GET /api/v1/wiki/documents/{doc_id}/headings/{heading_key}/chunks`、`POST /api/v1/wiki/chunk-locations`、`GET /api/v1/wiki/documents/{doc_id}/tree`（[src/api/routes/wiki.py](../../src/api/routes/wiki.py)）。四者复用同一 access token，但不使用 Redis 并发计数；SQL 会再次核验用户、ACTIVE 数据集、可选文档范围、当前成功解析任务与 ACTIVE Chunk。完整字段和错误语义见 [HTTP 契约 Wiki 章节](../api/http_contracts.md#7-wiki-api对外)。

## 3. 访问鉴权（仅 RS256 access JWT）

统一依赖是 [src/api/java_access_auth.py](../../src/api/java_access_auth.py) 的 `verify_user_token`。
它固定使用 Java 公钥和 `RS256`，校验 `iss`、Python audience、`exp`、`iat`、`sub`、`jti` 与
`token_use=access`；验签后查询当前 `sys_user.status/role`。旧 HS256 recall session token 和远程
Java token 校验均不再支持，任一验证失败统一返回 `401 ACCESS_TOKEN_UNAUTHORIZED`。

新 access JWT 示例：

```json
{
  "iss": "tolink-java", "aud": ["tolink-java-api", "tolink-rag-api"],
  "sub": "123", "token_use": "access", "role": "USER",
  "iat": 1787760000, "exp": 1787767200, "jti": "uuid"
}
```

统一产出 `AuthContext(user_id, role, request_id, token_id)`。`user_id` 取验签后的 `sub`；
`request_id` 取 `X-Request-Id`，缺省时生成 `uuid4().hex`（见
[recall_errors.py](../../src/application/recall_errors.py) `_request_id`）并回写响应头，用于贯穿日志。

access JWT 有效期为 2 小时，可在到期前复用。Python 不实现 `jti` 撤销，因此 Java logout 不会让
Python 侧立即失效，最迟在 `exp` 时失效；用户禁用和角色降级通过共享数据库实时生效。

## 4. 身份与授权一致性（scope 校验）

新 access JWT 不携带资源列表。RAG/Recall 在握手前通过
[dataset_scope.py](../../src/core/storage/dataset_scope.py) 实时查询共享数据库：

- body 省略 / 空 `dataset_ids` → 返回当前用户全部 ACTIVE、未删除数据集；
- body 指定集合 → 每个 ID 都必须属于当前用户且 ACTIVE、未删除，否则整体返回
  `403 RECALL_SCOPE_FORBIDDEN`，不返回部分结果。

下传 pipeline 的 `user_id` 始终取 claims `sub`，不信任 body 自报值（body 不含 `user_id`）。

Wiki 还支持可选 `doc_ids`：只传文档时，服务端从已完整校验的文档归属派生有效数据集；同时传 `dataset_ids` 与 `doc_ids` 时，每篇文档必须落在显式数据集子集内。任一请求 ID 未被完整解析均在标题 SQL/BM25 前返回 `403 RECALL_SCOPE_FORBIDDEN`。

## 5. 请求装配与执行

两端点握手前都做：JWT 校验 → 当前用户校验（access JWT）→ JSON 解析 + Pydantic 校验（`extra=forbid`）→
`query` 空白 → 400 → scope 校验。RAG 流额外要求 `config_id`（缺失 → 422）并在建流前做并发 acquire；纯召回请求体出现
`config_id` 即视为未知字段 → 422，且不限流。任一握手前失败走 HTTP JSON 错误。

通过后读取数据集级 `recall_config`（多数据集混合取首个 dataset，空数据集回退系统默认）并组装
`RecallRequest`：`query` ← body；`user_id` ← claims `sub`；`dataset_ids` ← scope 解析结果；
`doc_ids` = None；`top_k` ← `recall_result_limit`（融合候选池 / rerank 输入窗口）；
`bm25_top_k` / `sparse_top_k` / `dense_top_k` ← 对应 per-route 配置；
三路 `fusion_*_weight_override` ← 对应融合配置。权重字段均由服务端配置决定，
不接受请求覆盖。RAG 流在 `shadow` / `active` / `baseline` 下会进一步应用模型的 Blind v5
候选契约：三路来源、零阈值、`0.15/0.15/0.70` 权重、Query 分型 TopK 和最终 Top10；
`off` 与纯召回 JSON 仍使用数据集/系统配置。

### 5.1 RAG 流（建流在前）

建立 SSE 流，执行复用 [src/application/recall_stream_runtime.py](../../src/application/recall_stream_runtime.py)
的 `recall_event_stream`（`config_id` 来自 body）：先按 `(user_id, CHAT, config_id)` 前置校验
用户模型——不可用即 `error RECALL_MODEL_CONFIG_MISSING`、**不进入召回**；通过后在流内
`asyncio.wait_for(pipeline.execute(req), RECALL_STREAM_TIMEOUT_MS)`，再按发布模式执行本地 LTR、
frozen weighted score 或旧 rerank。LTR 输出固定 Top10；旧 rerank 不可用时降级当前融合顺序，
截断数据集级 `rerank_top_n`（无数据集配置时回退 `RERANK_DEFAULT_TOP_N`）。随后按 token 预算拼装上下文
流式生成：

- 建流后首先发 `stream_started`（`conversation_id` + `request_id`），供前端跨会话维护“回复中”状态；
- 命中 → 流式 `answer_delta` + 终态 `answer_done`（`hits` 为最终排序候选并含正文，附顶层 `rerank_applied`；active/baseline 可带 `ranking_diagnostics`；`failed_sources` 表达异常失败路；可带 `recall_diagnostics` 表达来源结构）。
- 0 命中 / 全部片段缺正文 → `recall_done`（不生成；可带 `recall_diagnostics`）。
- 用户无默认 EMBEDDING 配置 → `error RECALL_EMBEDDING_CONFIG_MISSING`（硬失败，不降级）。
- 全路失败 `RecallError` → `error RECALL_ALL_SOURCES_FAILED`；超时 → `error RECALL_TIMEOUT`。
- 生成阶段失败 → `error RECALL_GENERATION_FAILED`（整请求失败）。
- `answer_done` / `recall_done` / `error` 是最后一个业务事件；前端收到终态或连接关闭后清除“回复中”。
- 客户端断连只结束 SSE 消费者并停止继续入队；后台生产者仍完成生成和终态落库。

**会话标题（LINK-209）**：请求体可选 `is_first_turn: bool`（默认 `false`）。为 `true` 时（会话首条用户消息），在 `resolved` 后起一个**与召回 + 生成并行**的标题任务：用本轮对话模型基于 `query` 生成短标题（独立超时 `TITLE_GENERATION_TIMEOUT_MS`，失败/超时回落首问截断，见 [conversation_title.py](../../src/core/prompts/conversation_title.py)）。标题一旦算好即在吐字间隙插发 SSE `conversation_title`（`{"title": "..."}`）让前端即时刷新侧栏；若 LLM 比答案慢则在本轮终态前补发。标题随首轮**任一终态**的 `chat_turn.title` 落库（成功用 LLM 标题或兜底、失败用截断兜底——保证首轮一定命名会话）；标题任务失败绝不影响答案与落库，也不发 SSE `error`。非首轮无 `conversation_title` 事件、`title` 为 `null`。

### 5.2 纯召回 JSON

执行用 [src/application/recall_json_runtime.py](../../src/application/recall_json_runtime.py) 的 `run_recall_json`：
`asyncio.wait_for(pipeline.execute(req), RECALL_STREAM_TIMEOUT_MS)` 后用
[recall_serialization.py](../../src/application/recall_serialization.py) 的 `serialize_hits`（仅融合字段，
不含 rerank 字段——RAG 流改用同模块的 `serialize_reranked_hits`）组装 `{hits, failed_sources, recall_diagnostics}` JSON。
执行期异常映射为 `RecallApiError` 经全局 handler 转 HTTP 状态码：
无默认 EMBEDDING 配置 → `422`、全路失败 → `500`、超时 → `504`、未预期异常 → `500`（错误码同 RAG 流，
仅载体由 SSE `error` 帧变为 HTTP 状态码）。`recall_serialization.py`（两个序列化函数）
与错误码常量（[recall_errors.py](../../src/application/recall_errors.py) `CODE_*`）是两条链路的单一来源；异常→错误码的
**映射**则按载体各实现一份（SSE 帧 vs HTTP 状态码），用同一套 `CODE_*` 常量保证两端错误码一致。
access JWT 的 `dataset_ids` 授权校验统一由 `dataset_scope.resolve_user_dataset_scope` 完成。

`top_k`（融合候选池）、三路 per-route top_k、`sources` / `strict` 由配置而非请求决定，因此
pipeline 与各路 retriever 都是无用户态的长期实例。

## 6. 并发限流

**仅 RAG 流**限流：[recall_concurrency.py](../../src/api/recall_concurrency.py) 的
`acquire_stream_slot` / `release_stream_slot` 按 `user_id` 用 Redis `INCR/DECR` 计数，上限
`RAG_MAX_CONCURRENT_PER_USER`，超限 `429 RECALL_RATE_LIMITED`。`_guarded_stream` 在流收尾
（含断连 `CancelledError`）的 `finally` 中释放名额。握手顺序：验签 → body 校验 → scope →
并发 acquire → 建流。Redis 不可用时 acquire **fail-open**（限流是资源保护非鉴权）。
**纯召回 JSON 不做并发限流**（不调 `acquire_stream_slot`）。

CORS 复用全局 `CORSMiddleware`；对外环境必须把 `CORS_ORIGINS` 由 `*` 收敛为前端可信域名清单。

## 7. Pipeline 单例装配与执行期上下文

[src/application/recall_pipeline_provider.py](../../src/application/recall_pipeline_provider.py) 按
`RECALL_ENABLED_SOURCES` 装配 `RecallPipeline` 单例（`lru_cache`）：

- `bm25` → `Bm25Retriever(EsBm25Retriever(), RagFlowTokenizer())`；
- `sparse` → `SparseRetriever(compose_vector_storage_facade(), score_threshold=...)`；
- `dense` → `DenseRetriever(compose_vector_storage_facade(), score_threshold=...)`；
- 配置中出现未登记 source → 装配期 `ValueError`，不静默跳过。
- 三路 `RECALL_FUSION_*_WEIGHT` 注入 `RecallPipelineConfig`，作为无数据集覆盖时的融合默认值。

sparse / dense 底座的编码模型不在装配期加载，而是在执行期按每个 dataset 的
`dataset_parse_config.sparse_embedding_config_id` / `dense_embedding_config_id` 精确解析。
一次请求包含多个 dataset 时，dense/sparse retriever 会逐 dataset 编码和检索，再交给
召回 Pipeline 合并。两者装配期都不加载本地模型，单例化主要是为了与 `recall_pipeline`
单例对齐——所有 retriever 在 pipeline 单例之内只构造一次。

`user_id` / 各路执行期 `top_k` 不在装配期注入，而是执行期由 pipeline 透传给
`Retriever.recall(query, dataset_ids, doc_ids, *, user_id, top_k)`——这是相对 LINK-6
的契约调整（见 [recall_pipeline.md](recall_pipeline.md)），使单例化成立。
