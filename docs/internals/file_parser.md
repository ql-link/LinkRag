# File Parser Module

本文说明 `src/core/parser` 文件解析模块的架构、使用方式，以及新增或修改解析器的方法。

## 1. 模块框架

```text
src/core/parser/
├── base.py                    # 通用解析器接口和基类
├── factory.py                 # 按文件类型分发解析器
├── providers/                 # 文件格式级解析器
│   ├── pdf_parser.py          # PDF 解析入口
│   ├── word_parser.py         # Word/docx 解析器
│   └── html_parser.py         # HTML 解析器
├── html/                      # HTML 专用解析体系
│   ├── models.py              # HTML 参数、表格和图片结果模型
│   ├── service.py             # DOM 构建、去噪和渲染编排
│   ├── renderer.py            # HTML 节点到 Markdown 的结构化渲染
│   ├── table_processor.py     # 表格分类、展开和 Markdown/记录式输出
│   └── image_rewriter.py      # 图片 URL 绝对化和模拟对象存储路径
└── pdf/                       # PDF 专用解析体系
    ├── base.py                # PDF 后端接口
    ├── models.py              # PDF 参数和图片资产模型
    ├── registry.py            # PDF 后端注册表
    ├── service.py             # PDF 解析流程编排
    └── backends/
        ├── mineru_backend.py
        ├── opendataloader_backend.py
        └── naive_backend.py
```

上层调用链：

```text
ParseTaskService
  -> ParserFactory
    -> WordParser / HtmlParser / PdfParser
      -> MarkdownEnhancementOrchestrator
      -> MarkdownParser
```

PDF 内部调用链：

```text
PdfParser
  -> PdfParserService
    -> PdfBackendRegistry
      -> MinerUBackend / OpenDataLoaderBackend / NaivePdfBackend / 自定义后端
```

HTML 内部调用链：

```text
HtmlParser
  -> HtmlParseService
    -> BeautifulSoup DOM（去噪声/隐藏/全部 HTML 注释）
    -> trafilatura 定位正文（仅取正文纯文本作信号，不取其结构输出）
    -> 文本重合度映射回 soup 容器（低置信分级回退：语义容器 -> 整篇 body）
    -> HtmlMarkdownRenderer
      -> HtmlTableProcessor
      -> HtmlImageRewriter
```

混合方案：trafilatura 负责"哪一块是正文 / 去站点样板 / 空内容(None)识别"，最终 Markdown
仍由自研渲染器在我们清理后的完好 DOM 上生成（表格/图片保真）。trafilatura 返回 None 或
渲染根正文低于保守下限时抛 `ParseBaseException`，经 pipeline 映射 `PARSE_ENGINE_FAILED`。

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `BaseParser` | `base.py` | 通用文件解析器基类，提供空文件校验和 metadata |
| `ParserFactory` | `factory.py` | 根据 `file_type` 返回具体解析器 |
| `ParseTaskService` | `src/core/parse_task_service.py` | 业务推荐入口，解析后执行 Markdown 清洗和增强 |
| `HtmlParser` | `providers/html_parser.py` | HTML 格式入口，解码文件流并适配 HTML 专用服务 |
| `HtmlParseService` | `html/service.py` | 构建并清理 DOM（含删全部 HTML 注释）、trafilatura 定位正文/去样板、文本重合度映射回 soup 容器（低置信分级回退）、空内容判定、编排 Markdown 渲染 |
| `HtmlMarkdownRenderer` | `html/renderer.py` | 按 DOM 顺序渲染标题、段落、列表、代码块、图片和表格 |
| `HtmlTableProcessor` | `html/table_processor.py` | 将普通表格输出为 Markdown table，将复杂表格输出为记录式 Markdown |
| `HtmlImageRewriter` | `html/image_rewriter.py` | 将图片 URL 绝对化，并生成模拟对象存储路径 |
| `PdfParser` | `providers/pdf_parser.py` | PDF 格式入口，读取配置并组装 PDF 参数 |
| `PdfParserService` | `pdf/service.py` | PDF 解析流程编排、图片上传和引用替换 |
| `PdfBackendRegistry` | `pdf/registry.py` | PDF 后端注册、实例创建、解析顺序解析 |
| `BasePdfBackend` | `pdf/base.py` | 单个 PDF 解析后端必须实现的接口 |

