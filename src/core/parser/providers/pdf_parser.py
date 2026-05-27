from pathlib import Path

import fitz

from src.config import settings
from src.core.parser.pdf.models import PdfParseOptions
from src.core.parser.pdf.service import PdfParserService
from ..base import BaseParser


class PdfParser(BaseParser):
    """PDF -> Markdown 解析入口，可通过 backend 参数选择具体解析器。

    支持的 backend:
    - auto: MinerU → OpenDataLoader → Naive 全链路降级
    - mineru: MinerU HTTP API（默认不回退到本地解析器）
    - opendataloader: OpenDataLoader 本地解析
    - naive: PyMuPDF (最快，质量最低)

    入参从 ``bytes`` 切换为 ``Path | None``。``source is None`` 仅在"mineru 后端 +
    远端 URL 旁路"下合法（旧实现使用 ``file_stream == b""`` 表达同一语义）。
    """

    def __init__(
        self,
        backend: str | None = None,
        image_bucket: str | None = None,
        image_prefix: str | None = None,
        image_upload_async: bool | None = None,
        storage=None,
        source_file_url: str | None = None,
        docling_force_ocr: bool = False,
        mineru_api_url: str | None = None,
        mineru_api_key: str | None = None,
        mineru_timeout: int | None = None,
        mineru_model_version: str | None = None,
    ):
        super().__init__()
        self.backend = (backend or settings.PDF_PARSER_BACKEND).lower()
        self.image_bucket = image_bucket
        self.image_prefix = image_prefix
        self.image_upload_async = (
            settings.PDF_IMAGE_UPLOAD_ASYNC if image_upload_async is None else bool(image_upload_async)
        )
        self.storage = storage
        self.source_file_url = source_file_url
        self.docling_force_ocr = bool(docling_force_ocr)
        self.mineru_api_url = mineru_api_url or settings.MINERU_API_URL
        self.mineru_api_key = mineru_api_key or settings.MINERU_API_KEY
        self.mineru_timeout = mineru_timeout or settings.MINERU_TIMEOUT
        self.mineru_model_version = mineru_model_version or settings.MINERU_MODEL_VERSION
        self._service = PdfParserService()

    def parse(self, source: Path | None) -> str:
        # 旁路判定：mineru 后端 + 已有远端 URL + source 缺省时跳过本地 PDF 解析步骤。
        # 这里 ``source is None`` 与旧实现的 ``not file_stream`` 等价（旧路径用 b"" 表达旁路）。
        can_skip_local_pdf = (
            self.backend == "mineru"
            and bool(self.source_file_url)
            and source is None
        )
        doc = None
        if not can_skip_local_pdf:
            self.validate_source(source)
            doc = fitz.open(filename=str(source))
        markdown, metadata = self._service.parse(
            source,
            PdfParseOptions(
                backend=self.backend,
                image_bucket=self.image_bucket,
                image_prefix=self.image_prefix,
                image_upload_async=self.image_upload_async,
                storage=self.storage,
                source_file_url=self.source_file_url,
                docling_force_ocr=self.docling_force_ocr,
                mineru_api_url=self.mineru_api_url,
                mineru_api_key=self.mineru_api_key,
                mineru_timeout=self.mineru_timeout,
                mineru_model_version=self.mineru_model_version,
            ),
        )
        self.metadata.update(metadata)
        self.metadata["pages_or_length"] = len(doc) if doc is not None else 0
        self.metadata["pdf_info"] = doc.metadata if doc is not None else {}

        if not markdown.strip():
            attempts = metadata.get("pdf_parser_attempts") or []
            reason = attempts[-1].get("reason") if attempts else "empty result"
            raise RuntimeError(f"PDF 解析失败: {reason}")
        return markdown.strip()
