"""Background 与跨 Scenario 通用前置 step。"""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given, parsers

from src.config import settings


@given(parsers.re(r'配置 PARSE_TEMP_DIR = "(?P<path>[^"]+)"'))
def _config_parse_temp_dir(path: str):
    # Background 文案是契约层声明；实际目录在 conftest.py::state fixture 里被隔离到
    # tmp_path 下，这里只校验 settings 已被注入。
    assert settings.PARSE_TEMP_DIR


@given("PARSE_TEMP_DIR 已存在且为空")
def _temp_dir_exists_empty():
    temp_dir = Path(settings.PARSE_TEMP_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)
    for p in temp_dir.iterdir():
        if p.is_file() or p.is_symlink():
            p.unlink()


@given("ParseTaskPipeline 已初始化并连接到 MinIO 驱动")
def _pipeline_initialized(pipeline_factory, state):
    # 真正的 pipeline 装配延迟到 When 步骤；这里只标记前置成立。
    state.pipeline_factory = pipeline_factory
