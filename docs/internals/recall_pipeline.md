# 召回 Pipeline 架构

本文说明 `src/core/pipeline/recall/` 的多路召回 Pipeline。它与解析 Pipeline 独立：解析 Pipeline 负责文档入库和索引构建，召回 Pipeline 负责在查询时触发多路 Retriever、收敛异常、按配置做粗融合并返回候选 chunk。

解析链路见 [pipeline_architecture.md](pipeline_architecture.md) 和 [parse_task_pipeline.md](parse_task_pipeline.md)。

---

## 1. 设计目标

`RecallPipeline` 是查询侧的轻量编排层，只做四件事：

1. 按配置并行或串行触发已装配的全部召回路。
2. 按严格或宽松容错策略收敛单路异常。
3. 对成功路结果按配置做粗融合。
4. 通过注入的 `DocumentReadinessGate` 按 MySQL 当前任务过滤不可见文档，再返回稳定结构的候选列表。

它明确不做这些事情：

- query 预处理、embedding、稀疏化、分词。
- 直接访问 Qdrant、Elasticsearch、MySQL 等存储；MySQL 门禁由独立协作者实现并注入。
- 非融合策略所需的复杂排序或评测调参。
- reranker 精排、上下文拼装、答案生成。

这些能力归属各路 Retriever 自己或下游 RAG 阶段。其中"召回后生成准备"（按 chunk_id 回填 MySQL 正文、按 token 预算拼装上下文）由同包的 `generation.py` 承担，它独立于 `RecallPipeline`、不属于召回编排本身；`generation.py` 同样不调用 LLM，最终生成调用在 runtime 编排层。完整的生成阶段（含流式作答与 SSE 终态事件）见 [recall_generation.md](recall_generation.md)。

---

## 2. 包结构

```text
src/core/pipeline/recall/
├── __init__.py       # 对外导出 RecallPipeline / models / source 常量
├── pipeline.py       # RecallPipeline：多路触发、容错、融合和响应组装
├── models.py         # RecallRequest / RetrieverHit / RecallHit / RecallResponse / Config
├── protocols.py      # Retriever / DocumentReadinessGate 协议 + SOURCE_* 常量
├── document_readiness.py # MySQL 当前任务、ACTIVE chunk 与 visibility hold 门禁
├── fusion.py         # RRF / weighted_score 粗融合
├── generation.py     # 召回后生成准备：正文回填 + 按 token 预算拼装上下文（独立于 RecallPipeline，见 §1 说明）
└── exceptions.py     # RecallError / RecallValidationError / RecallFatalError
```

当前适配器示例：

| 路 | source | 适配器 |
| --- | --- | --- |
| sparse | `sparse` | `src/core/storage/vector/sparse_retriever.py` |
| BM25 | `bm25` | `src/core/storage/bm25_retriever.py` |
| dense | `dense` | `src/core/storage/vector/dense_retriever.py` |

`RecallPipeline` 不写死具体路数；新增 GraphRAG、wiki 或其他召回路时，只要实现 `Retriever` 协议并在构造时传入即可。

---

## 3. 核心流程

```text
RecallRequest(query, user_id, dataset_ids, doc_ids, top_k, bm25_top_k, sparse_top_k, dense_top_k)
  -> RecallPipeline.execute()
       -> validate query / user_id / fusion limit / per-route top_k
       -> run retrievers in parallel / serial（透传 user_id 与各路 top_k）
       -> check failures by strict / loose policy
       -> fuse successful hits with configured strategy
       -> filter visible hits by MySQL document readiness（保持融合顺序）
       -> truncate visible hits to top_k（融合候选池 / rerank 输入窗口）
       -> build RecallResponse
```

并行模式：

```text
asyncio.gather(
  dense.recall(...),
  sparse.recall(...),
  bm25.recall(...),
  return_exceptions=True,
)
```

串行模式：

```text
for retriever in retrievers:
    await retriever.recall(...)
```

串行与并行只影响触发方式，不改变容错语义：单路异常都会先收敛为该 source 的失败结果，再由 `_check_failures()` 统一判断。

### 3.1 文档级可见性门禁

门禁位于**融合完成后、最终 `top_k` 截断前**。因此不可见文档不会占用候选窗口，后续可见候选可以按原融合顺序补位；纯召回 JSON 与 RAG/SSE 都调用同一个 `RecallPipeline.execute()`，不会出现出口间口径分叉。

