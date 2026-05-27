"""trafilatura 定位 / 文本重合度映射 / 分级回退 / 空内容判定。"""

import pytest
from bs4 import BeautifulSoup

from src.core.exceptions import ParseBaseException
from src.core.parser.html import service as svc_mod
from src.core.parser.html.service import HtmlParseService
from src.core.parser.providers.html_parser import HtmlParser

PROSE = (
    "本文系统介绍知识库文档解析链路的设计与实现。文档解析是检索增强生成的第一道工序，"
    "解析质量直接决定后续分块、向量化与召回的上限。逐节说明解析流程与结构保真策略。"
) * 2


def _page(article_inner: str, chrome: bool = True) -> bytes:
    nav = "<nav>首页 档案 SiteSearch 站内搜索</nav>" if chrome else ""
    footer = "<footer>上一篇 下一篇 分类：开发者手册 微博 GitHub License</footer>" if chrome else ""
    return f"<html><body>{nav}<article>{article_inner}</article>{footer}</body></html>".encode()


# ==== 定位 + 去样板 ====

def test_located_main_content_strips_outside_chrome():
    parser = HtmlParser()
    md = parser.parse(_page(f"<h1>正文标题</h1><p>{PROSE}</p>"))

    assert "正文标题" in md
    assert "SiteSearch" not in md
    assert "站内搜索" not in md
    assert "上一篇" not in md
    assert "分类：开发者手册" not in md
    assert "微博 GitHub License" not in md


def test_knowledge_inside_container_not_dropped_as_boilerplate():
    parser = HtmlParser(source_file_url="https://example.com/p.html")
    md = parser.parse(
        _page(
            f"<h1>接口说明</h1><p>{PROSE}</p>"
            "<table><tr><th>参数</th><th>说明</th></tr><tr><td>uid</td><td>用户ID</td></tr></table>"
            "<p>附录 A：错误码对照</p>"
            '<pre><code class="language-bash">curl -s /api</code></pre>'
        )
    )

    assert "| 参数 | 说明 |" in md
    assert "附录 A：错误码对照" in md
    assert "```bash\ncurl -s /api\n```" in md


def test_pure_content_without_chrome_not_judged_empty():
    parser = HtmlParser()
    md = parser.parse(
        _page(
            f"<h1>纯内容文档</h1><p>{PROSE}</p>"
            "<table><tr><th>字段</th><th>含义</th></tr><tr><td>a</td><td>甲</td></tr></table>",
            chrome=False,
        )
    )

    assert "# 纯内容文档" in md
    assert "| 字段 | 含义 |" in md


# ==== 文本重合度匹配（白盒）====

def test_text_overlap_match_picks_tightest_matching_container():
    svc = HtmlParseService()
    # 真实正文容器含结构性内容（段落/标题）；纯文本无结构块按新规则会被排除
    # （与参考文献/导航盒同理），故内容容器用 <p> 承载。
    soup = BeautifulSoup(
        "<body><div id='wrap'><nav>导航噪声内容</nav>"
        "<div id='content'><p>核心正文ABCDEFG核心正文HIJKLMN核心正文OPQRST</p></div>"
        "</div></body>",
        "html.parser",
    )
    target = "核心正文ABCDEFG核心正文HIJKLMN核心正文OPQRST"

    node, score = svc._text_overlap_match(target, soup.body)

    assert node is not None
    assert node.get("id") == "content"
    assert score >= svc_mod.OVERLAP_CONF


# ==== 分级回退（白盒 + 端到端 monkeypatch）====

def test_fallback_root_prefers_semantic_container():
    svc = HtmlParseService()
    body = BeautifulSoup(
        "<body><div>杂项</div><article>语义容器正文内容</article></body>", "html.parser"
    ).body

    node, level = svc._fallback_root(body)

    assert level == "semantic_container"
    assert node.name == "article"


def test_fallback_root_uses_full_body_when_no_semantic_container():
    svc = HtmlParseService()
    body = BeautifulSoup("<body><div>仅有 div 无语义容器</div></body>", "html.parser").body

    node, level = svc._fallback_root(body)

    assert level == "full_body"
    assert node.name == "body"


def test_locate_low_confidence_falls_back_to_semantic_container(monkeypatch):
    # 强制 trafilatura 返回与任何容器都对不上的正文 → 走分级回退。
    monkeypatch.setattr(
        svc_mod.trafilatura, "extract", lambda *a, **k: "完全无法与页面任何容器匹配的离散文本ZZZ"
    )
    parser = HtmlParser()
    md = parser.parse(_page(f"<h1>语义容器标题</h1><p>{PROSE}</p>", chrome=False))

    assert "语义容器标题" in md
    assert parser.extract_metadata()["content_locator_fallback"] == "semantic_container"


def test_locate_low_confidence_full_body_when_no_semantic_container(monkeypatch):
    monkeypatch.setattr(
        svc_mod.trafilatura, "extract", lambda *a, **k: "完全无法匹配的离散文本ZZZ"
    )
    parser = HtmlParser()
    html = f"<html><body><div><h1>整篇回退标题</h1><p>{PROSE}</p></div></body></html>".encode()
    md = parser.parse(html)

    assert "整篇回退标题" in md
    assert parser.extract_metadata()["content_locator_fallback"] == "full_body"


# ==== 空内容 / SPA 快速失败 ====

def test_spa_empty_shell_raises_parse_exception():
    parser = HtmlParser()
    with pytest.raises(ParseBaseException, match="正文"):
        parser.parse(
            b"<html><head><script src='/app.js'></script></head>"
            b"<body><div id='root'></div><script>window.__BOOT__=1</script></body></html>"
        )


def test_static_skeleton_spa_below_floor_raises(monkeypatch):
    # 静态骨架 SPA：trafilatura 抽出极短碎片，渲染根正文低于保守下限 → 失败。
    monkeypatch.setattr(svc_mod.trafilatura, "extract", lambda *a, **k: "加载中")
    parser = HtmlParser()
    with pytest.raises(ParseBaseException, match="正文"):
        parser.parse("<html><body><div id='app'>加载中</div></body></html>".encode())


def test_short_but_valid_content_not_killed():
    parser = HtmlParser()
    # “短但有效”：正文有效字符数高于保守下限（acceptance 明确该前置），
    # 远小于真实长文但属合法知识条目，不应被误杀。
    short_valid = "本页只有一句有效说明，但内容真实有效，足以构成可检索的知识条目，不应被误判为空内容而丢弃。" * 3
    md = parser.parse(_page(f"<h1>短文</h1><p>{short_valid}</p>", chrome=False))

    assert "本页只有一句有效说明" in md
