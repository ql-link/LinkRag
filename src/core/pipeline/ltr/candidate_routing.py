"""Blind v5 冻结的线上候选深度路由与 serving 契约。

路由只依赖用户 Query 文本，确保生产端能复现 LambdaMART Tune/Blind v5 的候选分布。
数据集配置仍用于 ``off`` 旧链路；``shadow`` / ``active`` / ``baseline`` 由应用装配层使用
本模块冻结的来源、阈值和分路 TopK，避免模型加载成功但候选分布已经漂移。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

CANDIDATE_CONTRACT_VERSION = "blind_v5_candidate_routing_v1"
FROZEN_SOURCES = ("bm25", "sparse", "dense")
FROZEN_SCORE_THRESHOLDS = {"dense": 0.0, "sparse": 0.0, "bm25": 0.0}
FROZEN_FUSION_WEIGHTS = {"dense": 0.70, "sparse": 0.15, "bm25": 0.15}
FROZEN_OUTPUT_TOP_N = 10


@dataclass(frozen=True)
class CandidateDepths:
    dense: int
    sparse: int
    bm25: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


BASELINE_DEPTHS = CandidateDepths(dense=150, sparse=50, bm25=100)
FROZEN_ROUTING_DEPTHS = {
    "short_keyword": CandidateDepths(dense=300, sparse=100, bm25=225),
    "exact_identifier": BASELINE_DEPTHS,
    "number_time": CandidateDepths(dense=275, sparse=50, bm25=200),
    "long_multi": CandidateDepths(dense=125, sparse=50, bm25=75),
    "natural_default": CandidateDepths(dense=150, sparse=50, bm25=225),
}

_EXACT_IDENTIFIER_RE = re.compile(
    r"(?:v(?:ersion)?\s*\d+(?:\.\d+)*|"
    r"\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2})?|"
    r"[A-Za-z]{2,}[-_]?[0-9]{2,}|(?<!\d)\d{5,}(?!\d))",
    re.IGNORECASE,
)
_NUMBER_TIME_RE = re.compile(
    r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十百]+)\s*" r"(?:分钟|小时|天|日|个月|年|次|%|％)",
    re.IGNORECASE,
)
_QUERY_CLEAN_RE = re.compile(r"[\s，。？！、；：,.?!;:]+")
_CONDITION_MARKERS = ("同时", "并且", "以及", "还是", "是否", "分别", "之后", "之前", "如果", "且")


def classify_candidate_query(query: str) -> str:
    """使用与 Blind v5 相同的纯文本规则确定候选深度档位。"""
    if _EXACT_IDENTIFIER_RE.search(query):
        return "exact_identifier"
    if _NUMBER_TIME_RE.search(query):
        return "number_time"

    compact = _QUERY_CLEAN_RE.sub("", query)
    if len(compact) <= 15:
        return "short_keyword"
    marker_count = sum(marker in query for marker in _CONDITION_MARKERS)
    if len(compact) > 35 or marker_count >= 3:
        return "long_multi"
    return "natural_default"


def depths_for_query(query: str) -> CandidateDepths:
    return FROZEN_ROUTING_DEPTHS[classify_candidate_query(query)]


def serving_contract_payload() -> dict[str, Any]:
    return {
        "version": CANDIDATE_CONTRACT_VERSION,
        "sources": list(FROZEN_SOURCES),
        "score_thresholds": FROZEN_SCORE_THRESHOLDS,
        "fusion_weights": FROZEN_FUSION_WEIGHTS,
        "routing_profiles": {
            name: depths.as_dict() for name, depths in FROZEN_ROUTING_DEPTHS.items()
        },
        "output_top_n": FROZEN_OUTPUT_TOP_N,
    }


def serving_contract_signature() -> str:
    payload = json.dumps(
        serving_contract_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
