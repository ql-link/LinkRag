import hashlib
import posixpath
import re
from urllib.parse import quote, unquote, urljoin, urlparse

from bs4 import Tag

from .models import HtmlParseOptions, ImageRewriteResult


class HtmlImageRewriter:
    """Normalize image URLs and build simulated object-store Markdown references."""

    def __init__(self, options: HtmlParseOptions):
        self.options = options

    def rewrite_img(self, img: Tag) -> ImageRewriteResult:
        original_url = self._select_source(img)
        alt = self._clean_inline_text(img.get("alt", ""))
        absolute_url = self.resolve_url(original_url)
        object_url = self.build_mock_object_url(absolute_url)

        target_url = object_url or absolute_url
        warning = None if object_url else f"无法生成模拟对象路径: {absolute_url}"
        return ImageRewriteResult(
            markdown=f"![{self._escape_alt(alt)}]({target_url})",
            original_url=original_url,
            absolute_url=absolute_url,
            object_url=object_url,
            warning=warning,
        )

    def resolve_url(self, url: str) -> str:
        url = (url or "").strip()
        if not url:
            return ""
        if self.options.source_file_url:
            return urljoin(self.options.source_file_url, url)
        return url

    def build_mock_object_url(self, absolute_url: str) -> str | None:
        if not absolute_url:
            return None
        parsed = urlparse(absolute_url)
        if parsed.scheme == "data":
            return None

        path = unquote(parsed.path or "")
        filename = posixpath.basename(path) or "image"
        filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-._") or "image"
        digest = hashlib.sha1(absolute_url.encode("utf-8")).hexdigest()[:12]
        prefix = self.options.image_prefix.strip("/") or "html-images"
        base = self.options.mock_minio_base_url.rstrip("/")
        return f"{base}/{quote(prefix)}/{digest}/{quote(filename)}"

    def _select_source(self, img: Tag) -> str:
        srcset = img.get("srcset")
        if srcset:
            candidate = self._select_srcset_candidate(srcset)
            if candidate:
                return candidate
        return str(img.get("src", "")).strip()

    def _select_srcset_candidate(self, srcset: str) -> str:
        candidates: list[tuple[float, str]] = []
        for raw_part in srcset.split(","):
            part = raw_part.strip()
            if not part:
                continue
            pieces = part.split()
            url = pieces[0]
            score = 1.0
            if len(pieces) > 1:
                descriptor = pieces[1]
                try:
                    if descriptor.endswith("w"):
                        score = float(descriptor[:-1])
                    elif descriptor.endswith("x"):
                        score = float(descriptor[:-1]) * 1000
                except ValueError:
                    score = 1.0
            candidates.append((score, url))
        if not candidates:
            return ""
        return max(candidates, key=lambda item: item[0])[1]

    def _escape_alt(self, text: str) -> str:
        return text.replace("[", "\\[").replace("]", "\\]")

    def _clean_inline_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
