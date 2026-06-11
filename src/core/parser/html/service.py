import re

import trafilatura
from bs4 import BeautifulSoup, Comment, Tag

from src.core.parser.exceptions import ParseBaseException

from .models import HtmlParseOptions, HtmlParseResult
from .renderer import HtmlMarkdownRenderer

# 正文有效字符数下限。trafilatura 判无正文(None)是主判据，本常量只做保守兜底，
# 取低值以“宁漏拦不误杀”。经 blog/ 6 个真实样本校准：真实文章正文数千字以上，
# 远高于该阈值；纯空壳由 trafilatura 直接 None；静态骨架 SPA 残留小，按原则放行。
MIN_CONTENT_CHARS = 100

# 文本重合度置信阈值：trafilatura 正文文本被候选容器覆盖比例 ≥ 此值才算定位命中。
# 低于则走分级回退。经 blog/ 校准，0.6 能稳定命中真实文章主体容器。
OVERLAP_CONF = 0.6


class HtmlParseService:
    """trafilatura 定位正文 + 自研渲染器保真转换 HTML 为 Markdown。

    设计要点：trafilatura 只提供“正文长什么样”的纯文本信号，**不取其结构输出**
    （实测它会拍平表格、丢图片链接）；用文本重合度把该信号映射回我们自己清理过、
    结构完好的 BeautifulSoup 子树，再由一轮渲染器产出最终 Markdown。
    """

    NOISE_SELECTORS = [
        "script",
        "style",
        "noscript",
        "template",
        "iframe",
        "svg",
        "canvas",
        "form",
        "input",
        "button",
        "select",
        "textarea",
        "aside",
        "nav",
        "header nav",
        "footer nav",
    ]

    # 文本重合度匹配的候选块容器；body 单独兜底，不进入竞选。
    CANDIDATE_SELECTOR = "article, main, [role=main], section, div"
    # 分级回退优先级：语义容器优先，再整篇 body。
    SEMANTIC_SELECTORS = ["article", "main", "[role=main]"]
    # 噪声容器 class/id 关键词：参考文献、导航盒、目录、编辑链、分类、页脚、评论、
    # 侧栏等。这些容器即使文本对正文覆盖率达标也不得作渲染根（参考文献会复述
    # 正文术语骗过覆盖率，曾导致维基 GPT 条目选中 div.reflist 而丢正文）。
    NOISE_CONTAINER_HINTS = (
        "reflist",
        "references",
        "refbegin",
        "navbox",
        "vertical-navbox",
        "sidebar",
        "infobox",
        "metadata",
        "mw-editsection",
        "mw-jump",
        "catlinks",
        "printfooter",
        "toc",
        "navigation",
        "breadcrumb",
        "comment",
        "reply",
        "related",
        "footer",
    )
    # 结构性标签：用于度量候选容器“像不像正文”（正文标题/段落多，
    # 参考文献/导航盒几乎没有）。
    STRUCTURE_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "li", "table"]

    def __init__(self, options: HtmlParseOptions | None = None):
        self.options = options or HtmlParseOptions()

    def parse(self, html_content: str) -> HtmlParseResult:
        # 空文件/空白校验（trafilatura 对空输入也会 None，这里给更明确的异常文案）。
        self._build_soup(html_content)

        root, fallback, comment_removed = self._locate_main_content(html_content)
        self._assert_content_valid(root)

        renderer = HtmlMarkdownRenderer(self.options)
        markdown = renderer.render_children(root)
        if not markdown.strip():
            raise ParseBaseException("HTML 解析失败：DOM 中没有有效内容")

        metadata = {
            "pages_or_length": (len(markdown) // 500) + 1,
            "table_count": renderer.table_count,
            "record_table_count": renderer.record_table_count,
            "table_failure_count": renderer.table_failure_count,
            "table_split_count": renderer.table_split_count,
            "image_count": renderer.image_count,
            "image_upload_count": renderer.image_upload_count,
            "content_located": True,
            "content_locator_fallback": fallback,
            "comment_removed_count": comment_removed,
        }
        return HtmlParseResult(markdown=markdown, metadata=metadata, warnings=renderer.warnings)

    def _build_soup(self, html_content: str) -> BeautifulSoup:
        if not html_content or not html_content.strip():
            raise ParseBaseException("HTML 解析失败：文件内容为空")
        # 用 lxml 而非内置 html.parser：后者把正文里的内联 <meta>（如维基 Parsoid
        # 输出）误当容器，会把后续标题/段落错误嵌进 <meta>，导致 <h2> 被走 inline
        # 渲染丢失 `##`。lxml 正确将 <meta> 视为空元素，保住标题结构。lxml 已是
        # trafilatura 的传递依赖，无需新增。
        return BeautifulSoup(html_content, "lxml")

    def _locate_main_content(self, html_content: str) -> tuple[Tag | None, str, int]:
        """trafilatura 取正文纯文本作定位信号，文本重合度映射回我们的 soup 容器。

        返回 (渲染根, 回退级别, 删除注释数)。回退级别取值：
        ``matched``（重合度命中）/ ``semantic_container`` / ``full_body`` / ``none``。
        trafilatura 返回 None（纯空壳/SPA/无正文）时渲染根为 None，由
        ``_assert_content_valid`` 统一转成解析异常。
        """
        # trafilatura 只取正文纯文本，绝不取其 markdown/html（会拍平表格、丢图片链接）。
        try:
            main_text = trafilatura.extract(
                html_content,
                output_format="txt",
                favor_recall=True,
                include_comments=False,
                include_tables=True,
            )
        except Exception:
            main_text = None
        if not main_text or not main_text.strip():
            return None, "none", 0

        # 在我们自己清理过、结构完好的树上定位（trafilatura 的树丢表格，不能用）。
        soup = self._build_soup(html_content)
        comment_removed = self._clean_soup(soup)
        body = soup.body or soup

        node, score = self._text_overlap_match(main_text, body)
        if node is not None and node is not body and score >= OVERLAP_CONF:
            return node, "matched", comment_removed

        # 低置信分级回退：trafilatura 已确认有正文，保内容优先，绝不失败。
        root, level = self._fallback_root(body)
        return root, level, comment_removed

    def _text_overlap_match(self, main_text: str, body: Tag) -> tuple[Tag | None, float]:
        """在候选块容器里定位真正的正文容器。

        步骤：① 排除参考文献/导航盒/目录等噪声容器（其文本会复述正文术语，
        覆盖率可能达标却不是正文，曾致维基 GPT 选中 div.reflist 丢正文）；
        ② 长度预过滤——正文容器文本必 ≥ trafilatura 正文的大半，先 O(1) 刷掉
        海量小 div，避免对它们做重合度计算（性能关键）；③ 在覆盖率（k-gram
        集合包含率，线性复杂度，替代原 O(n·m) SequenceMatcher）≥ 阈值且含结构
        内容的候选里取**文本最短**者——最紧凑且仍覆盖整段正文的容器即正文本体，
        既排除参考文献这类局部子集，又避开 #container 这种含 nav/页脚的外层壳。
        """
        target = self._normalize_text(main_text)
        if not target:
            return None, 0.0
        target_grams = self._kgrams(target)
        min_len = int(len(target) * 0.5)  # 正文容器至少覆盖 trafilatura 正文的一半长度

        best_node: Tag | None = None
        best_len = -1
        best_score = 0.0
        for candidate in body.select(self.CANDIDATE_SELECTOR):
            if candidate is body or self._is_noise_container(candidate):
                continue
            cand_text = self._normalize_text(candidate.get_text(" ", strip=True))
            # 长度预过滤：短于正文一半的容器不可能覆盖大半正文，O(1) 跳过，
            # 不进入 k-gram 计算（维基页有上千个小 div，这步是性能关键）。
            if len(cand_text) < min_len:
                continue
            if self._structure_score(candidate) < 1:
                continue
            score = self._coverage(target_grams, cand_text)
            best_score = max(best_score, score)
            if score < OVERLAP_CONF:
                continue
            # 达标候选里取文本最短者（粒度最紧、样板最少）。
            if best_node is None or len(cand_text) < best_len:
                best_node, best_len, best_score = candidate, len(cand_text), score
        return best_node, best_score

    def _is_noise_container(self, node: Tag) -> bool:
        """class/id 命中噪声关键词（参考文献/导航盒/目录/分类/页脚等）即排除。"""
        tokens = " ".join(node.get("class", []) + [node.get("id", "")]).lower()
        return any(hint in tokens for hint in self.NOISE_CONTAINER_HINTS)

    def _structure_score(self, node: Tag) -> int:
        """容器内结构性标签数量，用于区分“正文容器”与“参考文献/导航盒”。"""
        return len(node.find_all(self.STRUCTURE_TAGS))

    def _fallback_root(self, body: Tag) -> tuple[Tag, str]:
        """分级回退：语义容器 article/main/[role=main] 优先，否则整篇 body。"""
        for selector in self.SEMANTIC_SELECTORS:
            node = body.select_one(selector)
            if node is not None and node.get_text(strip=True):
                return node, "semantic_container"
        return body, "full_body"

    def _assert_content_valid(self, root: Tag | None) -> None:
        """trafilatura 判无正文 / 渲染根正文过少 → 抛异常（经 pipeline 映射 PARSE_ENGINE_FAILED）。"""
        if root is None:
            raise ParseBaseException("HTML 解析失败：未定位到正文主内容")
        if len(root.get_text(" ", strip=True)) < MIN_CONTENT_CHARS:
            raise ParseBaseException("HTML 解析失败：正文内容过少")

    def _clean_soup(self, soup: BeautifulSoup) -> int:
        """移除噪声标签、隐藏节点与全部 HTML 注释，返回删除的注释节点数。

        bs4 的 ``Comment`` 是 ``NavigableString`` 子类，渲染器会把它当文本输出，
        因此必须在渲染前显式删除（注释非 Tag，只能 ``extract()`` 不能 ``decompose()``），
        否则被注释掉的标记、内嵌 base64 ``data:`` 图片会泄漏进 Markdown。
        """
        for selector in self.NOISE_SELECTORS:
            for node in soup.select(selector):
                node.decompose()

        for node in soup.find_all(attrs={"hidden": True}):
            node.decompose()

        for node in soup.find_all(attrs={"aria-hidden": "true"}):
            node.decompose()

        # 维基每个章节标题旁的 [编辑] 链接（.mw-editsection）是站点 chrome，
        # 嵌在标题块内，会以 `[编辑](…)` 噪声跟在每个标题后，统一剥离。
        for node in soup.select(".mw-editsection"):
            node.decompose()

        comments = soup.find_all(string=lambda s: isinstance(s, Comment))
        for comment in comments:
            comment.extract()
        return len(comments)

    @staticmethod
    def _normalize_text(text: str) -> str:
        # 去掉所有空白做归一化，规避 trafilatura 与 DOM 文本的空白/换行差异。
        return re.sub(r"\s+", "", text or "")

    # k-gram 长度：足够长以保证区分度，又不过长导致集合过大。
    _KGRAM = 12

    @classmethod
    def _kgrams(cls, text: str) -> set[str]:
        k = cls._KGRAM
        if len(text) < k:
            return {text} if text else set()
        return {text[i : i + k] for i in range(len(text) - k + 1)}

    @classmethod
    def _coverage(cls, target_grams: set[str], candidate: str) -> float:
        # trafilatura 正文的 k-gram 有多大比例出现在候选容器文本里。
        # 线性复杂度（构候选 gram 集 O(len) + 集合交 O(|target|)），
        # 替代原 O(n·m) SequenceMatcher，消除维基大页 26s 性能病灶。
        if not target_grams:
            return 0.0
        cand_grams = cls._kgrams(candidate)
        return len(target_grams & cand_grams) / len(target_grams)
