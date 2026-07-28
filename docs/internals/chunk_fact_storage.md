# Chunk 事实存储（chunk_fact_storage）

本文说明 `src/core/storage/chunks/` —— Chunk 的 **SQL 真值源**。它是整条 RAG 链路的单一事实来源：解析流水线把分片落到这里，向量化 / 稀疏 / BM25 三路在这里翻转各自的子状态，召回生成阶段按 `chunk_id` 从这里回读正文。Qdrant 与 Manticore 都只是它的派生索引，最终一致而非强一致。

底层表结构见 [docs/api/schemas/mysql.md](../api/schemas/mysql.md) 的 `kb_document_chunk`，ORM 为 [`ChunkRecordDB`](../../src/models/chunk_record.py)。

---

## 1. 定位与职责

- **唯一真值**：`kb_document_chunk` 一行 = 一个 chunk 的权威记录（正文、来源、三路索引状态、生命周期）。下游读取（召回正文回填、补偿修复、状态统计）以本表为准，不以 Qdrant/Manticore 为准。
- **薄仓储**：`ChunkRepository` 只做 SQL 读写与 CAS（compare-and-set）状态翻转，不含业务编排、不发通知、不调外部存储。编排归 [parse_task_pipeline](parse_task_pipeline.md) 的各 Stage，外部索引写入归 [vectorization](vectorization.md) / [sparse_vector](sparse_vector.md) / Manticore BM25。

```text
src/core/storage/chunks/
├── repository.py   # ChunkRepository：插入 / CAS 状态翻转 / 计数 / 候选查询 / 修复
├── models.py       # FactChunkDraft（插入草稿）/ ChunkPostStatus / decide_chunk_post_status
├── constants.py    # 三路子状态 + 生命周期常量、允许更新/删除的状态集合
└── exceptions.py
```

---

## 2. 状态模型

每个 chunk 有**三条相互独立的索引子状态** + **一条生命周期**，互不耦合（一路失败不连带翻转另一路）：

| 列 | 取值 | 含义 |
| --- | --- | --- |
| `dense_vector_status` | `PENDING` / `SUCCESS` / `FAILED` | Qdrant 稠密向量索引 |
| `sparse_vector_status` | `PENDING` / `SUCCESS` / `FAILED` | 稀疏向量索引 |
| `es_status` | `PENDING` / `SUCCESS` / `FAILED` | BM25 入库（字段名保留历史 `es`，实际后端可为 Qdrant BM25 或 Elasticsearch） |
| `lifecycle_status` | `ACTIVE` / `REMOVED` | 软删除生命周期 |

> **常量命名陷阱**（见 [constants.py](../../src/core/storage/chunks/constants.py)）：代码里 `CHUNK_STATUS_INDEXING` 与 `CHUNK_STATUS_PENDING` 是**同一个 DB 值 `"PENDING"`**，`CHUNK_STATUS_INDEXED` / `SUCCESS` 同为 `"SUCCESS"`。即落库只有 `PENDING` / `SUCCESS` / `FAILED` 三态，"INDEXING" 只是语义别名、不是独立第四态。读写时不要把 `INDEXING` 当成区别于 `PENDING` 的状态。

三路子状态只承担处理进度、诊断与补偿，不聚合成新的 chunk `processing_status`，也不直接决定文档可见性。文档是否可召回由 `document_parse_file.latest_parse_task_id` 指向的当前 `document_parse_pipeline.pipeline_status=SUCCESS` 统一判断。

允许状态集合（CAS 白名单）：

- `CHUNK_UPDATE_ALLOWED_STATUSES = (SUCCESS, FAILED)`：可被重建/改写的 dense 状态。
- `CHUNK_DELETE_ALLOWED_STATUSES = (PENDING, SUCCESS, FAILED)`：可被删除清理的 dense 状态。

`decide_chunk_post_status(record, sparse_enabled)`（[models.py](../../src/core/storage/chunks/models.py)）按三路子状态 + 生命周期派生文件级后处理结论：`PROCESSING` / `VECTOR_FAILED` / `ES_FAILED` / `COMPLETED`（非 `ACTIVE` 一律 `PROCESSING`）。

