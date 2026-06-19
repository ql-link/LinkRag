# 稀疏向量模块

本文说明 `src/core/encoding/sparse/`：稀疏向量的编码与索引模块。它在**写入侧**把 chunk 原文编码成稀疏向量写进 Qdrant，在**召回侧**把用户 query 编码后做稀疏检索。dense 向量编排见 [vectorization.md](vectorization.md)，Qdrant 存储结构见 [schemas/qdrant.md](../api/schemas/qdrant.md)，召回编排见 [recall_pipeline.md](recall_pipeline.md)。

> 编码模型按**发起用户的默认 SPARSE_EMBEDDING 配置**经统一 `(protocol, capability)` adapter 解析（必配、不保留系统级兜底）。历史上由 `.env` 的 `SPARSE_VECTOR_PROVIDER` 在本地 / HTTP / 远程 BGE-M3 间切换的整套机制已移除，相关 provider 实现与配置项参见 §3 与 §8。

---

## 1. 职责边界

稀疏向量是 lexical weights（token_id → 权重），与 dense 向量互补：dense 擅长语义相似，sparse 擅长关键词/术语精确匹配。本模块只负责：

1. 文本 → 稀疏向量的编码（按用户配置经统一 adapter 解析 provider）。
2. 输出规整（截断 top_k、过滤低权重、唯一化、有限性校验）。
3. 文件级稀疏索引阶段编排（写入 Qdrant、推进 chunk 状态）。
4. 召回侧 query 编码与 Retriever 适配。

它明确不做：dense 编码、Qdrant collection/point 结构定义（结构见 [schemas/qdrant.md](../api/schemas/qdrant.md)）、query 改写/清洗、跨路融合（属于召回 Pipeline）。

与 LLM 配置能力的关系：稀疏编码模型不再走系统级 `.env`，而是按发起用户的默认 `SPARSE_EMBEDDING` 配置解析——经 `user_model_resolver.aresolve_user_model` 按 `(protocol, capability)` 做 adapter 门禁，产出统一的 `SparseEmbeddingResult`，再转成本模块的 `SparseVector`。写入与召回共用同一份解析配置，保证两侧落在同一 token 权重空间、sparse score 可比。**这是必配项**：用户没有默认 `SPARSE_EMBEDDING` 配置即抛 `SparseEmbeddingConfigMissingError`，不再有进程级兜底。

---

## 2. 包结构

```text
src/core/encoding/sparse/
├── __init__.py          # 公共入口（见 §7 关于循环导入的取舍）
├── constants.py         # 默认向量名、状态常量
├── models.py            # SparseVector / SparseChunkVectorizationRequest / *Result
├── exceptions.py        # SparseVectorError 异常族
├── encoder.py           # SparseVectorEncoderProtocol + normalize_lexical_weights 清洗工具
├── adapter_encoder.py   # AdapterSparseVectorEncoder：llm adapter 输出 → SparseVector 的唯一桥接点
├── factory.py           # 按用户配置解析 provider 装配 SparseVectorService
├── pipeline.py          # SparseVectorService：对编排层暴露的稳定服务接口
└── deploy_bge_m3.py     # 本地模型部署与冒烟脚本
```

> 索引侧 `sparse_indexing.py`（SparseIndexingPipeline）与召回适配器 `sparse_retriever.py` 位于 `src/core/storage/vector/`。

---

## 3. 编码器抽象与 per-user adapter 解析

编码器实现同一个 `SparseVectorEncoderProtocol`（定义在 `encoder.py`）：

```python
class SparseVectorEncoderProtocol(Protocol):
    async def aencode(self, texts: Sequence[str]) -> list[SparseVector]: ...
    @property
    def model_name(self) -> str: ...
```

`aencode` 的契约：返回列表与输入 `texts` **等长同序**；推理失败抛 `SparseVectorEncodingError`，输出非法抛 `SparseVectorOutputError`。上层 `SparseVectorService` 信任这个契约，编码器只管"文本进、稀疏向量出"，不碰 MySQL/Qdrant 状态。

运行时**唯一**的装配入口是 `factory.py::aresolve_user_sparse_vector_service(user_id)`：

```text
aresolve_user_sparse_vector_service(user_id)
    ↓ 读发起用户的默认 SPARSE_EMBEDDING 配置
aresolve_user_model(user_id, capability="SPARSE_EMBEDDING")   # (protocol, capability) 门禁
    ↓ 解析出 provider（必配，无配置抛 SparseEmbeddingConfigMissingError）
AdapterSparseVectorEncoder(provider, top_k=…, min_weight=…)
    ↓
SparseVectorService(encoder, vector_name=SPARSE_VECTOR_QDRANT_VECTOR_NAME)
```

