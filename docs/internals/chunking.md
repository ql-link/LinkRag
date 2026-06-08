# Chunking Module

本文说明 `src/core/splitter` 分片模块的架构、使用方式，以及新增或修改分片策略的方法。

## 1. 模块框架

```text
src/core/splitter/
├── base.py                 # 分片器抽象接口
├── models.py               # Chunk、EmbeddedChunk、统计模型
├── chunking_engine.py      # Markdown 解析与分片编排入口
├── rule_chunker.py         # 基于 Markdown AST 的规则分片
├── candidate_boundary_chunker.py # 基于候选结构边界的粗分片
├── element_derived_chunker.py     # 图片/表格 derived chunk 构造与标题路径追踪
├── oversized_chunk_refiner.py    # oversized 粗 chunk 二次细分
├── semantic_chunker.py     # 基于 embedding 距离的语义细分
├── overlap.py              # chunk overlap 配置与上下文拼接
├── pipeline_chunker.py     # 候选边界粗分片 + oversized 细分编排
└── embedding_pipeline.py   # Chunk 向量化批处理管线
```

上游调用链：

```text
ParseTaskPipeline
  -> _chunk_markdown()
    -> ChunkingEngine
      -> MarkdownParser
      -> BaseChunker
  -> _persist_chunk_facts()
    -> ChunkDraftFactory
    -> ChunkRepository.bulk_insert_pending()
```

解析任务流水线通过配置构建分片器。`CHUNKING_ENABLE_ADVANCED_PIPELINE=true` 时优先使用
`StructuredSemanticChunker`，初始化失败时回退到 `ASTAwareChunker`：

```text
ChunkingEngine(chunker=StructuredSemanticChunker(...))
```

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `Chunk` | `models.py` | 分片输出基础模型，包含内容、行号、metadata |
| `BaseChunker` | `base.py` | 所有分片策略的统一接口 |
| `ChunkingEngine` | `chunking_engine.py` | 连接 `MarkdownParser` 和具体 chunker |
| `ASTAwareChunker` | `rule_chunker.py` | 按标题、表格、图片、代码块等结构规则分片 |
| `CandidateBoundaryChunker` | `candidate_boundary_chunker.py` | 第一阶段结构候选边界粗分片，避免短小节被过度切碎 |
| `HeadingTrailTracker` / `DerivedElementChunkBuilder` | `element_derived_chunker.py` | 复用标题路径规则，并为图片、表格生成 derived chunk |
| `OversizedChunkRefiner` | `oversized_chunk_refiner.py` | 第二阶段只处理超过最大 token 上限的粗 chunk |
| `PercentileSemanticChunker` | `semantic_chunker.py` | 对超长文本执行语义断点切分 |
| `StructuredSemanticChunker` | `pipeline_chunker.py` | 串联候选边界粗分片、oversized 细分和相邻上下文 overlap |
| `ChunkEmbeddingPipeline` | `embedding_pipeline.py` | 对最终 Chunk 做批量 embedding |

通用分片器接口：

```python
class BaseChunker(ABC):
    def chunk(self, elements: list[MarkdownElement], **kwargs) -> list[Chunk]:
        ...
```

约定：

- 输入是 `MarkdownParser` 输出的 `MarkdownElement` 列表。
- 输出是按文档顺序排列的 `Chunk` 列表。
- `Chunk.metadata` 应携带 `chunk_index`、`element_types` 等下游可用信息。
- `StructuredSemanticChunker` 会在第一阶段输出进入 oversized refine 前校验行号范围、`chunk_index`、`element_types` 和 derived chunk 的 `source_chunk_index`，避免不完整算法输出继续进入第二阶段。
- 分片器不负责写数据库、调用 MQ 或写向量库。
- 解析流水线的 chunking 阶段会在分片完成后批量写入 `kb_document_chunk` 真值记录；这是编排层职责，不属于分片器职责。

## 3. 当前分片策略

### 3.1 ASTAwareChunker

`ASTAwareChunker` 是当前解析流水线默认分片器。

行为：

- 忽略 front matter、水平分割线等噪声元素。
- `h1` 到 `h3` 标题触发结构边界。
- 代码块、数学块、表格、图片作为独立 Chunk。
- 普通段落按标题上下文聚合。
- 输出 metadata 包含：
  - `element_types`
  - `chunk_index`
  - `heading_trail`

### 3.2 PercentileSemanticChunker

`PercentileSemanticChunker` 用于超长文本语义细分。

核心思路：

- 先按 `semantic_unit` 配置把文本拆成语义比较原子；默认 `sentence` 保持原有段落、行、句子逐级降级行为，`paragraph` 则以段落作为相似度计算单位。
- 调用 embedding 模型计算相邻原子的语义距离。
- 使用距离分位数作为动态阈值寻找断点。
- 受 `min_chunk_tokens`、`max_chunk_tokens` 控制；overlap 由独立配置控制，但仍在原切分位置追加，保证算法流程不变。

