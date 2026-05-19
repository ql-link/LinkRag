import hashlib
import zipfile
from io import BytesIO

import mammoth
import mammoth.images
from bs4 import BeautifulSoup

from src.core.exceptions import ParseBaseException

from ..base import BaseParser
from ..html.image_rewriter import HtmlImageRewriter
from ..html.models import HtmlParseOptions
from ..html.renderer import HtmlMarkdownRenderer
from ..html.service import HtmlParseService

# content-type → 文件扩展名，用于内嵌图模拟对象路径的可读文件名。
_CONTENT_TYPE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/tiff": "tiff",
    "image/x-emf": "emf",
    "image/x-wmf": "wmf",
}

# mammoth 默认把 Word 多级列表样式（List Bullet 2/3、List Number 2/3）拍平成
# 同级 <li>，丢失层级。下面的 style_map 把这些内置多级样式映射为真正嵌套的
# ul/ol>li，使渲染器能输出带缩进的嵌套列表。仅追加列表规则，标题/加粗等
# 其余样式仍走 mammoth 默认映射。基于 numPr/ilvl 的真列表（真实 Word 文档）
# 仍由 mammoth 默认的编号解析处理，不受影响。
_LIST_STYLE_MAP = "\n".join(
    [
        "p[style-name='List Bullet'] => ul > li:fresh",
        "p[style-name='List Bullet 2'] => ul|ol > li > ul > li:fresh",
        "p[style-name='List Bullet 3'] => ul|ol > li > ul|ol > li > ul > li:fresh",
        "p[style-name='List Number'] => ol > li:fresh",
        "p[style-name='List Number 2'] => ol|ul > li > ol > li:fresh",
        "p[style-name='List Number 3'] => ol|ul > li > ol|ul > li > ol > li:fresh",
    ]
)


class WordParser(BaseParser):
    """.docx -> Markdown：mammoth 转语义 HTML，复用 HTML 渲染引擎产出结构保真 Markdown。

    docx 本身即正文、无站点样板，故复用 HTML 引擎时**跳过 trafilatura 正文定位**，
    直接清理 mammoth HTML 后交 HtmlMarkdownRenderer。内嵌图片在 mammoth 图片钩子
    内转模拟 MinIO 对象路径（复用 HtmlImageRewriter 同款规则），不输出 data:base64。
    """

    def __init__(self) -> None:
        super().__init__()
        # WordParser 自包含解析选项（Word 无相对 URL，无需来源 URL 上下文）。
        self._options = HtmlParseOptions()
        self._image_warning_count = 0

    def parse(self, file_stream: bytes) -> str:
        self.validate_stream(file_stream)
        self._image_warning_count = 0

        if not self._is_ooxml(file_stream):
            raise ParseBaseException("Word 解析失败：非 .docx（OOXML）文件或文件损坏")

        try:
            html = self._docx_to_html(file_stream)
        except ParseBaseException:
            raise
        except Exception as exc:
            # legacy .doc / 损坏 docx 等 mammoth 无法处理的输入统一收敛为解析异常，
            # 经 pipeline 映射 PARSE_ENGINE_FAILED，不静默产空、不新增错误码。
            raise ParseBaseException(f"Word 解析失败：mammoth 转换异常 {exc}") from exc

        renderer = self._render_html(html)
        self._build_metadata(renderer)
        return self._last_markdown

    def _is_ooxml(self, file_stream: bytes) -> bool:
        # .docx 是 zip 容器且含 OOXML 标志文件；legacy .doc（OLE 二进制）、
        # 损坏文件、任意二进制都不是合法 zip 或缺标志文件，据此快速拦截。
        try:
            if not zipfile.is_zipfile(BytesIO(file_stream)):
                return False
            with zipfile.ZipFile(BytesIO(file_stream)) as zf:
                names = set(zf.namelist())
            return "[Content_Types].xml" in names and "word/document.xml" in names
        except (zipfile.BadZipFile, OSError, ValueError):
            return False

    def _docx_to_html(self, file_stream: bytes) -> str:
        result = mammoth.convert_to_html(
            BytesIO(file_stream),
            convert_image=mammoth.images.img_element(self._image_hook),
            style_map=_LIST_STYLE_MAP,
        )
        # mammoth.messages 为样式映射告警，记数备查但不阻断整篇解析。
        self._mammoth_message_count = len(result.messages)
        return result.value or ""

    def _image_hook(self, image) -> dict:
        # 内嵌图是真内容：取字节 → 按字节 sha1 合成伪 URI → 复用 HTML 模块
        # build_mock_object_url 同款规则生成 mock-minio:// 路径（image_rewriter 零改动）。
        try:
            with image.open() as image_bytes:
                data = image_bytes.read()
            ext = _CONTENT_TYPE_EXT.get((image.content_type or "").lower(), "bin")
            digest = hashlib.sha1(data).hexdigest()
            # 三斜杠使路径段非空，build_mock_object_url 能提取出带扩展名的文件名。
            pseudo_uri = f"docx-embedded:///{digest}.{ext}"
            object_url = HtmlImageRewriter(self._options).build_mock_object_url(pseudo_uri)
            if not object_url:
                raise ValueError("对象路径生成失败")
            return {"src": object_url}
        except Exception:
            # 单图失败不阻断整篇：记 warning + 占位引用。
            self._image_warning_count += 1
            return {"src": "mock-minio://unresolved/word-embedded-image"}

    def _render_html(self, html: str) -> HtmlMarkdownRenderer:
        soup = BeautifulSoup(html, "lxml")
        # 复用 HTML 模块的噪声/注释清理；不调用 HtmlParseService.parse，
        # 因其内置 trafilatura 正文定位针对网页样板，对 Word（整篇即正文）不适用。
        HtmlParseService()._clean_soup(soup)
        root = soup.body or soup

        renderer = HtmlMarkdownRenderer(self._options)
        markdown = renderer.render_children(root)
        if not markdown.strip():
            raise ParseBaseException("Word 解析失败：文档无有效内容")
        self._last_markdown = markdown
        return renderer

    def _build_metadata(self, renderer: HtmlMarkdownRenderer) -> None:
        self.metadata.update(
            {
                "table_count": renderer.table_count,
                "record_table_count": renderer.record_table_count,
                "table_failure_count": renderer.table_failure_count,
                "image_count": renderer.image_count,
                "image_warning_count": self._image_warning_count,
            }
        )