约定：

- 通用解析器实现 `parse(source: Path | None) -> str`，返回 Markdown 字符串。`source is None`
  仅在 MinerU URL 旁路下合法，由具体 provider 自行决定是否拒绝。
- PDF 后端实现 `parse(source: Path | None, options)`，并声明唯一 `name`。
- 解析器元数据写入 `self.metadata`，通过 `extract_metadata()` 读取。
- PDF 后端返回 `tuple[str, list[PdfBinaryAsset]]`。
- "解析任务 OOM 风险治理"治理后，协议层不再接受 `bytes` 入参——pipeline 在调用前已通过
  `ParseSourceIO.download_to_path` 把对象存储源文件流式落到 `PARSE_TEMP_DIR/parse-*.tmp`，
  避免源文件以完整 bytes 形态全量驻留内存。

## 3. 当前支持的解析器

| 文件类型 | 解析器 | 说明 |
| --- | --- | --- |
| `pdf` | `PdfParser` | PDF 入口，内部按参数选择后端 |
| `docx` | `WordParser` | mammoth 转语义 HTML + 复用 HTML 渲染引擎（标题/列表/表格/图片保真，跳过 trafilatura）；legacy `.doc`/非 OOXML 快速失败 |
| `html` / `htm` | `HtmlParser` | trafilatura 定位正文/去样板 + 自研渲染器结构化转 Markdown（表格/图片保真） |

当前 PDF 后端：

| backend | 实现 | 说明 |
| --- | --- | --- |
| `mineru` | `MinerUBackend` | 调用 MinerU API，当前默认后端 |
| `opendataloader` | `OpenDataLoaderBackend` | 本地 OpenDataLoader 解析 |
| `naive` | `NaivePdfBackend` | PyMuPDF 本地解析 |
| `auto` | 注册表内置顺序 | 按 `mineru -> opendataloader -> naive` 尝试 |

## 4. 配置

PDF 默认解析器由 `src/config.py` 和 `.env` 控制：

```env
PDF_PARSER_BACKEND=mineru
PDF_PARSER_FALLBACKS=
PDF_IMAGE_UPLOAD_ASYNC=true
PDF_IMAGE_ENHANCEMENT_MEMORY_MAX_IMAGES=20
PDF_IMAGE_ENHANCEMENT_MEMORY_MAX_BYTES=52428800
MINERU_API_URL=https://mineru.net/api/v4/extract/task
MINERU_API_KEY=...
MINERU_TIMEOUT=300
MINERU_MODEL_VERSION=vlm
```

说明：

- `PDF_PARSER_BACKEND`：调用方未传 `backend` 时使用，当前默认 `mineru`。
- `PDF_PARSER_FALLBACKS`：逗号分隔的兜底后端列表；留空表示不自动回退本地解析器。显式选择 `mineru` 时不会使用本地兜底后端。
- `PDF_IMAGE_UPLOAD_ASYNC`：是否将 PDF 图片上传切到后台线程执行。默认 `true`，主链路会先生成最终图片 URL 并返回 Markdown，不等待 MinIO 上传完成。
- `PDF_IMAGE_ENHANCEMENT_MEMORY_MAX_IMAGES` / `PDF_IMAGE_ENHANCEMENT_MEMORY_MAX_BYTES`：图片增强可直接使用的解析阶段内存图片上限，避免大 PDF 占用过多 worker 内存。
- `MINERU_*`：MinerU 官方精准解析 API 调用配置。`MINERU_MODEL_VERSION` 默认 `vlm`，可按官方支持切换为 `pipeline`、`vlm` 或 `MinerU-HTML`。

## 5. 使用方式

### 5.1 推荐入口

业务层优先使用 `ParseTaskService.aprocess`：

```python
from src.core.parse_task_service import ParseTaskService

result = await ParseTaskService.aprocess(
    file_stream=file_bytes,
    file_type="pdf",
    source_file="example.pdf",
    backend="mineru",
    source_file_url="https://cdn.example.com/example.pdf",
)

markdown = result["markdown"]
metadata = result["metadata"]
time_cost_ms = result["time_cost_ms"]
```

返回结构包含 `markdown`、`parse_result`、`metadata` 和 `time_cost_ms`。

### 5.2 直接使用 ParserFactory

适合单元测试或轻量脚本：