- `AdapterSparseVectorEncoder`（`adapter_encoder.py`）是 llm 层与 encoding 层之间**唯一**的桥接点：llm 层（provider / adapter）只懂 protocol 与 HTTP、不认识 `SparseVector`；encoding 层只认识 `SparseVector`、不关心走哪个厂商。它调 `provider.embed_sparse` 拿到中性的 `SparseEmbeddingResult`，再用 `normalize_lexical_weights` 做 `top_k` / `min_weight` 清洗、升序排序、空向量报错，转成 `SparseVector`。
- 清洗参数 `top_k` / `min_weight` 与命名 `vector_name` 仍取全局 `SPARSE_VECTOR_*`（见 §8），各 provider 复用同一套规则，保证不同用户、不同 provider 产出的稀疏向量在召回侧表现一致。
- **写入与召回共用本入口**，保证「同一用户写入 / 召回走同一份解析配置」——token 权重空间一致，召回打分才可比。
- 配置缺失（用户无默认 `SPARSE_EMBEDDING`）抛 `SparseEmbeddingConfigMissingError`；配置读取本身失败（Redis/DB 异常）按原异常向上传播，便于上层区分「未配置」与「读取失败(可重试)」。

`create_sparse_vector_service(encoder)` 是显式注入入口，仅用于测试或自定义编码器。

> bge-m3 后续会以 **adapter provider** 形式重新接入：llm 层已有对接独立 `bge-m3-service` 的 `BgeM3ServiceProvider`（protocol=`bge_m3`），后续会在 DB 登记为可选模型走 per-user 解析。这部分是另开 issue 的未来工作，详见对应 issue，不要视为当前可用的系统配置。

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

编码模型不再由系统级配置项指定，而是按用户默认 `SPARSE_EMBEDDING` 配置经 adapter 解析（见 §3）。保留的配置项都是与具体 provider 无关的全局开关与清洗 / 命名规则：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `SPARSE_VECTOR_ENABLED` | `True` | 稀疏向量总开关；关闭后保持旧 dense-only 语义 |
| `SPARSE_VECTOR_QDRANT_VECTOR_NAME` | `sparse_text` | Qdrant named sparse vector 名，写入与召回共用 |
| `SPARSE_VECTOR_TOP_K` / `SPARSE_VECTOR_MIN_WEIGHT` | `256` / `0.0` | 全局输出清洗：保留非零 token 数上限、低权重阈值；各 provider 复用，保证召回侧表现一致 |
| `SPARSE_VECTOR_BATCH_SIZE` | `32` | 稀疏索引**外层批大小**（一次从 DB 取多少 chunk 原文喂给编码器）；编码器内部批大小由 provider 自行决定，不随之变化 |

> 已移除：`SPARSE_VECTOR_PROVIDER` 切换机制及其相关的 `SPARSE_VECTOR_MODEL_NAME` / `SPARSE_VECTOR_MODEL_CACHE_DIR` / `SPARSE_VECTOR_LOCAL_FILES_ONLY` / `SPARSE_VECTOR_DEVICE` / `SPARSE_VECTOR_MAX_LENGTH`、`SPARSE_VECTOR_HTTP_*`、`BGE_M3_SERVICE_URL` / `BGE_M3_TIMEOUT_SECONDS` / `BGE_M3_MAX_RETRIES`、`SPARSE_VECTOR_RETRY_LIMIT` / `SPARSE_VECTOR_INDEXING_STALE_SECONDS` 等。

配置详解见 [ops/configure.md](../ops/configure.md)。

---

## 9. `deploy_bge_m3.py`

独立可执行脚本（`argparse` 入口），用于在目标机器上**部署并冒烟验证**本地 BGE-M3 模型：拉取/定位模型、按 `DeploymentConfig` 加载、对样例文本跑一次编码、报告耗时与非零维度。它是离线运维 / 冒烟工具，不参与运行时调用链（运行时编码走 per-user adapter 解析，见 §3）。

---

## 10. 测试约定

| 测试目标 | 入口 |
| --- | --- |
| 编码器输出规整、清洗、协议 | `tests/unit/core/encoding/sparse/` |
| adapter 桥接（`AdapterSparseVectorEncoder`） | `tests/unit/core/encoding/sparse/` |
| 召回适配器 | `tests/unit/core/storage/vector/test_sparse_retriever.py` |
