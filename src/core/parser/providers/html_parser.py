from ..base import BaseParser
from ..html import HtmlParseOptions, HtmlParseService


class HtmlParser(BaseParser):
    """HTML document parser that preserves RAG-relevant structure."""

    def __init__(
        self,
        source_file_url: str | None = None,
        image_prefix: str = "html-images",
        mock_minio_base_url: str = "mock-minio://tolink-rag",
        **_: object,
    ):
        super().__init__()
        self.options = HtmlParseOptions(
            source_file_url=source_file_url,
            image_prefix=image_prefix,
            mock_minio_base_url=mock_minio_base_url,
        )
        self.service = HtmlParseService(self.options)

    def parse(self, file_stream: bytes) -> str:
        self.validate_stream(file_stream)

        html_content = file_stream.decode("utf-8", errors="ignore")
        result = self.service.parse(html_content)

        self.metadata.update(result.metadata)
        if result.warnings:
            self.metadata["warnings"] = result.warnings

        return result.markdown
