# 召回 HTTP API（对外直连 SSE）

本文描述 Python 侧的**多路召回 SSE 运行时**：暴露面、会话鉴权、请求装配与降级语义。
对外契约见 [docs/api/http_contracts.md §6](../api/http_contracts.md#6-recall-api)；
错误码见 [docs/api/error_codes.md §6](../api/error_codes.md#6-对外直连-recall-错误码)；
配置见 [docs/ops/configure.md](../ops/configure.md#对外直连召回-sse-配置)；召回 pipeline 编排见
[recall_pipeline.md](recall_pipeline.md)。

> 历史背景：早期曾存在一条 Java Recall Gateway → Python **内部端点**
> `/api/v1/internal/recall/stream` 的网关链路（纯召回、无生成）。该链路已随前端直连方案
> 废弃并清理（LINK-122），Python 侧只保留下述对外直连端点。

## 1. 边界：身份与授权归属

外部用户态的登录态、用户状态、数据集 / 文档归属校验都在 Java 端完成（Sa-Token）。
Python **不接受前端 Sa-Token，也不信任请求体里自报的 `user_id`**——身份只取 Java 为每次
会话签发的短期 session token 的 claims，避免绕过租户隔离、伪造身份越权召回他人数据集。

前端流程：先 `POST /api/v1/recall/sessions`（向 Java，带登录态）换取短期 session token +
`streamUrl`，再凭 token 直连 Python `streamUrl`（= 下述端点）拉召回 SSE。Java 只负责签发
token，不在召回 / 生成请求路径上。

## 2. 暴露面

- 端点：`POST /api/v1/recall/stream`（[src/api/routes/recall_direct.py](../../src/api/routes/recall_direct.py)）。
- 仅此一个流式端点；不提供一次性 JSON 接口。
- 返回 `text/event-stream`。召回融合后基于片段调用用户 CHAT 模型流式生成答案：逐 token
  `answer_delta`、结束 `answer_done`（附召回片段元信息）；0 命中 / 全部片段缺正文 →
  `recall_done`（不生成）；失败 → `error`（见对外契约与错误码）。

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

握手前在 [recall_direct.py](../../src/api/routes/recall_direct.py) `_resolve_dataset_ids` 完成：

- body 省略 / 空 `dataset_ids` → 用 claims 全量授权范围（claims 也空表示 Java 已授权全库，
  交由 pipeline 全库召回）。
- body 指定子集 → 必须 ⊆ claims 授权范围，否则 `403 RECALL_SCOPE_FORBIDDEN`。

下传 pipeline 的 `user_id` 始终取 claims `sub`，不信任 body 自报值（body 不含 `user_id`）。

## 5. 请求装配与执行（方案 A：建流在前）

握手前依次完成：JWT 校验 → JSON 解析 + Pydantic 校验（`extra=forbid`，含 `user_id` /
非首版字段 → 422；缺 `config_id` → 422）→ `query` 空白 → 400 → scope 校验 → 并发 acquire。
任一失败走 HTTP JSON 错误。

通过后组装 `RecallRequest`：

- `query` ← body；`user_id` ← claims `sub`；`dataset_ids` ← scope 解析结果；`doc_ids` = None；
- `top_k` ← `RECALL_RESULT_LIMIT`（服务端配置，不接受请求覆盖）。

随后建立 SSE 流，执行复用 [src/api/recall_stream_runtime.py](../../src/api/recall_stream_runtime.py)
的 `recall_event_stream`（`config_id` 来自 body）：先按 `(user_id, CHAT, config_id)` 前置校验
用户模型——不可用即 `error RECALL_MODEL_CONFIG_MISSING`、**不进入召回**；通过后在流内
`asyncio.wait_for(pipeline.execute(req), RECALL_STREAM_TIMEOUT_MS)`，再按 token 预算拼装上下文
流式生成：

- 命中 → 流式 `answer_delta` + 终态 `answer_done`（`hits` / `failed_sources` 表达降级，hits 不含正文）。
- 0 命中 / 全部片段缺正文 → `recall_done`（不生成）。
- 用户无默认 EMBEDDING 配置 → `error RECALL_EMBEDDING_CONFIG_MISSING`（硬失败，不降级）。
- 全路失败 `RecallError` → `error RECALL_ALL_SOURCES_FAILED`；超时 → `error RECALL_TIMEOUT`。
- 生成阶段失败 → `error RECALL_GENERATION_FAILED`（整请求失败）。
- 客户端断连（`CancelledError`）→ 停止发送事件并向上传播取消，pipeline 协程随之结束。

`top_k` / `sources` / `strict` 由配置而非请求决定，因此 pipeline 与各路 retriever 都是
无用户态的长期实例。

## 6. 并发限流

[recall_session_auth.py](../../src/api/recall_session_auth.py) 的 `acquire_stream_slot` /
`release_stream_slot` 按 `user_id` 用 Redis `INCR/DECR` 计数，上限
`RECALL_SESSION_MAX_CONCURRENT`，超限 `429 RECALL_RATE_LIMITED`。`_guarded_stream` 在流收尾
（含断连 `CancelledError`）的 `finally` 中释放名额。握手顺序：验签 → body 校验 → scope →
并发 acquire → 建流。Redis 不可用时 acquire **fail-open**（限流是资源保护非鉴权）。

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
