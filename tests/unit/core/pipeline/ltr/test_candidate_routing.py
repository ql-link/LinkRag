from src.core.pipeline.ltr.candidate_routing import (
    CANDIDATE_CONTRACT_VERSION,
    FROZEN_OUTPUT_TOP_N,
    classify_candidate_query,
    depths_for_query,
    serving_contract_payload,
    serving_contract_signature,
)


def test_blind_v5_query_profiles_and_depths_are_frozen():
    cases = {
        "退款": ("short_keyword", (300, 100, 225)),
        "版本 v2.4.1 如何升级": ("exact_identifier", (150, 50, 100)),
        "最多等待 30 分钟": ("number_time", (275, 50, 200)),
        "如果合同到期并且尚未续签，同时发生欠费以及资料缺失应该如何处理": (
            "long_multi",
            (125, 50, 75),
        ),
        "请说明企业账户完成实名认证以后如何修改结算资料": (
            "natural_default",
            (150, 50, 225),
        ),
    }

    for query, (profile, expected) in cases.items():
        depths = depths_for_query(query)
        assert classify_candidate_query(query) == profile
        assert (depths.dense, depths.sparse, depths.bm25) == expected


def test_serving_contract_is_versioned_and_deterministic():
    payload = serving_contract_payload()

    assert payload["version"] == CANDIDATE_CONTRACT_VERSION
    assert payload["output_top_n"] == FROZEN_OUTPUT_TOP_N == 10
    assert payload["score_thresholds"] == {"dense": 0.0, "sparse": 0.0, "bm25": 0.0}
    assert (
        serving_contract_signature()
        == "8dbf9c9e463105a9be0d127d196952a8adddbd2af68b4dacd12af64d78d8026c"
    )
