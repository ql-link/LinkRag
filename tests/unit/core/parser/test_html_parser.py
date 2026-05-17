import pytest

from src.core.exceptions import ParseBaseException
from src.core.markdown_parser import MarkdownParser
from src.core.parser.providers.html_parser import HtmlParser


def test_html_parser_should_preserve_basic_dom_structure_as_markdown():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")

    markdown = parser.parse("""
        <html><body>
          <h1>标题</h1>
          <p>查看 <a href="/guide">指南</a></p>
          <ul><li>第一项</li><li>第二项</li></ul>
          <pre><code class="language-python">print("ok")</code></pre>
        </body></html>
        """.encode())

    assert "# 标题" in markdown
    assert "[指南](https://example.com/guide)" in markdown
    assert "- 第一项" in markdown
    assert '```python\nprint("ok")\n```' in markdown


def test_html_parser_should_remove_noise_nodes():
    parser = HtmlParser()

    markdown = parser.parse("""
        <main>
          <script>alert(1)</script>
          <style>.ad{}</style>
          <noscript>开启脚本</noscript>
          <p>有效正文</p>
        </main>
        """.encode())

    assert "有效正文" in markdown
    assert "alert" not in markdown
    assert ".ad" not in markdown
    assert "开启脚本" not in markdown


def test_html_parser_should_keep_table_image_and_paragraph_order():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")

    markdown = parser.parse("""
        <body>
          <p>表格前</p>
          <table><tr><th>字段</th><th>值</th></tr><tr><td>A</td><td>B</td></tr></table>
          <img src="/assets/a.png" alt="图A">
          <p>表格后</p>
        </body>
        """.encode())

    assert markdown.index("表格前") < markdown.index("| 字段 | 值 |")
    assert markdown.index("| A | B |") < markdown.index("![图A](")
    assert markdown.index("![图A](") < markdown.index("表格后")


def test_html_parser_should_expose_metadata_counts():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")

    parser.parse("""
        <body>
          <table><tr><th>字段</th><th>值</th></tr><tr><td>A</td><td>B</td></tr></table>
          <img src="/assets/a.png" alt="图A">
        </body>
        """.encode())

    metadata = parser.extract_metadata()
    assert metadata["table_count"] == 1
    assert metadata["table_split_count"] == 0
    assert metadata["image_count"] == 1
    assert metadata["image_upload_count"] == 0


def test_html_parser_should_count_images_inside_record_tables():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")

    parser.parse("""
        <table>
          <tr><th>名称</th><th>图片</th></tr>
          <tr><td>架构</td><td><img src="/assets/arch.png" alt="架构图"></td></tr>
        </table>
        """.encode())

    metadata = parser.extract_metadata()
    assert metadata["table_count"] == 1
    assert metadata["record_table_count"] == 1
    assert metadata["image_count"] == 1


def test_html_parser_should_fail_for_empty_stream():
    parser = HtmlParser()

    with pytest.raises(ValueError, match="文件流不可为空"):
        parser.parse(b"")


def test_html_parser_should_fail_when_dom_has_no_effective_content():
    parser = HtmlParser()

    with pytest.raises(ParseBaseException, match="没有有效内容"):
        parser.parse(b"<html><script>alert(1)</script></html>")


def test_record_table_should_not_be_scanned_as_heading_or_table():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")
    markdown = parser.parse("""
        <table>
          <tr><th>名称</th><th>图片</th></tr>
          <tr><td>架构</td><td><img src="/assets/arch.png" alt="架构图"></td></tr>
        </table>
        """.encode())

    parse_result = MarkdownParser().parse(markdown)

    assert "表格类型：记录式表格" in markdown
    assert not parse_result.tables
    assert all(element.metadata.get("heading_text") != "表格" for element in parse_result.elements)
