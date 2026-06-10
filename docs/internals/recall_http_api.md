# 召回 HTTP API（对外 RAG 流 / 纯召回 JSON）

本文描述 Python 侧对外召回的两个端点运行时：暴露面、会话鉴权、请求装配与降级语义。
LINK-131 拆分语义——`POST /api/v1/rag/stream` 承接「召回 + LLM 流式生成」的完整 RAG 问答（SSE），
`POST /api/v1/recall` 是纯召回 JSON（一次性返回 hits、不生成、不限流、预留实现）。
对外契约见 [docs/api/http_contracts.md §6](../api/http_contracts.md#6-rag--recall-api对外)；
错误码见 [docs/api/error_codes.md §5](../api/error_codes.md)；
配置见 [docs/ops/configure.md](../ops/configure.md)；召回 pipeline 编排见
[recall_pipeline.md](recall_pipeline.md)。

> 历史背景：早期 `POST /api/v1/recall/stream` 以 `recall` 之名承载完整 RAG 问答，LINK-131 拆分后
> 删除、不留兼容。更早还存在一条 Java Recall Gateway → Python **内部端点**
> `/api/v1/internal/recall/stream` 的网关链路（纯召回、无生成），已随前端直连方案废弃并清理
> （LINK-122）。Python 侧现只保留下述两个对外端点。

## 1. 边界：身份与授权归属

外部用户态的登录态、用户状态、数据集 / 文档归属校验都在 Java 端完成（Sa-Token）。
Python **不接受前端 Sa-Token，也不信任请求体里自报的 `user_id`**——身份只取 Java 为每次
会话签发的短期 session token 的 claims，避免绕过租户隔离、伪造身份越权召回他人数据集。

前端流程：先 `POST /api/v1/recall/sessions`（向 Java，带登录态）换取短期 session token，
再凭 token 直连 Python 下述端点。Java 只负责签发 token，不在召回 / 生成请求路径上。

## 2. 暴露面

两个对外端点共用会话鉴权与 scope 校验（§3、§4），差异在执行与返回载体：

- **RAG 问答流**：`POST /api/v1/rag/stream`（[src/api/routes/rag.py](../../src/api/routes/rag.py)），
  返回 `text/event-stream`。RRF 融合后做 rerank 精排（不可用即降级 RRF 顺序），再基于最终片段调用用户
  CHAT 模型流式生成答案：逐 token `answer_delta`、结束 `answer_done`（附 rerank 后片段元信息与
  `rerank_applied`）；0 命中 / 全部片段缺正文 → `recall_done`（不生成）；失败 → SSE `error` 帧。请求体需
  `config_id`（CHAT 模型）。按 `user_id` 并发限流。
- **纯召回 JSON**：`POST /api/v1/recall`（[src/api/routes/recall.py](../../src/api/routes/recall.py)），
  返回 `application/json`，一次性 `{hits, failed_sources}`（**RRF 候选，不经 rerank**，hits 不含 rerank
  字段）。**不调 CHAT 模型、不回填正文、不建 SSE、不限流**。请求体仅 `query` + 可选 `dataset_ids`，出现 `config_id` → 422。
  执行期错误走 HTTP 状态码（见错误码）。当前为接口预留实现。

## 3. 会话鉴权（HS256 JWT）

实现见 [src/api/recall_session_auth.py](../../src/api/recall_session_auth.py) 的
`verify_session_token` 依赖——用**独立密钥** `RECALL_SESSION_JWT_SECRET` HS256 验签，校验
`aud=tolink-rag-frontend` / `iss=tolink-java` / `scope=recall:stream` / `exp`。独立密钥便于
前端面 token 疑似泄露时单独轮转。任一失败 → `RecallApiError(401, RECALL_SESSION_UNAUTHORIZED)`。

产出 `SessionAuthContext(user_id, dataset_ids, request_id)`。`user_id` 取 claims `sub`；
`request_id` 取 `X-Request-Id`，缺省时生成 `uuid4().hex`（见
[internal_auth.py](../../src/api/internal_auth.py) `_request_id`）并回写响应头，用于贯穿日志。

JWT 推荐 claims：

```json
{
  "iss": "tolink-java", "aud": "tolink-rag-frontend", "sub": "123",
  "scope": "recall:stream", "dataset_ids": [1, 2], "exp": 1710000300
}
```

**token 短期可复用**：只校验 `exp`，**不做一次性 / 防重放 / 撤销**。本场景只读、不可越权
（只能召回本人授权范围）、且有并发上限作资源闸门，一次性收益不抵复杂度（决策见
`.specs/recall-direct-sse/brief.md §3.3`）。断线重连可复用未过期 token，过期后回 Java 重申。
`RECALL_SESSION_AUTH_ENABLED=False` 仅供本地联调（跳过验签，仍需 token 解析身份），生产恒开启。

## 4. 身份与授权一致性（scope 校验）

握手前在各路由的 `_resolve_dataset_ids`（[rag.py](../../src/api/routes/rag.py) /
[recall.py](../../src/api/routes/recall.py)）完成：

- body 省略 / 空 `dataset_ids` → 用 claims 全量授权范围（claims 也空表示 Java 已授权全库，
  交由 pipeline 全库召回）。
- body 指定子集 → 必须 ⊆ claims 授权范围，否则 `403 RECALL_SCOPE_FORBIDDEN`。

下传 pipeline 的 `user_id` 始终取 claims `sub`，不信任 body 自报值（body 不含 `user_id`）。

## 5. 请求装配与执行

两端点握手前都做：JWT 校验 → JSON 解析 + Pydantic 校验（`extra=forbid`）→ `query` 空白 → 400 →
scope 校验。RAG 流额外要求 `config_id`（缺失 → 422）并在建流前做并发 acquire；纯召回请求体出现
`config_id` 即视为未知字段 → 422，且不限流。任一握手前失败走 HTTP JSON 错误。

通过后组装 `RecallRequest`：`query` ← body；`user_id` ← claims `sub`；`dataset_ids` ← scope 解析结果；
`doc_ids` = None；`top_k` ← `RECALL_RESULT_LIMIT`（服务端配置，不接受请求覆盖）。

### 5.1 RAG 流（建流在前）

建立 SSE 流，执行复用 [src/api/recall_stream_runtime.py](../../src/api/recall_stream_runtime.py)
的 `recall_event_stream`（`config_id` 来自 body）：先按 `(user_id, CHAT, config_id)` 前置校验
用户模型——不可用即 `error RECALL_MODEL_CONFIG_MISSING`、**不进入召回**；通过后在流内
`asyncio.wait_for(pipeline.execute(req), RECALL_STREAM_TIMEOUT_MS)`，对 RRF 候选做 rerank 精排
（`_rerank_hits`：不可用一律降级 RRF 顺序、截断 `RERANK_DEFAULT_TOP_N`），再按 token 预算拼装上下文
流式生成：

- 命中 → 流式 `answer_delta` + 终态 `answer_done`（`hits` 为 rerank 后最终候选、不含正文，附顶层 `rerank_applied`；`failed_sources` 表达降级）。
- 0 命中 / 全部片段缺正文 → `recall_done`（不生成）。
- 用户无默认 EMBEDDING 配置 → `error RECALL_EMBEDDING_CONFIG_MISSING`（硬失败，不降级）。
- 全路失败 `RecallError` → `error RECALL_ALL_SOURCES_FAILED`；超时 → `error RECALL_TIMEOUT`。
- 生成阶段失败 → `error RECALL_GENERATION_FAILED`（整请求失败）。
- 客户端断连（`CancelledError`）→ 停止发送事件并向上传播取消，pipeline 协程随之结束。

### 5.2 纯召回 JSON

执行用 [src/api/recall_json_runtime.py](../../src/api/recall_json_runtime.py) 的 `run_recall_json`：
`asyncio.wait_for(pipeline.execute(req), RECALL_STREAM_TIMEOUT_MS)` 后用
[recall_serialization.py](../../src/api/recall_serialization.py) 的 `serialize_hits`（仅 RRF 字段，
不含 rerank 字段——RAG 流改用同模块的 `serialize_reranked_hits`）组装 `{hits, failed_sources}` JSON。
执行期异常映射为 `RecallApiError` 经全局 handler 转 HTTP 状态码：
无默认 EMBEDDING 配置 → `422`、全路失败 → `500`、超时 → `504`、未预期异常 → `500`（错误码同 RAG 流，
仅载体由 SSE `error` 帧变为 HTTP 状态码）。`recall_serialization.py`（两个序列化函数）
与错误码常量（[internal_auth.py](../../src/api/internal_auth.py) `CODE_*`）是两条链路的单一来源；异常→错误码的
**映射**则按载体各实现一份（SSE 帧 vs HTTP 状态码），用同一套 `CODE_*` 常量保证两端错误码一致。
`dataset_ids` scope 授权校验亦抽为单一来源 `recall_session_auth.resolve_dataset_scope`，两端点共用。

`top_k` / `sources` / `strict` 由配置而非请求决定，因此 pipeline 与各路 retriever 都是
无用户态的长期实例。

## 6. 并发限流

**仅 RAG 流**限流：[recall_session_auth.py](../../src/api/recall_session_auth.py) 的
`acquire_stream_slot` / `release_stream_slot` 按 `user_id` 用 Redis `INCR/DECR` 计数，上限
`RECALL_SESSION_MAX_CONCURRENT`，超限 `429 RECALL_RATE_LIMITED`。`_guarded_stream` 在流收尾
（含断连 `CancelledError`）的 `finally` 中释放名额。握手顺序：验签 → body 校验 → scope →
并发 acquire → 建流。Redis 不可用时 acquire **fail-open**（限流是资源保护非鉴权）。
**纯召回 JSON 不做并发限流**（不调 `acquire_stream_slot`）。

CORS 复用全局 `CORSMiddleware`；对外环境必须把 `CORS_ORIGINS` 由 `*` 收敛为前端可信域名清单。

## 7. Pipeline 单例装配与执行期上下文

[src/api/recall_pipeline_provider.py](../../src/api/recall_pipeline_provider.py) 按
`RECALL_ENABLED_SOURCES` 装配 `RecallPipeline` 单例（`lru_cache`）：

- `bm25` → `Bm25Retriever(EsBm25Retriever(), RagFlowTokenizer())`；
- `sparse` → `SparseRetriever(compose_vector_storage_facade(), score_threshold=...)`；
- `dense` → `DenseRetriever(compose_vector_storage_facade(), score_threshold=...)`；
- 配置中出现未登记 source → 装配期 `ValueError`，不静默跳过。

sparse 底座含本地 BGE-M3，装配较重，必须单例。dense 底座走远程 system embedding HTTP
（无本地模型加载），单例化主要是为了与 `recall_pipeline` 单例对齐——所有 retriever
在 pipeline 单例之内只构造一次。

`user_id` / `top_k` 不在装配期注入，而是执行期由 pipeline 透传给
`Retriever.recall(query, dataset_ids, doc_ids, *, user_id, top_k)`——这是相对 LINK-6
的契约调整（见 [recall_pipeline.md](recall_pipeline.md)），使单例化成立。
