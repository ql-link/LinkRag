---
name: rag-recall-eval
description: 评估 dense/sparse/bm25 三路召回及融合的检索质量，用一组带期望命中的 query 跑召回，量化命中率/排序，支撑换 embedding provider、调 top_k/threshold、改 RECALL_ENABLED_SOURCES 后的回归判断。 - 当用户要求评估召回效果、对比检索质量、验证换向量模型/调参后是否退化、排查「召回不准/漏召」时激活。触发示例：'评估一下召回质量'、'换了 bge 服务召回有没有变差'、'调 top_k 后对比一下'、'sparse 和 dense 哪个召回好'、'搭个召回评测'
when_to_use: "当用户要求评估/对比 RAG 召回质量、验证换 embedding provider 或调 top_k/threshold/RECALL_ENABLED_SOURCES 后是否退化、或排查召回不准/漏召时激活。触发示例：'评估一下召回质量'、'换了 bge 服务召回有没有变差'、'调 top_k 后对比一下'、'sparse 和 dense 哪个召回好'、'搭个召回评测'。若用户是排查召回报错/为空的故障转 incident-triage；只写单测转 auto-test。"
---

# RAG 召回质量评估（Skill）

## 目的

为本项目的三路召回（dense / sparse(BGE-M3) / bm25）及其融合提供**可量化、可复跑**的评估，
用于回答："换 BGE provider（本地↔HTTP）后召回退化了吗？""调 top_k / score_threshold 值不值？"
"某类 query 漏召的根因是什么？"。避免凭感觉调参。

## 必读 / 入口

1. `docs/internals/recall_pipeline.md` / `recall_http_api.md`（召回链路与入口）
2. `src/core/vector_storage/facade.py`：`search_sparse_chunks` / `search_dense_chunks`
3. `src/core/sparse_vector/`（sparse 编码：provider=bge_m3 / bge_m3_http）
4. 配置：`RECALL_ENABLED_SOURCES`、`SPARSE_RETRIEVAL_TOP_K/SCORE_THRESHOLD`、
   `DENSE_RETRIEVAL_TOP_K/SCORE_THRESHOLD`、`RECALL_RESULT_LIMIT`
5. 既有测试参考：`tests/acceptance/test_sparse_vector_recall.py`

## 评估集（黄金集）

- 形态：`[{query, expected_chunk_ids|expected_doc_ids, note}]`，覆盖
  关键词命中、语义改写、长尾、跨文档等类型。
- 范围：固定 `user_id` / `set_id`，确保数据可复现（建议用已稳定入库的 dataset）。
- 存放：建议 `.specs/<feature>/recall_eval/golden.jsonl`，与本次评测一起留档。

## 指标（每路单独 + 融合）

- **Recall@k**：期望命中是否落在前 k。
- **Hit@1 / MRR**：首位/倒数排名质量。
- **命中重叠**：dense vs sparse vs bm25 各自独有/共有的命中（看互补性）。
- **延迟**：单 query 各路耗时（换 HTTP provider 时尤其要看）。

## 执行流程

1. **确认数据就绪**：黄金集涉及的 chunk 已正确入库（MySQL 状态 SUCCESS 且 Qdrant 有 point；
   若刚清过库，先按 incident-triage 重置 + 重灌，否则评测无意义）。
2. **固定变量**：记录本轮配置快照（provider、top_k、threshold、enabled_sources）。
3. **跑召回**：对每条 query 调用 facade 的 `search_*_chunks`，分别取 dense/sparse/bm25 结果。
4. **算指标**：对照 expected 计算上面各指标，按路与融合分别汇总。
5. **对比基线**：若是"换 provider/调参"场景，与上一轮快照同口径对比，标出涨跌。
6. **归因**：对退化/漏召的 query，定位是编码差异、threshold 过滤、还是数据缺失。

## 输出要求

- 一张结果表：`配置快照 × {Recall@k, Hit@1, MRR, 延迟}`，分 dense/sparse/bm25/融合。
- 变更对比（如有基线）：明确"哪些 query 变好/变差"，附根因。
- 结论与建议：是否接受本次变更、推荐的 top_k/threshold 取值。
- 复现信息：黄金集路径、配置快照、运行命令，保证可重跑。

## 原则

- 数据可复现 > 指标好看；评测前先确认入库一致性，避免拿脏数据下结论。
- 单一变量对比：一次只改一个配置（provider 或 top_k 或 threshold）。
- 换 BGE provider（本地↔HTTP）属于"编码实现变更"，必须同口径回归而非只看能跑通。
- 不把评测脚本当生产代码混入 src；评测产物留在 `.specs/` 下。
