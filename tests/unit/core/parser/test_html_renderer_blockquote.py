"""引用块内代码块保真：blockquote 内 pre/code 不被 "> " 前缀破坏围栏。"""

from bs4 import BeautifulSoup

from src.core.parser.html.models import HtmlParseOptions
from src.core.parser.html.renderer import HtmlMarkdownRenderer


def _render(html: str) -> str:
    renderer = HtmlMarkdownRenderer(HtmlParseOptions())
    soup = BeautifulSoup(html, "html.parser")
    return renderer.render_children(soup)


def test_blockquote_code_block_keeps_valid_fence():
    md = _render(
        "<blockquote>"
        "<p>克隆远程版本库的命令如下：</p>"
        '<pre><code class="language-javascript">$ git clone &lt;版本库的网址&gt;</code></pre>'
        "</blockquote>"
    )

    # 引用文本带 "> " 前缀
    assert "> 克隆远程版本库的命令如下：" in md
    # 代码围栏合法、不被引用前缀破坏
    assert "```javascript" in md
    assert "$ git clone <版本库的网址>" in md
    for line in md.splitlines():
        assert not line.strip().startswith("> ```")
    assert "> $ git clone" not in md


def test_blockquote_plain_text_still_quoted():
    md = _render("<blockquote><p>这是一段纯引用说明文字</p></blockquote>")

    assert "> 这是一段纯引用说明文字" in md
