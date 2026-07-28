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
| `enable_table_enhancement` | `bool` | `True` | 是否启用表格 LLM 增强；开启时要求 `enhancement_chat_config_id` |
| `enable_image_enhancement` | `bool` | `True` | 是否启用图片 LLM 增强；开启时要求 `enhancement_vision_config_id` |
| `enable_heading_hierarchy` | `bool` | `False` | 是否启用 LLM 标题层级插入；门禁命中时复用 `enhancement_chat_config_id` |

> 数据集行中的空对象 `{}` 会关闭上述三个开关，不使用表内静态默认。开启表格/图片增强后，
> 用户默认和 LinkRag 系统默认预设均无对应能力模型时归 `ENHANCEMENT_MODEL_MISSING`；标题层级
> 增强门禁命中但两层均无 `CHAT` 时归 `LLM_CONFIG_MISSING`。

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
| `fusion_bm25_weight` | `float` | `0.2` | ≥ 0，有限浮点 | 固定 weighted score 融合的 BM25 路权重 |
| `fusion_sparse_weight` | `float` | `0.3` | ≥ 0，有限浮点 | 固定 weighted score 融合的稀疏路权重 |
| `fusion_dense_weight` | `float` | `0.5` | ≥ 0，有限浮点 | 固定 weighted score 融合的稠密路权重 |
| `rerank_top_n` | `int` | `8` | > 0 | 重排后返回的候选条数上限 |
| `recall_strict` | `bool` | `False` | — | `True` 时任一召回路失败即整体报错；`False` 时允许单路失败降级继续 |

> active source 对应权重之和为 0 时运行期拒绝（无意义的融合）。历史 JSON 中的旧融合策略字段读取时忽略，下一次保存后自然清除。

---

## 五、LLMModelBindingConfig — 五用途模型绑定

**DB 列**：`dense_embedding_config_id` / `sparse_embedding_config_id` /
`enhancement_chat_config_id` / `enhancement_vision_config_id` / `rerank_config_id`（均为全局 `llm_model_config.id`）。

`DatasetExecutionContextBuilder` 在解析的任何 stage 或召回的任何 retriever 之前一次性解析所需绑定：

- dense/sparse 始终必需；
- CHAT/VISION 只在对应增强开启时必需；
- RERANK 只在 `enable_rerank=true` 时必需。

必需字段为 `NULL`、配置停用/越权/能力错误都明确失败；不降级到用户或平台默认。整次执行复用同一 snapshot。

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
            └─ 五个 config_id → DatasetExecutionContext（按开关校验必需，无默认兜底）
```
