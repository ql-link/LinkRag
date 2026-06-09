# 召回后生成（RAG 答案生成）

本文说明**对外直连 SSE 召回**在拿到候选 chunk 之后、到流式产出答案之间的"生成阶段"。它是 [召回 Pipeline](recall_pipeline.md) 的下游姊妹环节：召回只负责返回不含正文的候选，生成阶段负责回填正文、按预算拼装上下文、调用用户模型流式作答。

入口端点与 SSE 事件契约见 [recall_http_api.md](recall_http_api.md) 与 [http_contracts.md §6](../api/http_contracts.md#6-recall-api对外直连-sse)；错误码见 [error_codes.md §5](../api/error_codes.md#5-recall-错误码对外直连-sse)。

---

## 1. 涉及代码

| 文件 | 职责 |
| --- | --- |
| [`src/api/recall_stream_runtime.py`](../../src/api/recall_stream_runtime.py) | SSE 流式执行 runtime：模型前置校验、召回执行、生成编排、事件序列化与异常→终态事件映射 |
| [`src/core/pipeline/recall/generation.py`](../../src/core/pipeline/recall/generation.py) | `fetch_chunk_contents`（按 chunk_id 回填正文）、`assemble_context`（按 token 预算拼装上下文） |
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

2. 召回执行（带超时）
   asyncio.wait_for(pipeline.execute(recall_req), RECALL_STREAM_TIMEOUT_MS/1000)

3. 生成（_generate_answer）
   ├─ response.hits 为空 → recall_done（不生成）
   ├─ fetch_chunk_contents(hit.chunk_id, user_id)        # 仅 ACTIVE、非空正文
   ├─ assemble_context(hits, contents, 预算)              # 按 fused_score 顺序、token 预算
   │    └─ 拼装后 blocks 为空（全部缺正文）→ recall_done（不生成）
   └─ provider.stream(user_prompt, system_prompt)
        ├─ 逐 token → answer_delta
        └─ 结束    → answer_done（answer + hits 元信息 + failed_sources）
```

关键设计点：

- **模型校验在召回之前**：CHAT 模型不可用就别浪费召回算力；且 `allow_system_fallback=False`——直连场景必须用发起用户自己选定的模型，不静默回落系统模型。
- **0 命中 / 全部缺正文 → `recall_done` 而非 error**：这是正常业务终态（没召回到东西不是错误），客户端据此走"无答案"分支。
- **生成失败 → 整请求失败**：进入流式生成后任何异常统一收敛为 `error` GENERATION_FAILED，**不**把"已召回片段"当成功终态返回，避免给用户一个没有答案的"成功"。

---

## 3. 上下文拼装规则

`assemble_context`（[generation.py](../../src/core/pipeline/recall/generation.py)）把命中片段按调用方给定的融合排序（`fused_score` 降序）依次纳入，受 `RECALL_GENERATION_CONTEXT_TOKEN_BUDGET` 约束：

- 查不到正文的片段**跳过**并计入 `skipped_no_content`，不打断后续纳入。
- 累计 token 超预算则停止纳入，剩余有正文片段计入 `truncated`。
- **至少纳入第一个有正文的片段**（即便其单片超预算），避免空上下文。
- 产物 `AssembledContext`：`context_text`（`[片段N] ...` 编号拼装，可直接注入 user prompt）+ 可观测计数（纳入 / 跳过 / 截断），runtime 会落一条 `[recall] generation context` 日志。

正文回填 `fetch_chunk_contents` 一次性批量查询（不逐条），且强制 `user_id == 发起用户 AND lifecycle_status == ACTIVE AND 正文非空`——既做权限隔离，又顺带过滤[鬼影 hit](vectorization.md)。

---

## 4. SSE 终态事件与错误码

`recall_event_stream` 把每类结果/异常映射为一帧终态 SSE 事件后关闭流（错误码常量定义在 [`src/api/internal_auth.py`](../../src/api/internal_auth.py)，语义见 [error_codes.md §5](../api/error_codes.md#5-recall-错误码对外直连-sse)）：

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

详见 [ops/configure.md](../ops/configure.md#对外直连召回-sse-配置)。

---

## 6. 协作关系

- **上游**：[recall_pipeline.md](recall_pipeline.md) 产出不含正文的融合候选；本阶段消费 `RecallResponse.hits`。
- **正文来源**：[chunk_fact_storage.md](chunk_fact_storage.md) —— `fetch_chunk_contents` 按 ACTIVE 回读正文。
- **模型一致性**：dense 召回 query 编码按发起用户的 EMBEDDING 配置解析（读写同源），生成则用用户选定的 CHAT 模型；二者都不回落系统模型。背景见错误码文档对 `RECALL_EMBEDDING_CONFIG_MISSING` 的说明。

---

## 7. 测试与修改原则

- 改动事件类型或错误码映射时，同步更新 [error_codes.md §5](../api/error_codes.md) 与 [recall_http_api.md](recall_http_api.md)（SSE 事件是对外契约）。
- 保持两条不变量：**生成失败不降级为成功终态**、**异常 except 顺序 `RecallFatalError` 先于 `RecallError`**。
- 提示词改动在 [`rag_generation.py`](../../src/core/prompts/rag_generation.py)，核心约束是"答案必须基于召回片段、无依据时明确说无法回答"。