---

## 3. 写入与状态翻转

| 方法 | 作用 | CAS / 保护 |
| --- | --- | --- |
| `bulk_insert_pending(drafts)` | 由 `FactChunkDraft` 批量插入，初始 `lifecycle=ACTIVE`、sparse/es=`PENDING` | `chunk_id` 全局唯一键去重 |
| `delete_by_doc_id(doc_id)` | **硬删除**一个 doc 的全部 chunk 行（不分 lifecycle） | 服务于「重试从 CHUNKING 恢复」：先清场再 `bulk_insert_pending`，同事务原子重建 |
| `mark_indexing` / `mark_indexed` / `mark_failed` | dense 状态翻转，只修改 dense 维度 | 见下方 CAS 优先级；恒带 `_active_predicate` |
| `mark_sparse_indexing` / `mark_sparse_indexed` / `mark_sparse_failed` | sparse 状态翻转 | CAS 同下；只 SET sparse 维度 |
| `mark_es_success` / `mark_es_failed` / `mark_es_retrying` | BM25 chunk 状态翻转 | 使用 ES/BM25 专属 CAS，并恒带 `_active_predicate` |
| `mark_document_es_failed` / `mark_document_es_success` | 文档级 BM25 清理/重建后统一更新整篇 ACTIVE chunk | 按 `doc_id + user_id + set_id` 限定范围 |

Wiki 标题树只保存 `chunk_id` 引用。管理端删除 Chunk 时，`lifecycle_status: ACTIVE → REMOVED` 与删除该 Chunk 的全部 `wiki_tree_node.CHUNK_REF` 必须在同一 MySQL 事务中完成；批量 CAS 只要不是全量命中就整体回滚，不能删除仍为 ACTIVE 的 Chunk 引用。即使清理重试窗口内存在悬挂引用，所有 Wiki 读取仍以 ACTIVE Chunk 为最终门禁。

单 Chunk 正文更新继续复用既有 `chunk_id` 和 Wiki 引用；请求若实际改变 `start_line`、`end_line` 或 `chunk_index`，会在 content hash、MySQL 更新、embedding 及外部索引 mutation 前抛出 `ChunkStructuralUpdateNotAllowedError`，并提示通过整文档重新解析原子替换 Chunk 与标题树。字段省略或携带相同值不视为结构变化。
| `mark_removed(chunk_ids)` | 软删除：`lifecycle ACTIVE→REMOVED` | 触发「鬼影 hit」窗口（见 §5） |
| `update_chunk_for_reindex` / `update_chunk_metadata` | 改写正文/元数据并重置索引状态 | 限 `dense_vector_status ∈ (SUCCESS, FAILED)` 且 `ACTIVE` |

系统不保存补偿状态，也不扫描失败记录。外部写入未被 MySQL 确认时由当前写入链路同步清理，随后等待用户重试；不得凭三路共享的 `update_time` 推断任务已经失活。

外部 Qdrant point、named vector 或 ES document 的存在性只作诊断，绝不能反向证明 chunk 状态成功。MySQL 未确认时，统一补偿会先幂等清理目标产物、把分支收敛为 `FAILED`，再从本表正文重建并确认 `SUCCESS`。

旧补偿入口均为 no-op，不回填状态、不重建外部索引。恢复方式是重新发起整篇文档解析。

**CAS 优先级（关键不变量）**：状态翻转分别走 dense、sparse、ES/BM25 专属 update helper，条件优先级统一为

```
allowed_statuses（多值 IN）  >  expected_status（单值 =）  >  无状态 CAS
并且：始终叠加 _active_predicate（lifecycle == ACTIVE）
```

多值 CAS 用于「首次（PENDING）/ 重试（PENDING+FAILED）」一条 UPDATE 覆盖两种合法旧态，同时挡住把已 `SUCCESS` 的 chunk 误拉回 `INDEXING`（防止流水线现场过滤口径错误时回退已完成工作）。`_active_predicate` 兜底保证永远改不到已 `REMOVED` 的行。

