"""pytest-bdd 入口：加载对外直连召回 SSE 流式 acceptance.feature。

step 实现见 ``tests/acceptance/steps/recall_direct_sse_steps.py``。pytest-bdd 通过
star-import 在本测试模块命名空间发现 step 函数；缺少 step 绑定时收集阶段直接抛错，
覆盖完整性由收集机制强制保证。
"""

from pathlib import Path

from pytest_bdd import scenarios

from tests.acceptance.steps.recall_direct_sse_steps import *  # noqa: F401,F403

_FEATURE = Path(__file__).resolve().parent / "features" / "recall_direct_sse.feature"

scenarios(str(_FEATURE))
