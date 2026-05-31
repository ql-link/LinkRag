"""blog/ 真实样本回归：混合方案在真实中文技术博客上的去样板/保真效果。

blog/ 为本地抓取目录（.gitignore 忽略）。缺失时跳过，不阻断 CI。
"""

import pathlib

import pytest

from src.core.exceptions import ParseBaseException
from src.core.parser.providers.html_parser import HtmlParser

BLOG_HTML = pathlib.Path(__file__).resolve().parents[4] / "blog" / "html"

pytestmark = pytest.mark.skipif(
    not BLOG_HTML.is_dir() or not any(BLOG_HTML.glob("*.html")),
    reason="blog/html 真实样本不存在（本地抓取目录，已 gitignore）",
)


def _parse(name: str) -> str:
    # parser 协议入参为 Path：直接传本地样本文件路径。
    return HtmlParser(source_file_url="https://www.ruanyifeng.com/blog/x.html").parse(
        BLOG_HTML / name
    )


def test_ruanyifeng_git_remote_deboilerplated_and_clean():
    md = _parse("ruanyifeng_git_remote.html")

    # 原始 bug：base64 注释泄漏 / 字面 div 标签 / 站点装饰
    assert "iVBORw0KGgo" not in md
    assert 'div class="asset-body"' not in md
    assert "SiteSearch" not in md
    assert "上一篇" not in md
    # 正文与结构保真
    assert "git clone" in md
    assert "#" in md
    # blockquote 内代码块未被引用前缀破坏
    assert not any(line.strip().startswith("> ```") for line in md.splitlines())


def test_coolshell_keeps_code_and_drops_comments():
    md = _parse("coolshell_go.html")

    assert "```" in md
    assert "disqus" not in md.lower()
    assert len(md) > 1000


@pytest.mark.parametrize(
    "name",
    ["ruanyifeng_git_remote.html", "ruanyifeng_docker.html", "coolshell_go.html"],
)
def test_real_articles_produce_non_empty_markdown(name):
    if not (BLOG_HTML / name).exists():
        pytest.skip(f"{name} 不存在")
    md = _parse(name)
    assert md.strip()
    assert len(md) > 500


def test_spa_like_sample_does_not_emit_nav_shell_noise():
    # 廖雪峰为 Vue SPA：要么失败，要么至少不把课程导航当正文大量输出。
    name = "liaoxuefeng_python_function.html"
    if not (BLOG_HTML / name).exists():
        pytest.skip(f"{name} 不存在")
    try:
        md = _parse(name)
    except ParseBaseException:
        return  # 判失败，符合预期
    # 未失败时（宁漏拦不误杀），不应大段输出课程导航清单
    assert md.count("教程") < 20