---

## 4. 查询与健康校验

供各 Stage 在编排层做「现场过滤」与 all-or-nothing 健康检查（不在 dense/sparse/es 模块内自查 SQL）：

| 方法 | 用途 |
| --- | --- |
| `get_by_chunk_ids` / `get_updatable_by_chunk_ids` / `get_deletable_by_chunk_ids` | 按 chunk_id 反查，返回顺序与入参顺序一致 |
| `list_vector_candidates_by_doc_id(sparse_enabled)` | 仍需 dense（或 sparse）补做的 chunk |
| `list_sparse_candidates_by_doc_id(statuses)` | 指定 sparse 状态的 chunk |
| `list_es_pending_or_failed_chunk_ids_by_doc_id` | ES 仍 `PENDING/FAILED` 的 chunk_id |
| `count_by_doc_id` | 有效 chunk 总数（=0 视为状态严重不一致，文件级兜底） |
| `count_sparse_not_success_by_doc_id` / `count_es_not_success_by_doc_id` | 未完成计数，供阶段成败判定 |

以上查询**一律带 `_active_predicate`**，只看 `ACTIVE` 行。

---

## 5. 一致性边界（鬼影 hit）

`lifecycle_status` 是删除的**权威信号**且即时翻转；Qdrant / ES 的实际清理经 MQ + 补偿异步完成（窗口数十秒至分钟级）。窗口内向量/BM25 召回**可能返回已 `REMOVED` 但索引尚未清理的 `chunk_id`**（"鬼影 hit"）。

因此**所有下游读回正文都必须按 `lifecycle_status == ACTIVE` 过滤**。公共 `RecallPipeline` 已在融合后、top_k 前通过 MySQL 门禁同时校验 ACTIVE、当前 pipeline 整体成功与当前 task 的 `visibility_hold`；旧 task 的 hold 不影响新 current task。召回生成阶段的 [`fetch_chunk_contents`](../../src/core/pipeline/recall/generation.py) 回填时再次过滤 ACTIVE。完整边界与调用模式见 [recall_pipeline.md §3.1](recall_pipeline.md#31-文档级可见性门禁) 和 [vectorization.md §9.6](vectorization.md#96-鬼影-hit-边界删除一致性)。

---

## 6. 协作关系

- **写入侧**：解析流水线 `ChunkingStage` 经 `StageServices._persist_chunk_facts` 调 `bulk_insert_pending`；`VectorizingStage` / `SparseVectorizingStage` / `EsIndexingStage` 翻转各自子状态。三路正常写、统一补偿清理/重建和文档删除共用 MySQL `(doc_id, branch)` 锁；dense/sparse repair 固定同时取得 `DENSE → SPARSE`。锁内 current-task SELECT 持有共享行锁到 mutation guard 退出，阻止 Java 在外部 mutation 中途切换 `latest_parse_task_id`。详见 [parse_task_pipeline.md](parse_task_pipeline.md)。
- **读取侧**：公共召回门禁先判断当前文档就绪，再由召回生成阶段回填正文（[recall_pipeline.md](recall_pipeline.md)、[recall_generation.md](recall_generation.md)）；向量存储补偿/修复链路见 [vectorization.md](vectorization.md)。
- **schema 权威**：字段/索引以 ORM + Alembic 迁移为准，对外摘要见 [mysql.md](../api/schemas/mysql.md)。

---

## 7. 测试与修改原则

- 仓储单测入口：`tests/unit/core/storage/chunks/`。
- 改 CAS 条件或新增状态翻转方法时，务必保留两条不变量：**`_active_predicate` 恒在**、**已 `SUCCESS` 不被多值 CAS 拉回**。二者是防数据回退与防写已删 chunk 的底线。
- 新增/修改字段只改 ORM + 写 migration，并同步 [mysql.md](../api/schemas/mysql.md)（受 [文档同步规则](../contributing.md) 强制）。
