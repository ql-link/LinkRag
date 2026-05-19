"""观测日志字段断言 step。"""

from __future__ import annotations

import re

from pytest_bdd import parsers, then


def _find_log(state, fragment: str) -> dict | None:
    for rec in state.captured_logs:
        if fragment in rec["message"] or fragment in str(rec["rendered"]):
            return rec
    return None


@then(parsers.re(r'loguru 日志中存在一条匹配 "(?P<fragment>[^"]+)" 的记录'))
def _then_log_present(state, fragment):
    rec = _find_log(state, fragment)
    assert rec is not None, f"未找到匹配 {fragment!r} 的日志，实际日志列表={state.captured_logs}"
    state._last_log_record = rec


@then(parsers.re(r"该记录包含字段 (?P<field>[A-Za-z_]+)$"))
def _then_log_has_field(state, field):
    rec = state.__dict__.get("_last_log_record")
    assert rec is not None
    rendered = str(rec["rendered"])
    assert field in rendered, f"字段 {field} 未出现在日志：{rendered}"


@then(parsers.re(r"该记录包含字段 (?P<field>[A-Za-z_]+) 数值 ≈ (?P<value>\d+(?:\.\d+)?)"))
def _then_log_field_approx(state, field, value):
    rec = state.__dict__.get("_last_log_record")
    assert rec is not None
    rendered = str(rec["rendered"])
    # 字段格式如 ``file_size_mb=100.0``；提取后做近似比较，允许 ±5%。
    m = re.search(rf"{field}=([\d.]+)", rendered)
    assert m is not None, f"未在日志中找到字段 {field}：{rendered}"
    actual = float(m.group(1))
    expected = float(value)
    tol = max(expected * 0.05, 0.5)
    assert abs(actual - expected) <= tol, f"{field} 期望≈{expected}，实际{actual}"


@then(parsers.re(r"该记录包含字段 (?P<field>[A-Za-z_]+) 数值 > 0"))
def _then_log_field_positive(state, field):
    rec = state.__dict__.get("_last_log_record")
    assert rec is not None
    rendered = str(rec["rendered"])
    m = re.search(rf"{field}=([\d.]+)", rendered)
    assert m is not None, f"未在日志中找到字段 {field}：{rendered}"
    assert float(m.group(1)) > 0
