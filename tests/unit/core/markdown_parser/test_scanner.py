# -*- coding: utf-8 -*-
"""MarkdownScanner 直接单元测试。

补齐历史盲区：此前 scanner 仅经 splitter 集成测试间接覆盖，且 fixture 全为
标准表格，从未喂入「含 `|` 但不是表格」的普通正文——正是该输入曾使主扫描循环
原地死循环（见 issue #164 / 线上样本 document_parse_file_id=10015）。

本文件直接对 ``MarkdownScanner.scan()`` 做断言，并用 ``signal.alarm`` 硬超时守卫，
确保一旦行号推进逻辑回归为死循环，测试会清晰失败（TimeoutError）而非挂起 CI。
"""

import signal
from contextlib import contextmanager

import pytest

from src.core.markdown_parser.models import ElementType
from src.core.markdown_parser.scanner import MarkdownScanner


@contextmanager
def deadline(seconds: int = 3):
    """硬超时守卫：扫描在 seconds 内未返回即判定为死循环回归。

    依赖 POSIX SIGALRM（macOS/Linux 可用），且仅在主线程生效——pytest 默认在
    主线程执行用例，满足条件。
    """

    def _handler(signum, frame):
        raise TimeoutError(f"scan() 超过 {seconds}s 未返回，疑似行号未推进的死循环")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _scan(text: str):
    with deadline(3):
        return MarkdownScanner().scan(text)


def test_issue_164_pipe_prose_does_not_hang_and_becomes_paragraph():
    """issue #164 原始触发样本：含 `|` 的普通正文，不应死循环，应识别为段落。"""
    text = "正文开头\n\n项目 | 特点 | 借鉴点\n\n结尾段落"
    elements = _scan(text)

    paragraphs = [e for e in elements if e.type == ElementType.PARAGRAPH]
    assert any("项目 | 特点 | 借鉴点" in e.content for e in paragraphs)
    assert not any(e.type == ElementType.TABLE for e in elements)


def test_backtick_pipe_text_is_not_table():
    """反引号包裹/命令管道等含 `|` 文本不应被误判为表格，也不应死循环。"""
    elements = _scan("# H\n\n执行 `a | b | c` 仅为示例\n\n下一段\n")

    assert not any(e.type == ElementType.TABLE for e in elements)
    assert any(e.type == ElementType.PARAGRAPH and "a | b | c" in e.content for e in elements)


def test_single_pipe_line_at_eof_does_not_hang():
    """含 `|` 的单行且位于文件末尾（无下一行可判分隔符）也必须正常收敛。"""
    elements = _scan("项目 | 特点 | 借鉴点")

    assert len(elements) == 1
    assert elements[0].type == ElementType.PARAGRAPH


def test_standard_table_still_recognized():
    """回归保护：标准 Markdown 表格仍应被识别为单个 TABLE。"""
    text = "## 指标\n\n| 指标 | 值 |\n| :--- | ---: |\n| 召回 | 0.82 |\n| 时延 | 128 |\n"
    elements = _scan(text)

    tables = [e for e in elements if e.type == ElementType.TABLE]
    assert len(tables) == 1
    assert "| 召回 | 0.82 |" in tables[0].content
    assert "| 时延 | 128 |" in tables[0].content


def test_mixed_pipe_prose_and_real_table():
    """混排：含 `|` 的正文 + 真实表格 + 段落，应在限时内完成且切分正确。"""
    text = (
        "# 标题\n\n"
        "对比 项目 | 特点 | 借鉴点 三列只是正文\n\n"
        "| 指标 | 值 |\n| :--- | ---: |\n| 召回 | 0.82 |\n\n"
        "收尾段落\n"
    )
    elements = _scan(text)

    types = [e.type for e in elements]
    assert ElementType.TABLE in types
    # 含 `|` 的正文行落入段落，未被并进表格
    assert any(
        e.type == ElementType.PARAGRAPH and "项目 | 特点 | 借鉴点" in e.content for e in elements
    )
    tables = [e for e in elements if e.type == ElementType.TABLE]
    assert len(tables) == 1
    assert "项目" not in tables[0].content


def test_many_pipe_lines_terminate_in_bounded_time():
    """对抗性输入：大量含 `|` 的非表格行，scanner 必须每轮推进、限时内完成。"""
    text = "\n\n".join(f"第{n}行 a | b | c" for n in range(200))
    elements = _scan(text)

    assert len(elements) == 200
    assert all(e.type == ElementType.PARAGRAPH for e in elements)