`MySqlDocumentReadinessGate` 以候选 `chunk_id` 批量查询 MySQL，单批最多 500 个。候选必须同时满足：

- chunk 属于当前请求用户，且 `lifecycle_status=ACTIVE`；hit 中的 `doc_id` / `dataset_id` 与 MySQL 归属一致。
- `document_parse_file.latest_parse_task_id` 指向的 `document_parse_pipeline` 行存在，且该**当前任务**的 `pipeline_status=SUCCESS`。
- 当前 `latest_parse_task_id` 不存在 `visibility_hold=1` 且尚未进入 `SUCCEEDED` / `CANCELLED_SUPERSEDED` 的索引补偿任务。

历史 pipeline 即使曾经成功也不能放行文档；`latest_parse_task_id` 为空、当前 pipeline 缺行或未成功时，整篇文档的 dense / sparse / BM25 命中全部被过滤。门禁查询异常直接向上抛出，按 fail-closed 处理，不降级为返回未过滤候选。

`visibility_hold` 用于防御性反向补偿：当 MySQL 已确认成功但外部索引缺失时，补偿从 MySQL 重建期间先隐藏整篇文档；重建成功或任务因 current task 切换而取消后才释放。门禁同时要求 job 的 `source_task_id == latest_parse_task_id`，因此旧 task 遗留的 hold 不会阻断已经切换到新 current task 的文档。

每次门禁输出结构化汇总日志：`candidate_count`、`visible_count`、`filtered_count`、`query_ms`，以及 `filtered_by_routing_or_missing` / `filtered_by_lifecycle` / `filtered_by_pipeline` / `filtered_by_hold`。为保证各原因之和等于过滤总量，同一 hit 同时不满足多个条件时按 `routing_or_missing → lifecycle → pipeline → hold` 选择首个原因；日志不记录 query 或 chunk 正文。

异常与降级日志统一携带 `request_id/user_id/dataset_count/source/model/config_id` 等可用
业务锚点：单路召回失败为 `recall_source_failed`，生成失败为
`recall_generation_failed`，rerank 模型失败为 `rerank_model_failed`，并发 Redis
故障为 `recall_concurrency_guard_failed`。只记录候选数、耗时、部分答案字符数等统计，
不记录 query、prompt、answer、上下文或 chunk 正文；外部异常使用脱敏摘要和安全调用栈。

---

## 4. Retriever 协议

`RecallPipeline` 只依赖 `Retriever` 协议：

```python
class Retriever(Protocol):
    source: str

    async def recall(
        self,
        query: str,
        dataset_ids: list[int],
        doc_ids: list[int] | None = None,
        *,
        user_id: int,
        top_k: int,
    ) -> list[RetrieverHit]:
        ...
```

实现要求：

- `source` 必须是稳定字符串，且同一个 Pipeline 内不能重复。
- `recall()` 返回的列表必须已按该路原始 `score` 降序排列；Pipeline 信任这个顺序，不会重新按原始分排序。
- 合法但无命中时返回 `[]`，不要抛异常。
- 模型不可达、ES 超时、存储异常等不可恢复失败可抛任意 Exception，由 Pipeline 根据容错配置处理。
- `RetrieverHit.chunk_id` 必须锚定 MySQL `kb_document_chunk.chunk_id`，下游 reranker / 上下文拼装阶段用它反查正文。
- `user_id` / 本路 `top_k` 在**执行期**由 Pipeline 透传（来自 `RecallRequest` 的 `bm25_top_k` / `sparse_top_k` / `dense_top_k`），retriever 不在装配期持有它们——这样 Pipeline 与 retriever 可单例复用，HTTP 入口按请求注入用户上下文。召回 HTTP 入口见 [recall_http_api.md](recall_http_api.md)。

---

## 5. 数据模型

