from __future__ import annotations

import tempfile

import fitz

from src.core.parser.pdf.base import BasePdfBackend
from src.core.parser.pdf.models import PdfBinaryAsset


class NaivePdfBackend(BasePdfBackend):
    name = "naive"

    def parse(self, file_stream: bytes, options=None) -> tuple[str, list[PdfBinaryAsset]]:
        markdown = self._extract_with_pymupdf4llm(file_stream)
        if markdown:
            return markdown, []

        doc = fitz.open(stream=file_stream, filetype="pdf")
        markdown_lines = []
        for page_num, page in enumerate(doc):
            page_markdown = self._extract_page_markdown(page_num, page)
            if page_markdown:
                markdown_lines.append(page_markdown)
        return "\n\n---\n\n".join(markdown_lines), []

    def _extract_with_pymupdf4llm(self, file_stream: bytes) -> str:
        try:
            import pymupdf4llm
        except Exception:
            return ""

        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf") as temp_file:
                temp_file.write(file_stream)
                temp_file.flush()
                markdown = pymupdf4llm.to_markdown(temp_file.name)
                return markdown if isinstance(markdown, str) else ""
        except Exception as exc:
            self.metadata["naive_backend_error"] = str(exc)
            return ""

    def _extract_page_markdown(self, page_num: int, page: fitz.Page) -> str:
        text_blocks = []
        image_block_count = 0

        for block in page.get_text("dict").get("blocks", []):
            block_type = block.get("type")
            if block_type == 1:
                image_block_count += 1
                continue
            if block_type != 0:
                continue

            lines = []
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if line_text:
                    lines.append(line_text)

            if not lines:
                continue

            x0, y0, x1, _ = block["bbox"]
            text_blocks.append({
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "text": "\n".join(lines),
            })

        if not text_blocks:
            if image_block_count:
                return (
                    f"## 第 {page_num + 1} 页\n\n"
                    "> [系统提示] 当前页面主要为图片或流程图，默认解析器未对图片内容执行 OCR。"
                )
            return ""

        text_blocks.sort(key=lambda item: (round(item["y0"], 1), round(item["x0"], 1), round(item["x1"], 1)))

        markdown_lines = [f"## 第 {page_num + 1} 页", ""]
        for block in text_blocks:
            block_text = block["text"].strip()
            if not block_text:
                continue
            if self._is_heading_block(block_text):
                markdown_lines.append(f"### {block_text}")
            else:
                markdown_lines.append(block_text)
            markdown_lines.append("")

        if image_block_count:
            markdown_lines.append(
                "> [系统提示] 当前页面包含图片/流程图，默认文本解析器未提取图片内部文字。"
            )
            markdown_lines.append("")

        return "\n".join(markdown_lines).strip()

    @staticmethod
    def _is_heading_block(text: str) -> bool:
        stripped = text.replace(" ", "")
        if not stripped:
            return False
        if len(stripped) <= 30 and (stripped.startswith(("第", "一", "二", "三", "四", "五", "六", "七", "八", "九")) or stripped.endswith(("方案", "策略", "总结", "问题", "优化", "处理"))):
            return True
        return False