@pytest.mark.parametrize(
    "line",
    [
        "a | b",
        "| 只有一根竖线开头",
        "结尾竖线 |",
        "多 | 竖 | 线 | 文本",
    ],
)
def test_various_non_table_pipe_lines_advance(line: str):
    """各形态含 `|` 非表格行都必须推进行号、不死循环。"""
    elements = _scan(f"{line}\n")
    assert len(elements) == 1
    assert elements[0].type == ElementType.PARAGRAPH


def test_yaml_front_matter_is_recognized_and_fields_are_not_parsed():
    elements = _scan(
        "---\n"
        "title: 检索设计\n"
        "tags:\n"
        "  - rag\n"
        "draft: false\n"
        "---\n\n"
        "# 正文标题\n\n"
        "正文段落。"
    )

    assert elements[0].type == ElementType.FRONT_MATTER
    assert "title: 检索设计" in elements[0].content
    assert "title" not in elements[0].metadata
    assert any(element.type == ElementType.HEADING for element in elements[1:])


def test_toml_front_matter_is_recognized():
    elements = _scan(
        "+++\n"
        'title = "检索设计"\n'
        "draft = false\n"
        'tags = ["rag", "splitter"]\n'
        "+++\n\n"
        "# 正文标题\n\n"
        "正文段落。"
    )

    assert elements[0].type == ElementType.FRONT_MATTER
    assert 'title = "检索设计"' in elements[0].content
    assert "title" not in elements[0].metadata
    assert any(element.type == ElementType.HEADING for element in elements[1:])


def test_opening_horizontal_rule_with_prose_is_not_front_matter():
    elements = _scan("---\n这是一段普通正文\n---\n\n# 后续标题")

    assert [element.type for element in elements[:3]] == [
        ElementType.HORIZONTAL_RULE,
        ElementType.PARAGRAPH,
        ElementType.HORIZONTAL_RULE,
    ]
    assert not any(element.type == ElementType.FRONT_MATTER for element in elements)


def test_opening_markdown_heading_block_is_not_front_matter():
    elements = _scan("---\n# 临时说明\n---\n\n正文。")

    assert elements[0].type == ElementType.HORIZONTAL_RULE
    assert any(
        element.type == ElementType.HEADING and element.metadata["heading_text"] == "临时说明"
        for element in elements
    )
    assert not any(element.type == ElementType.FRONT_MATTER for element in elements)


def test_middle_horizontal_rule_is_never_front_matter():
    elements = _scan("# 标题\n\n上半部分正文。\n\n---\n\n下半部分正文。")

    hr_elements = [element for element in elements if element.type == ElementType.HORIZONTAL_RULE]
    assert len(hr_elements) == 1
    assert hr_elements[0].start_line > 0
    assert not any(element.type == ElementType.FRONT_MATTER for element in elements)


def test_unclosed_opening_fence_falls_back_to_horizontal_rule():
    elements = _scan("---\ntitle: 未闭合元数据\n\n# 正文标题")

    assert elements[0].type == ElementType.HORIZONTAL_RULE
    assert not any(element.type == ElementType.FRONT_MATTER for element in elements)
    assert any(element.type == ElementType.PARAGRAPH for element in elements)


def test_indented_opening_fence_is_horizontal_rule_not_front_matter():
    elements = _scan("  ---\ntitle: 缩进分割线\n  ---\n\n正文段落。")

    assert [element.type for element in elements[:3]] == [
        ElementType.HORIZONTAL_RULE,
        ElementType.PARAGRAPH,
        ElementType.HORIZONTAL_RULE,
    ]
    assert not any(element.type == ElementType.FRONT_MATTER for element in elements)


def test_mismatched_front_matter_fence_does_not_consume_body():
    elements = _scan("---\ntitle: 不匹配 fence\n+++\n正文段落。")

    assert elements[0].type == ElementType.HORIZONTAL_RULE
    assert not any(element.type == ElementType.FRONT_MATTER for element in elements)
    assert any(
        element.type == ElementType.PARAGRAPH and "title: 不匹配 fence" in element.content
        for element in elements
    )


def test_empty_or_comment_only_front_matter_candidate_falls_back_to_hr():
    elements = _scan("---\n\n# 只是 Markdown 标题\n---\n正文段落。")

    assert elements[0].type == ElementType.HORIZONTAL_RULE
    assert any(
        element.type == ElementType.HEADING
        and element.metadata["heading_text"] == "只是 Markdown 标题"
        for element in elements
    )
    assert not any(element.type == ElementType.FRONT_MATTER for element in elements)


def test_toml_front_matter_candidate_requires_metadata_shape():
    elements = _scan("+++\n这里其实是普通正文\n+++\n正文段落。")

    assert elements[0].type == ElementType.PARAGRAPH
    assert "+++" in elements[0].content
    assert not any(element.type == ElementType.FRONT_MATTER for element in elements)
