# Markdown Parser Module

本文说明 `src/core/markdown_parser` Markdown 结构化解析和增强模块的架构、边界，以及修改表格/图片增强逻辑的方法。

## 1. 模块框架

```text
src/core/markdown_parser/
├── models.py             # MarkdownElement / ParseResult / TableRef / ImageRef
├── parser.py             # MarkdownParser 主入口
├── scanner.py            # 行扫描器，识别块级元素
├── image_extractor.py    # Markdown/HTML 图片引用提取
├── orchestrator.py       # MarkdownEnhancementOrchestrator
├── llm_integration.py    # TableDescriber / ImageDescriber 合并逻辑
└── provider_clients.py   # 基于项目 LLM Provider 的表格/图片客户端
```

上游调用：

```text
ParseTaskService
  -> MarkdownEnhancementOrchestrator
    -> MarkdownParser
    -> TableDescriber / ImageDescriber
```

下游调用：

```text
ParseResult
  -> ChunkingEngine.process_parse_result()
  -> ASTAwareChunker / StructuredSemanticChunker
```

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `MarkdownParser` | `parser.py` | 将 Markdown 文本解析为 `ParseResult` |
| `MarkdownScanner` | `scanner.py` | 逐行识别标题、段落、表格、图片、代码块等元素 |
| `ImageExtractor` | `image_extractor.py` | 提取图片 URL、行号和 alt 文本 |
| `ParseResult` | `models.py` | 结构化解析结果，包含 `elements/tables/images/source_file` |
| `MarkdownEnhancementOrchestrator` | `orchestrator.py` | 按配置触发表格和图片增强 |
| `TableDescriber` | `llm_integration.py` | 将表格摘要合并回 `ParseResult` |
| `ImageDescriber` | `llm_integration.py` | 将图片视觉描述合并回 `ParseResult` |
| `ProviderTableClient` / `ProviderVisionClient` | `provider_clients.py` | 调用系统 LLM Provider 完成增强 |

## 3. 元素模型

`ElementType` 当前支持：

- `heading`
- `paragraph`
- `code_block`
- `list`
- `blockquote`
- `table`
- `image`
- `hr`
- `front_matter`
- `math_block`

`MarkdownElement` 记录：

- `type`
- `content`
- `start_line`
- `end_line`
- `metadata`

`ParseResult.to_markdown()` 会按元素顺序重新物化 Markdown。

## 4. 增强配置

增强开关来自 `src/config.py::Settings`：

- `MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT`
- `MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT`
- `MARKDOWN_PARSER_TABLE_MODEL`
- `MARKDOWN_PARSER_VISION_MODEL`
- `MARKDOWN_PARSER_LLM_TIMEOUT_MS`
- `MARKDOWN_PARSER_VISION_CONCURRENCY`

表格增强使用文本能力；图片增强使用视觉能力。Provider 默认来自系统级 LLM 配置：

- `SYSTEM_LLM_PROVIDER`
- `SYSTEM_LLM_API_KEY`
- `SYSTEM_LLM_API_BASE`
- `SYSTEM_LLM_MODEL_CHAT`
- `SYSTEM_LLM_MODEL_VISION`

PDF 解析阶段如果提供了 `image_bytes_by_url`，图片增强会优先使用内存图片 bytes；缺失时才回退读取 Markdown 中的图片 URL 或本地路径。

图片增强通过 `ProviderVisionClient` 对同一批图片执行受控并发调用，最大并发数由
`MARKDOWN_PARSER_VISION_CONCURRENCY` 控制，默认值为 `24`。单张图片加载或视觉模型调用失败时只跳过该图片描述，不阻断基础 Markdown 解析。非内存图片读取会通过线程执行，避免同步文件/URL 读取阻塞事件循环。

## 5. 使用方式

### 5.1 只做结构化解析

```python
from src.core.markdown_parser import MarkdownParser

result = MarkdownParser().parse(markdown, source_file="example.md")
elements = result.elements
tables = result.tables
images = result.images
```

### 5.2 解析并增强

```python
from src.core.markdown_parser import MarkdownEnhancementOrchestrator

result = await MarkdownEnhancementOrchestrator().aenhance_parse_result(
    markdown,
    source_file="example.md",
)
enhanced_markdown = result.to_markdown()
```

### 5.3 交给分片模块

```python
chunks = ChunkingEngine().process_parse_result(result)
```

该路径可避免对增强后的 Markdown 再做重复解析。

## 6. 修改原则

- `MarkdownParser` 只负责结构化解析，不负责对象存储、数据库、MQ 或向量化。
- 表格/图片增强失败时应降级跳过，不应阻断基础 Markdown 解析。
- 新增元素类型时，需要同步 `ElementType`、scanner、分片策略和相关测试。
- 修改增强 Prompt 时，同步检查 `src/core/prompts/markdown_enhancement.py`。

## 7. 测试建议

```bash
.venv/bin/pytest tests/integration/core/markdown_parser -q
.venv/bin/pytest tests/unit/core/markdown_parser -q
.venv/bin/pytest tests/integration/core/splitter/test_markdown_parser_to_splitter_integration.py -q
```

建议覆盖：

- 标题、段落、列表、代码块、表格、图片和公式块识别。
- 行号和 `heading_trail` 传递。
- 表格摘要和图片视觉描述合并。
- 图片视觉增强的并发上限、失败隔离和内存图片优先级。
- 增强失败时的降级行为。