| 模型 | 方向 | 说明 |
| --- | --- | --- |
| `RecallRequest` | 入参 | `query` 必须非空；`user_id` 必须为正（HTTP 入口从凭证 claims 注入）；`dataset_ids` 允许空列表，表示不限数据集；`doc_ids` 可选；`top_k` 为正，表示融合候选池上限 / rerank 输入窗口，由数据集级 `recall_result_limit` 或系统 `RECALL_RESULT_LIMIT` 决定；`bm25_top_k` / `sparse_top_k` / `dense_top_k` 分别控制三路执行期召回深度；融合策略/权重与 `rrf_k` override 来自数据集级 `recall_config`，不来自 HTTP 请求体 |
| `RetrieverHit` | 单路内部结果 | 单路返回的原始候选，包含 `chunk_id`、`doc_id`、`dataset_id`、`score`、`source` |
| `RecallHit` | 融合结果 | 当前融合策略产出的候选，包含 `fused_score` 和每路原始 `scores` |
| `RecallDiagnostics` | 诊断结果 | LINK-195 召回来源结构诊断；完整三路启用且结果可归入四态时，标记 `hybrid` / `bm25_only` / `missing_sparse` / `missing_dense` |
| `RecallResponse` | 出参 | 回显 query、融合候选、各路命中数、失败路、整体耗时 |
| `RecallPipelineConfig` | 装配配置 | `parallel`、`strict`、`rrf_k`、`fusion_strategy`、三路 `fusion_*_weight` |

召回阶段不返回 chunk 正文字段。正文获取属于 reranker 或上下文拼装阶段，避免召回层把存储读取、权限补偿和内容裁剪混在一起。

---

## 6. 容错语义

构造期失败：

- `retrievers` 为空：抛 `ValueError`。
- `source` 重复：抛 `ValueError`，把装配错误暴露在启动或测试阶段。

执行期失败：

| 场景 | 结果 |
| --- | --- |
| `query` 为空或纯空白 | 抛 `RecallValidationError` |
| 宽松模式，部分路失败 | 继续融合成功路；失败 source 写入 `failed_sources` |
| 宽松模式，全部路失败 | 抛 `RecallError` |
| 严格模式，任一路失败 | 抛 `RecallError` |
| 任一路抛 `RecallFatalError`（前置必备条件缺失） | **绕过宽松降级**，`_check_failures` 立即重抛，由路由映射为明确错误码 |
| 某路合法返回空列表 | 不算失败；该路 `per_source_counts[source] = 0` |

`per_source_counts` 的键集合等于已装配的全部 source。失败路与返回空列表的路都计 0；二者通过 `failed_sources` 区分。

LINK-195 后，`RecallResponse.recall_diagnostics` 在完整三路 `bm25` / `sparse` / `dense` 启用且结果可归入四态时返回：

| `source_mode` | 语义 |
| --- | --- |
| `hybrid` | bm25 / sparse / dense 都有候选贡献 |
| `bm25_only` | 只有 bm25 有候选贡献，sparse 与 dense 没有候选贡献 |
| `missing_sparse` | bm25 与 dense 有候选贡献，sparse 没有候选贡献 |
| `missing_dense` | bm25 与 sparse 有候选贡献，dense 没有候选贡献 |

诊断字段同时包含 `active_sources`、`per_source_counts`、`empty_sources` 与 `failed_sources`。
`empty_sources` 只表示成功执行但 0 命中的路；`failed_sources` 仍只表示异常失败路。三路全空保持既有空召回语义，不扩展新的 `source_mode`。

`RecallFatalError`（`RecallError` 子类）是宽松模式的例外：当前来源包括数据集缺少有效 `dense_embedding_config_id` / `sparse_embedding_config_id`、对应向量路无法编码 query。此时即便宽松模式也不能"降级为其余路继续"，否则会静默返回与建库模型不一致或不完整的结果。由 dense/sparse retriever 捕获 `VectorRetrievalUserConfigMissingError` 后抛出。

---

## 7. 融合策略

融合逻辑在 `fusion.py`。`fused_score` 表示当前策略产出的融合分；`RecallHit.scores` 始终保留各路原始分。默认策略是 `rrf`，可通过系统配置 `RECALL_FUSION_STRATEGY` 或数据集级 `recall_config.recall_fusion_strategy` 切换为 `weighted_score`。RRF 的 rank constant 默认取系统配置 `RECALL_RRF_K=60`，数据集级 `recall_config.rrf_k` 可覆盖。

### 7.1 RRF

融合逻辑在 `fusion.py::fuse_with_rrf()`：

```text
contribution = 1 / (rrf_k + rank)
fused_score = sum(contribution for every source where chunk_id appears)
```

选择 RRF 的原因：

- dense、sparse、BM25 的原始分数物理意义不同，不适合直接相加。
- RRF 只依赖各路排名，对不同分数尺度更稳定。
- 同一个 `chunk_id` 被多路命中时贡献累加，只被一路命中时也保留。