`paragraph` 模式只改变相似度计算粒度：单个段落超过 `max_chunk_tokens` 时，不会再改用句子级 embedding 计算断点，但最终输出仍会做长度保底拆分，避免生成超长 Chunk。

它通常不直接作为主分片器使用，而是被 `StructuredSemanticChunker` 注入。

### 3.3 CandidateBoundaryChunker

`CandidateBoundaryChunker` 用于 `StructuredSemanticChunker` 的第一阶段粗分片。

行为：

- 忽略 front matter、水平分割线等噪声元素。
- 标题、段落、列表、引用、代码块、公式、表格、图片等块级结构都作为候选元素。
- 候选边界不等于硬 chunk 边界；只有当前 buffer 达到 `CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS` 后，才在下一个 heading 边界处切分，优先保证多数 chunk 从标题结构开始，并避免同一标题下的正文被普通段落边界拆开。生产配置范围为 `128..256`，它是第一阶段软下限，不是最终 chunk 的绝对最小值。
- 未达到 token 软下限时，会按当前文档实际标题结构执行动态标题层级保护：参与判断的标题层级由 `CHUNKING_HEADING_BREAK_LEVEL` 控制，最多到 5 级；同级或回到上级标题默认提前切分，但当前文档最深叶子标题之间允许继续合并。
- 6 级标题不参与动态标题层级保护，也不会作为文档最深标题层级参与判断。
- 纯标题 buffer 不会因为达到软下限而单独输出；文档尾部只有标题时会并入前一个 chunk，除非全文只有标题。
- 代码块、公式、表格、图片作为 protected element 参与粗 chunk 聚合，不在元素内部截断。
- 图片、表格会在保留 mixed chunk 原文位置连续性的同时生成 derived chunk，用于独立召回。
- 图片在 mixed chunk 中替换为稳定图片引用和视觉说明；derived chunk 保留图片说明、标题路径、相邻上下文和原始引用。
- 表格总是生成 table-derived chunk；短表格在 mixed chunk 中保留原始 Markdown 表格结构，长表格在 mixed chunk 中替换为稳定表格引用和表格摘要。
- 短表格判定为：表格 token 数 `<= 256`、表格所有非空行数 `<= 12`、最大列数 `<= 5`。这些阈值是 splitter 模块内部常量，不作为运维配置暴露；行数包含表头、分隔行和数据行。
- 第一阶段允许输出超过 `CHUNKING_MAX_CHUNK_TOKENS` 的粗 chunk，是否二次细分由第二阶段判断。

输出 metadata 包含：

- `element_types`
- `chunk_index`
- `heading_trail`
- `heading_trails`（当一个粗 chunk 横跨多个标题路径时记录完整路径集合）
- `split_strategy="candidate_boundary"`
- `coarse_token_count`
- `protected_element_types`（仅当 chunk 内包含 protected element 时出现）
- `chunk_role="mixed"`（第一阶段 source chunk）
- `derived_element_ids`（仅当 source chunk 产生图片或表格 derived chunk 时出现）

derived chunk 额外包含：

- `chunk_role="derived_element"`
- `split_strategy="derived_element"`
- `element_type`（`image` / `table`）
- `element_id`，以及对应的 `image_id` 或 `table_id`
- `source_chunk_index`（指向最终输出中的 source mixed chunk）
- `heading_trail`
- 表格 derived chunk 会记录 `table_inline_in_source`、`table_row_count`、`table_col_count`、`table_token_count`

derived chunk 不使用 parent/child chunk 关系，不改向量库 schema；它作为普通最终 chunk 进入后续 embedding 与索引流程。

### 3.4 OversizedChunkRefiner

`OversizedChunkRefiner` 是 `StructuredSemanticChunker` 的第二阶段。

行为：

- 只处理 token 数超过 `CHUNKING_MAX_CHUNK_TOKENS` 的粗 chunk。
- 未超长 chunk 原样保留。
- 纯文本 oversized chunk 复用 `PercentileSemanticChunker.split()` 做语义细分。
- 含代码块、公式、表格、图片的 oversized chunk 本期保守保留，不在 protected element 内部截断；第二阶段不额外写入跳过状态 metadata。

### 3.5 ChunkOverlapper

`ChunkOverlapper` 负责相邻 Chunk 的上下文 overlap，不参与语义断点计算。

配置：

- `CHUNKING_OVERLAP_TOKENS`：追加的 token 数上限，范围 `0..64`；`0` 表示关闭 overlap。

`CHUNKING_OVERLAP_TOKENS=0` 时，不追加 overlap。默认 `64` 保持现有分片行为。

图片/表格 derived chunk 的 `相邻上下文` 也复用 `ChunkOverlapper` 的 token 截取能力：取异构元素前一个可见元素尾部 N tokens 与后一个可见元素头部 N tokens，N 同样由 `CHUNKING_OVERLAP_TOKENS` 决定。`CHUNKING_OVERLAP_TOKENS=0` 时 derived chunk 仍会生成，但不写入相邻上下文。最终相邻 Chunk overlap 只在非 derived、且不含 protected element 的 chunk 之间追加，避免表格、代码块、公式块或图片引用片段通过 overlap 泄漏到其他 chunk。

