"""正文回填 helper 迁移回归：``generation.fetch_chunk_contents`` 仍可用且为同一函数。

``fetch_chunk_contents`` 已从 ``recall.generation`` 迁到中立的 ``pipeline.chunk_content``，
``generation`` 保留 re-export。本测试只验证迁移不破坏既有导入路径（runtime 仍从
``recall.generation`` 导入），DB 查询行为本身由集成测试覆盖。
"""

from __future__ import annotations

from src.core.pipeline import chunk_content
from src.core.pipeline.recall import generation


def test_fetch_chunk_contents_reexported_from_generation():
    # runtime 仍 `from ...recall.generation import fetch_chunk_contents`，必须指向迁移后同一函数。
    assert generation.fetch_chunk_contents is chunk_content.fetch_chunk_contents


def test_fetch_chunk_contents_in_generation_all():
    assert "fetch_chunk_contents" in generation.__all__
