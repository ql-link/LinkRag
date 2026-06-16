# Elasticsearch 索引与 BM25 检索

本文说明 `src/core/storage/es/`。该模块承担**两个职责**：

1. **写入侧（入库）**：把预分词后的 chunk token 文档批量写进 Elasticsearch。
2. **召回侧（检索）**：对预分词字段做 BM25 检索，返回 topK chunk。

它消费上游 [preprocessor](preprocessor.md) 产出的 `FilePostIndexPlan`（预分词计划），召回侧通过适配器接入 [recall_pipeline.md](recall_pipeline.md)。ES 索引结构权威说明见 [schemas/elasticsearch.md](../api/schemas/elasticsearch.md)。

---

## 1. 包结构

```text
src/core/storage/es/
├── __init__.py          # 公共入口：入库 Pipeline + 召回 Retriever + 模型 + 异常
├── client.py            # 进程级 AsyncElasticsearch 客户端单例
├── mapping.py           # ES index settings + mappings（analyzer / 字段）
├── document_factory.py  # chunk token plan → ES bulk action（瘦文档）
├── batcher.py           # 按字节/条数把 bulk action 分批
├── pipeline.py          # EsIndexingPipeline：文件级入库阶段
├── models.py            # 入库结果模型（EsIndexingResult / BulkBatchResult）
├── retrieval.py         # EsBm25Retriever：BM25 topK 检索
├── retrieval_models.py  # Bm25RecallRequest / Bm25ChunkHit
├── bm25_retriever.py    # 召回 Pipeline 适配器（Bm25Retriever）
├── exceptions.py        # ES 入库/召回异常族
└── smoke.py             # 集成测试用最小 keyword query 冒烟工具
```

---

## 2. ES 索引结构

`mapping.py::build_es_index_body(shards, replicas)` 定义索引。要点：

- **瘦文档**：`_source` 排除 `coarse_tokens` / `fine_tokens`，token 只进倒排索引不回存正文，控制存储与 `_source` 体积。
- **routing 必填**：`routing.required = True`，写入与检索都按 `dataset_id` 路由，保证同数据集 chunk 落同分片。
- **字段**：定位字段 `chunk_id`（keyword）、`user_id` / `dataset_id` / `doc_id`（long）、`task_id`（keyword）、`chunk_index`（integer）；检索字段 `coarse_tokens` / `fine_tokens`（text）。
- **分词器**：token 已由上游 RAGFlow 预分词为空格分隔词串，ES 侧 `chunk_index_analyzer` / `chunk_search_analyzer` 都用 `whitespace` tokenizer + `lowercase` filter，不在 ES 内二次分词——索引侧和召回侧用同一份分词产物，避免 token 分布漂移。

---

## 3. 写入路径

```text
FilePostIndexPlan（来自 preprocessor）
  → EsIndexingPipeline.run(...)
      → EsDocumentFactory.build_action()  # 每个 chunk 转 bulk action，校验大小
      → TokenBatcher                       # 按字节/条数分批
      → client.bulk(...)                   # 逐批写 ES
      → 汇总为 EsIndexingResult
```

- **`EsDocumentFactory`（document_factory.py）**：把 `ChunkWithTokens` + `FileIndexMeta` 转成 `EsBulkAction`（operation + document + estimated_bytes），超过 `ES_MAX_DOCUMENT_BYTES` 的文档抛 `EsDocumentValidationError`。
- **`TokenBatcher`（batcher.py）**：按 `ES_MAX_TOKEN_BATCH_BYTES` / `ES_MAX_TOKEN_BATCH_CHUNKS` 把 action 切成多个 `TokenBatch`，校验失败的 chunk 收集进 `failed_errors`。
- **`EsIndexingPipeline`（pipeline.py）**：编排上述步骤，依赖 `ChunkRepository` 推进 chunk 的 ES 索引状态，ES 服务级失败抛 `EsBulkError`。

结果模型在 `models.py`：`EsIndexingResult`（`total_items` / `indexed_items` / `failed_item_ids` / `succeeded_item_ids` / `skipped_item_ids`，`is_success` 判定全成功）、`BulkBatchResult`（单次 bulk 的成功/失败明细）。

---

## 4. 召回路径

### 4.1 `EsBm25Retriever`（retrieval.py）

底层 BM25 检索器，输入 `Bm25RecallRequest`，输出 `list[Bm25ChunkHit]`：

```python
@dataclass(frozen=True)
class Bm25RecallRequest:
    user_id: int
    dataset_id: int
    tokens: Sequence[str]   # 已分词的 query token
    top_k: int
    doc_id: int | None = None

@dataclass(frozen=True)
class Bm25ChunkHit:
    chunk_id: str
    doc_id: int             # 同步返回，省去召回后回查 MySQL
    score: float            # ES 原始 BM25 分
```

