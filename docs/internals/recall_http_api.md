# 内部召回 HTTP API 与内部鉴权

本文描述 Python 侧的**内部多路召回 SSE 运行时**：暴露面、内部鉴权、请求装配与降级
语义。对外契约见 [docs/api/http_contracts.md §6](../api/http_contracts.md#6-internal-recall-api)；
错误码见 [docs/api/error_codes.md §5](../api/error_codes.md#5-internal-recall-错误码)；
配置见 [docs/ops/configure.md](../ops/configure.md#内部召回-api-配置)；召回 pipeline 编排见
[recall_pipeline.md](recall_pipeline.md)。

## 1. 边界：为什么 Python 只做内部 runtime

外部用户态 Recall API 归属 Java Recall Gateway：Sa-Token 登录态、用户状态、数据集 /
文档归属校验都在 Java 端完成。若让前端直连 Python 并透传 `user_id`，会绕过 Java 的
租户隔离，可伪造身份越权召回他人数据集。

因此 Python 只暴露**内部** runtime，且只信任 Java 为每次调用签发的短期内部凭证，不接受
前端 Sa-Token，也不信任请求体里自报的 `user_id`。

## 2. 暴露面

- 端点：`POST /api/v1/internal/recall/stream`（[src/api/routes/recall.py](../../src/api/routes/recall.py)）。
- 仅此一个流式端点；首版不提供一次性 JSON 接口。
- 返回 `text/event-stream`，终态事件 `recall_done` / `error`（见对外契约）。

## 3. 内部鉴权（HS256 JWT）

实现见 [src/api/internal_auth.py](../../src/api/internal_auth.py) 的 `verify_internal_jwt`
依赖。Java 用共享密钥签发，Python 用同一密钥验签。

校验链（任一失败 → `RecallApiError(401, RECALL_INTERNAL_UNAUTHORIZED)`）：

1. 取 `Authorization: Bearer <token>`，缺失或非 Bearer → 401。
2. HS256 验签 + 校验 `aud` / `iss` / `exp`（PyJWT 内置，`require=["exp"]`）。
3. 手动校验 `scope == RECALL_INTERNAL_JWT_SCOPE`。
4. `sub` → 正整数 `user_id`；`dataset_ids`（可选 list）作为授权范围。

产出 `InternalAuthContext(user_id, dataset_ids, jti, request_id)`。`request_id` 取
`X-Request-Id`，缺省时生成 `uuid4().hex` 并回写响应头，用于贯穿日志。

JWT 推荐 claims：

```json
{
  "iss": "tolink-java", "aud": "tolink-rag", "sub": "123",
  "scope": "recall:execute", "dataset_ids": [1, 2],
  "jti": "request-id", "exp": 1710000300
}
```

`jti` 本期仅用于日志 / 审计 / trace，不做防重放存储。
`RECALL_INTERNAL_AUTH_ENABLED=False` 仅供本地联调（跳过验签，仍需 token 解析身份），
生产恒开启。

## 4. 身份与授权一致性（scope 校验）

握手前在 [recall.py](../../src/api/routes/recall.py) `_check_scope` 完成：

- `body.user_id` 必须等于凭证 `sub`，否则 `403 RECALL_USER_MISMATCH`。
- 凭证带 `dataset_ids` 时，`body.dataset_ids` 必须是其子集，否则 `403 RECALL_SCOPE_FORBIDDEN`；
  凭证 `dataset_ids` 为空 / 缺省表示 Java 已授权全库召回，不限制 body 范围。

下传 pipeline 的 `user_id` 始终取凭证 `sub`，不信任 body 自报值。

## 5. 请求装配与执行（方案 A：建流在前）

握手前依次完成：JWT 校验 → JSON 解析 + Pydantic 校验（`extra=forbid`，非首版字段
→ 422）→ `query` 空白 → 400 → scope 校验。任一失败走 HTTP JSON 错误。

通过后组装 `RecallRequest`：

- `query` ← body；`user_id` ← 凭证 `sub`；`dataset_ids` ← body；`doc_ids` = None；
- `top_k` ← `RECALL_RESULT_LIMIT`（服务端配置，不接受请求覆盖）。

随后建立 SSE 流，在流内 `asyncio.wait_for(pipeline.execute(req), RECALL_STREAM_TIMEOUT_MS)`：

- 成功 / 宽松降级 → `recall_done`（`failed_sources` 表达降级）。
- 全路失败 `RecallError` → `error` `RECALL_ALL_SOURCES_FAILED`。
- 超时 → `error` `RECALL_TIMEOUT`。
- 客户端断连（`CancelledError`）→ 停止发送事件并向上传播取消，pipeline 协程随之结束；
  recall-only 无后续 rerank / 上下文 / LLM 步骤。

`top_k` / `sources` / `strict` 由配置而非请求决定，因此 pipeline 与各路 retriever 都是
无用户态的长期实例。

## 6. Pipeline 单例装配与执行期上下文

[src/api/recall_pipeline_provider.py](../../src/api/recall_pipeline_provider.py) 按
`RECALL_ENABLED_SOURCES` 装配 `RecallPipeline` 单例（`lru_cache`）：

- `bm25` → `Bm25Retriever(EsBm25Retriever(), RagFlowTokenizer())`；
- `sparse` → `SparseRetriever(compose_vector_storage_facade(), score_threshold=...)`；
- 配置中出现未登记 source（如 dense）→ 装配期 `ValueError`，不静默跳过。

sparse 底座含本地 BGE-M3，装配较重，必须单例。`user_id` / `top_k` 不在装配期注入，而是
执行期由 pipeline 透传给 `Retriever.recall(query, dataset_ids, doc_ids, *, user_id, top_k)`
——这是相对 LINK-6 的契约调整（见 [recall_pipeline.md](recall_pipeline.md)），使单例化成立。
