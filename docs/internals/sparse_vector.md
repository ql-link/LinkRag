# 稀疏向量模块（BGE-M3）

本文说明 `src/core/encoding/sparse/`：基于 BGE-M3 的稀疏向量编码与索引模块。它在**写入侧**把 chunk 原文编码成稀疏向量写进 Qdrant，在**召回侧**把用户 query 编码后做稀疏检索。dense 向量编排见 [vectorization.md](vectorization.md)，Qdrant 存储结构见 [schemas/qdrant.md](../api/schemas/qdrant.md)，召回编排见 [recall_pipeline.md](recall_pipeline.md)。

---

## 1. 职责边界

稀疏向量是 BGE-M3 输出的 lexical weights（token_id → 权重），与 dense 向量互补：dense 擅长语义相似，sparse 擅长关键词/术语精确匹配。本模块只负责：

1. 文本 → 稀疏向量的编码（本地或远程三种 provider）。
2. 输出规整（截断 top_k、过滤低权重、唯一化、有限性校验）。
3. 文件级稀疏索引阶段编排（写入 Qdrant、推进 chunk 状态）。
4. 召回侧 query 编码与 Retriever 适配。

它明确不做：dense 编码、Qdrant collection/point 结构定义（结构见 [schemas/qdrant.md](../api/schemas/qdrant.md)）、query 改写/清洗、跨路融合（属于召回 Pipeline）。

---

## 2. 包结构

```text
src/core/encoding/sparse/
├── __init__.py          # 公共入口（见 §7 关于循环导入的取舍）
├── constants.py         # 默认模型名、provider 取值、向量名、状态常量
├── models.py            # SparseVector / SparseChunkVectorizationRequest / *Result
├── exceptions.py        # SparseVectorError 异常族
├── encoder.py           # 本地 BGE-M3 编码器 + SparseVectorEncoderProtocol + 清洗工具
├── http_encoder.py      # 远程 bge-m3-server HTTP 编码器（仅 sparse）
├── remote_encoder.py    # 独立 bge-m3-service 远程编码器（dense + sparse，带重试）
├── factory.py           # 按 settings 选 provider 装配 SparseVectorService
├── pipeline.py          # SparseVectorService：对编排层暴露的稳定服务接口
└── deploy_bge_m3.py     # 本地模型部署与冒烟脚本
```

> 索引侧 `sparse_indexing.py`（SparseIndexingPipeline）与召回适配器 `sparse_retriever.py` 位于 `src/core/storage/vector/`。

---

## 3. 编码器抽象与三种 Provider

所有编码器实现同一个 `SparseVectorEncoderProtocol`（定义在 `encoder.py`）：

```python
class SparseVectorEncoderProtocol(Protocol):
    async def aencode(self, texts: Sequence[str]) -> list[SparseVector]: ...
    @property
    def model_name(self) -> str: ...
```

`aencode` 的契约：返回列表与输入 `texts` **等长同序**；推理失败抛 `SparseVectorEncodingError`，输出非法抛 `SparseVectorOutputError`。上层 `SparseVectorService` 信任这个契约，编码器只管"文本进、稀疏向量出"，不碰 MySQL/Qdrant 状态。

`factory.py::create_sparse_vector_service_from_settings()` 按 `SPARSE_VECTOR_PROVIDER` 在三种实现间切换：

| provider | 实现类 | 说明 |
| --- | --- | --- |
| `bge_m3`（默认） | `BGEM3SparseVectorEncoder`（encoder.py） | 本地进程内加载 BGE-M3 模型推理，零外部依赖 |
| `bge_m3_http` | `BGEM3HttpSparseVectorEncoder`（http_encoder.py） | 调用早期 `bge-m3-server` 的 `/encode`，仅取 sparse，无重试 |
| `remote_bge_m3` | `RemoteBGEM3Encoder`（remote_encoder.py） | 调用独立 `bge-m3-service`，dense（1024 维）+ sparse 同出，带超时/5xx 重试 |

