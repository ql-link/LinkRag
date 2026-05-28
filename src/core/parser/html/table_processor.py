import re
from typing import Literal

from bs4 import Tag

from .image_rewriter import HtmlImageRewriter
from .models import TableRenderResult

TableStrategy = Literal["markdown_table", "record_markdown", "failure"]


class HtmlTableProcessor:
    """Convert HTML tables to Markdown table or explicit record-style blocks."""

    def __init__(self, image_rewriter: HtmlImageRewriter):
        self.image_rewriter = image_rewriter
        self._current_image_count = 0
        self._current_warnings: list[str] = []

    def render(self, table: Tag) -> TableRenderResult:
        self._current_image_count = 0
        self._current_warnings = []
        try:
            strategy, reason = self._classify_table(table)
            if strategy == "record_markdown":
                return TableRenderResult(
                    markdown=self._render_record_markdown(table, reason),
                    strategy=strategy,
                    image_count=self._current_image_count,
                    warnings=list(self._current_warnings),
                )

            headers, rows = self._extract_headers_and_rows(table)
            if not headers and not rows:
                return TableRenderResult(
                    markdown=self._render_record_markdown(table, "没有可表格化的行列内容"),
                    strategy="record_markdown",
                    image_count=self._current_image_count,
                    warnings=list(self._current_warnings),
                )
            return TableRenderResult(
                markdown=self._render_markdown_table(headers, rows),
                strategy="markdown_table",
                image_count=self._current_image_count,
                warnings=list(self._current_warnings),
            )
        except Exception as exc:
            return TableRenderResult(
                markdown=self._render_failure_note(table, exc),
                strategy="failure",
                warning=str(exc),
                image_count=self._current_image_count,
                warnings=list(self._current_warnings),
            )

    def _classify_table(self, table: Tag) -> tuple[TableStrategy, str]:
        if table.find("table"):
            return "record_markdown", "嵌套表格"
        if table.find("img"):
            return "record_markdown", "图片单元格"
        for cell in table.find_all(["td", "th"]):
            block_count = len(cell.find_all(["p", "pre", "blockquote"], recursive=False))
            if block_count > 1:
                return "record_markdown", "多段长文本单元格"
        return "markdown_table", ""

    def _extract_headers_and_rows(self, table: Tag) -> tuple[list[str], list[list[str]]]:
        matrix, header_row_indexes = self._build_matrix(table)
        if not matrix:
            return [], []

        if header_row_indexes:
            header_count = max(header_row_indexes) + 1
        else:
            header_count = 1

        headers = self._flatten_headers(matrix[:header_count])
        data_rows = matrix[header_count:]
        if not data_rows and not header_row_indexes and len(matrix) > 1:
            data_rows = matrix[1:]
        if not data_rows and matrix:
            data_rows = matrix[1:]

        width = max(len(headers), *(len(row) for row in data_rows), 1)
        headers = self._normalize_row(headers, width, default_prefix="列")
        rows = [self._normalize_row(row, width) for row in data_rows]
        return headers, rows

    def _build_matrix(self, table: Tag) -> tuple[list[list[str]], set[int]]:
        matrix: list[list[str]] = []
        occupied: dict[tuple[int, int], str] = {}
        header_row_indexes: set[int] = set()

        rows = self._direct_rows(table)
        for row_index, tr in enumerate(rows):
            output_row: list[str] = []
            col_index = 0
            cells = tr.find_all(["th", "td"], recursive=False)
            if cells and all(cell.name == "th" for cell in cells):
                header_row_indexes.add(row_index)

            for cell in cells:
                while (row_index, col_index) in occupied:
                    output_row.append(occupied.pop((row_index, col_index)))
                    col_index += 1

                text = self._cell_to_text(cell)
                rowspan = self._parse_span(cell.get("rowspan"))
                colspan = self._parse_span(cell.get("colspan"))
                for offset in range(colspan):
                    output_row.append(text)
                    if rowspan > 1:
                        for row_offset in range(1, rowspan):
                            occupied[(row_index + row_offset, col_index + offset)] = text
                col_index += colspan

            while (row_index, col_index) in occupied:
                output_row.append(occupied.pop((row_index, col_index)))
                col_index += 1

            if output_row:
                matrix.append(output_row)

        return matrix, header_row_indexes

    def _flatten_headers(self, header_rows: list[list[str]]) -> list[str]:
        if not header_rows:
            return []

        width = max(len(row) for row in header_rows)
        headers: list[str] = []
        for col_index in range(width):
            parts: list[str] = []
            for row in header_rows:
                value = row[col_index].strip() if col_index < len(row) else ""
                if value and value not in parts:
                    parts.append(value)
            headers.append(" / ".join(parts) if parts else f"列{col_index + 1}")
        return headers

    def _render_markdown_table(self, headers: list[str], rows: list[list[str]]) -> str:
        width = max(len(headers), *(len(row) for row in rows), 1)
        normalized_headers = self._normalize_row(headers, width, default_prefix="列")
        normalized_rows = [self._normalize_row(row, width) for row in rows]

        lines = [
            "| " + " | ".join(self._escape_table_cell(cell) for cell in normalized_headers) + " |",
            "| " + " | ".join("---" for _ in normalized_headers) + " |",
        ]
        for row in normalized_rows:
            lines.append("| " + " | ".join(self._escape_table_cell(cell) for cell in row) + " |")
        return "\n".join(lines)

    def _render_record_markdown(self, table: Tag, reason: str) -> str:
        caption = self._table_caption(table)
        headers, rows = self._extract_record_headers_and_rows(table)

        lines = [
            f"[HTML表格开始：{caption}]",
            "表格类型：记录式表格",
            f"表格说明：该 HTML 表格包含{reason}",
            "表格结构：" + ("、".join(headers) if headers else "未识别出稳定表头"),
            "",
        ]

        for row_index, row in enumerate(rows, start=1):
            lines.append(f"记录 {row_index}：")
            for col_index, value in enumerate(row):
                header = headers[col_index] if col_index < len(headers) else f"列{col_index + 1}"
                lines.append(f"- {header}：{value or '（空）'}")
            lines.append("")

        lines.append(f"[HTML表格结束：{caption}]")
        return "\n".join(lines).strip()

    def _render_failure_note(self, table: Tag, error: Exception) -> str:
        caption = self._table_caption(table)
        summary = self._clean_text(table.get_text(" ", strip=True))[:300]
        lines = [
            f"[HTML表格开始：{caption}]",
            "表格类型：解析失败表格",
            "表格说明：该 HTML 表格解析失败，保留原位置摘要。",
            f"失败原因：{self._clean_text(str(error))[:160]}",
        ]
        if summary:
            lines.append(f"文本摘要：{summary}")
        lines.append(f"[HTML表格结束：{caption}]")
        return "\n".join(lines)

    def _extract_record_headers_and_rows(self, table: Tag) -> tuple[list[str], list[list[str]]]:
        matrix, header_row_indexes = self._build_matrix(table)
        if not matrix:
            return [], []
        header_count = max(header_row_indexes) + 1 if header_row_indexes else 1
        headers = self._flatten_headers(matrix[:header_count])
        rows = matrix[header_count:] or matrix[1:]
        width = max(len(headers), *(len(row) for row in rows), 1)
        return self._normalize_row(headers, width, default_prefix="列"), [
            self._normalize_row(row, width) for row in rows
        ]

    def _cell_to_text(self, cell: Tag) -> str:
        nested = cell.find("table")
        if nested:
            return "嵌套表格：" + self._clean_text(nested.get_text(" ", strip=True))

        images = []
        for img in cell.find_all("img"):
            result = self.image_rewriter.rewrite_img(img)
            self._current_image_count += 1
            if result.warning:
                self._current_warnings.append(result.warning)
            images.append(result.markdown)

        list_items = [self._clean_text(li.get_text(" ", strip=True)) for li in cell.find_all("li")]
        if list_items:
            text = "；".join(item for item in list_items if item)
        else:
            text = self._clean_text(cell.get_text(" ", strip=True))

        if images:
            return self._clean_text(" ".join([text, *images]))
        return text

    def _table_caption(self, table: Tag) -> str:
        caption = table.find("caption")
        text = self._clean_text(caption.get_text(" ", strip=True)) if caption else ""
        return text or "未命名表格"

    def _direct_rows(self, table: Tag) -> list[Tag]:
        rows: list[Tag] = []
        for child in table.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "tr":
                rows.append(child)
            elif child.name in {"thead", "tbody", "tfoot"}:
                rows.extend(child.find_all("tr", recursive=False))
        return rows

    def _normalize_row(
        self, row: list[str], width: int, default_prefix: str | None = None
    ) -> list[str]:
        normalized = list(row[:width])
        while len(normalized) < width:
            if default_prefix:
                normalized.append(f"{default_prefix}{len(normalized) + 1}")
            else:
                normalized.append("")
        return normalized

    def _parse_span(self, raw_value: object) -> int:
        try:
            return max(1, int(str(raw_value or "1")))
        except ValueError:
            return 1

    def _escape_table_cell(self, text: str) -> str:
        return self._clean_text(text).replace("|", "\\|").replace("\n", " ")

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()