查询构造（`_build_query`）：

- **filter**（不打分，做范围裁剪）：`user_id` term + `dataset_id` term，可选 `doc_id` term。
- **must**（打分）：`multi_match` 在 `coarse_tokens^2`（权重 2）和 `fine_tokens` 上做 `best_fields`，query 为 token 空格拼接。
- 检索按 `dataset_id` 路由（`routing=str(dataset_id)`），`_source` 只取 `chunk_id` / `doc_id`，`size=top_k`。
- 空 token 直接返空；ES 调用异常包成 `EsRetrievalError`，非法请求抛 `EsRecallValidationError`。

### 4.2 `Bm25Retriever`（bm25_retriever.py）—— 召回 Pipeline 适配器

实现 `Retriever` 协议（见 [recall_pipeline.md §4](recall_pipeline.md#4-retriever-协议)），`source = "bm25"`。只做形状翻译：

```text
Retriever.recall(query, dataset_ids, doc_ids, *, user_id, top_k)
    ↓ tokenizer.tokenize(query) 取 coarse_tokens
    ↓ 对每个 dataset_id（×doc_id）构造 Bm25RecallRequest
EsBm25Retriever.recall_topk_chunks(request)
    ↓ 合并、按 ES 原始分降序、截断 top_k
list[RetrieverHit]
```

- **分词器复用写入侧**：`tokenizer` 装配期注入，生产上用 `preprocessor.RagFlowTokenizer`，召回只取 `coarse_tokens` 切回 list——和入库用同一份分词器，避免召回/索引 token 分布漂移。
- `user_id` / `top_k` 由 pipeline 执行期透传并校验为正。
- `dataset_ids` 为空 → 返空（BM25 依赖 dataset routing，放弃"全库"语义）；多 dataset/doc 做笛卡儿积逐次下发，合并截断。

---

## 5. ES 客户端

`client.py` 维护**进程级单例** `AsyncElasticsearch`：`get_async_es_client(settings)` 懒初始化（`asyncio.Lock` 保护），`close_async_es_client()` 在应用关闭时释放。连接参数取自 settings：`ES_HOST`、`ES_BULK_REQUEST_TIMEOUT_SECONDS`（request_timeout），`ES_USER` + `ES_PASSWORD` 都存在时启用 basic auth。

---

## 6. 配置项

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `ES_HOST` | `http://localhost:9200` | ES 地址 |
| `ES_USER` / `ES_PASSWORD` | — | basic auth（两者都设才启用） |
| `ES_INDEX_NAME` | `tolink_rag_index` | 索引名 |
| `ES_INDEX_SHARDS` / `ES_INDEX_REPLICAS` | `3` / `1` | 分片与副本 |
| `ES_MAX_DOCUMENT_BYTES` | `131072` | 单文档字节上限 |
| `ES_MAX_TOKEN_BATCH_BYTES` / `ES_MAX_TOKEN_BATCH_CHUNKS` | `5242880` / `500` | 单次 bulk 字节/条数上限 |
| `ES_BULK_REQUEST_TIMEOUT_SECONDS` | `30` | bulk/search 请求超时 |
| `ES_SMOKE_ENABLED` | `False` | 是否启用 smoke 冒烟 |

配置详解见 [ops/configure.md](../ops/configure.md)。

---

## 7. 异常族

| 异常 | 触发 |
| --- | --- |
| `EsIndexingError` | 入库异常基类 |
| `EsDocumentValidationError` | chunk 无法转成合法 ES 文档（如超大） |
| `EsBulkError` | ES 服务级操作失败 |
| `EsRecallValidationError`（继承 `ValueError`） | 召回请求非法 |
| `EsRetrievalError` | 召回检索失败 |

---

## 8. 公共入口

`__init__.py` 导出：`EsIndexingPipeline`、`EsIndexingResult`、`EsBm25Retriever`、`Bm25Retriever`、`Bm25RecallRequest`、`Bm25ChunkHit`，以及全部异常。`smoke.py::run_es_index_smoke()` 仅供集成测试做最小 keyword query 验证。

---

## 9. 测试约定

| 测试目标 | 入口 |
| --- | --- |
| 入库阶段、分批、文档工厂 | `tests/unit/core/storage/es/` |
| BM25 召回适配器 | `tests/unit/core/storage/es/test_bm25_retriever.py` |
| 真实 ES（需开关） | `ES_SMOKE_ENABLED=True` + 集成测试 |