三种 provider 共享同一套输出清洗规则（`SPARSE_VECTOR_TOP_K` / `SPARSE_VECTOR_MIN_WEIGHT`，由 `normalize_lexical_weights` 实施），保证不同 provider 产出的稀疏向量在召回侧表现一致。远程两种 provider 的 `/encode` 响应里 `sparse` 元素均为 BGE-M3 lexical weights，与本地推理 `output["lexical_weights"]` 同构，因此复用同一清洗函数。

`create_sparse_vector_service(encoder)` 是显式注入入口，主要用于测试或自定义编码器。

---

## 4. 数据模型

| 模型 | 说明 |
| --- | --- |
| `SparseVector` | 写入 Qdrant 的稀疏向量结构：`indices: list[int]` + `values: list[float]`。`__post_init__` 强校验：长度一致、非空、indices 唯一且非负、values 有限 |
| `SparseChunkVectorizationRequest` | 一个待稀疏向量化的 chunk：`chunk_id` / `content` / `doc_id` / `bucket_id` / `user_id` / `set_id` / `task_id` / `chunk_index` |
| `SparseChunkResult` | 单 chunk 处理结果：`indexed` / `nonzero_count` / `error_msg` |
| `SparseVectorizationResult` | 文档级或批量重试汇总：`total_chunks` / `indexed_chunks` / `failed_chunk_ids`，`is_success` 判断是否全部成功 |

---

## 5. 写入路径

### 5.1 `SparseVectorService`（pipeline.py）

对编排层暴露的稳定服务接口，封装编码器并记录 Qdrant named sparse vector 名（默认 `sparse_text`）：

- `vectorize_chunk(request)`：单 chunk 编码，校验返回数量为 1。
- `vectorize_texts(texts)`：批量编码，服务于文件级索引；空输入返回空列表，返回数量必须与输入一致，否则抛 `ValueError`（避免错位写入 Qdrant）。
- `vectorize_query(query)`：召回侧 query 编码。**写入与召回共用的唯一编码入口**，保证 query 与 chunk 走同一套 token 权重空间，sparse score 分布两侧一致。本方法不做 query 改写/清洗。

### 5.2 `SparseIndexingPipeline`（indexing.py）

解析主流水线的最后一段（对应 parse_task 的 `sparse_vectorizing` 阶段）。文件级 all-or-nothing 语义：

- 输入是 pipeline 已过滤的 `chunks` 列表 + `task_id` + `db`。调用方需保证：已剔除 `sparse_vector_status=SUCCESS` 的条目；每条 `dense_vector_status` 必须是 `SUCCESS`（稀疏向量追加在 dense point 上，本模块入口 fail-fast 兜底）；`bucket_id` 从首条取作权威并校验同批一致。
- 任一 chunk 失败 → 失败 chunk 标 `FAILED`，整体抛 `SparseIndexingError`，由上层转为 `sparse_vectorizing_status=FAILED` + `pipeline_status=FAILED` + 通知 Java。
- 空集短路：传入 chunks 为空 → 幂等 no-op SUCCESS。

> `SparseIndexingPipeline` / `SparseIndexingError` / `SparseRetriever` **不在 `__init__.py` 导出**，需直接 `from src.core.storage.vector.sparse_indexing import ...` / `from src.core.storage.vector.sparse_retriever import ...`，原因见 §7。

---

## 6. 召回路径：`SparseRetriever`（sparse_retriever.py）