```python
from src.core.parser.factory import ParserFactory

parser = ParserFactory.get_parser(
    "pdf",
    backend="mineru",
    source_file_url="https://cdn.example.com/example.pdf",
)
markdown = parser.parse(file_bytes)
metadata = parser.extract_metadata()
```

### 5.3 指定 PDF 后端

调用方可用 `backend` 覆盖默认后端：

```python
await ParseTaskService.aprocess(
    file_bytes,
    "pdf",
    backend="mineru",
    source_file_url="https://cdn.example.com/example.pdf",
)
await ParseTaskService.aprocess(file_bytes, "pdf", backend="opendataloader")
await ParseTaskService.aprocess(file_bytes, "pdf", backend="naive")
await ParseTaskService.aprocess(file_bytes, "pdf", backend="auto")
```

MinerU 后端只调用官方 V4 精准解析 API：`POST /api/v4/extract/task` 提交文件 URL 与 `model_version`，再通过 `GET /api/v4/extract/task/{task_id}` 轮询解析结果。若返回结果包含 Markdown 直链（如 `markdown_url` / `full_md_url` / `md_url`），优先直接下载 Markdown；否则流式下载 `full_zip_url` 并解压提取 Markdown 与图片资产。该接口不支持直接上传本地 bytes，因此显式选择 `mineru` 时必须提供 `source_file_url`，且该 URL 必须能被 MinerU 云端访问。缺少 `MINERU_API_KEY`、`MINERU_API_URL` 或 `source_file_url` 时，该后端会直接失败并记录 `mineru_backend_error`，不会回退到本地 mineru-api。轮询策略会先立即查询一次，未完成时按 `1s -> 1.5s -> 2.25s` 退避，最大间隔 5s。下载阶段会记录 `mineru_download_mode`、下载字节数与耗时，便于定位 CDN 传输瓶颈。

MQ 解析任务通过 `pdf_parser_backend` 指定：

```json
{
  "file_type": "pdf",
  "pdf_parser_backend": "mineru"
}
```

如果未传 `pdf_parser_backend`，默认使用 `mineru`。

在 MQ 流水线中，当 `pdf_parser_backend="mineru"` 时，`ParseTaskPipeline` 会使用源文件的 `source_bucket` 与 `source_object_key` 通过对象存储构造 `source_file_url`，并跳过本服务下载源 PDF 的步骤。生产环境需保证该对象 URL 对 MinerU 云端可访问，否则精准解析任务会创建失败或轮询失败。

### 5.4 图片资产输出

PDF 解析可传 `image_bucket`、`image_prefix` 配合对象存储输出图片资产；完整流水线中，这些参数通常由 `ParseTaskPipeline` 从 MQ payload 和 Markdown 输出路径中组装。

MinerU 精准解析返回的 ZIP 中，Markdown 图片默认是 `images/xxx` 相对路径。`MinerUBackend` 会保留该相对路径作为图片资产的 `source_path`，`PdfParserService` 会先同步生成最终对象 key 与 URL，再把 Markdown 中的相对路径替换为对象存储 URL。

所有 PDF 图片上传路径都会收敛到同一套图片准备逻辑，包括 MinerU/OpenDataLoader 已提取的二进制图片、PyMuPDF 内嵌图、Naive 图片块、页渲染图片和视觉区域裁剪图片。对象存储层仍然是一张图片一个 object 上传，不使用单次批量上传；当 `PDF_IMAGE_UPLOAD_ASYNC=true` 时，主链路只负责生成 URL 并提交后台上传任务，不等待 MinIO 上传完成，因此 Markdown 中的图片链接会经历一个短暂的最终一致性窗口。

图片增强不会依赖 MinIO 图片已上传完成。`PdfParserService` 会把受限数量的图片 bytes 作为进程内临时映射交给 `ParseTaskService`，`ProviderVisionClient` 优先使用内存图片进行视觉模型调用，只有内存映射缺失时才回退读取 Markdown 中的图片 URL。该内存映射不会写入最终 metadata、MQ 或数据库。

## 6. 新增文件格式解析器

适用于新增 `txt`、`xlsx` 等非 PDF 文件类型。

步骤：

1. 在 `src/core/parser/providers/` 下新增解析器文件。
2. 继承 `BaseParser`，实现 `parse(file_stream: bytes) -> str`。
3. 在 `ParserFactory.get_parser` 中增加文件类型分发。
4. 增加单元测试。

