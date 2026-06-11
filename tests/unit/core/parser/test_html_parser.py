"""HtmlParser 端到端用例（trafilatura 混合方案）。

混合方案下解析需真实文章体量：trafilatura 负责正文定位/去样板，定位不到则失败。
故 fixture 用带 article 容器 + 足量正文的现实结构（一轮迷你 fixture 已不再是合法输入）。
"""

import tempfile
from pathlib import Path

import pytest

from src.core.parser.exceptions import ParseBaseException
from src.core.markdown_parser import MarkdownParser
from src.core.parser.providers.html_parser import HtmlParser

# parser 协议为 ``parse(source: Path)``：测试把字节落到临时文件再传路径。
_TMP_DIR = Path(tempfile.mkdtemp(prefix="html-parser-test-"))
_seq = 0


def _as_path(content: bytes) -> Path:
    global _seq
    _seq += 1
    path = _TMP_DIR / f"doc-{_seq}.html"
    path.write_bytes(content)
    return path


# 足量中文正文，确保 trafilatura 判定为主体内容并被文本重合度命中。
PROSE = (
    "本文系统介绍知识库文档解析链路的设计与实现。文档解析是检索增强生成的第一道工序，"
    "解析质量直接决定后续分块、向量化与召回的上限。我们将逐节说明解析流程、结构保真策略"
    "以及与业务系统的集成方式，帮助读者完整理解整个处理链路的来龙去脉。"
) * 2


def _article(body: str) -> Path:
    """把被测结构包进带站点装饰的现实文章页，验证去样板同时保留正文能力。"""
    html = f"""
        <html><body>
          <nav>首页 档案 SiteSearch</nav>
          <article>
            <p>{PROSE}</p>
            {body}
            <p>{PROSE}</p>
          </article>
          <footer>上一篇 下一篇 分类：开发者手册 微博 GitHub License</footer>
        </body></html>
        """.encode()
    return _as_path(html)


def test_html_parser_should_preserve_basic_dom_structure_as_markdown():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")

    markdown = parser.parse(
        _article(
            "<h1>主标题</h1>"
            '<p>这是正文段落，查看 <a href="/docs/api">接口文档</a> 获取细节。</p>'
            "<ul><li>第一项</li><li>第二项</li></ul>"
            '<pre><code class="language-python">print("ok")</code></pre>'
        )
    )

    assert "# 主标题" in markdown
    assert "这是正文段落" in markdown
    assert "[接口文档](https://example.com/docs/api)" in markdown
    assert "- 第一项" in markdown
    assert '```python\nprint("ok")\n```' in markdown
    assert parser.extract_metadata()["content_located"] is True


def test_html_parser_should_remove_noise_nodes_and_site_chrome():
    parser = HtmlParser()

    markdown = parser.parse(
        _article(
            "<script>console.log(1)</script>"
            "<style>.hidden{}</style>"
            "<noscript>noscript fallback</noscript>"
            "<template>template text</template>"
            "<p>有效知识内容标记段落</p>"
        )
    )

    assert "有效知识内容标记段落" in markdown
    assert "console.log" not in markdown
    assert ".hidden" not in markdown
    assert "noscript fallback" not in markdown
    assert "template text" not in markdown
    # 容器外站点装饰被 trafilatura 去样板剔除
    assert "SiteSearch" not in markdown
    assert "上一篇" not in markdown
    assert "分类：开发者手册" not in markdown


def test_html_parser_should_keep_table_image_and_paragraph_order():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")

    markdown = parser.parse(
        _article(
            "<p>表格前说明段落</p>"
            "<table><tr><th>字段</th><th>值</th></tr><tr><td>A</td><td>B</td></tr></table>"
            '<img src="/assets/a.png" alt="图A">'
            "<p>表格后说明段落</p>"
        )
    )

    assert markdown.index("表格前说明段落") < markdown.index("| 字段 | 值 |")
    assert markdown.index("| A | B |") < markdown.index("![图A](")
    assert markdown.index("![图A](") < markdown.index("表格后说明段落")


def test_html_parser_should_expose_metadata_counts():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")

    parser.parse(
        _article(
            "<table><tr><th>字段</th><th>值</th></tr><tr><td>A</td><td>B</td></tr></table>"
            '<img src="/assets/a.png" alt="图A">'
        )
    )

    metadata = parser.extract_metadata()
    assert metadata["table_count"] == 1
    assert metadata["table_split_count"] == 0
    assert metadata["image_count"] == 1
    assert metadata["image_upload_count"] == 0
    assert metadata["content_locator_fallback"] in {"matched", "semantic_container", "full_body"}


def test_html_parser_should_count_images_inside_record_tables():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")

    parser.parse(
        _article(
            "<table>"
            "<tr><th>名称</th><th>图片</th></tr>"
            '<tr><td>架构</td><td><img src="/assets/arch.png" alt="架构图"></td></tr>'
            "</table>"
        )
    )

    metadata = parser.extract_metadata()
    assert metadata["table_count"] == 1
    assert metadata["record_table_count"] == 1
    assert metadata["image_count"] == 1


def test_html_parser_should_fail_for_empty_stream():
    parser = HtmlParser()

    with pytest.raises(ValueError, match="文件流不可为空"):
        parser.parse(_as_path(b""))


def test_html_parser_should_fail_when_no_main_content_located():
    parser = HtmlParser()

    # 纯脚本/无正文 → trafilatura 返回 None → 抛解析异常（经 pipeline 映射 PARSE_ENGINE_FAILED）。
    with pytest.raises(ParseBaseException, match="正文"):
        parser.parse(
            _as_path(b"<html><body><div id='root'></div><script>window.x=1</script></body></html>")
        )


def test_html_parser_should_remove_html_comments_including_base64():
    parser = HtmlParser()

    markdown = parser.parse(
        _article(
            "<p>注释删除验证正文</p>"
            '<!-- div class="asset-body" -->'
            '<!--img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg" -->'
        )
    )

    assert "注释删除验证正文" in markdown
    assert 'div class="asset-body"' not in markdown
    assert "iVBORw0KGgo" not in markdown
    assert parser.extract_metadata()["comment_removed_count"] >= 2


def test_record_table_should_not_be_scanned_as_heading_or_table():
    parser = HtmlParser(source_file_url="https://example.com/docs/page.html")
    markdown = parser.parse(
        _article(
            "<table>"
            "<tr><th>名称</th><th>图片</th></tr>"
            '<tr><td>架构</td><td><img src="/assets/arch.png" alt="架构图"></td></tr>'
            "</table>"
        )
    )

    parse_result = MarkdownParser().parse(markdown)

    assert "表格类型：记录式表格" in markdown
    assert not parse_result.tables
    assert all(element.metadata.get("heading_text") != "表格" for element in parse_result.elements)