实现召回 Pipeline 的 `Retriever` 协议（见 [recall_pipeline.md §4](recall_pipeline.md#4-retriever-协议)），`source = "sparse"`。它只做"形状翻译"，把协议方法适配到后端的 `search_sparse_chunks`：

```text
Retriever.recall(query, dataset_ids, doc_ids, *, user_id, top_k)
    ↓
backend.search_sparse_chunks(query, user_id, set_id, doc_id, top_k, score_threshold)
```

- 生产路径上 `backend` 由 `VectorStorageFacade` 提供；适配器用 `Protocol` 做最小契约，不 hard import facade（避免与 `vector_storage` 循环）。
- `user_id` / `top_k` 由 pipeline 执行期透传；`score_threshold` 非用户上下文，装配期注入。
- `dataset_ids` 为空 → 直接返空；底层 `set_id` 是单值，多 dataset 逐个下发、合并后按 score 降序截断。

---

## 7. 关于循环导入

`__init__.py` 刻意不导出 `SparseIndexingPipeline`、`SparseIndexingError`、`SparseRetriever`：

- `qdrant_vector_storage.models` 引用 `sparse_vector.models`，若 `__init__` 顶层导入 `indexing`（它 import `qdrant_vector_storage`）会形成循环。
- `vector_storage.facade` 依赖 `sparse_vector`，而 `sparse_retriever` 类型上又引用 facade 的 `search_sparse_chunks` 契约。

解决办法是：公共数据/编码能力从 `__init__` 导出，索引与召回适配器按需直接从子模块导入，把 import 行为限制在调用方代码里。

---

## 8. 配置项

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `SPARSE_VECTOR_ENABLED` | `True` | 是否启用稀疏向量 |
| `SPARSE_VECTOR_PROVIDER` | `bge_m3` | `bge_m3` / `bge_m3_http` / `remote_bge_m3` |
| `SPARSE_VECTOR_MODEL_NAME` | `BAAI/bge-m3` | HF 模型名或本地路径 |
| `SPARSE_VECTOR_MODEL_CACHE_DIR` / `SPARSE_VECTOR_LOCAL_FILES_ONLY` | — | 本地模型缓存与离线开关 |
| `SPARSE_VECTOR_DEVICE` | `auto` | 推理设备（auto/cpu/cuda…） |
| `SPARSE_VECTOR_BATCH_SIZE` / `SPARSE_VECTOR_MAX_LENGTH` | `12` / `8192` | 本地推理批大小与最大 token 长度 |
| `SPARSE_VECTOR_HTTP_ENDPOINT` / `SPARSE_VECTOR_HTTP_TIMEOUT` / `SPARSE_VECTOR_HTTP_BATCH_SIZE` | — | `bge_m3_http` provider 专用 |
| `BGE_M3_SERVICE_URL` / `BGE_M3_TIMEOUT_SECONDS` / `BGE_M3_MAX_RETRIES` | — / `30` / `3` | `remote_bge_m3` provider 专用 |
| `SPARSE_VECTOR_QDRANT_VECTOR_NAME` | `sparse_text` | Qdrant named sparse vector 名 |
| `SPARSE_VECTOR_TOP_K` / `SPARSE_VECTOR_MIN_WEIGHT` | `256` / `0.0` | 输出清洗：保留非零 token 数上限、低权重阈值 |
| `SPARSE_VECTOR_RETRY_LIMIT` / `SPARSE_VECTOR_INDEXING_STALE_SECONDS` | `3` / `900` | 索引重试上限、INDEXING 滞留判定 |

配置详解见 [ops/configure.md](../ops/configure.md)。

---

## 9. `deploy_bge_m3.py`

独立可执行脚本（`argparse` 入口），用于在目标机器上**部署并冒烟验证**本地 BGE-M3 模型：拉取/定位模型、按 `DeploymentConfig` 加载、对样例文本跑一次编码、报告耗时与非零维度。用于上线前确认本地 provider 可用，不参与运行时调用链。

---

## 10. 测试约定

| 测试目标 | 入口 |
| --- | --- |
| 编码器输出规整、协议 | `tests/unit/core/encoding/sparse/` |
| 召回适配器 | `tests/unit/core/storage/vector/test_sparse_retriever.py` |
| 真实模型推理（需显式开关） | `TOLINK_RUN_REAL_SPARSE_VECTOR_TESTS=True` |
