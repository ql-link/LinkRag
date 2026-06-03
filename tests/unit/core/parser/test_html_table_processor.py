from bs4 import BeautifulSoup

from src.core.parser.html import HtmlParseOptions
from src.core.parser.html.image_rewriter import HtmlImageRewriter
from src.core.parser.html.table_processor import HtmlTableProcessor


def _processor() -> HtmlTableProcessor:
    return HtmlTableProcessor(
        HtmlImageRewriter(HtmlParseOptions(source_file_url="https://example.com/docs/page.html"))
    )


def _table(html: str):
    return BeautifulSoup(html, "html.parser").table


def test_simple_table_should_render_markdown_table():
    result = _processor().render(_table("""
            <table>
              <tr><th>字段</th><th>值</th></tr>
              <tr><td>名称</td><td>RAG</td></tr>
            </table>
            """))

    assert result.strategy == "markdown_table"
    assert "| 字段 | 值 |" in result.markdown
    assert "| 名称 | RAG |" in result.markdown


def test_rowspan_table_should_keep_field_value_mapping():
    result = _processor().render(_table("""
            <table>
              <tr><th>模块</th><th>权限</th></tr>
              <tr><td rowspan="2">知识库</td><td>读权限</td></tr>
              <tr><td>写权限</td></tr>
            </table>
            """))

    assert "| 知识库 | 读权限 |" in result.markdown
    assert "| 知识库 | 写权限 |" in result.markdown


def test_colspan_header_should_flatten_to_readable_column_names():
    result = _processor().render(_table("""
            <table>
              <tr><th colspan="2">用户</th><th>状态</th></tr>
              <tr><th>姓名</th><th>角色</th><th>启用</th></tr>
              <tr><td>张三</td><td>管理员</td><td>是</td></tr>
            </table>
            """))

    assert "| 用户 / 姓名 | 用户 / 角色 | 状态 / 启用 |" in result.markdown


def test_list_cell_should_not_break_markdown_table_columns():
    result = _processor().render(_table("""
            <table>
              <tr><th>角色</th><th>权限</th></tr>
              <tr><td>管理员</td><td><ul><li>读权限</li><li>写权限</li></ul></td></tr>
            </table>
            """))

    lines = result.markdown.splitlines()
    assert "读权限；写权限" in result.markdown
    assert len({line.count("|") for line in lines}) == 1


def test_nested_table_should_render_record_markdown_without_heading_markers():
    result = _processor().render(_table("""
            <table>
              <tr><th>名称</th><th>详情</th></tr>
              <tr><td>模块</td><td><table><tr><td>子项</td></tr></table></td></tr>
            </table>
            """))

    assert result.strategy == "record_markdown"
    assert "[HTML表格开始：" in result.markdown
    assert "表格类型：记录式表格" in result.markdown
    assert "表格说明：该 HTML 表格包含嵌套表格" in result.markdown
    assert "记录 1：" in result.markdown
    assert "\n### 表格：" not in result.markdown
    assert "\n#### 记录" not in result.markdown
    assert "<table" not in result.markdown


def test_image_cell_should_render_record_markdown_with_mock_object_path():
    result = _processor().render(_table("""
            <table>
              <tr><th>名称</th><th>图片</th></tr>
              <tr><td>架构</td><td><img src="/assets/arch.png" alt="架构图"></td></tr>
            </table>
            """))

    assert result.strategy == "record_markdown"
    assert result.image_count == 1
    assert "表格说明：该 HTML 表格包含图片单元格" in result.markdown
    assert "![架构图](mock-minio://tolink-rag/html-images/" in result.markdown


def test_large_table_should_not_split_into_multiple_table_fragments():
    rows = "".join(f"<tr><td>{index}</td><td>值{index}</td></tr>" for index in range(120))
    result = _processor().render(_table(f"<table><tr><th>ID</th><th>值</th></tr>{rows}</table>"))

    assert result.strategy == "markdown_table"
    assert result.markdown.count("| ID | 值 |") == 1
    assert "[HTML表格开始：" not in result.markdown
