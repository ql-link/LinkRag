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
├── heading_hierarchy.py  # 标题层级生成门禁、标题计划校验与写回
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
  -> splitter stage pipeline
  -> list[Chunk]
```

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `MarkdownParser` | `parser.py` | 将 Markdown 文本解析为 `ParseResult`；解码增强描述标记归位为结构化字段 |
| `MarkdownScanner` | `scanner.py` | 逐行识别标题、段落、表格、图片、代码块等元素 |
| `ImageExtractor` | `image_extractor.py` | 提取图片 URL、行号和 alt 文本 |
| `ParseResult` | `models.py` | 结构化解析结果，包含 `elements/tables/images/source_file`；`to_markdown()` 把描述字段重新编码为标记（与解码对称） |
| `MarkdownEnhancementOrchestrator` | `orchestrator.py` | 按配置触发表格和图片增强 |
| `HeadingHierarchyProcessor` | `heading_hierarchy.py` | 可选标题层级后处理：门禁命中后应用标题插入计划，并返回同构更新后的 Markdown + `ParseResult` |
| `aprocess_existing_markdown_heading_hierarchy` | `heading_hierarchy.py` | 已有 Markdown 的标题处理适配器：复用同一处理器，并统一构造运行配置与四项标题 metadata |
| `TableDescriber` | `llm_integration.py` | 把表格总结**编码**为标记 `[表格总结: …]` 写入对应元素 content |
| `ImageDescriber` | `llm_integration.py` | 把图片视觉描述**编码**为标记 `[视觉描述\|src=<url>: …]` 写入 content |
| `ProviderTableClient` / `ProviderVisionClient` | `provider_clients.py` | 调用系统 LLM Provider 完成增强 |

> **增强描述的编解码（对称）**：增强阶段把图片/表格描述以文本标记写入 `content`（编码），使其能随 markdown 持久化并扛过 `to_markdown() → 重新 parse()` 的字符串往返；`MarkdownParser.parse()` 解析时再把标记**解码**为结构化字段——独立图写 `metadata.visual_description`、表格写 `metadata.table_summary`，并从 `content` 剥离标记；内联图（无独立元素）的描述改写为干净的可读段落 `图片说明：…`。下游（splitter）只读结构化字段，不再从文本正则提取。`src` 必须匹配文档内真实图片 URL，正文巧合的同形文本不会被误解码。

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

`front_matter` 只在文档第一行出现严格 fence 时探测，支持 `--- ... ---` 与
`+++ ... +++`。scanner 不解析 YAML/TOML 字段值，只用低误判规则判断 fence 内是否像元数据；
识别失败时不消费候选块，开头的 `---` 回到普通 `hr` 解析路径，文档中间的 `---` 永远只作为
`hr`。`hr` 保留为 parser 内部结构信号，下游 splitter 不把它作为最终 chunk 类型输出。

`MarkdownElement` 记录：

- `type`
- `content`
- `start_line`
- `end_line`
- `metadata`

`ParseResult.to_markdown()` 会按元素顺序重新物化 Markdown。

## 4. 增强配置

增强开关优先来自数据集 `enhancement_config`；数据集配置行中的 `{}` 表示所有增强关闭，非空
对象的缺失字段以及无配置行场景才读取 `src/config.py::Settings`：

- `MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT`
- `MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT`
- `MARKDOWN_PARSER_TABLE_MODEL`
- `MARKDOWN_PARSER_VISION_MODEL`
- `MARKDOWN_PARSER_LLM_TIMEOUT_MS`
- `MARKDOWN_PARSER_VISION_CONCURRENCY`
- `MARKDOWN_PARSER_ENABLE_HEADING_HIERARCHY`
- `MARKDOWN_PARSER_HEADING_NO_HEADING_MIN_TOKENS`
- `MARKDOWN_PARSER_HEADING_FLAT_MIN_HEADINGS`
- `MARKDOWN_PARSER_HEADING_SPARSE_TOKENS_PER_HEADING`
- `MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET`
- `MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS`

表格增强使用文本能力；图片增强使用视觉能力。有 `user_id` 的生产解析路径按“用户 active +
default → LinkRag active + default 系统预设”解析：表格增强使用 `CHAT`，图片增强使用 `VISION`。
两层都未命中时抛 `EnhancementModelMissingError`。无 `user_id` 的调试入口使用遗留 env 系统配置：

- `SYSTEM_LLM_PROVIDER`
- `SYSTEM_LLM_API_KEY`
- `SYSTEM_LLM_API_BASE`
- `SYSTEM_LLM_MODEL_CHAT`
- `SYSTEM_LLM_MODEL_VISION`

PDF 解析阶段如果提供了 `image_bytes_by_url`，图片增强会优先使用内存图片 bytes；缺失时才回退读取 Markdown 中的图片 URL 或本地路径。

Java 规范化 Markdown 的 RAW 图片由 parse-task 层先完成对象存储范围校验和下载，再调用 `ImageDescriber.aprocess(..., image_bytes_by_url=..., target_urls=...)`。`target_urls` 只允许选择当前 `ParseResult.images` 中的 URL，使一个批次只调用成功加载的图片，同时仍把描述合并回同一个完整 `ParseResult`。对象存储读取不放入 provider client，Vision provider 继续只负责字节分析和单图失败降级。

图片增强通过 `ProviderVisionClient` 对同一批图片执行受控并发调用，最大并发数由
`MARKDOWN_PARSER_VISION_CONCURRENCY` 控制，默认值为 `24`。单张图片加载或视觉模型调用失败时只跳过该图片描述，不阻断基础 Markdown 解析。非内存图片读取会通过线程执行，避免同步文件/URL 读取阻塞事件循环。

增强降级日志使用 `markdown_enhancement_failed` / `image_enhancement_failed`，记录
`task_id/user_id/dataset_id/source_filename`（生产解析上下文可用时）、失败子阶段、
模型标识、图片数量或图片短指纹以及安全调用栈。图片 URL 会移除 query/fragment，
不会记录签名参数；表格正文、图片 base64、prompt 和模型响应正文均不进入日志。

标题层级后处理是可选增强，默认关闭。配置关闭时行为与普通 `MarkdownParser.parse()` 等价，不执行门禁，也不读取模型配置。配置开启且门禁命中时，标题生成器按“发起用户默认 → LinkRag 系统默认预设”解析 `CHAT` 模型并生成标题插入计划；无 `user_id` 的调试入口使用遗留 env 系统级 `CHAT` 配置。该模块不新增标题专用模型选择参数，也不允许 LLM 返回整篇 Markdown。

门禁命中场景：

- 全文无 heading 且 token 数达到 `MARKDOWN_PARSER_HEADING_NO_HEADING_MIN_TOKENS`（默认 `512`）。
- 全篇只有同级 heading，heading 数达到 `MARKDOWN_PARSER_HEADING_FLAT_MIN_HEADINGS`（默认/下限 `5`），且存在章节编号或常见章节短语等层级线索。
- 已有多级 heading，但 `total_tokens / heading_count` 达到 `MARKDOWN_PARSER_HEADING_SPARSE_TOKENS_PER_HEADING`（默认 `1536`，下限 `1024`）。

标题写回只支持插入新 heading，等级限制为 `#` 到 `#####`。插入计划的 `line` 始终是原始 Markdown 行号，写回时先按原始行号分组，再一次性重建 Markdown，避免前序插入导致后续行号漂移。写回后必须重新走 `MarkdownParser.parse()`，因此对外最终 Markdown 与 `ParseResult` 来自同一份处理后的文本；splitter 不需要感知标题来源，仍按 `heading_level` / `heading_text` / `heading_trail` 消费。标题生成是显式开启能力：开启后如果门禁命中但用户默认与 LinkRag 系统默认预设均无 `CHAT` 配置、LLM 调用失败、响应无法解析或计划校验失败，解析任务失败，不静默降级。