融合结果按 `fused_score` 降序返回。RRF 函数保持历史排序语义，默认 `rrf_k=60` 时行为不变。`weighted_score` 策略不读取 `rrf_k`。

### 7.2 weighted_score

`weighted_score` 只支持当前内置三路 source：`bm25` / `sparse` / `dense`。算法：

- BM25、sparse：先对 raw score 做 `log1p(raw_score)`；dense：直接使用 raw score。
- 每一路独立做 min-max 归一化；某一路只有一个命中或 `max == min` 时，该路命中项 normalized score 为 `1.0`。
- 某一路无命中时不进入 active source 权重归一；某个 chunk 未命中某一路时该路贡献为 `0`。
- 权重按 active sources 归一，但不按单个 chunk 命中的 source 重分配。
- 单项权重允许为 `0`；若本次 active source 权重和为 `0`，抛 `RecallValidationError`，不静默回退 RRF。
- 结果按 `fused_score` 降序；仅分数完全相同时按 `chunk_id` 升序稳定排序。

`scores` 字典键集合等于本次生效 source；未命中的路填 `None`，不输出 normalized score。

---

## 8. 扩展指南

### 8.1 新增一路召回

1. 在所属存储或检索模块内实现 `Retriever` 协议，不把存储细节放进 `src/core/pipeline/recall/`。
2. 选择稳定 `source` 名；若是内置常用路，可在 `protocols.py` 增加 `SOURCE_*` 常量。
3. 确保返回的 `RetrieverHit` 已按本路原始分降序排列。
4. 在装配层把新 Retriever 传入 `RecallPipeline([...])`。
5. 增加单路适配器测试和 `tests/unit/core/pipeline/recall/` 下的编排测试。

### 8.2 调整容错策略

通过 `RecallPipelineConfig` 控制：

```python
RecallPipelineConfig(
    parallel=True,
    strict=False,
    rrf_k=60,
)
```

- `parallel=True`：默认并行触发各路，适合线上低延迟路径。
- `parallel=False`：按构造顺序串行触发，适合调试或受限资源场景。
- `strict=True`：任一路失败即整体失败，适合对召回完整性要求高的内部验证。

---

## 9. 测试约定

| 测试目标 | 推荐入口 |
| --- | --- |
| 主流程、并行/串行触发 | `tests/unit/core/pipeline/recall/test_recall_pipeline_main_flow.py` |
| RRF 融合 | `tests/unit/core/pipeline/recall/test_recall_pipeline_rrf.py` |
| weighted_score 融合 | `tests/unit/core/pipeline/recall/test_recall_pipeline_weighted_score.py` |
| 容错语义 | `tests/unit/core/pipeline/recall/test_recall_pipeline_fault.py` |
| 文档级门禁、保序与 top_k 补位 | `tests/unit/core/pipeline/recall/test_recall_pipeline_readiness.py` |
| 入参与构造边界 | `tests/unit/core/pipeline/recall/test_recall_pipeline_validation.py`、`test_recall_pipeline_boundary.py` |
| 单路适配器 | `tests/unit/core/storage/vector/test_sparse_retriever.py`、`tests/unit/core/storage/test_bm25_retriever.py` |

测试 Pipeline 编排时优先使用 fake Retriever，不要 mock Qdrant、ES 或 tokenizer；这些属于各路适配器自己的测试范围。

---

## 10. 修改原则

- `src/core/pipeline/recall/` 保持编排层纯度，不直接读写存储。
- 单路查询、预处理、过滤和打分逻辑放在各自 Retriever 内。
- 文档业务可见性只由必传的 `DocumentReadinessGate` 判定；不得在单路 Retriever、JSON/SSE 出口或正文回填处各自复制一套 current-task 规则。
- Pipeline 只消费 `RetrieverHit`，只输出 `RecallHit`，不携带 chunk 正文。
- 不在召回层接入 rerank score；rerank 永远消费融合后的 `RecallHit`。

## 11. top_k 配置边界（LINK-136）

LINK-136 后，`RecallRequest.top_k` 不再是三路共同的执行期 top_k，而是融合后的候选池窗口。三路深召回分别由 `bm25_top_k` / `sparse_top_k` / `dense_top_k` 控制：

