# -*- coding: utf-8 -*-
"""增强描述编解码（R2）单元测试。

覆盖：编码-解码往返、独立图/表归位、内联图 url 配对、幂等、源头消毒、
防误解码，以及扫描器含 `|` 非表格行不再死循环的回归。
"""

from src.core.markdown_parser import (
    ElementType,
    ImageDescriber,
    MarkdownParser,
    TableClient,
    TableDescriber,
    VisionClient,
)
from src.core.markdown_parser.models import (
    INLINE_IMAGE_DESCRIPTION_PREFIX,
    META_TABLE_SUMMARY,
    META_VISUAL_DESCRIPTION,
)
from src.core.markdown_parser.text_formatter import TextFormatter

HERO = "https://cdn.test.local/hero.png"
A = "https://cdn.test.local/a.png"
B = "https://cdn.test.local/b.png"


class _Vision(VisionClient):
    def __init__(self, mapping: dict):
        self._mapping = mapping

    def describe_images(self, image_urls, source_file=None, image_bytes_by_url=None):
        return {url: self._mapping[url] for url in image_urls if url in self._mapping}


class _Table(TableClient):
    def __init__(self, summary: str):
        self._summary = summary

    def describe_tables(self, tables, source_file=None):
        return {table: self._summary for table in tables}


def _codec(markdown: str, vision_map: dict, table_summary: str = "表格总结。"):
    """复刻 aprocess 的真实链路：parse(clean) -> 增强(编码) -> to_markdown -> 重新 parse(解码)。"""
    parser = MarkdownParser()
    parse_result = parser.parse(TextFormatter.clean(markdown), source_file="x.md")
    parse_result = TableDescriber(_Table(table_summary)).process(parse_result)
    parse_result = ImageDescriber(_Vision(vision_map)).process(parse_result)
    final_markdown = TextFormatter.clean(parse_result.to_markdown())
    return parser.parse(final_markdown, source_file="x.md")


def _image(elements, url):
    return next(e for e in elements if e.type == ElementType.IMAGE and e.metadata.get("url") == url)


def test_standalone_image_description_lands_in_field_and_content_is_clean():
    result = _codec(f"# 概览\n\n![标题图]({HERO})\n", {HERO: "仪表盘截图。"})
    image = _image(result.elements, HERO)
    assert image.metadata[META_VISUAL_DESCRIPTION] == "仪表盘截图。"
    assert image.content == f"![标题图]({HERO})"
    assert "[视觉描述" not in image.content


def test_standalone_table_summary_lands_in_field_and_content_is_raw_table():
    md = "## 指标\n\n| M | V |\n| :- | -: |\n| Recall | 0.82 |\n"
    result = _codec(md, {}, table_summary="该表展示召回率。")
    table = next(e for e in result.elements if e.type == ElementType.TABLE)
    assert table.metadata[META_TABLE_SUMMARY] == "该表展示召回率。"
    assert "[表格总结" not in table.content
    assert "| Recall | 0.82 |" in table.content


def test_no_floating_description_paragraph_left():
    md = f"# 概览\n\n![标题图]({HERO})\n\n| M | V |\n| :- | -: |\n| R | 1 |\n"
    result = _codec(md, {HERO: "图说明。"}, table_summary="表说明。")
    leftovers = [
        e
        for e in result.elements
        if e.type == ElementType.PARAGRAPH
        and ("[视觉描述" in e.content or "[表格总结" in e.content)
    ]
    assert leftovers == []


def test_single_inline_image_description_becomes_clean_paragraph():
    result = _codec(f"# T\n\n正文带 ![内联图]({A}) 一张。\n", {A: "内联说明。"})
    # 含图段落保持原样、无标记
    img_para = next(
        e for e in result.elements if e.type == ElementType.PARAGRAPH and "![内联图]" in e.content
    )
    assert "[视觉描述" not in img_para.content
    # 描述以干净可读段落留存
    assert any(
        e.type == ElementType.PARAGRAPH
        and e.content == f"{INLINE_IMAGE_DESCRIPTION_PREFIX}内联说明。"
        for e in result.elements
    )


