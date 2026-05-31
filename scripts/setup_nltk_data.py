"""下载项目所需的 NLTK 数据资源到项目内固定目录，摆脱对用户家目录 ``~/nltk_data`` 的依赖。

为什么需要它：
- ``deepdoc_lib`` / ``infinity-sdk`` / ``langchain_text_splitters`` / ``transformers`` 等依赖会在
  运行时请求 NLTK 资源（``punkt`` / ``punkt_tab`` / ``stopwords`` 等）。
- NLTK 默认优先搜索 ``~/nltk_data``，这在本机能跑，但部署到服务器（家目录无数据）会触发
  运行时联网下载，甚至直接失败。

本脚本把资源统一下载到 ``<项目根>/nltk_data``（或 ``NLTK_DATA`` 指定目录），供构建/部署阶段调用：
- Docker 构建：``RUN python scripts/setup_nltk_data.py``
- 本地开发：``python scripts/setup_nltk_data.py``

下载策略（国内网络友好）：
1. 若设置环境变量 ``NLTK_GH_PROXY``（如 ``https://gh-proxy.com/``），优先经该 GitHub 加速代理下载；
2. 否则/失败后回退官方 ``raw.githubusercontent.com``；
3. 仍失败则最后用 ``nltk.download`` 兜底。
已存在的资源会跳过，re-run 幂等。

运行时由 :mod:`src.nltk_bootstrap` 把该目录注入 ``nltk.data.path``，保证优先命中项目内资源。
"""

from __future__ import annotations

import io
import os
import sys
import zipfile
import urllib.request
from pathlib import Path

# 需要的资源 -> (NLTK 类别目录, 官方 packages 下的相对 zip 路径)
PACKAGE_LAYOUT = {
    "punkt":     ("tokenizers", "tokenizers/punkt.zip"),
    "punkt_tab": ("tokenizers", "tokenizers/punkt_tab.zip"),
    "stopwords": ("corpora", "corpora/stopwords.zip"),
    "wordnet":   ("corpora", "corpora/wordnet.zip"),
    "omw-1.4":   ("corpora", "corpora/omw-1.4.zip"),
}
REQUIRED_PACKAGES = tuple(PACKAGE_LAYOUT.keys())

OFFICIAL_BASE = "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/"


def resolve_target_dir() -> Path:
    """解析下载目标目录：优先 ``NLTK_DATA`` 环境变量，否则用 ``<项目根>/nltk_data``。"""
    env_dir = os.environ.get("NLTK_DATA")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    project_root = Path(__file__).resolve().parent.parent
    return project_root / "nltk_data"


def _download_and_extract(url: str, dest_category_dir: Path) -> bool:
    """下载 zip 并解压到指定类别目录。成功返回 True。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(dest_category_dir)
        return True
    except Exception as exc:  # noqa: BLE001 - 下载失败原因多样，统一兜底
        print(f"  [setup_nltk_data] 失败 {url} -> {exc}", file=sys.stderr)
        return False


def main() -> int:
    target_dir = resolve_target_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    proxy = os.environ.get("NLTK_GH_PROXY", "").strip()
    print(f"[setup_nltk_data] 目标目录: {target_dir}; GitHub 代理: {proxy or '(无)'}")

    failed: list[str] = []
    for pkg, (category, rel_path) in PACKAGE_LAYOUT.items():
        dest = target_dir / category
        dest.mkdir(parents=True, exist_ok=True)
        if (dest / pkg).exists():
            print(f"[setup_nltk_data] {pkg} 已存在，跳过")
            continue

        official_url = OFFICIAL_BASE + rel_path
        candidate_urls = ([proxy + official_url] if proxy else []) + [official_url]

        ok = False
        for url in candidate_urls:
            print(f"[setup_nltk_data] 下载 {pkg} <- {url}")
            if _download_and_extract(url, dest):
                ok = True
                break

        if not ok:
            # 最后兜底：交给 nltk 自身的下载器（官方源）
            try:
                import nltk
                ok = bool(nltk.download(pkg, download_dir=str(target_dir), quiet=True))
            except Exception as exc:  # noqa: BLE001
                print(f"  [setup_nltk_data] nltk.download 兜底失败 {pkg} -> {exc}", file=sys.stderr)
                ok = False

        if not ok:
            failed.append(pkg)

    if failed:
        print(f"[setup_nltk_data] 以下资源下载失败: {', '.join(failed)}", file=sys.stderr)
        return 1

    print(f"[setup_nltk_data] 完成，共 {len(REQUIRED_PACKAGES)} 个资源就绪于 {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