已有 Markdown 通过 `aprocess_existing_markdown_heading_hierarchy()` 进入同一处理器。适配器以 Settings 中的阈值为基础，只用数据集 `enhancement_config` 覆盖开关，并统一返回 `heading_hierarchy_enabled/applied/reason/insertions` 四项 metadata。#322 完成通用候选位置与校验器修复前，若 parser 已把首元素识别为第 0 行开始的 YAML/TOML `front_matter`，该适配器会以 `front_matter_pending_322` 原因保守跳过整次标题生成：不构建 generator、不调用 provider，原文和同源 `ParseResult` 保持不变。这只是原生 Markdown 接入的过渡保护，不改变通用 candidate/validator 语义，也不替代 #322。

标题生成器的单次输入受 `MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET` 控制（默认 `65536`，允许范围 `2048` - `262144`）：预算内优先发送带原始行号的全文 Markdown；超预算时构造压缩结构摘要，保留门禁原因、标题指标、已有标题树、候选插入位置、protected block 边界和元素 preview，再要求 LLM 输出标题插入计划。输出插入计划的上限由 `MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS` 控制（默认 `4096`，允许范围 `512` - `65536`）。默认值按系统默认 `qwen3.5-flash` 的百万级上下文能力放宽，但仍保留应用侧上限，避免标题后处理在长文上无限扩大成本和延迟。

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
- 表格总结/图片视觉描述的编码与解码归位（独立图/表写结构化字段、内联图改写为可读段落）。
- 解码的防误判（`src` 必须匹配真实图片 URL）与幂等（重复解析不重复/丢失字段）。
- 图片视觉增强的并发上限、失败隔离和内存图片优先级。
- 增强失败时的降级行为。