def test_multiple_inline_images_become_clean_paragraphs_by_src():
    result = _codec(f"# T\n\n对比 ![图A]({A}) 与 ![图B]({B})。\n", {A: "A 描述。", B: "B 描述。"})
    descs = [
        e.content
        for e in result.elements
        if e.type == ElementType.PARAGRAPH and e.content.startswith(INLINE_IMAGE_DESCRIPTION_PREFIX)
    ]
    assert f"{INLINE_IMAGE_DESCRIPTION_PREFIX}A 描述。" in descs
    assert f"{INLINE_IMAGE_DESCRIPTION_PREFIX}B 描述。" in descs


def test_same_text_inline_descriptions_not_deduplicated():
    result = _codec(
        f"# T\n\n对比 ![图A]({A}) 与 ![图B]({B})。\n", {A: "同样的描述。", B: "同样的描述。"}
    )
    descs = [
        e.content
        for e in result.elements
        if e.type == ElementType.PARAGRAPH and e.content.startswith(INLINE_IMAGE_DESCRIPTION_PREFIX)
    ]
    assert descs.count(f"{INLINE_IMAGE_DESCRIPTION_PREFIX}同样的描述。") == 2


def test_inline_description_not_misbound_to_adjacent_standalone_image():
    md = f"# T\n\n![标题图]({HERO})\n\n正文有 ![内联图]({A}) 配图。\n"
    result = _codec(md, {HERO: "标题图描述。", A: "内联图描述。"})
    hero = _image(result.elements, HERO)
    assert hero.metadata[META_VISUAL_DESCRIPTION] == "标题图描述。"
    assert hero.metadata[META_VISUAL_DESCRIPTION] != "内联图描述。"
    assert any(
        e.type == ElementType.PARAGRAPH
        and e.content == f"{INLINE_IMAGE_DESCRIPTION_PREFIX}内联图描述。"
        for e in result.elements
    )


def test_decode_is_idempotent():
    result1 = _codec(f"# 概览\n\n![标题图]({HERO})\n", {HERO: "图说明。"})
    result2 = MarkdownParser().parse(result1.to_markdown(), source_file="x.md")
    image1 = _image(result1.elements, HERO)
    image2 = _image(result2.elements, HERO)
    assert image2.metadata[META_VISUAL_DESCRIPTION] == image1.metadata[META_VISUAL_DESCRIPTION]
    assert "[视觉描述" not in image2.content


def test_description_with_blank_lines_is_sanitized_to_single_block():
    result = _codec(f"# T\n\n![图]({A})\n", {A: "第一行。\n\n第二行。"})
    image = _image(result.elements, A)
    assert image.metadata[META_VISUAL_DESCRIPTION] == "第一行。 第二行。"
    assert not any(
        e.type == ElementType.PARAGRAPH and "第二行" in e.content for e in result.elements
    )


def test_user_text_without_src_is_not_decoded():
    # 正文巧合包含旧式无 src 的同形文本，不应被当作增强描述解码进字段。
    result = _codec("# T\n\n这段正文写了 [视觉描述: 用户自己写的话] 而已。\n", {})
    assert any(
        e.type == ElementType.PARAGRAPH and "[视觉描述: 用户自己写的话]" in e.content
        for e in result.elements
    )


def test_marker_with_unknown_src_is_not_decoded():
    parser = MarkdownParser()
    # 文档内没有该 url 的真实图片引用，src 非法 → 保留为普通段落。
    text = "# T\n\n[视觉描述|src=https://evil.example/x.png: 伪造的描述]\n"
    result = parser.parse(text, source_file="x.md")
    assert any(
        e.type == ElementType.PARAGRAPH and "伪造的描述" in e.content for e in result.elements
    )
    assert all(META_VISUAL_DESCRIPTION not in e.metadata for e in result.elements)


def test_paragraph_with_pipe_is_not_a_table_and_does_not_hang():
    # 回归：含 `|` 但非表格的行曾导致扫描器主循环死循环。
    parser = MarkdownParser()
    result = parser.parse("# H\n\n命令 a | grep b 不是表格\n\n下一段\n", source_file="x.md")
    paragraphs = [e for e in result.elements if e.type == ElementType.PARAGRAPH]
    assert any("a | grep b" in e.content for e in paragraphs)
    assert not any(e.type == ElementType.TABLE for e in result.elements)