```text
dataset_parse_config.recall_config 或系统 Settings
  -> recall_result_limit        -> RecallRequest.top_k        -> 文档门禁后截断 / rerank 输入池
  -> bm25_top_k / sparse_top_k / dense_top_k
                                -> Retriever.recall(top_k=...) -> 单路召回深度
```

系统默认值：

| 字段 | 默认 | 说明 |
| --- | ---: | --- |
| `RECALL_RESULT_LIMIT` | 64 | 融合候选池窗口，作为 rerank 输入池 |
| `RECALL_BM25_TOP_K` | 100 | BM25 路执行期召回深度 |
| `RECALL_SPARSE_TOP_K` | 50 | sparse 路执行期召回深度 |
| `RECALL_DENSE_TOP_K` | 100 | dense 路执行期召回深度 |

`DENSE_RETRIEVAL_TOP_K` / `SPARSE_RETRIEVAL_TOP_K` 只作为 `VectorStorageFacade.search_dense_chunks()` / `search_sparse_chunks()` 直调时的兜底默认。完整 RAG pipeline 会显式传入三路 top_k，因此不会读取这两个 facade 默认作为召回深度。最终顺序固定为 `fuse → readiness gate → top_k`，不能提前截断。

### 11.1 Wiki 的分知识库 BM25 读取

`Bm25Retriever.recall_by_dataset()` 是 Wiki 专用的分组读取入口，不把 Wiki 注册成 RecallPipeline 的第四路，也不改变既有 `recall()` 结果。它对 query 只分词一次，按 `dataset_id` 排序去重后以最多 8 个并发 work item 调用当前 BM25 后端；每库独立按 `(-score, doc_id, chunk_id)` 稳定排序、按 `chunk_id` 去重并截取 `WIKI_BM25_TOP_K_PER_DATASET`。

超时、连接中断和明确的 502/503/504 最多重试一次，退避时释放并发槽；参数、认证、权限、配置和协议错误不重试。任一 work item 最终失败即让整条 BM25 来源失败，交由 Wiki 的系统级 strict/lenient 规则处理，不能静默遗漏故障知识库。详情见 [wiki_heading_tree.md](wiki_heading_tree.md)。

---

## 12. 召回后重排模块（独立下游，LINK-130）

`RecallPipeline` 只到粗融合为止。融合之后的精排由一个**独立模块**承接，与纯召回解耦：

```text
src/core/pipeline/
├── chunk_content.py     # 中立正文回填 helper：按 chunk_id 批量取本用户 ACTIVE 非空正文
│                        #   （rerank 与 recall.generation 共享，避免 rerank 反向依赖 generation）
└── rerank/
    ├── __init__.py      # 导出 PostRecallReranker / RerankRequest / RerankResponse / RerankedHit
    ├── models.py        # RerankRequest / RerankedHit / RerankResponse
    └── reranker.py      # PostRecallReranker：回填正文 → 解析用户 RERANK 模型 → 调用 → 映射/降级
```

流程：`RecallHit 列表 → 回表取正文 → 按当前融合顺序构造 documents → 调用用户 RERANK 模型 →
按返回 index/score 映射回候选、补 rerank_score/rerank_rank → 截断 top_n`。

边界与语义：

- **不触碰召回边界**：`RecallPipeline` 仍只返回融合后的 `RecallResponse`，不查正文、不调 rerank。
- **输出保留融合解释信息**：`RerankedHit` 在 chunk 元信息上保留 `fused_score` 与各路 `scores`，新增 `rerank_score` / `rerank_rank`。
- **失败语义**：用户未配置 RERANK 模型 → 硬失败（异常上抛，不降级）；rerank 调用失败 / 返回不可用 → 降级返回当前融合顺序候选并标记 `rerank_applied=False`。
- **top_n**：调用方传入，缺省取数据集级 `recall_config.rerank_top_n`，无数据集配置时回退 `RERANK_DEFAULT_TOP_N`（默认 8）。
- **LINK-136 配套**：融合候选池默认放大为 64，并与三路 per-route top_k 解耦，使 rerank 有足够候选可筛。
- 测试：`tests/unit/core/pipeline/rerank/`，以替身注入正文回填与模型解析，不连真实 DB / LLM。

> 注：当前 LLM provider 尚无具体 RERANK 实现（各 provider `rerank()` 为 `NotImplementedError`、未声明 `CapabilityType.RERANK`）。本模块按 `IReranker` 接口契约实现并以替身单测，接入真实 rerank-capable provider 后即可端到端生效。
