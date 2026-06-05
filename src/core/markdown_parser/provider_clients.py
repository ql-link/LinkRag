# -*- coding: utf-8 -*-
"""Provider-backed implementations for markdown parser table/image enhancement."""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from src.core.prompts.markdown_enhancement import (
    TABLE_PROMPT_TEMPLATE,
    TABLE_SYSTEM_PROMPT,
    VISION_PROMPT_TEMPLATE,
)

from .llm_integration import TableClient, VisionClient

logger = logging.getLogger(__name__)


class LLMConfigMissingError(RuntimeError):
    """发起用户缺少某项必配能力的默认 LLM 配置。

    专用于区分「用户确实未配置」与「配置读取失败」：仅在 ``ConfigReaderService``
    成功返回且结果为空（用户没有该能力的 ``is_default`` 配置）时抛出。读取本身
    失败（Redis/DB 异常）不在此列，按原异常向上传播，避免被误判为「无配置」。

    解析链路据此把 CHAT（必配）缺失收敛为任务失败（``LLM_CONFIG_MISSING``），
    而 VISION（非必配）缺失由调用方捕获后跳过图片增强。
    """

    def __init__(self, capability: str, user_id: int) -> None:
        self.capability = capability
        self.user_id = user_id
        super().__init__(
            f"User {user_id} has no default LLM config for capability '{capability}'"
        )


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


async def _resolve_user_provider(
    capability_str: str,
    *,
    user_id: int,
    model_name: str | None,
) -> BaseProvider:
    """按发起用户解析增强用 LLM Provider。

    经统一的 :func:`src.core.llm.user_model_resolver.aresolve_user_model` 按
    ``user_id + capability`` 取默认配置并构造 Provider。用户无该能力默认配置时统一解析抛
    ``UserModelConfigMissingError``，本函数在边界重抛 :class:`LLMConfigMissingError` 以保留
    解析链路既有的失败语义；配置读取异常按原样向上传播（不转成「无配置」）。

    Args:
        capability_str: 配置表能力字符串（CHAT / VISION），用于按能力查配置与能力校验。
        user_id: 发起解析任务的用户 ID。
        model_name: 用户配置未指定模型时的回退模型名。

    Returns:
        按用户配置构造的 Provider 实例。

    Raises:
        LLMConfigMissingError: 用户无该能力的默认 LLM 配置。
        ValueError: 配置的 provider 不支持该能力。
    """
    from src.core.llm.exceptions import UserModelConfigMissingError
    from src.core.llm.user_model_resolver import aresolve_user_model

    try:
        resolved = await aresolve_user_model(
            user_id=user_id, capability=capability_str, fallback_model=model_name
        )
    except UserModelConfigMissingError as exc:
        raise LLMConfigMissingError(capability_str, user_id) from exc
    return resolved.provider


async def abuild_table_client(user_id: int) -> "ProviderTableClient":
    """按发起用户的 CHAT 默认配置构造表格增强 client（缺失则抛 LLMConfigMissingError）。"""
    settings = _get_settings()
    model_name = settings.MARKDOWN_PARSER_TABLE_MODEL or settings.SYSTEM_LLM_MODEL_CHAT
    provider = await _resolve_user_provider("CHAT", user_id=user_id, model_name=model_name)
    return ProviderTableClient(provider=provider)


async def abuild_vision_client(user_id: int) -> "ProviderVisionClient":
    """按发起用户的 VISION 默认配置构造图片增强 client（缺失则抛 LLMConfigMissingError）。"""
    settings = _get_settings()
    model_name = settings.MARKDOWN_PARSER_VISION_MODEL or settings.SYSTEM_LLM_MODEL_VISION
    provider = await _resolve_user_provider("VISION", user_id=user_id, model_name=model_name)
    return ProviderVisionClient(provider=provider, model_name=model_name)


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
        max_concurrency: int | None = None,
    ) -> None:
        capability_type = _get_capability_type()
        settings = _get_settings()
        resolved_model_name = model_name
        if provider is None:
            resolved_model_name = (
                model_name or settings.MARKDOWN_PARSER_VISION_MODEL or settings.SYSTEM_LLM_MODEL_VISION
            )
            self._provider = _build_system_provider(capability_type.VISION, resolved_model_name)
        else:
            self._provider = provider
        self._prompt_template = prompt_template
        self._model_name = resolved_model_name
        concurrency = (
            max_concurrency
            if max_concurrency is not None
            else getattr(settings, "MARKDOWN_PARSER_VISION_CONCURRENCY", 24)
        )
        self._max_concurrency = self._normalize_concurrency(concurrency)

    def describe_images(self, image_urls, source_file=None, image_bytes_by_url=None):
        raise RuntimeError("ProviderVisionClient only supports async usage. Please call `adescribe_images`.")

    async def adescribe_images(
        self,
        image_urls: list[str],
        source_file: str | None = None,
        image_bytes_by_url: dict[str, tuple[bytes, str]] | None = None,
    ) -> dict[str, str]:
        if not image_urls:
            return {}

        source_context = f"\n来源文件: {_guess_source_file(source_file)}" if source_file else ""
        semaphore = asyncio.Semaphore(self._max_concurrency)
        tasks = [
            self._adescribe_one_image(
                image_url=image_url,
                source_file=source_file,
                source_context=source_context,
                image_bytes_by_url=image_bytes_by_url,
                semaphore=semaphore,
            )
            for image_url in image_urls
        ]
        pairs = await asyncio.gather(*tasks)

        return {
            image_url: description
            for image_url, description in pairs
            if description
        }

    async def _adescribe_one_image(
        self,
        *,
        image_url: str,
        source_file: str | None,
        source_context: str,
        image_bytes_by_url: dict[str, tuple[bytes, str]] | None,
        semaphore: asyncio.Semaphore,
    ) -> tuple[str, str | None]:
        async with semaphore:
            try:
                if image_bytes_by_url and image_url in image_bytes_by_url:
                    image_bytes, _mime_type = image_bytes_by_url[image_url]
                else:
                    image_bytes, _mime_type = await asyncio.to_thread(
                        _load_image_bytes,
                        image_url,
                        source_file,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Image enhancement failed for %s: %s", image_url, exc)
                return image_url, None

            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            prompt = self._prompt_template.format(source_context=source_context)
            analyze_kwargs = {"model": self._model_name} if self._model_name else {}
            try:
                response = await self._provider.analyze_image(
                    image_base64=image_base64,
                    prompt=prompt,
                    **analyze_kwargs,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Image enhancement failed for %s: %s", image_url, exc)
                return image_url, None

            description = _clean_llm_text(response.content if response else "")
            return image_url, description or None

    @staticmethod
    def _normalize_concurrency(value: int | str | None) -> int:
        try:
            return max(1, int(value if value is not None else 1))
        except (TypeError, ValueError):
            logger.warning("Invalid image enhancement concurrency %r, fallback to 1", value)
            return 1


def build_default_table_client() -> ProviderTableClient:
    return ProviderTableClient()


def build_default_vision_client() -> ProviderVisionClient:
    return ProviderVisionClient()
