# -*- coding: utf-8 -*-
"""
Markdown 图片引用提取器

从 Markdown 文本中提取所有图片引用的 URL 及其所在行号。

核心逻辑来自 RAGFlow 的 rag/app/naive.py 中的
Markdown.extract_image_urls_with_lines() 方法。
保留了三阶段提取策略，但不包含图片下载/加载功能。
"""

import logging
import re
from .models import ImageRef


class ImageExtractor:
    """Markdown 图片引用提取器

    三阶段提取:
    1. Markdown 语法: ![alt](url)
    2. HTML 内联 (单行): <img src="url">
    3. HTML 跨行 (BeautifulSoup 兜底)

    用法:
        extractor = ImageExtractor()
        refs = extractor.extract("![logo](logo.png)\\nsome text")
    """

    # 来自 RAGFlow naive.py L598
    _MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)")

    # 来自 RAGFlow naive.py L599
    _HTML_IMG_RE = re.compile(r'<img[^>]*\bsrc=["\']([^"\'>\s]+)["\']', re.IGNORECASE)

    def extract(self, text: str) -> list[ImageRef]:
        """提取所有图片引用

        来自 RAGFlow Markdown.extract_image_urls_with_lines() L597-641

        Args:
            text: 原始 Markdown 文本

        Returns:
            图片引用列表，每个包含 url、行号和 alt 文本
        """
        refs: list[ImageRef] = []
        seen: set[tuple[str, int]] = set()
        lines = text.splitlines()

        # ----- 阶段1: Markdown 语法图片 -----
        # 来自 RAGFlow L603-607
        for idx, line in enumerate(lines):
            for m in self._MD_IMG_RE.finditer(line):
                alt, url = m.group(1), m.group(2)
                if (url, idx) not in seen:
                    refs.append(ImageRef(url=url, line=idx, alt=alt))
                    seen.add((url, idx))

        # ----- 阶段2: HTML 内联图片 (单行) -----
        # 来自 RAGFlow L608-611
        for idx, line in enumerate(lines):
            for m in self._HTML_IMG_RE.finditer(line):
                url = m.group(1)
                if (url, idx) not in seen:
                    refs.append(ImageRef(url=url, line=idx))
                    seen.add((url, idx))

        # ----- 阶段3: HTML 跨行图片 (BeautifulSoup 兜底) -----
        # 来自 RAGFlow L614-636
        # 处理 <img> 标签跨多行的情况
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(text, "html.parser")
            newline_offsets = [m.start() for m in re.finditer(r"\n", text)] + [len(text)]

            for img_tag in soup.find_all("img"):
                src = img_tag.get("src")
                if not src:
                    continue

                alt = img_tag.get("alt", "")

                # 定位行号: 通过字符偏移量计算
                tag_str = str(img_tag)
                pos = text.find(tag_str)
                if pos == -1:
                    pos = max(text.find(src), 0)

                line_no = 0
                for i, off in enumerate(newline_offsets):
                    if pos <= off:
                        line_no = i
                        break

                if (src, line_no) not in seen:
                    refs.append(ImageRef(url=src, line=line_no, alt=alt))
                    seen.add((src, line_no))

        except ImportError:
            # BeautifulSoup 不可用时，阶段3跳过（阶段1+2 已覆盖大部分场景）
            pass
        except Exception as e:
            logging.warning(f"Failed to extract cross-line image URLs: {e}")

        return refs