### 3.6 StructuredSemanticChunker

`StructuredSemanticChunker` 是两阶段分片器：

```text
MarkdownElement[]
  -> 候选边界粗分片
  -> oversized Chunk 语义细分
  -> 邻接上下文 overlap
  -> Chunk[]
```

适用于既要减少短结构化 Markdown 过度切分，又要控制长正文 chunk 尺寸的场景。

## 4. 使用方式

### 4.1 解析流水线中的使用

解析 Pipeline 的 `ChunkingStage` 会通过 `StageServices.run_chunking()` 优先使用上游已经生成的 `ParseResult`：

```python
chunks = await services.run_chunking(
    markdown=markdown,
    source_file=md_object_key,
    parse_result=parse_result,
)
```

如果没有 `parse_result`，`ChunkingEngine` 会先调用 `MarkdownParser.parse()` 再分片。

`ChunkingStage` 在获得 `list[Chunk]` 后，会把分片转换为 chunk 真值草稿，并在同一 chunking 阶段通过 `ChunkRepository.bulk_insert_pending()` 单事务写入 MySQL。写入成功后才标记文件级 `chunking_status=SUCCESS`；写入失败会回滚整批 chunk 真值并终止流水线，不进入 vectorizing。

### 4.2 直接使用 ChunkingEngine

```python
from src.core.markdown_parser import MarkdownParser
from src.core.splitter import ChunkingEngine
from src.core.splitter.rule_chunker import ASTAwareChunker

engine = ChunkingEngine(chunker=ASTAwareChunker(), parser=MarkdownParser())
chunks = engine.process(markdown, source_file="example.md")
```

### 4.3 直接消费 ParseResult

```python
chunks = engine.process_parse_result(parse_result)
```

该方式会跳过 Markdown 重新解析，适合解析服务已经产出结构化结果的场景。

## 5. 新增分片策略

新增策略时：

1. 在 `src/core/splitter/` 下新增 chunker 文件。
2. 继承 `BaseChunker`。
3. 实现 `chunk(elements, **kwargs) -> list[Chunk]`。
4. 必要时实现 `achunk`。
5. 补充单元测试。

示例：

```python
from src.core.markdown_parser import MarkdownElement
from src.core.splitter.base import BaseChunker
from src.core.splitter.models import Chunk


class SimpleChunker(BaseChunker):
    def chunk(self, elements: list[MarkdownElement], **kwargs) -> list[Chunk]:
        chunks = []
        for index, element in enumerate(elements):
            chunks.append(
                Chunk(
                    content=element.content,
                    start_line=element.start_line,
                    end_line=element.end_line,
                    metadata={
                        "chunk_index": index,
                        "element_types": [element.type.value],
                    },
                )
            )
        return chunks
```

接入方式：

```python
engine = ChunkingEngine(chunker=SimpleChunker())
chunks = engine.process(markdown)
```

如果要替换解析流水线默认策略，需要修改 `ParseTaskPipeline._build_chunk_processor()`。

## 6. 修改已有分片器

修改 `ASTAwareChunker` 时关注：

- 标题边界是否仍然稳定。
- 表格、图片、代码块是否仍保持独立。
- `heading_trail`、`chunk_index` 是否仍正确。

修改 `CandidateBoundaryChunker` 时关注：

- `CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS` 是否只作为第一阶段软下限。
- 标题、段落、列表和 protected element 是否只作为候选边界。
- 动态标题保护是否只考虑 `CHUNKING_HEADING_BREAK_LEVEL` 内且不超过 5 级的标题。
- protected element 是否保持完整，不在元素内部截断。
- `heading_trail` 与 `heading_trails` 是否能表达跨小节粗 chunk。
- 第一阶段输出是否能通过 `StructuredSemanticChunker` 的完整性校验。

修改 `OversizedChunkRefiner` 时关注：

- 第二阶段是否只处理超过 `CHUNKING_MAX_CHUNK_TOKENS` 的粗 chunk。
- 含 protected element 的 oversized chunk 是否按保守策略跳过内部截断。
- 语义细分后 `chunk_index` 是否连续。

修改语义分片时关注：

- token 上下限是否合理。
- overlap 是否按 `CHUNKING_OVERLAP_TOKENS` 生效，且没有造成内容膨胀。
- embedding 调用是否批量且可测试。
- 语义断点失败时是否有 fallback。

## 7. 测试建议

常用测试范围：

```bash
.venv/bin/pytest tests/unit/core/splitter -q
.venv/bin/pytest tests/unit/core/pipeline/test_parse_task_pipeline.py -q
```

建议覆盖：

- 标题边界分片。
- 候选边界达到软下限前的短小节合并。
- 表格、图片、代码块、公式作为 protected element 参与粗 chunk。
- `source_file` 元数据注入。
- chunking 阶段成功后批量落库 chunk 真值，失败时整批回滚。
- 超长文本语义细分。
- 空文档或纯噪声文档。
