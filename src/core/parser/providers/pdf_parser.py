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
    - opendataloader: OpenDataLoader 本地解析（可通过 PDF_PARSER_FALLBACKS 配置回退）
    - naive: PyMuPDF (最快，质量最低)
    """

    def __init__(
        self,
        backend: str | None = None,
        image_bucket: str | None = None,
        image_prefix: str | None = None,
        storage=None,
        docling_force_ocr: bool = False,
        mineru_api_url: str | None = None,
        mineru_api_key: str | None = None,
        mineru_timeout: int | None = None,
    ):
        super().__init__()
        self.backend = (backend or settings.PDF_PARSER_BACKEND).lower()
        self.image_bucket = image_bucket
        self.image_prefix = image_prefix
        self.storage = storage
        self.docling_force_ocr = bool(docling_force_ocr)
        self.mineru_api_url = mineru_api_url or settings.MINERU_API_URL
        self.mineru_api_key = mineru_api_key or settings.MINERU_API_KEY
        self.mineru_timeout = mineru_timeout or settings.MINERU_TIMEOUT
        self._service = PdfParserService()

    def parse(self, file_stream: bytes) -> str:
        self.validate_stream(file_stream)
        doc = fitz.open(stream=file_stream, filetype="pdf")
        markdown, metadata = self._service.parse(
            file_stream,
            PdfParseOptions(
                backend=self.backend,
                image_bucket=self.image_bucket,
                image_prefix=self.image_prefix,
                storage=self.storage,
                docling_force_ocr=self.docling_force_ocr,
                mineru_api_url=self.mineru_api_url,
                mineru_api_key=self.mineru_api_key,
                mineru_timeout=self.mineru_timeout,
            ),
        )
        self.metadata.update(metadata)
        self.metadata["pages_or_length"] = len(doc)
        self.metadata["pdf_info"] = doc.metadata

        if not markdown.strip():
            attempts = metadata.get("pdf_parser_attempts") or []
            reason = attempts[-1].get("reason") if attempts else "empty result"
            raise RuntimeError(f"PDF 解析失败: {reason}")
        return markdown.strip()
