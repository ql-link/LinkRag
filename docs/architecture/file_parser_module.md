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

## 2. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `BaseParser` | `base.py` | 通用文件解析器基类，提供空文件校验和 metadata |
| `ParserFactory` | `factory.py` | 根据 `file_type` 返回具体解析器 |
| `ParseTaskService` | `src/services/parse_task_service.py` | 业务推荐入口，解析后执行 Markdown 清洗和增强 |
| `PdfParser` | `providers/pdf_parser.py` | PDF 格式入口，读取配置并组装 PDF 参数 |
| `PdfParserService` | `pdf/service.py` | PDF 解析流程编排、图片上传和引用替换 |
| `PdfBackendRegistry` | `pdf/registry.py` | PDF 后端注册、实例创建、解析顺序解析 |
| `BasePdfBackend` | `pdf/base.py` | 单个 PDF 解析后端必须实现的接口 |

约定：

- 通用解析器实现 `parse(file_stream: bytes) -> str`，返回 Markdown 字符串。
- PDF 后端实现 `parse(file_stream, options)`，并声明唯一 `name`。
- 解析器元数据写入 `self.metadata`，通过 `extract_metadata()` 读取。
- PDF 后端返回 `tuple[str, list[PdfBinaryAsset]]`。

## 3. 当前支持的解析器

| 文件类型 | 解析器 | 说明 |
| --- | --- | --- |
| `pdf` | `PdfParser` | PDF 入口，内部按参数选择后端 |
| `docx` / `doc` | `WordParser` | Word 段落和表格转 Markdown |
| `html` / `htm` | `HtmlParser` | 使用 trafilatura 提取正文并转 Markdown |

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
MINERU_API_URL=https://mineru.net/api/v4/extract/task
MINERU_API_KEY=...
MINERU_TIMEOUT=300
```

说明：

- `PDF_PARSER_BACKEND`：调用方未传 `backend` 时使用，当前默认 `mineru`。
- `PDF_PARSER_FALLBACKS`：逗号分隔的兜底后端列表；留空表示不自动回退本地解析器。
- `MINERU_*`：MinerU API 调用配置。
- `MINIO_PUBLIC_ENDPOINT`：可选公网 MinIO endpoint；当 MQ 解析任务使用 MinerU 官方云端时，流水线会尝试生成预签名源文件 URL 并传给 MinerU，减少本服务到 MinerU 的重复上传。当前主流程仍会先下载源文件字节用于解析入口校验、页数元数据和失败回退。

## 5. 使用方式

### 5.1 推荐入口

业务层优先使用 `ParseTaskService.aprocess`：

```python
from src.services.parse_task_service import ParseTaskService

result = await ParseTaskService.aprocess(
    file_stream=file_bytes,
    file_type="pdf",
    source_file="example.pdf",
    backend="mineru",
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

parser = ParserFactory.get_parser("pdf", backend="mineru")
markdown = parser.parse(file_bytes)
metadata = parser.extract_metadata()
```

### 5.3 指定 PDF 后端

调用方可用 `backend` 覆盖默认后端：

```python
await ParseTaskService.aprocess(file_bytes, "pdf", backend="mineru")
await ParseTaskService.aprocess(file_bytes, "pdf", backend="opendataloader")
await ParseTaskService.aprocess(file_bytes, "pdf", backend="naive")
await ParseTaskService.aprocess(file_bytes, "pdf", backend="auto")
```

MinerU 官方云端后端还支持传入 `source_file_url`：

```python
await ParseTaskService.aprocess(
    file_bytes,
    "pdf",
    backend="mineru",
    source_file_url="https://example.com/presigned/document.pdf",
)
```

仅当 `MINERU_API_KEY` 已配置且 `MINERU_API_URL` 指向 `mineru.net` 时，`source_file_url` 会触发 URL 直拉模式；否则仍走本地 HTTP API 或云端文件上传路径。

MQ 解析任务通过 `pdf_parser_backend` 指定：

```json
{
  "file_type": "pdf",
  "pdf_parser_backend": "mineru"
}
```

如果未传 `pdf_parser_backend`，默认使用 `mineru`。

### 5.4 图片资产输出

PDF 解析可传 `image_bucket`、`image_prefix` 配合对象存储输出图片资产；完整流水线中，这些参数通常由 `ParseTaskPipeline` 从 MQ payload 和 Markdown 输出路径中组装。

### 5.5 MinerU 云端 URL 直拉

MQ 解析任务使用 `mineru` 后端时，`ParseTaskPipeline` 会尝试通过对象存储生成源文件预签名 URL：

```text
ParseTaskPipeline
  -> BaseObjectStorage.generate_presigned_url()
  -> PdfParser(source_file_url=...)
  -> MinerUBackend._call_cloud_api_by_url()
```

该优化的边界：

- 只对 MinerU 官方云端后端生效。
- 存储层无法生成 URL、URL 不可外部访问或非云端 MinerU 配置时自动回到原有上传路径。
- MinIO 私有部署如需让 MinerU 云端访问，应配置 `MINIO_PUBLIC_ENDPOINT`，用于替换预签名 URL 中的内网 endpoint。

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

- Word：`src/core/parser/providers/word_parser.py`
- HTML：`src/core/parser/providers/html_parser.py`

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
.venv/bin/pytest tests/unit/services/test_parse_task_service.py -q
.venv/bin/pytest tests/unit/core/pipeline tests/unit/core/mq -q
```
