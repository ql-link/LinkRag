# -*- coding: utf-8 -*-
"""
Markdown 解析器主入口

组合 MarkdownScanner、TableExtractor、ImageExtractor，
提供统一的解析 API。

设计对标 RAGFlow 的 rag/app/naive.py 中的 Markdown.__call__() 方法，
但不包含图片下载、Vision 增强、超链接提取等上层功能。
"""

from .image_extractor import ImageExtractor
from .models import (
    INLINE_IMAGE_DESCRIPTION_PREFIX,
    META_TABLE_SUMMARY,
    META_VISUAL_DESCRIPTION,
    TABLE_MARKER_RE,
    VISION_MARKER_RE,
    ElementType,
    ImageRef,
    MarkdownElement,
    ParseResult,
    TableRef,
)
from .scanner import MarkdownScanner


class MarkdownParser:
    """Markdown 解析器

    将 Markdown 文本解析为结构化的 ParseResult。

    对标 RAGFlow 的 Markdown 类（rag/app/naive.py L575-710），
    简化为仅关注解析，不涉及分片和图片加载。

    用法:
        parser = MarkdownParser()
        result = parser.parse("# Hello\\n\\nWorld\\n\\n| A | B |\\n|--|--|\\n| 1 | 2 |")
        print(result.elements)  # 扁平元素列表
        print(result.tables)    # 提取出的表格
        print(result.images)    # 图片引用
    """

    def __init__(self):
        self._scanner = MarkdownScanner()
        self._image_extractor = ImageExtractor()

    def parse(
        self,
        text: str,
        source_file: str | None = None,
    ) -> ParseResult:
        """完整解析 Markdown 文本

        执行流程对标 RAGFlow Markdown.__call__() L673-710:
        1. 图片 URL 提取
        2. 逐行扫描 → 元素列表 (原生拆出表格)

        与 RAGFlow 的关键差异:
        - RAGFlow 依赖于提前将内容切割/剪切。
        - 本架构采用了原生行扫描识别表格，保证元素的绝对物理位置和类型严谨性。

        Args:
            text: 原始 Markdown 文本
            source_file: 来源文件名（可选，记录到 ParseResult）

        Returns:
            ParseResult 包含 elements, tables, images, source_file
        """
        # ----- 步骤1: 图片 URL 提取 -----
        images = self._image_extractor.extract(text)

        # ----- 步骤2: 逐行扫描 -----
        elements = self._scanner.scan(text)

        # ----- 步骤2.5: 解码增强描述 -----
        # 增强阶段把图片/表格描述编码成内联标记写进 content，经 to_markdown() 拼回字符串、
        # 重新 parse() 后这些标记被切成独立段落。此处把它们归位为结构化字段并从 content 剥离。
        # 无标记文档为 no-op。
        elements = self._decode_descriptions(elements, images)

        # ----- 步骤3: 提取表格供外部 Pipeline 使用 -----
        tables = [
            TableRef(content=e.content, start_line=e.start_line, end_line=e.end_line)
            for e in elements
            if e.type == ElementType.TABLE
        ]

        return ParseResult(
            elements=elements,
            tables=tables,
            images=images,
            source_file=source_file,
            remainder=text,
        )

    def _decode_descriptions(
        self,
        elements: list[MarkdownElement],
        images: list[ImageRef],
    ) -> list[MarkdownElement]:
        """把游离的增强描述标记段落归位为结构化字段，并剔除这些段落。

        归位规则：
        - 视觉描述 ``[视觉描述|src=<url>: desc]``：用 ``src`` 的 url 精确定位「拥有」该 url
          的元素（其行号范围包含该图片行）。
          - 独立图（owner 为 IMAGE 元素）：把 desc 写入 ``visual_description`` 字段并消化标记段落
            （IMAGE 视图是 derived 锚点，可携带字段/语义）。
          - 内联图（owner 为含该图的 PARAGRAPH）：把游离标记段落**改写为干净的可读描述段落**
            ``图片说明：desc``。普通段落视图在 mixed chunk 中必须精确还原自身 content，故内联描述
            不能塞进段落字段后回注（会破坏还原校验），而是以正文形式独立留存——对检索可见、
            往返稳定（``图片说明：`` 不是标记，不会被再次解码）。
          - url 必须是文档内真实存在的图片（``valid_urls``），否则视为正文巧合，保留原样（防误解码）。
        - 表格总结 ``[表格总结: desc]``：绑定到紧邻前一个 TABLE 元素（单表无 url）。

        无标记时为 no-op，不改变 elements。

        Args:
            elements: 扫描产物。
            images: 文档图片引用（提供 url->line 与合法 url 集合）。

        Returns:
            list[MarkdownElement]: 归位并剔除已消化标记段落后的元素列表。
        """
        if not elements:
            return elements

        valid_urls = {img.url for img in images if img.url}

        # url -> 拥有该 url 的元素索引（行号范围包含图片行的那个元素）。
        url_owner: dict[str, int] = {}
        for img in images:
            if not img.url or img.url in url_owner:
                continue
            for idx, element in enumerate(elements):
                if element.start_line <= img.line <= element.end_line:
                    url_owner[img.url] = idx
                    break

        consumed: set[int] = set()
        # 最近的非标记元素索引，供表格总结「紧邻前驱」绑定。
        prev_real_index: int | None = None

        for idx, element in enumerate(elements):
            if element.type != ElementType.PARAGRAPH:
                prev_real_index = idx
                continue

            stripped = element.content.strip()

            vision_match = VISION_MARKER_RE.match(stripped)
            if vision_match:
                url = vision_match.group("url").strip()
                desc = vision_match.group("desc").strip()
                owner_index = url_owner.get(url)
                if url in valid_urls and owner_index is not None:
                    owner = elements[owner_index]
                    if owner.type == ElementType.IMAGE:
                        owner.metadata[META_VISUAL_DESCRIPTION] = desc
                        consumed.add(idx)
                        continue
                    if owner.type == ElementType.PARAGRAPH:
                        # 内联图：把游离标记段落改写为干净可读的描述段落，保留在流中。
                        element.content = f"{INLINE_IMAGE_DESCRIPTION_PREFIX}{desc}"
                        prev_real_index = idx
                        continue
                # 非法 src / 无主：保留为普通段落（防误解码）。
                prev_real_index = idx
                continue

            table_match = TABLE_MARKER_RE.match(stripped)
            if table_match:
                desc = table_match.group("desc").strip()
                if (
                    prev_real_index is not None
                    and elements[prev_real_index].type == ElementType.TABLE
                ):
                    elements[prev_real_index].metadata[META_TABLE_SUMMARY] = desc
                    consumed.add(idx)
                    continue
                prev_real_index = idx
                continue

            prev_real_index = idx

        if not consumed:
            return elements
        return [element for i, element in enumerate(elements) if i not in consumed]

    def parse_flat(self, text: str) -> list[MarkdownElement]:
        """仅扫描: 文本 → 扁平元素列表 (不提取图片)

        轻量级接口，等价于直接调用 MarkdownScanner.scan()

        Args:
            text: 原始 Markdown 文本

        Returns:
            按文档顺序排列的 MarkdownElement 列表
        """
        return self._scanner.scan(text)

    def parse_images(self, text: str) -> list[ImageRef]:
        """仅提取图片引用

        Args:
            text: 原始 Markdown 文本

        Returns:
            图片引用列表
        """
        return self._image_extractor.extract(text)

    def parse_file(
        self,
        filepath: str,
        encoding: str = "utf-8",
    ) -> ParseResult:
        """解析 Markdown 文件

        Args:
            filepath: 文件路径
            encoding: 文件编码，默认为 utf-8

        Returns:
            ParseResult
        """
        with open(filepath, "r", encoding=encoding, errors="ignore") as f:
            text = f.read()

        return self.parse(text, source_file=filepath)
