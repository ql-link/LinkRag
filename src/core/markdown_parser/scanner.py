# -*- coding: utf-8 -*-
"""
Markdown 逐行扫描器

将 Markdown 文本按行扫描，识别各种块级元素并输出扁平的 MarkdownElement 列表。

核心逻辑来自 RAGFlow 的 deepdoc/parser/markdown_parser.py 中的
MarkdownElementExtractor 类，在其基础上做了以下改进：
1. 输出 MarkdownElement dataclass 而非 dict
2. 增加了 HORIZONTAL_RULE、FRONT_MATTER、IMAGE 的识别
3. 为 HEADING 记录 level，为 CODE_BLOCK 记录 language
4. 不再支持 delimiter 分割模式（那属于分片逻辑，不在本模块范围内）
"""

import re
from .models import ElementType, MarkdownElement


class MarkdownScanner:
    """Markdown 逐行扫描器

    将原始 Markdown 文本解析为有序的 MarkdownElement 列表。

    用法:
        scanner = MarkdownScanner()
        elements = scanner.scan("# Hello\\n\\nWorld")
    """

    # ----- 行级正则 -----
    # 来自 RAGFlow MarkdownElementExtractor.extract_elements() L176
    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

    # 来自 RAGFlow L186
    _UNORDERED_LIST_RE = re.compile(r"^\s*[-*+]\s+.*$")
    _ORDERED_LIST_RE = re.compile(r"^\s*\d+\.\s+.*$")

    # 新增：水平线识别
    _HR_RE = re.compile(r"^\s*([-*_])\s*\1\s*\1[\s\1]*$")

    # 新增：独立图片行识别 (![alt](url) 独占一行)
    _IMAGE_LINE_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")

    # 新增：YAML front matter 边界
    _FRONT_MATTER_FENCE = re.compile(r"^---\s*$")

    # 新增：表头分隔线正则 (支持 |---| 或 ---|--- 甚至 :---:)
    _TABLE_DELIMITER_RE = re.compile(r"^\s*\|?\s*[:-]+[-| :]*\s*\|?\s*$")

    # 新增：公式块识别
    _MATH_BLOCK_START_RE = re.compile(r"^\s*(\$\$|\\\[)(.*?)$")

    def scan(self, text: str) -> list[MarkdownElement]:
        """扫描 Markdown 文本，返回扁平元素列表

        Args:
            text: 原始 Markdown 文本

        Returns:
            按文档顺序排列的 MarkdownElement 列表
        """
        self._lines = text.split("\n")
        elements: list[MarkdownElement] = []

        i = 0

        # ----- YAML Front Matter 检测（必须在文件开头）-----
        if i < len(self._lines) and self._FRONT_MATTER_FENCE.match(self._lines[i]):
            element = self._extract_front_matter(i)
            if element is not None:
                elements.append(element)
                i = element.end_line + 1

        # ----- 主扫描循环 -----
        # 整体结构复刻自 RAGFlow MarkdownElementExtractor.extract_elements() L173-202
        while i < len(self._lines):
            line = self._lines[i]

            # 空行跳过
            if not line.strip():
                i += 1
                continue

            # 水平线 (新增, RAGFlow 不识别)
            if self._HR_RE.match(line):
                elements.append(MarkdownElement(
                    type=ElementType.HORIZONTAL_RULE,
                    content=line,
                    start_line=i,
                    end_line=i,
                ))
                i += 1

            # 标题 — 来自 RAGFlow L176
            elif self._HEADING_RE.match(line):
                element = self._extract_heading(i)
                elements.append(element)
                i = element.end_line + 1

            # 围栏代码块 — 来自 RAGFlow L181
            elif line.strip().startswith("```"):
                element = self._extract_code_block(i)
                elements.append(element)
                i = element.end_line + 1
                
            # 公式块 (新增)
            elif self._MATH_BLOCK_START_RE.match(line):
                element = self._extract_math_block(i)
                elements.append(element)
                i = element.end_line + 1

            # 独立图片行 (新增)
            elif self._IMAGE_LINE_RE.match(line):
                element = self._extract_image(i)
                elements.append(element)
                i = element.end_line + 1

            # 表格探测 (新增: 直接原生支持 TABLE 切分)
            elif "|" in line:
                table_element = self._extract_table(i)
                if table_element:
                    elements.append(table_element)
                    i = table_element.end_line + 1
                    continue
                # 如果不是表格，则顺延到可能成为 list 或者 blockquote，甚至是段落。

            # 列表块 — 来自 RAGFlow L186
            elif self._UNORDERED_LIST_RE.match(line) or self._ORDERED_LIST_RE.match(line):
                element = self._extract_list_block(i)
                elements.append(element)
                i = element.end_line + 1

            # 引用块 — 来自 RAGFlow L191
            elif line.strip().startswith(">"):
                element = self._extract_blockquote(i)
                elements.append(element)
                i = element.end_line + 1

            # 段落（兜底）— 来自 RAGFlow L196
            else:
                element = self._extract_paragraph(i)
                elements.append(element)
                i = element.end_line + 1

        # 过滤空 content — 来自 RAGFlow L204-207
        elements = [e for e in elements if e.content.strip()]
        return elements

    # ===== 元素提取方法 =====

    def _extract_heading(self, start: int) -> MarkdownElement:
        """提取标题元素

        来自 RAGFlow MarkdownElementExtractor._extract_header() L210-216
        改进: 解析 heading level 并记录到 metadata
        """
        m = self._HEADING_RE.match(self._lines[start])
        level = len(m.group(1))  # '#' 的数量即 level
        return MarkdownElement(
            type=ElementType.HEADING,
            content=self._lines[start],
            start_line=start,
            end_line=start,
            metadata={"heading_level": level, "heading_text": m.group(2).strip()},
        )

    def _extract_code_block(self, start: int) -> MarkdownElement:
        """提取围栏代码块

        来自 RAGFlow MarkdownElementExtractor._extract_code_block() L218-234
        改进: 解析语言标签并记录到 metadata
        """
        first_line = self._lines[start].strip()
        # 提取语言标签: ```python → "python"
        language = first_line[3:].strip() if len(first_line) > 3 else ""

        end = start
        content_lines = [self._lines[start]]

        # 向下扫描直到遇到关闭的 ```
        for i in range(start + 1, len(self._lines)):
            content_lines.append(self._lines[i])
            end = i
            if self._lines[i].strip().startswith("```"):
                break

        return MarkdownElement(
            type=ElementType.CODE_BLOCK,
            content="\n".join(content_lines),
            start_line=start,
            end_line=end,
            metadata={"language": language} if language else {},
        )

    def _extract_list_block(self, start: int) -> MarkdownElement:
        """提取列表块

        来自 RAGFlow MarkdownElementExtractor._extract_list_block() L236-263
        逻辑完全保留: 持续吞入列表项、空行间隙、缩进续行。
        """
        end = start
        content_lines = []

        i = start
        while i < len(self._lines):
            line = self._lines[i]
            if (
                self._UNORDERED_LIST_RE.match(line)
                or self._ORDERED_LIST_RE.match(line)
                or (i > start and not line.strip())
                or (i > start and re.match(r"^\s{2,}[-*+]\s+.*$", line))
                or (i > start and re.match(r"^\s{2,}\d+\.\s+.*$", line))
                or (i > start and re.match(r"^\s+\w+.*$", line))
            ):
                content_lines.append(line)
                end = i
                i += 1
            else:
                break

        return MarkdownElement(
            type=ElementType.LIST,
            content="\n".join(content_lines),
            start_line=start,
            end_line=end,
        )

    def _extract_blockquote(self, start: int) -> MarkdownElement:
        """提取引用块

        来自 RAGFlow MarkdownElementExtractor._extract_blockquote() L265-284
        """
        end = start
        content_lines = []

        i = start
        while i < len(self._lines):
            line = self._lines[i]
            if line.strip().startswith(">") or (i > start and not line.strip()):
                content_lines.append(line)
                end = i
                i += 1
            else:
                break

        return MarkdownElement(
            type=ElementType.BLOCKQUOTE,
            content="\n".join(content_lines),
            start_line=start,
            end_line=end,
        )

    def _extract_paragraph(self, start: int) -> MarkdownElement:
        """提取段落（兜底）

        改进自 RAGFlow MarkdownElementExtractor._extract_text_block() L286-321
        RAGFlow 的实现会跨越空行继续吞入非块级元素行，导致表格移除后
        留下的空白区域被跨越，将不相关的段落合并。
        改进: 遇到空行即截止，符合标准 Markdown 段落语义。
        """
        end = start
        content_lines = [self._lines[start]]

        i = start + 1
        while i < len(self._lines):
            line = self._lines[i]

            # 空行截止段落
            if not line.strip():
                break

            # 遇到块级元素标志则停止
            if (
                self._HEADING_RE.match(line)
                or line.strip().startswith("```")
                or self._MATH_BLOCK_START_RE.match(line)
                or self._UNORDERED_LIST_RE.match(line)
                or self._ORDERED_LIST_RE.match(line)
                or line.strip().startswith(">")
                or self._HR_RE.match(line)
                or self._IMAGE_LINE_RE.match(line)
            ):
                break
                
            # 若下一行突然有了 |---| 表格符，则说明表格开始了，应该切断当前段落
            if "|" in line:
                if i + 1 < len(self._lines) and self._TABLE_DELIMITER_RE.match(self._lines[i + 1]):
                    break

            content_lines.append(line)
            end = i
            i += 1

        return MarkdownElement(
            type=ElementType.PARAGRAPH,
            content="\n".join(content_lines),
            start_line=start,
            end_line=end,
        )

    def _extract_image(self, start: int) -> MarkdownElement:
        """提取独立图片行 (新增, RAGFlow 不单独识别)"""
        m = self._IMAGE_LINE_RE.match(self._lines[start])
        return MarkdownElement(
            type=ElementType.IMAGE,
            content=self._lines[start],
            start_line=start,
            end_line=start,
            metadata={"alt": m.group(1), "url": m.group(2)},
        )

    def _extract_table(self, start: int) -> MarkdownElement | None:
        """提取表格块 (原生行扫描)
        
        通过识别当前行含有 `|`，且下一行匹配 `_TABLE_DELIMITER_RE` 即确认为表格，并持续吃入直至断开。
        """
        if start + 1 >= len(self._lines):
            return None
            
        l1 = self._lines[start]
        l2 = self._lines[start + 1]
        
        # 必须都包含管线符号，且下一行是标准的头部分隔符
        if "|" not in l1 or "|" not in l2:
            return None
            
        if not self._TABLE_DELIMITER_RE.match(l2):
            return None
            
        end = start
        content_lines = []
        for i in range(start, len(self._lines)):
            line = self._lines[i]
            # 当遇到空行、或不再包含管线符时，判定表格结束。
            # 通常标准化 Markdown 表格中间没有空行。
            if not line.strip() or "|" not in line:
                break
            content_lines.append(line)
            end = i
            
        if len(content_lines) >= 2:
            return MarkdownElement(
                type=ElementType.TABLE,
                content="\n".join(content_lines),
                start_line=start,
                end_line=end,
            )
        return None

    def _extract_front_matter(self, start: int) -> MarkdownElement | None:
        """提取 YAML front matter (新增)

        YAML front matter 必须在文件第一行以 --- 开头，
        到下一个 --- 结束。
        """
        if start != 0:
            return None

        for i in range(start + 1, len(self._lines)):
            if self._FRONT_MATTER_FENCE.match(self._lines[i]):
                content = "\n".join(self._lines[start : i + 1])
                return MarkdownElement(
                    type=ElementType.FRONT_MATTER,
                    content=content,
                    start_line=start,
                    end_line=i,
                )
        return None  # 没有找到关闭的 ---

    def _extract_math_block(self, start: int) -> MarkdownElement:
        """提取块级公式（支持 $$ 或者 \\[ 开头）"""
        m = self._MATH_BLOCK_START_RE.match(self._lines[start])
        delimiter = m.group(1)
        closing_delimiter = r"\]" if delimiter == r"\[" else "$$"
        
        # 探测是否为单行公式块 (例如：$$ E=mc^2 $$)
        line_stripped = self._lines[start].strip()
        if len(line_stripped) > len(delimiter) and line_stripped.endswith(closing_delimiter):
            return MarkdownElement(
                type=ElementType.MATH_BLOCK,
                content=self._lines[start],
                start_line=start,
                end_line=start
            )
            
        end = start
        content_lines = [self._lines[start]]
        for i in range(start + 1, len(self._lines)):
            line = self._lines[i]
            content_lines.append(line)
            end = i
            # 公式块闭合只要包含对应的符号即可（宽松匹配以增加容错）
            if closing_delimiter in line:
                break
                
        return MarkdownElement(
            type=ElementType.MATH_BLOCK,
            content="\n".join(content_lines),
            start_line=start,
            end_line=end
        )
