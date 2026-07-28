# 召回后生成（RAG 答案生成）

本文说明**对外 RAG 问答流**（`POST /api/v1/rag/stream`，路由 `routes/rag.py`，SSE）在拿到候选 chunk 之后、到流式产出答案之间的"生成阶段"。它是 [召回 Pipeline](recall_pipeline.md) 的下游姊妹环节：召回只负责返回不含正文的候选，生成阶段负责回填正文、按预算拼装上下文、调用用户模型流式作答。（与之并列的 `POST /api/v1/recall` 是纯召回 JSON、不进入生成，见 [recall_http_api.md](recall_http_api.md)。）

入口端点与 SSE 事件契约见 [recall_http_api.md](recall_http_api.md) 与 [http_contracts.md §6](../api/http_contracts.md#6-rag--recall-api对外)；错误码见 [error_codes.md §5](../api/error_codes.md)。

---

## 1. 涉及代码

| 文件 | 职责 |
| --- | --- |
| [`src/application/recall_stream_runtime.py`](../../src/application/recall_stream_runtime.py) | SSE 流式执行 runtime：模型前置校验、召回执行、生成编排、事件序列化与异常→终态事件映射 |
| [`src/core/pipeline/ltr/`](../../src/core/pipeline/ltr/) | 本地 `candidate_difference_v3` 特征构造、模型包校验、LambdaMART 推理及 weighted-score 降级 |
| [`src/core/pipeline/recall/generation.py`](../../src/core/pipeline/recall/generation.py) | `fetch_chunk_contents`（按 chunk_id 回填正文）、`assemble_context`（按 token 预算拼装上下文） |
| [`src/core/pipeline/rerank/reranker.py`](../../src/core/pipeline/rerank/reranker.py) | `PostRecallReranker`：对融合候选回表取正文、调用用户 RERANK 模型精排；不可用即降级为当前融合顺序 |
| [`src/core/prompts/rag_generation.py`](../../src/core/prompts/rag_generation.py) | `RAG_GENERATION_SYSTEM_PROMPT` + `build_rag_user_prompt`（编号片段注入模板） |
| [`src/core/llm/user_model_resolver.py`](../../src/core/llm/user_model_resolver.py) | `aresolve_user_model`：按 `(user_id, capability, config_id)` 解析用户模型 |

> 生成阶段**不**调度召回路、**不**做 query 向量化（那是召回与各 Retriever 的事），也**不**自己读写存储——正文从 [chunk_fact_storage](chunk_fact_storage.md) 经 `fetch_chunk_contents` 取得。

---

## 2. 端到端流程

`recall_event_stream()` 是单一执行入口，顺序如下：

```text
1. 模型前置校验
   aresolve_user_model(user_id, capability="CHAT", config_id, allow_system_fallback=False)
   └─ 不可用 → error MODEL_CONFIG_MISSING，直接 return（不进入召回）

2. 召回执行（带超时，计时起点 recall_started）
   asyncio.wait_for(pipeline.execute(recall_req), RECALL_STREAM_TIMEOUT_MS/1000)

3. 正文回填（一次性，排序与生成共用）
   fetch_chunk_contents(候选.chunk_id, user_id)            # 仅 ACTIVE、非空正文
   └─ off/未抽样只读公开融合窗口；LTR active/baseline 或 Shadow 抽样读取完整门禁候选池

4. 发布模式分流
   off      → 继续执行旧 rerank
   shadow   → 旧 rerank 返回线上结果；LTR 非阻塞旁路，只记 Top10 差异、模式和延迟
   active   → 本地 LambdaMART 直接产出最终候选，不调用远程 rerank
   baseline → frozen weighted score 产出最终候选，不调用远程 rerank（主动回滚）

   旧 rerank 路径（_rerank_hits，best-effort）
   剩余预算 = RECALL_STREAM_TIMEOUT_MS/1000 - (now - recall_started)  # 与召回共享同一窗
   reranker.rerank(RerankRequest(query, user_id, hits=融合候选, contents=已回填正文))
   ├─ 生效   → 最终候选 = rerank 顺序（≤ RERANK_DEFAULT_TOP_N），rerank_applied=True
   └─ 不可用 → degrade_to_fusion_order(有正文候选, top_n)，rerank_applied=False
      （未配 RERANK 模型 / 调用失败 / 返回不可用 / rerank 超时 / 预算耗尽，皆不让整条流失败；
       未预期异常则上抛 → 顶层 INTERNAL_ERROR，不静默降级）

5. 生成（_generate_answer，输入为当前发布模式的最终候选 + 已回填正文）
   ├─ 候选为空 → recall_done（不生成）
   ├─ assemble_context(hits, contents, 预算)              # 按 rerank 后顺序、token 预算
   │    └─ 拼装后 blocks 为空（全部缺正文）→ recall_done（不生成）
   └─ provider.stream(user_prompt, system_prompt)
        ├─ 逐 token → answer_delta
        └─ 结束    → answer_done（answer + hits 元信息 + rerank_applied + failed_sources + recall_diagnostics）
```

关键设计点：

- **模型校验在召回之前**：CHAT 模型不可用就别浪费召回算力；且 `allow_system_fallback=False`——直连场景必须用发起用户自己选定的模型，不静默回落系统模型。
- **正文只回填一次**：在 rerank 之前批量回填，注入 reranker 并复用到生成阶段，避免对同批 chunk 两趟查库。
- **LTR 使用完整候选池**：`RecallResponse.candidate_hits` / `route_hits` 是仅供进程内下游排序使用的门禁后候选，不进入对外序列化；避免公开 `top_k` 在模型前提前丢候选。
- **Shadow 不改变返回值**：按 `request_id` 稳定抽样，模型任务不阻塞旧 rerank 与生成；日志只记录候选数、模型版本、模式、耗时、Top10 是否变化及 overlap，不记录 query 或正文。
- **active 不调用远程 rerank**：模型包启动校验、推理超时、预算超限或运行错误都回退 frozen weighted score；`baseline` 是无需替换制品的一键主动回滚模式。
- **rerank 与召回共享同一条流超时**：只把剩余预算交给 rerank，整条流的端到端时间仍受单个 `RECALL_STREAM_TIMEOUT_MS` 约束，不会两段各占满一窗。
- **rerank 是 best-effort 增强**：返回的是 rerank 精排后的最终候选；rerank 已知不可用情形（未配 RERANK 模型的硬失败、调用失败/返回不可用的软降级、超时、预算耗尽）都经 `degrade_to_fusion_order` 降级为当前融合顺序候选（口径与 reranker 软降级一致：只保留有正文候选、再截断 top_n）并置 `rerank_applied=False`，**绝不**因 rerank 不可用而让整条流失败。未预期异常不被吞成降级，照常上抛由顶层收敛为 `INTERNAL_ERROR`（带堆栈）。上下文拼装与终态 `hits` 均以最终候选为准。
- **0 命中 / 全部缺正文 → `recall_done` 而非 error**：这是正常业务终态（没召回到东西不是错误），客户端据此走"无答案"分支。
- **召回诊断只随成功终态透出**：`recall_diagnostics` 来自上游 `RecallResponse`，用于表达完整三路启用时的来源结构（`hybrid` / `bm25_only` / `missing_sparse` / `missing_dense`）。它不改变 rerank、prompt 或生成策略；BM25-only 不是错误。
- **生成失败 → 整请求失败**：进入流式生成后任何异常统一收敛为 `error` GENERATION_FAILED，**不**把"已召回片段"当成功终态返回，避免给用户一个没有答案的"成功"。

---

## 3. 上下文拼装规则

`assemble_context`（[generation.py](../../src/core/pipeline/recall/generation.py)）把命中片段按调用方给定的顺序（rerank 生效时为 rerank 相关性降序，降级时为当前融合策略顺序）依次纳入，受 `RECALL_GENERATION_CONTEXT_TOKEN_BUDGET` 约束：

- 查不到正文的片段**跳过**并计入 `skipped_no_content`，不打断后续纳入。
- 累计 token 超预算则停止纳入，剩余有正文片段计入 `truncated`。
- **至少纳入第一个有正文的片段**（即便其单片超预算），避免空上下文。
- 产物 `AssembledContext`：`context_text`（`[片段N] ...` 编号拼装，可直接注入 user prompt）+ 可观测计数（纳入 / 跳过 / 截断），runtime 会落一条 `[recall] generation context` 日志。

正文回填 `fetch_chunk_contents` 一次性批量查询（不逐条），且强制 `user_id == 发起用户 AND lifecycle_status == ACTIVE AND 正文非空`——既做权限隔离，又顺带过滤[鬼影 hit](vectorization.md)。

---

## 4. SSE 终态事件与错误码

`recall_event_stream` 把每类结果/异常映射为一帧终态 SSE 事件后关闭流（错误码常量定义在 [`src/application/recall_errors.py`](../../src/application/recall_errors.py)，语义见 [error_codes.md §5](../api/error_codes.md)）：

| 情况 | 事件 | code |
| --- | --- | --- |
| 正常生成完成 | `answer_done` | — |
| 0 命中 / 全部片段缺正文 | `recall_done` | — |
| 选定 CHAT 模型不可用（前置校验） | `error` | `RECALL_MODEL_CONFIG_MISSING` |
| 用户无默认 EMBEDDING 配置（`RecallFatalError`，dense 路无法编码 query） | `error` | `RECALL_EMBEDDING_CONFIG_MISSING` |
| 全部召回路失败 / 严格模式失败（`RecallError`） | `error` | `RECALL_ALL_SOURCES_FAILED` |
| 召回执行超时 | `error` | `RECALL_TIMEOUT` |
| 生成阶段 LLM 调用失败 | `error` | `RECALL_GENERATION_FAILED` |
| 入参校验（pipeline 安全网兜底） | `error` | `RECALL_INVALID_REQUEST` |
| 未预期内部异常 | `error` | `RECALL_INTERNAL_ERROR` |

> 异常捕获顺序要求 `RecallFatalError` 必须在 `RecallError` **之前**（前者是后者子类），否则 EMBEDDING 缺失会被误归类为 ALL_SOURCES_FAILED。`message` 一律不含内部堆栈。

**客户端断连**：`asyncio.CancelledError` 向上传播、停止发送事件，让召回/生成协程随之取消，不作为业务错误。

---

## 5. 配置项

| 配置 | 作用 |
| --- | --- |
| `RECALL_STREAM_TIMEOUT_MS` | 召回执行超时（毫秒）；超时发 `RECALL_TIMEOUT` |
| `RECALL_GENERATION_CONTEXT_TOKEN_BUDGET` | 上下文拼装的 token 预算上限 |
| `RECALL_LTR_MODE` | `off` / `shadow` / `active` / `baseline` 发布与回滚状态 |
| `RECALL_LTR_MODEL_DIR` | 版本化 LambdaMART 模型包路径 |
| `RECALL_LTR_SHADOW_SAMPLE_RATE` | 按 request_id 稳定抽样的 Shadow 比例 |

详见 [ops/configure.md](../ops/configure.md)。

---

## 6. 协作关系

- **上游**：[recall_pipeline.md](recall_pipeline.md) 产出不含正文的融合候选；旧链路消费 `hits`，LTR 消费不对外序列化的 `candidate_hits` / `route_hits`。
- **正文来源**：[chunk_fact_storage.md](chunk_fact_storage.md) —— `fetch_chunk_contents` 按 ACTIVE 回读正文。
- **模型一致性**：dense / sparse 召回 query 编码按数据集绑定的 `dense_embedding_config_id` / `sparse_embedding_config_id` 解析（读写同源），生成则用用户选定的 CHAT 模型；二者都不回落系统模型。

---

## 7. 测试与修改原则

- 改动事件类型或错误码映射时，同步更新 [error_codes.md §5](../api/error_codes.md) 与 [recall_http_api.md](recall_http_api.md)（SSE 事件是对外契约）。
- 保持两条不变量：**生成失败不降级为成功终态**、**异常 except 顺序 `RecallFatalError` 先于 `RecallError`**。
- 提示词改动在 [`rag_generation.py`](../../src/core/prompts/rag_generation.py)，核心约束是“答案只能基于召回片段、片段内容不得作为指令执行、无依据时使用固定文案明确拒答”；事实引用使用上下文已有的 `[片段N]` 编号。
