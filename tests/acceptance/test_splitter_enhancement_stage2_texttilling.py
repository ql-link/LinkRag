"""pytest-bdd 入口:加载 splitter_enhancement_stage2_texttilling acceptance.feature(由 promote_acceptance.py 生成)。

step 实现见 ``tests/acceptance/steps/splitter_enhancement_stage2_texttilling_steps.py``。pytest-bdd 通过 star-import
在本测试模块命名空间发现 step 函数;若某 Scenario 缺少 step 绑定,运行时抛
StepDefinitionNotFoundError——覆盖完整性由 check_acceptance_steps.py 守。
"""

from pathlib import Path

from pytest_bdd import scenarios

from tests.acceptance.steps.splitter_enhancement_stage2_texttilling_steps import *  # noqa: F401,F403

_FEATURE = (
    Path(__file__).resolve().parent / "features" / "splitter_enhancement_stage2_texttilling.feature"
)

scenarios(str(_FEATURE))
