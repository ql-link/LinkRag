from __future__ import annotations

import pytest

from scripts import benchmark_bge_m3_sparse as benchmark


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ("cpu", False),
        ("cuda", True),
        ("cuda:0", True),
        ("CUDA:1", True),
        ("", False),
    ],
)
def test_benchmark_should_derive_fp16_from_device(device, expected):
    """benchmark 和主程序保持同一精度规则：CUDA 使用 fp16，其它设备使用 fp32。"""

    assert benchmark.use_fp16_for_device(device) is expected
