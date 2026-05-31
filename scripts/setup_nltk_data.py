"""下载项目所需的 NLTK 数据资源到项目内固定目录，摆脱对用户家目录 ``~/nltk_data`` 的依赖。

为什么需要它：
- ``deepdoc_lib`` / ``infinity-sdk`` / ``langchain_text_splitters`` / ``transformers`` 等依赖会在
  运行时请求 NLTK 资源（``punkt`` / ``punkt_tab`` / ``stopwords`` 等）。
- NLTK 默认优先搜索 ``~/nltk_data``，这在本机能跑，但部署到服务器（家目录无数据）会触发
  运行时联网下载，甚至直接失败。

本脚本把资源统一下载到 ``<项目根>/nltk_data``（或 ``NLTK_DATA`` 指定目录），供构建/部署阶段调用：
- Docker 构建：``RUN python scripts/setup_nltk_data.py``
- 本地开发：``python scripts/setup_nltk_data.py``

运行时由 :mod:`src.nltk_bootstrap` 把该目录注入 ``nltk.data.path``，保证优先命中项目内资源。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 项目实际用到的 NLTK 资源包：本地 ~/nltk_data 现存包 + 依赖库代码中 nltk.download 请求的包的并集。
REQUIRED_PACKAGES = (
    "punkt",
    "punkt_tab",
    "stopwords",
    "wordnet",
    "omw-1.4",
)


def resolve_target_dir() -> Path:
    """解析下载目标目录：优先 ``NLTK_DATA`` 环境变量，否则用 ``<项目根>/nltk_data``。"""
    env_dir = os.environ.get("NLTK_DATA")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    project_root = Path(__file__).resolve().parent.parent
    return project_root / "nltk_data"


def main() -> int:
    try:
        import nltk
    except ImportError:
        print("[setup_nltk_data] 未安装 nltk，请先 `pip install -e .` 或 `pip install nltk`", file=sys.stderr)
        return 1

    target_dir = resolve_target_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"[setup_nltk_data] 目标目录: {target_dir}")

    failed: list[str] = []
    for package in REQUIRED_PACKAGES:
        print(f"[setup_nltk_data] 下载 {package} ...")
        ok = nltk.download(package, download_dir=str(target_dir), quiet=True)
        if not ok:
            failed.append(package)
            print(f"[setup_nltk_data] 警告: {package} 下载失败", file=sys.stderr)

    if failed:
        print(f"[setup_nltk_data] 以下资源下载失败: {', '.join(failed)}", file=sys.stderr)
        return 1

    print(f"[setup_nltk_data] 完成，共 {len(REQUIRED_PACKAGES)} 个资源就绪于 {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
