"""NLTK 数据路径引导：让项目内的 ``nltk_data`` 目录始终优先于用户家目录。

部署痛点：NLTK 默认优先搜索 ``~/nltk_data``，本机能跑但服务器家目录无数据，会触发
运行时联网下载或直接失败。本模块在应用启动早期把项目内数据目录注入 ``nltk.data.path``
最前端，保证依赖（deepdoc/infinity-sdk/langchain/transformers）请求资源时优先命中项目目录。

解析顺序：
1. 环境变量 ``NLTK_DATA``（Docker 镜像里设为 ``/app/nltk_data``）；
2. 否则用 ``<项目根>/nltk_data``。

数据本身不入 Git，由 ``scripts/setup_nltk_data.py`` 在构建/部署阶段下载。
"""

from __future__ import annotations

import os
from pathlib import Path


def _resolve_nltk_data_dir() -> Path:
    env_dir = os.environ.get("NLTK_DATA")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path(__file__).resolve().parent.parent.parent / "nltk_data"


def configure_nltk_data_path() -> str:
    """把项目内 nltk_data 目录注入 ``nltk.data.path`` 最前端，返回该目录路径。

    幂等：重复调用不会重复插入。nltk 未安装时静默跳过（让真正用到它的依赖自行报错）。
    """
    target = _resolve_nltk_data_dir()
    target_str = str(target)

    # 同时设置环境变量，覆盖在本进程内尚未 import nltk 的子库读取场景。
    os.environ.setdefault("NLTK_DATA", target_str)

    try:
        import nltk
    except ImportError:
        return target_str

    if target_str not in nltk.data.path:
        nltk.data.path.insert(0, target_str)
    return target_str


__all__ = ["configure_nltk_data_path"]
