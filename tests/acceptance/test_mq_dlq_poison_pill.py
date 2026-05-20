"""pytest-bdd 入口：加载 MQ 死信兜底 acceptance.feature。

step 实现见 ``tests/acceptance/steps/mq_dlq_steps.py``。pytest-bdd 收集时若任一
Scenario 缺少 step 绑定会直接抛错 —— 覆盖完整性由收集机制强制保证。
"""

from pathlib import Path

from pytest_bdd import scenarios

# pytest-bdd 8.x 通过模块命名空间发现 step 函数：star-import 把所有 step 装饰器
# 加载到本测试模块，避免依赖全局 conftest 注册（保持作用域隔离）。
from tests.acceptance.steps.mq_dlq_steps import *  # noqa: F401,F403

_FEATURE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "MQ消费死信兜底"
    / "acceptance.feature"
)

scenarios(str(_FEATURE))
