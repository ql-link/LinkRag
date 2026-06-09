# Chunking Module

本文说明 `src/core/splitter` 分片模块的目标架构、阶段契约、配置方式，以及新增或修改分片算法的方法。

## 1. 模块边界

splitter 的输入边界是 parse pipeline 已生成的结构化 Markdown 结果，例如 `ParseResult` 或 `MarkdownElement[]`。splitter 不负责 raw markdown 解析、数据库写入、MQ、向量库或 ES。

splitter 对后续流程的外部输出保持为：

```python
list[Chunk]
```

该输出继续由 parse task pipeline、`ChunkDraftFactory`、dense / sparse / ES 后续阶段消费。内部实现不再把 `list[Chunk]` 作为阶段算法之间的传递结构。

目标主链路：

```text
ParseResult / MarkdownElement[]
  -> InputAdapter
  -> SplitInput
  -> StageOneRouter
  -> StageOneAlgorithm
  -> CoarseChunkSet
  -> CoarseChunkSetValidator
  -> StageTwoRouter
  -> StageTwoAlgorithm
  -> FinalChunkSet
  -> ChunkExporter
  -> list[Chunk]
```

```mermaid
flowchart LR
    A["ParseResult / MarkdownElement[]"] --> B["InputAdapter"]
    B --> C["SplitInput"]
    C --> D["StageOneRouter"]
    D --> E["StageOneAlgorithm"]
    E --> F["CoarseChunkSet"]
    F --> G["CoarseChunkSetValidator"]
    G --> H["StageTwoRouter"]
    H --> I["StageTwoAlgorithm"]
    I --> J["FinalChunkSet"]
    J --> K["ChunkExporter"]
    K --> L["list[Chunk]"]
```

## 2. 核心角色

| 组件 | 职责 |
| --- | --- |
| `SplitInput` | splitter 内部输入模型，承接 `MarkdownElement[]`、`source_file` 与文档级 metadata |
| `StageOneRouter` | 按配置在文档级选择第一阶段算法；当前仅支持 `candidate_boundary` |
| `StageOneAlgorithm` | 第一阶段算法契约：`SplitInput -> CoarseChunkSet` |
| `CoarseChunkSetValidator` | 在第一阶段后立即校验必填字段、顺序、行号、来源关系和 protected ranges |
| `StageTwoRouter` | 按配置在文档级选择第二阶段算法；当前支持 `semantic_oversized` / `noop` |
| `StageTwoAlgorithm` | 第二阶段算法契约：`CoarseChunkSet -> FinalChunkSet` |
| `ChunkExporter` | 将 `FinalChunkSet` 导出为后续流程稳定消费的 `list[Chunk]` |
| `Chunk` | splitter 对外最终输出模型，包含 `content`、`start_line`、`end_line`、`metadata` |

`BaseChunker` / `base.py` 不再作为新架构核心抽象保留。旧规则分片器 `ASTAwareChunker` / `rule_chunker.py` 不再作为 fallback 保留。重构实现后，源码中不应保留 `ASTAwareChunker` 类定义、`rule_chunker.py` 文件、导出、import、实例化、factory fallback 或测试引用。

## 3. 配置

splitter 算法选择使用显式算法名，不再使用布尔开关：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `CHUNKING_STAGE_ONE_ALGORITHM` | `candidate_boundary` | 第一阶段算法名；当前仅支持 `candidate_boundary` |
| `CHUNKING_STAGE_TWO_ALGORITHM` | `semantic_oversized` | 第二阶段算法名；当前支持 `semantic_oversized` / `noop` |

约定：

- router 只做纯配置路由，不根据 token 数、文档类型、protected element 或初始化状态自动选择算法。
- 未知算法名直接失败，不做隐式 fallback。
- `CHUNKING_ENABLE_ADVANCED_PIPELINE` 已废弃并移除。
- 不需要第二阶段实际细分时，应显式配置 `CHUNKING_STAGE_TWO_ALGORITHM=noop`。
- 第二阶段算法初始化失败或运行失败时的处理策略属于具体算法内部设计，本模块不提供旧规则分片 fallback。

## 4. 阶段模型

### 4.1 SplitInput

