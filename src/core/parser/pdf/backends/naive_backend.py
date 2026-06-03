from __future__ import annotations

import re
from pathlib import Path

import fitz

from src.core.parser.pdf.base import BasePdfBackend
from src.core.parser.pdf.models import PdfBinaryAsset


class NaivePdfBackend(BasePdfBackend):
    name = "naive"
    PICTURE_TEXT_BLOCK_PATTERN = re.compile(
        r"\*\*-----\s*Start of picture text\s*-----\*\*<br>\s*.*?"
        r"\*\*-----\s*End of picture text\s*-----\*\*<br>",
        re.IGNORECASE | re.DOTALL,
    )

    def parse(self, source: Path | None, options=None) -> tuple[str, list[PdfBinaryAsset]]:
        # ``source is None`` 仅在 MinerU 旁路出现，且本 backend 不会被旁路选中调用；
        # 防御性返回空，让上层 fallback 决策。
        if source is None:
            return "", []
        markdown = self._extract_with_pymupdf4llm(source)
        if markdown:
            return self._postprocess_markdown(markdown), []

        # 用 ``filename=`` 走 mmap，避免一次性把整份 PDF 读进内存。
        doc = fitz.open(filename=str(source))
        markdown_lines = []
        for page_num, page in enumerate(doc):
            page_markdown = self._extract_page_markdown(page_num, page)
            if page_markdown:
                markdown_lines.append(page_markdown)
        return "\n\n---\n\n".join(markdown_lines), []

    def _remove_picture_text_blocks(self, markdown: str) -> str:
        cleaned = self.PICTURE_TEXT_BLOCK_PATTERN.sub("", markdown)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    def _postprocess_markdown(self, markdown: str) -> str:
        markdown = self._remove_picture_text_blocks(markdown)
        markdown = self._merge_split_tables(markdown)
        markdown = self._normalize_numbered_lists(markdown)
        return re.sub(r"\n{3,}", "\n\n", markdown).strip()

    def _merge_split_tables(self, markdown: str) -> str:
        lines = markdown.splitlines()
        result: list[str] = []
        index = 0

        while index < len(lines):
            if not self._is_table_start(lines, index):
                result.append(lines[index])
                index += 1
                continue

            table_lines, index = self._consume_table(lines, index)
            while True:
                lookahead = index
                blank_lines: list[str] = []
                while lookahead < len(lines) and not lines[lookahead].strip():
                    blank_lines.append(lines[lookahead])
                    lookahead += 1

                if not self._is_table_start(lines, lookahead):
                    result.extend(table_lines)
                    result.extend(blank_lines)
                    index = lookahead
                    break

                next_table_lines, next_index = self._consume_table(lines, lookahead)
                if not self._same_table_header(table_lines, next_table_lines):
                    result.extend(table_lines)
                    result.extend(blank_lines)
                    table_lines = next_table_lines
                    index = next_index
                    continue

                table_lines.extend(next_table_lines[2:])
                index = next_index

        return "\n".join(result)

    def _consume_table(self, lines: list[str], start: int) -> tuple[list[str], int]:
        index = start
        table_lines = []
        while index < len(lines) and self._is_table_line(lines[index]):
            table_lines.append(lines[index])
            index += 1
        return table_lines, index

    def _is_table_start(self, lines: list[str], index: int) -> bool:
        return (
            index + 1 < len(lines)
            and self._is_table_line(lines[index])
            and self._is_table_separator(lines[index + 1])
        )

    @staticmethod
    def _is_table_line(line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3

    @staticmethod
    def _is_table_separator(line: str) -> bool:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            return False
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)

    def _same_table_header(self, first: list[str], second: list[str]) -> bool:
        if len(first) < 2 or len(second) < 2:
            return False
        return self._normalize_table_row(first[0]) == self._normalize_table_row(second[0])

    @staticmethod
    def _normalize_table_row(row: str) -> list[str]:
        return [
            re.sub(r"\s+", "", cell.replace("<br>", ""))
            for cell in row.strip().strip("|").split("|")
        ]

    def _normalize_numbered_lists(self, markdown: str) -> str:
        normalized_lines = []
        pending_first_level_marker = False

        for raw_line in markdown.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()

            if stripped in {"- 一", "- －", "- —"}:
                pending_first_level_marker = True
                continue

            if pending_first_level_marker and re.match(r"^-\s*1\.\s+", stripped):
                line = re.sub(r"（\s*级评论\s*）", "（一级评论）", line)
                pending_first_level_marker = False
            elif stripped:
                pending_first_level_marker = False

            line = re.sub(r"^(\s*)-\s+(\d+\.\s+)", r"\1\2", line)
            line = re.sub(r"\s+（", "（", line)
            line = re.sub(r"（\s*", "（", line)
            line = re.sub(r"\s*）", "）", line)

            if re.match(r"^\s*\d+\.\s+", line):
                parts = re.split(r"\s+(?=\d+\.\s+)", line)
                normalized_lines.extend(part.strip() for part in parts if part.strip())
            else:
                normalized_lines.append(line)

        return "\n".join(normalized_lines)

    def _extract_with_pymupdf4llm(self, source: Path) -> str:
        try:
            import pymupdf4llm
        except Exception:
            return ""

        try:
            # pymupdf4llm 原生支持基于路径，无需再落一份临时拷贝。
            markdown = pymupdf4llm.to_markdown(str(source))
            return markdown if isinstance(markdown, str) else ""
        except Exception as exc:
            self.metadata["naive_backend_error"] = str(exc)
            return ""

    def _extract_page_markdown(self, page_num: int, page: fitz.Page) -> str:
        ordered_blocks = []
        image_block_count = 0

        for block in page.get_text("dict").get("blocks", []):
            block_type = block.get("type")
            x0, y0, x1, _ = block["bbox"]
            if block_type == 1:
                image_block_count += 1
                ordered_blocks.append(
                    {
                        "kind": "image",
                        "x0": x0,
                        "y0": y0,
                        "x1": x1,
                        "text": (
                            f"**==> picture page {page_num + 1} image "
                            f"{image_block_count} intentionally omitted <==**"
                        ),
                    }
                )
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

            ordered_blocks.append(
                {
                    "kind": "text",
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "text": "\n".join(lines),
                }
            )

        if not ordered_blocks:
            if image_block_count:
                return f"## 第 {page_num + 1} 页"
            return ""

        ordered_blocks.sort(
            key=lambda item: (round(item["y0"], 1), round(item["x0"], 1), round(item["x1"], 1))
        )

        markdown_lines = [f"## 第 {page_num + 1} 页", ""]
        for block in ordered_blocks:
            block_text = block["text"].strip()
            if not block_text:
                continue
            if block["kind"] == "text" and self._is_heading_block(block_text):
                markdown_lines.append(f"### {block_text}")
            else:
                markdown_lines.append(block_text)
            markdown_lines.append("")

        return "\n".join(markdown_lines).strip()

    @staticmethod
    def _is_heading_block(text: str) -> bool:
        stripped = text.replace(" ", "")
        if not stripped:
            return False
        if len(stripped) <= 30 and (
            stripped.startswith(("第", "一", "二", "三", "四", "五", "六", "七", "八", "九"))
            or stripped.endswith(("方案", "策略", "总结", "问题", "优化", "处理"))
        ):
            return True
        return False
