from bs4 import BeautifulSoup

from src.core.parser.html import HtmlParseOptions
from src.core.parser.html.image_rewriter import HtmlImageRewriter


def test_rewrite_img_should_resolve_relative_url_and_build_mock_object_path():
    soup = BeautifulSoup('<img src="/assets/arch.png" alt="架构图">', "html.parser")
    rewriter = HtmlImageRewriter(
        HtmlParseOptions(source_file_url="https://example.com/docs/page.html")
    )

    result = rewriter.rewrite_img(soup.img)

    assert result.absolute_url == "https://example.com/assets/arch.png"
    assert result.object_url.startswith("mock-minio://tolink-rag/html-images/")
    assert result.object_url.endswith("/arch.png")
    assert result.markdown == f"![架构图]({result.object_url})"


def test_rewrite_img_should_choose_largest_srcset_candidate():
    soup = BeautifulSoup(
        '<img src="/small.png" srcset="/small.png 320w, /large.png 1280w" alt="photo">',
        "html.parser",
    )
    rewriter = HtmlImageRewriter(
        HtmlParseOptions(source_file_url="https://example.com/docs/page.html")
    )

    result = rewriter.rewrite_img(soup.img)

    assert result.absolute_url == "https://example.com/large.png"
    assert result.object_url.endswith("/large.png")


def test_rewrite_img_should_keep_absolute_original_when_mock_path_fails():
    soup = BeautifulSoup('<img src="data:image/png;base64,AAAA" alt="inline">', "html.parser")
    rewriter = HtmlImageRewriter(HtmlParseOptions())

    result = rewriter.rewrite_img(soup.img)

    assert result.object_url is None
    assert result.warning
    assert result.markdown == "![inline](data:image/png;base64,AAAA)"