示例：

```python
from ..base import BaseParser


class TxtParser(BaseParser):
    def parse(self, file_stream: bytes) -> str:
        self.validate_stream(file_stream)
        text = file_stream.decode("utf-8", errors="ignore")
        self.metadata["pages_or_length"] = (len(text) // 500) + 1
        return text
```

`ParserFactory` 中增加：

```python
elif ext == "txt":
    return TxtParser()
```

## 7. 新增 PDF 解析后端

如果只是新增 PDF 解析方式，不需要改 `ParserFactory`，只需要新增 PDF 后端并注册。

新增后端：

```python
from src.core.parser.pdf.base import BasePdfBackend


class CustomPdfBackend(BasePdfBackend):
    name = "custom"

    def parse(self, file_stream: bytes, options):
        self.metadata["custom_backend_status"] = "success"
        return "# parsed by custom", []
```

注册后端：

```python
from src.core.parser.pdf.registry import register_pdf_backend
from src.core.parser.pdf.backends.custom_backend import CustomPdfBackend

register_pdf_backend("custom", CustomPdfBackend)
```

使用：

```python
await ParseTaskService.aprocess(file_bytes, "pdf", backend="custom")
```

MQ 使用时传 `"pdf_parser_backend": "custom"`。

如果后端构造需要参数，可以注册 factory：

```python
register_pdf_backend(
    "custom",
    lambda options: CustomPdfBackend(api_url=options.custom_api_url),
)
```

新增专用参数时，通常需要同步修改：

- `src/core/parser/pdf/models.py` 的 `PdfParseOptions`
- `PdfParser.__init__`
- `PdfParser.parse` 中构造 `PdfParseOptions` 的代码
- MQ/API schema（如果参数来自外部请求或消息）

## 8. 修改已有解析器

修改 Word 或 HTML：

- Word：`src/core/parser/providers/word_parser.py`（适配层：mammoth→语义 HTML→复用 `src/core/parser/html` 渲染引擎，跳过 trafilatura；内嵌图经 mammoth 钩子转模拟 MinIO 路径）
- HTML 入口：`src/core/parser/providers/html_parser.py`
- HTML 内部流程：`src/core/parser/html/service.py`
- HTML 表格：`src/core/parser/html/table_processor.py`
- HTML 图片：`src/core/parser/html/image_rewriter.py`

HTML 解析约束：

- 只处理 HTML/HTM，不改变 Word、PDF、pipeline、MQ、API、数据库或对象存储公共契约。
- 标题只来自原始 HTML `h1` 到 `h6`，表格记录模板不生成 Markdown 标题，避免影响分片标题边界。
- 普通表格、可展开 `rowspan` / `colspan`、多级表头和列表单元格输出标准 Markdown table。
- 嵌套表格、图片单元格、多段复杂单元格输出显式记录式 Markdown，不输出原始 `<table>`。
- 图片仅做 URL 绝对化和模拟对象存储路径引用，不做真实下载或 MinIO 上传。
- 大表格本轮不拆分，`table_split_count` 保持为 0。

修改 PDF 通用流程：

- 文件：`src/core/parser/pdf/service.py`
- 适用场景：图片上传、Markdown 图片引用替换、多后端尝试记录、空结果处理。
- 注意：不要在 `service.py` 中硬编码新后端创建逻辑，应通过 `registry.py` 或 `register_pdf_backend` 接入。

修改某个 PDF 后端：

- MinerU：`src/core/parser/pdf/backends/mineru_backend.py`
- OpenDataLoader：`src/core/parser/pdf/backends/opendataloader_backend.py`
- Naive：`src/core/parser/pdf/backends/naive_backend.py`

后端约束：

- 成功时返回非空 Markdown。
- 失败时返回 `("", [])`，并写入 `self.metadata["<name>_backend_error"]`。
- 不直接写业务表、不发 MQ、不做向量入库。

## 9. 测试建议

新增或修改解析器时至少覆盖 `tests/unit/core/parser/`、PDF 后端注册和选择、`ParseTaskService` 调用链。

常用命令：

```bash
.venv/bin/pytest tests/unit/core/parser -q
.venv/bin/pytest tests/unit/core/pipeline tests/unit/core/mq -q
```
