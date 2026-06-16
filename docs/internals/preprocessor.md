# 预分词模块（Preprocessor）

本文说明 `src/core/preprocessor/`。它是 ES/BM25 链路的**上游**：把已落库的 chunk 正文用 RAGFlow 分词器预先切成 token，产出文件级"ES 后置索引计划"（`FilePostIndexPlan`），交给 [es_index_storage](es_index_storage.md) 写入 Elasticsearch。

"预分词"指**写入侧提前完成分词**：ES 索引文档里直接存空格分隔的 token 串，ES 端只做 `whitespace` 切分不再二次分词，从而索引侧与 BM25 召回侧共用同一份分词产物，避免 token 分布漂移（召回侧分词见 [es_index_storage.md §4.2](es_index_storage.md#42-bm25retrieverbm25_retrieverpy-召回-pipeline-适配器)）。

---

## 1. 包结构

```text
src/core/preprocessor/
├── __init__.py            # 包说明（不导出符号）
├── models.py              # 预分词产物契约：FileIndexMeta / ChunkWithTokens / FilePostIndexPlan
├── ragflow_tokenizer.py   # RagFlowTokenizer：RAGFlow 分词器适配
└── service.py             # Preprocessor：从库里读 chunk 构建 FilePostIndexPlan
```

---

## 2. 产物模型（models.py）

这些 dataclass 是预分词与 ES 入库之间的**共享契约**（`frozen` + `slots`）：

| 模型 | 字段 | 说明 |
| --- | --- | --- |
| `FileIndexMeta` | `user_id` / `dataset_id` / `doc_id` / `task_id` | 文件级归属元信息 |
| `ChunkWithTokens` | `chunk_id` / `chunk_index` / `coarse_tokens` / `fine_tokens` | 单 chunk 的两级 token 串 |
| `FilePostIndexPlan` | `file_meta` + `chunks_with_tokens: list[ChunkWithTokens]` | 一个文件的完整 ES 后置索引计划 |

`coarse_tokens`（粗粒度）与 `fine_tokens`（细粒度）对应 ES mapping 里的两个检索字段，召回时 `coarse_tokens` 权重更高（见 ES BM25 查询构造）。

---

## 3. 分词器（ragflow_tokenizer.py）

`RagFlowTokenizer` 是对 RAGFlow 分词实现的薄封装：

- 依赖 `infinity.rag_tokenizer.RagTokenizer`（来自 `infinity-sdk`）。依赖缺失时构造抛 `RuntimeError`，提示安装或注入替身。
- `tokenize(text) -> TokenizedText`：先用 `TABLE_TAG_RE` 把 `<table>/<td>/<tr>/<th>/<caption>` 等表格标签替换为空格，再 `tokenize` 得 `coarse_tokens`、`fine_grained_tokenize` 得 `fine_tokens`，二者均为空格分隔词串。
- `TokenizedText` 是 `(coarse_tokens, fine_tokens)` 的轻量载体。

> RAGFlow/infinity 分词器需要本地 NLTK 数据，路径引导见 [src/bootstrap/nltk_data.py](../../src/bootstrap/nltk_data.py)。

---

## 4. 服务（service.py）

`Preprocessor` 从 MySQL 读 chunk 并构建计划，核心方法 `build_file_post_index_plan(doc_id, task_id)`：

1. 通过 `_list_chunks_for_pretokenization` 查该文档**全部有效 chunk**（Issue #57：ES 文档级全量重建，不再按 `es_status` 过滤）。筛选条件：`doc_id` 匹配、`dense_vector_status = INDEXED`（dense 已就绪是前置依赖）、`lifecycle_status = ACTIVE`，按 `chunk_index` 升序。
2. 无记录 → 返回空计划（`file_meta` 用占位 0 值，`chunks_with_tokens=[]`）。
3. 对每条记录调 `_tokenize_record`：校验 `chunk_index` 合法、分词、`strip` 后校验 `coarse_tokens` / `fine_tokens` 非空，产出 `ChunkWithTokens`。
4. 文件级 all-or-nothing：任一 chunk 预分词失败 → 整体抛 `PreprocessorError`，不写任何 chunk 的 es_status；失败终态由上游解析阶段落地。
5. `file_meta` 的 `user_id` / `dataset_id`（取自 `set_id`）/ `doc_id` 从首条记录取。

依赖通过构造注入，便于测试：`session_factory`（默认 `get_async_session_factory()`）、`tokenizer` 或 `tokenizer_factory`（默认 `RagFlowTokenizer`，懒加载）。`ChunkTokenizer` Protocol 定义了 `tokenize` 最小契约。

---

## 5. 与相邻模块的关系

```text
storage.chunks (ChunkRecordDB)        ← 数据来源（dense 已 INDEXED 的 active chunk）
        │
        ▼
preprocessor.Preprocessor                  ← 本模块：读 chunk → 预分词
        │  FilePostIndexPlan
        ▼
storage.es.EsIndexingPipeline        ← 下游：批量写 ES
        ⋮
storage.es.Bm25Retriever             ← 召回侧复用 RagFlowTokenizer 分词 query
```

在解析主流水线里，预分词对应 parse_task 的 `pretokenize` 阶段，紧接其后是 `es_indexing` 阶段（见 [parse_task_pipeline.md](parse_task_pipeline.md)）。

---

## 6. 测试约定

`Preprocessor` 用注入的 fake tokenizer / session 测试，不依赖真实 infinity-sdk；`RagFlowTokenizer` 的真实分词行为属于集成测试范围。
