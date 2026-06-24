"""pytest-bdd 入口：加载轻量流程编排引擎 acceptance.feature。"""

from pathlib import Path

from pytest_bdd import scenarios

from tests.acceptance.steps.workflow_engine_steps import *  # noqa: F401,F403

_FEATURE = Path(__file__).resolve().parent / "features" / "workflow_engine.feature"

scenarios(str(_FEATURE))
