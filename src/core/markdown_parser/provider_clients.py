# -*- coding: utf-8 -*-
"""Provider-backed implementations for markdown parser table/image enhancement."""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from .llm_integration import TableClient, VisionClient

logger = logging.getLogger(__name__)

TABLE_SYSTEM_PROMPT = (
    "你是文档解析助手。你会阅读 Markdown 表格，并输出一句简洁、准确、可直接用于检索增强的中文总结。"
    "不要复述表头格式，不要输出多段内容，不要加前缀标签。"
)

VISION_PROMPT_TEMPLATE = (
    "请描述这张图片的关键信息，输出一段简洁、准确的中文说明。"
    "优先关注图片里可帮助理解文档的信息，不要输出'这是一张图片'之类空话。"
    "{source_context}"
)

TABLE_PROMPT_TEMPLATE = """请阅读下面的 Markdown 表格，并给出一句简洁、准确的中文总结。
如果表格中包含对比关系、统计结果或异常值，请优先点出最重要的信息。

来源文件: {source_file}

Markdown 表格:
{table}
"""


def _clean_llm_text(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    cleaned = cleaned.strip().strip('"').strip("'")
    return " ".join(part.strip() for part in cleaned.splitlines() if part.strip())


def _guess_source_file(source_file: str | None) -> str:
    return source_file or "unknown"


def _resolve_relative_path(image_url: str, source_file: str | None) -> Path:
    image_path = Path(image_url)
    if image_path.is_absolute():
        return image_path
    if source_file:
        return Path(source_file).resolve().parent / image_path
    return image_path.resolve()


def _load_image_bytes(image_url: str, source_file: str | None) -> tuple[bytes, str]:
    parsed = urlparse(image_url)

    if image_url.startswith("data:"):
        header, encoded = image_url.split(",", 1)
        mime_type = header.split(";")[0].split(":", 1)[1] if ":" in header else "image/jpeg"
        return base64.b64decode(encoded), mime_type

    if parsed.scheme in {"http", "https"}:
        settings = _get_settings()
        with urlopen(image_url, timeout=max(settings.MINERU_TIMEOUT, 30)) as response:
            content_type = response.headers.get_content_type() or "image/jpeg"
            return response.read(), content_type

    if parsed.scheme == "file":
        file_path = Path(parsed.path)
    else:
        file_path = _resolve_relative_path(image_url, source_file)

    image_bytes = file_path.read_bytes()
    mime_type = mimetypes.guess_type(str(file_path))[0] or "image/jpeg"
    return image_bytes, mime_type


def _build_system_provider(capability: CapabilityType, model_name: str | None = None) -> BaseProvider:
    settings = _get_settings()
    provider = _get_model_factory().create_client(
        provider_type=settings.SYSTEM_LLM_PROVIDER,
        api_key=settings.SYSTEM_LLM_API_KEY or "",
        api_base_url=settings.SYSTEM_LLM_API_BASE,
        model_name=model_name,
        timeout_ms=settings.MARKDOWN_PARSER_LLM_TIMEOUT_MS,
    )
    if not provider.has_capability(capability):
        raise ValueError(
            f"Configured provider '{provider.provider_type}' does not support capability '{capability.value}'"
        )
    return provider


def _get_settings():
    from src.config import settings

    return settings


def _get_model_factory():
    from src.core.llm.factory import ModelFactory

    return ModelFactory()


def _get_capability_type():
    from src.core.llm.interfaces import CapabilityType

    return CapabilityType


class ProviderTableClient(TableClient):
    """Async table description client backed by the project's text provider."""

    def __init__(
        self,
        provider: BaseProvider | None = None,
        *,
        system_prompt: str = TABLE_SYSTEM_PROMPT,
        temperature: float = 0.2,
        max_tokens: int = 256,
        model_name: str | None = None,
    ) -> None:
        capability_type = _get_capability_type()
        resolved_model_name = model_name
        if provider is None:
            settings = _get_settings()
            resolved_model_name = (
                model_name or settings.MARKDOWN_PARSER_TABLE_MODEL or settings.SYSTEM_LLM_MODEL_CHAT
            )
            self._provider = _build_system_provider(capability_type.TEXT, resolved_model_name)
        else:
            self._provider = provider
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._max_tokens = max_tokens

    def describe_tables(self, tables, source_file=None):
        raise RuntimeError("ProviderTableClient only supports async usage. Please call `adescribe_tables`.")

    async def adescribe_tables(self, tables: list[str], source_file: str | None = None) -> dict[str, str]:
        results: dict[str, str] = {}
        for table in tables:
            prompt = TABLE_PROMPT_TEMPLATE.format(
                source_file=_guess_source_file(source_file),
                table=table,
            )
            response = await self._provider.generate(
                prompt=prompt,
                system_prompt=self._system_prompt,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            description = _clean_llm_text(response.content if response else "")
            if description:
                results[table] = description
        return results


class ProviderVisionClient(VisionClient):
    """Async image description client backed by the project's vision provider."""

    def __init__(
        self,
        provider: BaseProvider | None = None,
        *,
        prompt_template: str = VISION_PROMPT_TEMPLATE,
        model_name: str | None = None,
    ) -> None:
        capability_type = _get_capability_type()
        resolved_model_name = model_name
        if provider is None:
            settings = _get_settings()
            resolved_model_name = (
                model_name or settings.MARKDOWN_PARSER_VISION_MODEL or settings.SYSTEM_LLM_MODEL_VISION
            )
            self._provider = _build_system_provider(capability_type.VISION, resolved_model_name)
        else:
            self._provider = provider
        self._prompt_template = prompt_template
        self._model_name = resolved_model_name

    def describe_images(self, image_urls, source_file=None):
        raise RuntimeError("ProviderVisionClient only supports async usage. Please call `adescribe_images`.")

    async def adescribe_images(self, image_urls: list[str], source_file: str | None = None) -> dict[str, str]:
        results: dict[str, str] = {}
        source_context = f"\n来源文件: {_guess_source_file(source_file)}" if source_file else ""

        for image_url in image_urls:
            try:
                image_bytes, _mime_type = _load_image_bytes(image_url, source_file)
            except Exception as exc:
                logger.warning("Load image failed for %s: %s", image_url, exc)
                continue

            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            prompt = self._prompt_template.format(source_context=source_context)
            response = await self._provider.analyze_image(
                image_base64=image_base64,
                prompt=prompt,
                model=self._model_name,
            )
            description = _clean_llm_text(response.content if response else "")
            if description:
                results[image_url] = description

        return results


def build_default_table_client() -> ProviderTableClient:
    return ProviderTableClient()


def build_default_vision_client() -> ProviderVisionClient:
    return ProviderVisionClient()
