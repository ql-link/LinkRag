from bs4 import BeautifulSoup

from src.core.exceptions import ParseBaseException

from .models import HtmlParseOptions, HtmlParseResult
from .renderer import HtmlMarkdownRenderer


class HtmlParseService:
    """Build a DOM, remove noise, and render HTML as structure-preserving Markdown."""

    NOISE_SELECTORS = [
        "script",
        "style",
        "noscript",
        "template",
        "iframe",
        "svg",
        "canvas",
        "form",
        "input",
        "button",
        "select",
        "textarea",
        "aside",
        "nav",
        "header nav",
        "footer nav",
    ]

    def __init__(self, options: HtmlParseOptions | None = None):
        self.options = options or HtmlParseOptions()

    def parse(self, html_content: str) -> HtmlParseResult:
        soup = self._build_soup(html_content)
        self._clean_soup(soup)
        root = soup.body or soup

        renderer = HtmlMarkdownRenderer(self.options)
        markdown = renderer.render_children(root)
        if not markdown.strip():
            raise ParseBaseException("HTML 解析失败：DOM 中没有有效内容")

        metadata = {
            "pages_or_length": (len(markdown) // 500) + 1,
            "table_count": renderer.table_count,
            "record_table_count": renderer.record_table_count,
            "table_failure_count": renderer.table_failure_count,
            "table_split_count": renderer.table_split_count,
            "image_count": renderer.image_count,
            "image_upload_count": renderer.image_upload_count,
        }
        return HtmlParseResult(markdown=markdown, metadata=metadata, warnings=renderer.warnings)

    def _build_soup(self, html_content: str) -> BeautifulSoup:
        if not html_content or not html_content.strip():
            raise ParseBaseException("HTML 解析失败：文件内容为空")
        return BeautifulSoup(html_content, "html.parser")

    def _clean_soup(self, soup: BeautifulSoup) -> None:
        for selector in self.NOISE_SELECTORS:
            for node in soup.select(selector):
                node.decompose()

        for node in soup.find_all(attrs={"hidden": True}):
            node.decompose()

        for node in soup.find_all(attrs={"aria-hidden": "true"}):
            node.decompose()
