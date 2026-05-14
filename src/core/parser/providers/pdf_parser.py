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
    - opendataloader: OpenDataLoader 本地解析（当前默认，可通过 PDF_PARSER_FALLBACKS 配置回退）
    - naive: PyMuPDF (最快，质量最低)
    """

    def __init__(
        self,
        backend: str | None = None,
        image_bucket: str | None = None,
        image_prefix: str | None = None,
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
        self.storage = storage
        self.source_file_url = source_file_url
        self.docling_force_ocr = bool(docling_force_ocr)
        self.mineru_api_url = mineru_api_url or settings.MINERU_API_URL
        self.mineru_api_key = mineru_api_key or settings.MINERU_API_KEY
        self.mineru_timeout = mineru_timeout or settings.MINERU_TIMEOUT
        self.mineru_model_version = mineru_model_version or settings.MINERU_MODEL_VERSION
        self._service = PdfParserService()

    def parse(self, file_stream: bytes) -> str:
        can_skip_local_pdf = self.backend == "mineru" and bool(self.source_file_url) and not file_stream
        doc = None
        if not can_skip_local_pdf:
            self.validate_stream(file_stream)
            doc = fitz.open(stream=file_stream, filetype="pdf")
        markdown, metadata = self._service.parse(
            file_stream,
            PdfParseOptions(
                backend=self.backend,
                image_bucket=self.image_bucket,
                image_prefix=self.image_prefix,
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
