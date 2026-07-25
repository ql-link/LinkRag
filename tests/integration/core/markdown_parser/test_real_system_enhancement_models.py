"""解析增强 Dataset 精确模型配置的真实环境冒烟测试。

本模块按显式 ``config_id`` 读取 ``DATABASE_URL`` 指向数据库中的 CHAT / VISION 配置，
并真实调用外部模型接口。默认跳过，仅在显式设置以下开关时运行：

    TOLINK_RUN_REAL_ENHANCEMENT_MODEL_TESTS=1 \
      TOLINK_REAL_ENHANCEMENT_USER_ID=<user_id> \
      TOLINK_REAL_ENHANCEMENT_CHAT_CONFIG_ID=<config_id> \
      TOLINK_REAL_ENHANCEMENT_VISION_CONFIG_ID=<config_id> \
      pytest --run-integration -m real_env \
      tests/integration/core/markdown_parser/test_real_system_enhancement_models.py

USER scope 配置必须归属于 ``TOLINK_REAL_ENHANCEMENT_USER_ID``；SYSTEM scope 配置可由任意
用户使用。测试只读数据库、不写业务数据，并屏蔽用量 MQ 上报。
"""

from __future__ import annotations

import os
import struct
import zlib
from unittest.mock import MagicMock

import pytest

from src.core.markdown_parser.heading_hierarchy import (
    HeadingHierarchyConfig,
    HeadingHierarchyProcessor,
    build_heading_plan_generator,
)
from src.core.markdown_parser.provider_clients import (
    abuild_table_client,
    abuild_vision_client,
)
from src.database import close_database
from src.core.llm.user_model_resolver import aresolve_model


def _enabled() -> bool:
    return os.getenv("TOLINK_RUN_REAL_ENHANCEMENT_MODEL_TESTS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _user_id() -> int:
    raw = os.getenv("TOLINK_REAL_ENHANCEMENT_USER_ID", "").strip()
    if not raw:
        pytest.skip("Set TOLINK_REAL_ENHANCEMENT_USER_ID to the config access user.")
    return int(raw)


def _config_id(capability: str) -> int:
    name = f"TOLINK_REAL_ENHANCEMENT_{capability}_CONFIG_ID"
    raw = os.getenv(name, "").strip()
    if not raw:
        pytest.skip(f"Set {name} to an exact llm_model_config id.")
    return int(raw)


async def _resolved(capability: str):
    return await aresolve_model(
        user_id=_user_id(),
        config_id=_config_id(capability),
        capability=capability,
    )


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def _test_png() -> bytes:
    """生成 32x32 左红右蓝 RGB PNG，避免依赖 Pillow 或本地测试图片。"""
    width = height = 32
    rows = []
    for _ in range(height):
        pixels = b"".join(
            b"\xff\x00\x00" if x < width // 2 else b"\x00\x00\xff" for x in range(width)
        )
        rows.append(b"\x00" + pixels)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + _png_chunk(b"IEND", b"")
    )


async def _close_provider(provider) -> None:
    client = getattr(provider, "_client", None)
    close = getattr(client, "close", None)
    if close is not None:
        await close()


class _FixedTokenCounter:
    def count_tokens(self, _text: str) -> int:
        return 512


pytestmark = [
    pytest.mark.real_env,
    pytest.mark.skipif(
        not _enabled(),
        reason=(
            "Set TOLINK_RUN_REAL_ENHANCEMENT_MODEL_TESTS=1 to call real CHAT / VISION "
            "exact Dataset-bound models."
        ),
    ),
]


@pytest.mark.asyncio
async def test_real_exact_chat_model_describes_table(monkeypatch):
    import src.core.markdown_parser.provider_clients as provider_clients

    monkeypatch.setattr(provider_clients, "_report_enhancement_usage", lambda **_kwargs: None)
    resolved = await _resolved("CHAT")
    client = await abuild_table_client(resolved, user_id=_user_id())
    await close_database()
    table = "| 产品 | 数量 |\n| --- | ---: |\n| A | 2 |\n| B | 3 |"
    try:
        descriptions = await client.adescribe_tables([table], source_file="real-smoke.md")
    finally:
        await _close_provider(client._provider)

    assert descriptions.get(table, "").strip()
    assert client._provider_type == resolved.provider_type
    assert client._config_id == _config_id("CHAT")


@pytest.mark.asyncio
async def test_real_exact_vision_model_describes_image(monkeypatch):
    import src.core.markdown_parser.provider_clients as provider_clients

    monkeypatch.setattr(provider_clients, "_report_enhancement_usage", lambda **_kwargs: None)
    resolved = await _resolved("VISION")
    client = await abuild_vision_client(resolved, user_id=_user_id())
    await close_database()
    image_url = "memory://red-blue.png"
    try:
        descriptions = await client.adescribe_images(
            [image_url],
            source_file="real-smoke.md",
            image_bytes_by_url={image_url: (_test_png(), "image/png")},
        )
    finally:
        await _close_provider(client._provider)

    assert descriptions.get(image_url, "").strip()
    assert client._provider_type == resolved.provider_type
    assert client._config_id == _config_id("VISION")


@pytest.mark.asyncio
async def test_real_exact_chat_model_generates_heading_plan(monkeypatch):
    import src.core.markdown_parser.heading_hierarchy as heading_hierarchy

    report = MagicMock()
    monkeypatch.setattr(heading_hierarchy, "_report_heading_usage", report)
    resolved = await _resolved("CHAT")
    generator = build_heading_plan_generator(
        resolved,
        user_id=_user_id(),
        context_token_budget=65536,
        max_output_tokens=4096,
    )
    await close_database()
    processor = HeadingHierarchyProcessor(
        config=HeadingHierarchyConfig(
            enabled=True,
            no_heading_min_tokens=1,
            llm_context_token_budget=65536,
            llm_max_output_tokens=4096,
        ),
        tokenizer=_FixedTokenCounter(),
        generator=generator,
    )
    try:
        result = await processor.aprocess(
            "第一段介绍系统目标。\n\n第二段说明实施步骤。",
            source_file="real-smoke.md",
            user_id=_user_id(),
        )
    finally:
        await _close_provider(generator._provider)

    assert result.decision.should_generate is True
    report.assert_called_once()
    assert generator._provider_type == resolved.provider_type
    assert generator._config_id == _config_id("CHAT")
