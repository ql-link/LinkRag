# 数据集配置参数参考

本文列出 `DatasetParseConfigBundle` 当前全部配置参数，共 5 类 27 项。

**权威源**：`src/core/dataset_config/models.py`。本文是对代码的人工整理，模型字段定义以代码为准。

**分层合并语义**：系统级 `Settings` 是 L1 fallback，数据集级 JSON 在其上覆盖。
增强配置是一个例外：数据集行中的 `enhancement_config={}` 明确表示所有增强关闭；非空增强
JSON 的缺失字段仍取运行期 `Settings` 值。数据集配置行不存在或读取失败时全部使用 Settings。

---

## 一、ChunkingConfig — 分块策略

**DB 列**：`chunking_config`（JSON，非空）  
**消费点**：`src/core/splitter/factory.py`，`src/core/splitter/pipeline_chunker.py`

| 字段 | 类型 | 默认值 | 约束 | 含义 |
|---|---|---|---|---|
| `heading_break_level` | `int` | `5` | — | 标题断层级；≤ 该级别的标题强制作为分块边界 |
| `min_candidate_chunk_tokens` | `int` | `128` | [128, 256] | Stage 1 候选分块 token 软下限 |
| `overlap_tokens` | `int` | `64` | [0, 64] | 相邻 chunk 的 neighbor overlap token 数 |
| `max_chunk_tokens` | `int` | `512` | [256, 2048]，须 ≥ `min_candidate_chunk_tokens` | 分块 token 目标上限 |
| `hard_max_tokens` | `int` | `1024` | [512, 8192]，须 ≥ `max_chunk_tokens` | 分块 token 硬上限，超出后由 Stage 2 再切 |
| `stage_two_algorithm` | `str` | `"noop"` | `{"noop", "semantic_depth_window"}` | Stage 2 分块算法；`semantic_depth_window` 对超长 chunk 按语义深度窗口递归细分 |
| `protected_neighbor_overlap` | `bool` | `False` | — | 含受保护元素（表格/代码块/公式）的 chunk 是否参与 neighbor overlap；默认跳过，防止代码/公式被截断 |

---

## 二、EnhancementConfig — Markdown 增强

**DB 列**：`enhancement_config`（JSON，非空）  
**消费点**：`src/core/markdown_parser/orchestrator.py`，`src/core/parse_task_service.py`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `enable_table_enhancement` | `bool` | `True` | 是否启用表格 LLM 增强，按用户默认 → LinkRag 系统默认预设解析 `CHAT` 模型 |
| `enable_image_enhancement` | `bool` | `True` | 是否启用图片 LLM 增强，按用户默认 → LinkRag 系统默认预设解析 `VISION` 模型 |
| `enable_heading_hierarchy` | `bool` | `False` | 是否启用 LLM 标题层级插入；对缺少标题结构的长文档，自动在段落前补充标题，辅助下游分块与召回定位 |

> 数据集行中的空对象 `{}` 会关闭上述三个开关，不使用表内静态默认。开启对应增强后，用户默认
> 和 LinkRag 系统默认预设均无对应能力模型时，解析任务失败（`ENHANCEMENT_MODEL_MISSING`）。

---

## 三、PDFConfig — PDF 解析

**DB 列**：`pdf_config`（JSON，非空）  
**消费点**：`src/core/pipeline/parse_task/stages/services.py:parse_file()`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `pdf_parser_backend` | `str \| None` | `None` | PDF 解析后端；`None` 降级到系统 `PDF_PARSER_BACKEND` 配置 |

---

## 四、RecallConfig — 召回检索

**DB 列**：`recall_config`（JSON，非空）  
**消费点**：`src/api/routes/rag.py`，`src/api/routes/recall.py`，`src/application/recall_pipeline_provider.py`

| 字段 | 类型 | 默认值 | 约束 | 含义 |
|---|---|---|---|---|
| `recall_result_limit` | `int` | `64` | > 0 | 融合候选池窗口大小，即传给 pipeline 的 `top_k` |
| `recall_context_token_budget` | `int` | `4000` | > 0 | 召回结果传入 LLM 时允许占用的 context token 上限 |
| `bm25_top_k` | `int` | `100` | > 0 | BM25 路执行期召回深度 |
| `sparse_top_k` | `int` | `50` | > 0 | 稀疏向量路执行期召回深度 |
| `sparse_score_threshold` | `float` | `0.0` | ≥ 0 | 稀疏路分数过滤阈值，低于此分的候选被丢弃 |
| `dense_top_k` | `int` | `100` | > 0 | 稠密向量路执行期召回深度 |
| `dense_score_threshold` | `float` | `0.0` | ≥ 0 | 稠密路分数过滤阈值，低于此分的候选被丢弃 |
| `recall_enabled_sources` | `list[str]` | `["bm25","sparse","dense"]` | 系统已装配路的子集 | 本数据集启用的召回路；空列表退回系统全部已装配路 |
| `recall_fusion_strategy` | `str` | `"rrf"` | `{"rrf", "weighted_score"}` | 多路融合算法；`rrf` 只按排名融合，不受各路分数量纲影响；`weighted_score` 按下方三项权重加权求和 |
| `rrf_k` | `int` | `60` | > 0 | RRF rank constant；仅 `recall_fusion_strategy="rrf"` 时用于 `1 / (rrf_k + rank)` |
| `fusion_bm25_weight` | `float` | `0.2` | ≥ 0，有限浮点 | `weighted_score` 模式下 BM25 路权重 |
| `fusion_sparse_weight` | `float` | `0.3` | ≥ 0，有限浮点 | `weighted_score` 模式下稀疏路权重 |
| `fusion_dense_weight` | `float` | `0.5` | ≥ 0，有限浮点 | `weighted_score` 模式下稠密路权重 |
| `rerank_top_n` | `int` | `8` | > 0 | 重排后返回的候选条数上限 |
| `recall_strict` | `bool` | `False` | — | `True` 时任一召回路失败即整体报错；`False` 时允许单路失败降级继续 |

> `weighted_score` 模式下，active source 对应权重之和为 0 时运行期拒绝（无意义的融合）。

---

## 五、VectorModelBindingConfig — 向量模型绑定

> 向量模型绑定不在本 PR 引入，已由数据集向量模型绑定特性落地（见 `dataset_parse_config` 的
> `dense_embedding_config_id` / `sparse_embedding_config_id` 两列与 `VectorModelBindingConfig`
> 模型）。此处仅列出读取入口，字段细节见 [mysql.md](../api/schemas/mysql.md) 与
> [vectorization.md](vectorization.md) / [sparse_vector.md](sparse_vector.md)。

**DB 列**：`dense_embedding_config_id` / `sparse_embedding_config_id`（BIGINT，**nullable**）  
**读取入口**：`DatasetConfigService.get_vector_model_binding(user_id, dataset_id, db)` 与
`get_config(...).vector_models`；消费点见写入/召回链路各 factory。`NULL` 表示存量数据集未指定，
降级到用户默认配置。

---

## 附：配置读取流程

```
dataset_parse_config 表
  └─ DatasetConfigService.get_config(user_id, dataset_id, db)
       ├─ 读行不存在 → DatasetParseConfigBundle.defaults()（全走 Settings L1）
       └─ 读行存在 → from_settings() 为基线，叠加各列 JSON 覆盖
            ├─ chunking_config   → ChunkingConfig
            ├─ enhancement_config → {} 时全关闭；非空时叠加 Settings
            ├─ pdf_config        → PDFConfig
            ├─ recall_config     → RecallConfig
            └─ dense/sparse_embedding_config_id → VectorModelBindingConfig（NULL 时降级用户默认）
```
