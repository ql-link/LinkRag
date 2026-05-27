import re
from html import escape

from bs4 import NavigableString, Tag

from .image_rewriter import HtmlImageRewriter
from .models import HtmlParseOptions
from .table_processor import HtmlTableProcessor


class HtmlMarkdownRenderer:
    """Render cleaned BeautifulSoup nodes to Markdown in DOM order."""

    CONTAINER_TAGS = {
        "html",
        "body",
        "main",
        "article",
        "section",
        "div",
        "header",
        "footer",
        "aside",
        "nav",
    }

    def __init__(self, options: HtmlParseOptions):
        self.options = options
        self.image_rewriter = HtmlImageRewriter(options)
        self.table_processor = HtmlTableProcessor(self.image_rewriter)
        self.table_count = 0
        self.record_table_count = 0
        self.table_failure_count = 0
        self.table_split_count = 0
        self.image_count = 0
        self.image_upload_count = 0
        self.warnings: list[str] = []

    def render_children(self, node: Tag) -> str:
        parts = [self.render_node(child) for child in node.children]
        return self._join_blocks(parts)

    def render_node(self, node) -> str:
        if isinstance(node, NavigableString):
            return self._clean_inline_text(str(node))
        if not isinstance(node, Tag):
            return ""

        name = node.name.lower()
        if name in self.CONTAINER_TAGS:
            return self.render_children(node)
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(name[1])
            text = self.render_inline_children(node)
            return f"{'#' * level} {text}" if text else ""
        if name == "p":
            return self.render_inline_children(node)
        if name in {"ul", "ol"}:
            return self.render_list(node, ordered=name == "ol")
        if name == "pre":
            return self.render_code_block(node)
        if name == "blockquote":
            return self.render_blockquote(node)
        if name == "br":
            return "\n"
        if name == "hr":
            return "---"
        if name == "img":
            result = self.image_rewriter.rewrite_img(node)
            self.image_count += 1
            if result.object_url:
                self.image_upload_count += 0
            if result.warning:
                self.warnings.append(result.warning)
            return result.markdown
        if name == "figure":
            body_parts = [
                self.render_node(child)
                for child in node.children
                if not (isinstance(child, Tag) and child.name.lower() == "figcaption")
            ]
            caption = node.find("figcaption", recursive=False)
            rendered = self._join_blocks(body_parts)
            if caption:
                caption_text = self.render_inline_children(caption)
                if caption_text:
                    rendered = self._join_blocks([rendered, f"图注：{caption_text}"])
            return rendered
        if name == "table":
            result = self.table_processor.render(node)
            self.table_count += 1
            if result.strategy == "record_markdown":
                self.record_table_count += 1
            elif result.strategy == "failure":
                self.table_failure_count += 1
            self.image_count += result.image_count
            self.warnings.extend(result.warnings)
            if result.warning:
                self.warnings.append(result.warning)
            return result.markdown
        if name in {"script", "style", "noscript", "template"}:
            return ""
        if name == "code":
            return f"`{self._clean_inline_text(node.get_text(' ', strip=True))}`"
        return self.render_inline_children(node) or self.render_children(node)

    def render_inline_children(self, node: Tag) -> str:
        parts = [self.render_inline(child) for child in node.children]
        return self._clean_inline_text("".join(parts))

    def render_inline(self, node) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""

        name = node.name.lower()
        if name == "br":
            return "\n"
        if name == "a":
            text = self.render_inline_children(node) or self._clean_inline_text(
                node.get_text(" ", strip=True)
            )
            href = self.image_rewriter.resolve_url(str(node.get("href", "")).strip())
            return f"[{text}]({href})" if href else text
        if name == "img":
            result = self.image_rewriter.rewrite_img(node)
            self.image_count += 1
            if result.warning:
                self.warnings.append(result.warning)
            return result.markdown
        if name in {"strong", "b"}:
            text = self.render_inline_children(node)
            return f"**{text}**" if text else ""
        if name in {"em", "i"}:
            text = self.render_inline_children(node)
            return f"*{text}*" if text else ""
        if name == "code":
            text = self._clean_inline_text(node.get_text(" ", strip=True))
            return f"`{text}`" if text else ""
        if name in {"script", "style", "noscript", "template"}:
            return ""
        return self.render_inline_children(node)

    def render_list(self, node: Tag, ordered: bool) -> str:
        lines: list[str] = []
        for index, li in enumerate(node.find_all("li", recursive=False), start=1):
            marker = f"{index}." if ordered else "-"
            content = self._join_blocks([self.render_node(child) for child in li.children])
            content_lines = content.splitlines() or [""]
            lines.append(f"{marker} {content_lines[0].strip()}")
            for continuation in content_lines[1:]:
                lines.append(f"  {continuation}".rstrip())
        return "\n".join(lines)

    def render_blockquote(self, node: Tag) -> str:
        # 代码块不能被 "> " 行前缀包裹，否则 fenced code 围栏失效（实测阮一峰样本）。
        # 因此按子节点切分：pre/code 作为独立块原样输出，其余文本才加引用前缀。
        blocks: list[str] = []
        quoted: list[str] = []

        def flush_quoted() -> None:
            text = self._join_blocks(quoted)
            quoted.clear()
            if text:
                blocks.append(
                    "\n".join(f"> {line}" if line else ">" for line in text.splitlines())
                )

        for child in node.children:
            if isinstance(child, Tag) and child.name.lower() == "pre":
                flush_quoted()
                blocks.append(self.render_code_block(child))
            else:
                quoted.append(self.render_node(child))
        flush_quoted()
        return self._join_blocks(blocks)

    def render_code_block(self, node: Tag) -> str:
        code = node.find("code")
        language = ""
        if code:
            classes = code.get("class", [])
            for class_name in classes:
                if class_name.startswith("language-"):
                    language = class_name.removeprefix("language-")
                    break
            text = code.get_text()
        else:
            text = node.get_text()
        return f"```{escape(language)}\n{text.rstrip()}\n```"

    def _join_blocks(self, parts: list[str]) -> str:
        cleaned = [part.strip() for part in parts if part and part.strip()]
        return "\n\n".join(cleaned)

    def _clean_inline_text(self, text: str) -> str:
        text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
        text = re.sub(r" *\n *", "\n", text)
        return text.strip()
