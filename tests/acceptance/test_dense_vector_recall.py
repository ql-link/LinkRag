"""pytest-bdd 入口：加载稠密向量召回 acceptance.feature。

step 实现见 ``tests/acceptance/steps/dense_vector_recall_steps.py``。pytest-bdd
通过 star-import 在本测试模块命名空间发现 step 函数；如某 Scenario 缺少 step
绑定，pytest-bdd 在收集阶段会直接抛错——覆盖完整性由收集机制强制保证。
"""

from pathlib import Path

from pytest_bdd import scenarios

# pytest-bdd 8.x 通过模块命名空间发现 step 函数：star-import 把所有 step 装饰器
# 加载到本测试模块，避免依赖全局 conftest 注册（保持作用域隔离）。
from tests.acceptance.steps.dense_vector_recall_steps import *  # noqa: F401,F403

_FEATURE = Path(__file__).resolve().parent / "features" / "dense_vector_recall.feature"

scenarios(str(_FEATURE))
