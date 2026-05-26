# Chunking Module

本文说明 `src/core/splitter` 分片模块的架构、使用方式，以及新增或修改分片策略的方法。

## 1. 模块框架

```text
src/core/splitter/
├── base.py                 # 分片器抽象接口
├── models.py               # Chunk、EmbeddedChunk、统计模型
├── chunking_engine.py      # Markdown 解析与分片编排入口
├── rule_chunker.py         # 基于 Markdown AST 的规则分片
├── semantic_chunker.py     # 基于 embedding 距离的语义细分
├── pipeline_chunker.py     # 结构分片 + 语义细分两阶段分片器
└── embedding_pipeline.py   # Chunk 向量化批处理管线
```

上游调用链：

```text
ParseTaskPipeline
  -> _chunk_markdown()
    -> ChunkingEngine
      -> MarkdownParser
      -> BaseChunker
```

当前解析任务流水线默认构建：

```text
ChunkingEngine(chunker=ASTAwareChunker())
```

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `Chunk` | `models.py` | 分片输出基础模型，包含内容、行号、metadata |
| `BaseChunker` | `base.py` | 所有分片策略的统一接口 |
| `ChunkingEngine` | `chunking_engine.py` | 连接 `MarkdownParser` 和具体 chunker |
| `ASTAwareChunker` | `rule_chunker.py` | 按标题、表格、图片、代码块等结构规则分片 |
| `PercentileSemanticChunker` | `semantic_chunker.py` | 对超长文本执行语义断点切分 |
| `StructuredSemanticChunker` | `pipeline_chunker.py` | 先结构切分，再对超长块做语义细分 |
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
- 分片器不负责写数据库、调用 MQ 或写向量库。

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

- 先把文本拆成段落、行或句子级原子单元。
- 调用 embedding 模型计算相邻原子的语义距离。
- 使用距离分位数作为动态阈值寻找断点。
- 受 `min_chunk_tokens`、`max_chunk_tokens`、`overlap_tokens` 控制。

它通常不直接作为主分片器使用，而是被 `StructuredSemanticChunker` 注入。

### 3.3 StructuredSemanticChunker

`StructuredSemanticChunker` 是两阶段分片器：

```text
MarkdownElement[]
  -> 结构规则分片
  -> 超长 Chunk 语义细分
  -> 邻接上下文 overlap
  -> Chunk[]
```

适用于需要更强语义边界控制的长文档场景。

## 4. 使用方式

### 4.1 解析流水线中的使用

`ParseTaskPipeline._chunk_markdown` 会优先使用上游已经生成的 `ParseResult`：

```python
chunks = ParseTaskPipeline._chunk_markdown(
    markdown=markdown,
    source_file=md_object_key,
    parse_result=parse_result,
)
```

如果没有 `parse_result`，`ChunkingEngine` 会先调用 `MarkdownParser.parse()` 再分片。

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

修改语义分片时关注：

- token 上下限是否合理。
- overlap 是否造成内容膨胀。
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
- 表格、图片、代码块独立分片。
- `source_file` 元数据注入。
- 超长文本语义细分。
- 空文档或纯噪声文档。
