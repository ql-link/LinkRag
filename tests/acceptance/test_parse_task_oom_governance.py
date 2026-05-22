"""pytest-bdd 入口：加载 ``acceptance.feature`` 中所有 Scenario。

step 实现集中在 ``tests/acceptance/steps/*.py``，按"存储 / 流水线 / parser / 临时目录
/ 日志 / 背景"六个关注点拆分。pytest-bdd 在 collection 阶段会校验每条 Scenario 都能
匹配到 step；若有遗漏会直接抛 ``StepDefinitionNotFoundError`` —— 覆盖完整性由收集机
制强制保证。
"""

from pathlib import Path

from pytest_bdd import scenarios

# step 模块仅导入即注册装饰器；按关注点拆分让单文件保持可读。
from tests.acceptance.steps import (  # noqa: F401  (importing for side effects)
    background_steps,
    logging_steps,
    parser_steps,
    pipeline_steps,
    storage_steps,
    temp_workspace_steps,
)

_FEATURE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "解析任务OOM风险治理"
    / "acceptance.feature"
)

scenarios(str(_FEATURE))