```python
@dataclass
class SplitInput:
    elements: list[MarkdownElement]
    source_file: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

`InputAdapter` 可接收 `ParseResult` 或 `MarkdownElement[]`，但不重新解析 raw markdown。

### 4.2 CoarseChunkSet

`CoarseChunkSet` 是第一阶段输出，只供第二阶段消费，不是最终产物。

```python
@dataclass
class CoarseChunkSet:
    chunks: list[CoarseChunk]
    source_file: str | None = None
    strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 4.3 CoarseChunk

```python
@dataclass
class CoarseChunk:
    id: str
    content: str
    start_line: int
    end_line: int
    token_count: int
    source_element_indexes: list[int]
    element_types: list[str]
    protected_ranges: list[ProtectedRange]
    heading_trail: list[str]
    heading_trails: list[list[str]]
    role: str
    strategy: str
    source_coarse_chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

约束：

- `id` 是 splitter 单次运行内唯一、顺序确定的内部 ID，例如 `coarse_000001`。
- `role` 当前使用 `mixed` / `derived_element`。
- derived chunk 通过 `source_coarse_chunk_id` 指向其 source mixed coarse chunk。
- `source_element_indexes` 和 `protected_ranges` 是第一阶段给第二阶段使用的内部结构字段，不进入最终 `Chunk`。
- `strategy` 是第一阶段算法名；derived chunk 仍属于 `candidate_boundary` 的内部产物，不把 `derived_element` 写成算法名。

### 4.4 ProtectedRange

`ProtectedRange` 表达 mixed chunk 内第二阶段默认不得盲切的结构化元素，例如 table、image、code block、math block。

```python
@dataclass
class ProtectedRange:
    kind: str
    start_line: int
    end_line: int
    element_index: int
    reason: str = "protected_element"
    metadata: dict[str, Any] = field(default_factory=dict)
```

约定：

- 初版不包含 `content_start_offset` / `content_end_offset`。
- 如果未来引入需要在 `chunk.content` 字符串内绕开 protected element 精确切分的第二阶段算法，再扩展 offset 字段。
- `ProtectedRange` 只挂在 mixed/source chunk 上。
- derived chunk 不包含 `protected_ranges`，使用 `role`、`element_type`、`source_coarse_chunk_id` 表达身份和来源。

### 4.5 FinalChunkSet

`FinalChunkSet` 是第二阶段输出，语义上表示“已完成第二阶段处理，可以导出为最终 `Chunk`”。

```python
@dataclass
class FinalChunkSet:
    chunks: list[FinalChunk]
    source_file: str | None = None
    stage1_strategy: str = ""
    stage2_strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 4.6 FinalChunk

`FinalChunk` 只保留导出 `list[Chunk]` 与下游入库、向量化、索引需要的信息。对最终阶段无意义的内部辅助字段不继续保留。

```python
@dataclass
class FinalChunk:
    id: str
    content: str
    start_line: int
    end_line: int
    element_types: list[str]
    heading_trail: list[str]
    heading_trails: list[list[str]]
    role: str
    stage1_strategy: str
    stage2_strategy: str
    source_coarse_chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

不进入 `FinalChunk` 的字段包括：

- `source_element_indexes`
- `protected_ranges`
- 第一阶段 validator 专用信息
- 不会写入最终 `Chunk.metadata` 的 parser 结构细节

`id` 同样是运行内唯一、顺序确定的内部 ID，例如 `final_000001`。

## 5. 第一阶段算法

### 5.1 StageOneRouter

`StageOneRouter` 是文档级纯配置路由。当前只支持：

```env
CHUNKING_STAGE_ONE_ALGORITHM=candidate_boundary
```

未知算法名直接失败。

### 5.2 candidate_boundary

`candidate_boundary` 是当前唯一第一阶段算法，输入输出契约为：

```text
SplitInput -> CoarseChunkSet
```

行为保持现有算法语义：

- 忽略 front matter、水平分割线等噪声元素。
- 标题、段落、列表、引用、代码块、公式、表格、图片等块级结构都作为候选元素。
- 候选边界不等于硬 chunk 边界；`CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS` 是第一阶段软下限。
- 未达到 token 软下限时，按当前文档实际标题结构执行动态标题层级保护；参与判断的标题层级由 `CHUNKING_HEADING_BREAK_LEVEL` 控制，最多到 5 级。
- 6 级标题不参与动态标题层级保护。
- 纯标题 buffer 不会因为达到软下限而单独输出；文档尾部只有标题时会并入前一个 chunk，除非全文只有标题。
- 代码块、公式、表格、图片作为 protected element 参与 mixed chunk 聚合，不在元素内部截断。
- 图片、表格在保留 mixed chunk 原文位置连续性的同时生成 derived chunk，用于独立召回。
- 表格总是生成 table-derived chunk；短表格在 mixed chunk 中保留原始 Markdown 表格结构，长表格在 mixed chunk 中替换为稳定表格引用和表格摘要。
- 短表格判定为：表格 token 数 `<= 256`、表格所有非空行数 `<= 12`、最大列数 `<= 5`。这些阈值是 splitter 内部常量。

第一阶段输出必须覆盖所有可见输入元素，不得静默丢弃内容。缺字段、行号异常、range 越界、derived/source 关系不完整等问题应由 `CoarseChunkSetValidator` 失败暴露。

## 6. 第二阶段算法

### 6.1 StageTwoRouter

`StageTwoRouter` 是文档级纯配置路由。当前支持：

```env
CHUNKING_STAGE_TWO_ALGORITHM=semantic_oversized
CHUNKING_STAGE_TWO_ALGORITHM=noop
```

未知算法名直接失败。router 不根据 token 数或 protected element 自动选择算法。

### 6.2 noop

`noop` 表达“不做第二阶段实际细分”，但仍然产生 `FinalChunkSet`：

```text
CoarseChunkSet -> NoopStageTwoAlgorithm -> FinalChunkSet
```

这样所有链路统一经过第二阶段，不存在“绕过第二阶段直接导出”的分支。

### 6.3 semantic_oversized

`semantic_oversized` 是现有 oversized 语义细分能力的第二阶段算法封装。

行为边界：

- 输入完整 `CoarseChunkSet`，输出 `FinalChunkSet`。
- 只处理超过 `CHUNKING_MAX_CHUNK_TOKENS` 的候选粗 chunk。
- 纯文本 oversized chunk 复用 `PercentileSemanticChunker` 做语义细分。
- derived chunk 默认 pass-through。
- protected range 如何处理属于该算法内部规则；当前可保持保守策略，不在 protected element 内部盲切。
- 算法初始化或运行失败时的具体策略由该算法自身定义，不由 router 自动 fallback。

## 7. ChunkExporter

`ChunkExporter` 负责把 `FinalChunkSet` 导出为当前后续流程需要的 `list[Chunk]`。

最终 `Chunk.metadata` 至少保持：

- `chunk_index`
- `element_types`
- `chunk_role`
- `heading_trail`
- `heading_trails`，仅在存在跨标题路径信息时写入
- `split_strategy`
- `source_file`，如果输入存在

derived chunk 还应写入：

- `element_type`
- `element_id`
- `image_id` 或 `table_id`
- `source_chunk_index`
- 表格统计字段，例如 `table_inline_in_source`、`table_row_count`、`table_col_count`、`table_token_count`

`split_strategy` 使用阶段算法拼接字符串：

```text
<stage1_algorithm> + <stage2_algorithm>
```

示例：

```text
candidate_boundary + noop
candidate_boundary + semantic_oversized
```

`derived_element` 是 `candidate_boundary` 第一阶段内部产物，不写入 `split_strategy`；derived 身份通过 `chunk_role="derived_element"` 表达。

## 8. Overlap

`ChunkOverlapper` 负责相邻最终 chunk 的上下文 overlap，不参与语义断点计算。

配置：

- `CHUNKING_OVERLAP_TOKENS`：追加的 token 数上限，范围 `0..64`；`0` 表示关闭 overlap。

图片/表格 derived chunk 的相邻上下文也复用 `ChunkOverlapper` 的 token 截取能力：取异构元素前一个可见元素尾部 N tokens 与后一个可见元素头部 N tokens，N 同样由 `CHUNKING_OVERLAP_TOKENS` 控制。

最终相邻 chunk overlap 应只在适合追加上下文的 chunk 间执行，避免 derived chunk 或含 protected element 的片段通过 overlap 泄漏到其他 chunk。具体判断可以在第二阶段算法或导出后处理内实现，但不得影响阶段契约。

## 9. 使用方式

解析 Pipeline 的 `ChunkingStage` 通过 `StageServices.run_chunking()` 获取最终 `list[Chunk]`：

```python
chunks = await services.run_chunking(
    markdown=markdown,
    source_file=md_object_key,
    parse_result=parse_result,
)
```

如果已有 `ParseResult`，`ChunkingEngine` 应直接消费该结构化结果；如果没有，则先调用 `MarkdownParser.parse()`。无论入口如何，最终对 parse pipeline 输出仍为 `list[Chunk]`。

`ChunkingStage` 获得 `list[Chunk]` 后，会把分片转换为 chunk 真值草稿，并通过 `ChunkRepository.bulk_insert_pending()` 单事务写入 MySQL。写入成功后才标记文件级 `chunking_status=SUCCESS`；写入失败会回滚整批 chunk 真值并终止流水线。

## 10. 新增算法接入

新增第一阶段算法时：

- 实现 `StageOneAlgorithm`，接收 `SplitInput`，返回 `CoarseChunkSet`。
- 在第一阶段 registry / router 中注册算法名。
- 直接产出完整 `CoarseChunk` 字段，不依赖第二阶段补救。
- 输出覆盖所有可见输入元素，顺序稳定，line range 合法。
- 对 table / image / code block / math block 生成 `ProtectedRange`。
- 不直接写数据库、MQ、向量库或 ES。
- 补充第一阶段契约测试。

新增第二阶段算法时：

- 实现 `StageTwoAlgorithm`，接收完整 `CoarseChunkSet`，返回 `FinalChunkSet`。
- 在第二阶段 registry / router 中注册算法名。
- 不从 `content` 重新猜测 protected element，优先消费 `protected_ranges`。
- 若改变 chunk 数量或顺序，必须保证输出可被 `ChunkExporter` 稳定导出。
- 支持空 `CoarseChunkSet`。
- 明确 derived chunk 的 pass-through 或映射策略。
- 不直接写数据库、MQ、向量库或 ES。
- 补充第二阶段算法测试和 exporter 回归测试。

## 11. 修改已有能力

修改 `candidate_boundary` 时关注：

- `CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS` 是否仍只作为第一阶段软下限。
- 动态标题保护是否仍只考虑 `CHUNKING_HEADING_BREAK_LEVEL` 内且不超过 5 级的标题。
- protected element 是否保持完整，不在元素内部截断。
- mixed chunk 与 derived chunk 的关系是否通过内部稳定 ID 表达。
- `heading_trail` 与 `heading_trails` 是否能表达跨小节粗 chunk。
- `CoarseChunkSet` 是否能通过 validator。

修改第二阶段算法时关注：

- router 是否仍只按配置选择算法。
- `noop` 是否保持等价通过语义。
- `semantic_oversized` 是否只处理自身算法定义范围内的 oversized chunk。
- 最终 `FinalChunkSet` 是否只保留下游有意义的信息。
- `ChunkExporter` 是否继续生成连续 `chunk_index` 和正确的 `source_chunk_index`。

## 12. 测试建议

常用测试范围：

```bash
.venv/bin/pytest tests/unit/core/splitter -q
.venv/bin/pytest tests/unit/core/pipeline/test_parse_task_pipeline.py -q
```

建议覆盖：

- `InputAdapter` 对 `ParseResult` / `MarkdownElement[]` 的适配。
- `StageOneRouter` / `StageTwoRouter` 的纯配置路由和未知算法失败。
- `candidate_boundary` 输出 `CoarseChunkSet` 的普通文本、多标题、derived chunk、protected range。
- `CoarseChunkSetValidator` 对缺字段、非法行号、重复 ID、derived/source 关系异常的失败。
- `noop` 第二阶段输出 `FinalChunkSet`。
- `semantic_oversized` 保持现有 oversized 细分语义。
- `ChunkExporter` 生成 `chunk_index`、`source_chunk_index`、`split_strategy`、`heading_trail` / `heading_trails`。
- parse pipeline 仍拿到最终 `list[Chunk]` 并可批量落库。
