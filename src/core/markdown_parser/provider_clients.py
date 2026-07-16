# -*- coding: utf-8 -*-
"""Provider-backed implementations for markdown parser table/image enhancement."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import urlopen

from loguru import logger

from src.core.prompts.markdown_enhancement import (
    TABLE_PROMPT_TEMPLATE,
    TABLE_SYSTEM_PROMPT,
    VISION_PROMPT_TEMPLATE,
)
from src.observability.logging import (
    fingerprint_log_value,
    safe_exception_stack,
    sanitize_url_for_log,
    truncate_log_value,
)

from .llm_integration import TableClient, VisionClient

if TYPE_CHECKING:
    from src.core.llm.interfaces import BaseProvider, CapabilityType
else:
    BaseProvider = Any
    CapabilityType = Any

class LLMConfigMissingError(RuntimeError):
    """指定能力没有可用的用户默认或 LinkRag 系统默认配置。

    专用于区分「确实未配置」与「配置读取失败」：仅在 ``ConfigReaderService``
    成功返回且用户默认、LinkRag 系统默认均为空时抛出。读取本身
    失败（Redis/DB 异常）不在此列，按原异常向上传播，避免被误判为「无配置」。

    增强构造器会把该异常转为 ``EnhancementModelMissingError``。
    """

    def __init__(self, capability: str, user_id: int) -> None:
        self.capability = capability
        self.user_id = user_id
        super().__init__(
            f"User {user_id} has no default LLM config for capability '{capability}'"
        )


class EnhancementModelMissingError(RuntimeError):
    """数据集开启了表格/图片增强，但没有对应能力的有效默认模型。

    数据集层已不再选择增强模型——增强按「发起用户默认 → LinkRag 系统默认预设」解析
    （表格→CHAT，图片→VISION）。两层都未命中时直接失败，解析链路据此把任务收敛为 FAILED，
    并通过 ``kind`` 区分是表格还是图片增强。
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind  # "table" | "vision"
        capability = "CHAT" if kind == "table" else "VISION"
        super().__init__(
            f"{kind} enhancement enabled but no effective default {capability} model is available"
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


def _report_enhancement_usage(
    *,
    user_id: int | None,
    provider_type: str | None,
    model_name: str | None,
    config_id: int | None,
    operation: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    """解析侧 vision/table 增强用量上报（旁路、非阻塞，失败不阻断）。

    仅在按用户构造（有 ``user_id``）且确有 token 时上报；系统默认 client 无 user_id，跳过。
    provider client 不知道所属解析任务，故不带 ``task_id``——user + model 足以做成本归因。
    lazy import ``report_usage_nowait`` 避免 core → services 的模块级耦合；它调度后台 task
    发送、立即返回，不阻塞增强主链路。
    """
    if not user_id or total_tokens <= 0:
        return
    from src.services.usage_reporter import report_usage_nowait

    report_usage_nowait(
        user_id=user_id,
        provider_type=provider_type or "",
        model_name=model_name or "",
        stage="parse",
        operation=operation,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        config_id=config_id,
    )


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
    # 系统级 LLM 固定 openai 兼容；env 配的是 base，按能力补 openai 后缀成完整端点 URL。
    _cap = _get_capability_type()
    _base = (settings.SYSTEM_LLM_API_BASE or "").rstrip("/")
    _suffix = "/embeddings" if capability == _cap.EMBEDDING else "/chat/completions"
    provider = _get_model_factory().create_client(
        protocol="openai",
        provider_type=settings.SYSTEM_LLM_PROVIDER,
        api_key=settings.SYSTEM_LLM_API_KEY or "",
        api_base_url=f"{_base}{_suffix}" if _base else settings.SYSTEM_LLM_API_BASE,
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


async def _resolve_user_model(capability_str: str, *, user_id: int):
    """按发起用户解析增强用 LLM 模型（provider + 模型名）。

    经统一的 :func:`src.core.llm.user_model_resolver.aresolve_user_model` 按
    ``user_id + capability`` 按「用户默认 → LinkRag 系统默认预设」取有效配置并构造 Provider。
    增强不在数据集层选择模型，故不传 ``fallback_model``——使用命中配置自身的模型名。
    两层均无该能力默认配置时统一解析抛 ``UserModelConfigMissingError``，本函数在边界重抛
    :class:`LLMConfigMissingError`（再由 ``abuild_*`` 转为 :class:`EnhancementModelMissingError`）；
    配置读取异常按原样向上传播（不转成「无配置」）。

    Args:
        capability_str: 配置表能力字符串（CHAT / VISION），用于按能力查配置与能力校验。
        user_id: 发起解析任务的用户 ID。

    Returns:
        ``ResolvedModel``：含 provider、命中配置的模型名与来源。

    Raises:
        LLMConfigMissingError: 用户和 LinkRag 系统均无该能力的默认 LLM 配置。
        ValueError: 配置的 provider 不支持该能力。
    """
    from src.core.llm.exceptions import UserModelConfigMissingError
    from src.core.llm.user_model_resolver import aresolve_user_model

    try:
        resolved = await aresolve_user_model(
            user_id=user_id,
            capability=capability_str,
            allow_linkrag_default=True,
        )
    except UserModelConfigMissingError as exc:
        raise LLMConfigMissingError(capability_str, user_id) from exc
    return resolved


async def abuild_table_client(user_id: int) -> "ProviderTableClient":
    """按发起用户 CHAT 默认配置构造表格增强 client（增强开启时校验默认模型已配）。

    表格增强不在数据集层选择模型，统一用发起用户 CHAT 能力的默认 LLM 配置（含其模型名）。
    用户未配置 CHAT 默认模型时回退 LinkRag 系统默认预设；两层都未命中时抛
    :class:`EnhancementModelMissingError`。
    """
    try:
        resolved = await _resolve_user_model("CHAT", user_id=user_id)
    except LLMConfigMissingError as exc:
        raise EnhancementModelMissingError("table") from exc
    return ProviderTableClient(
        provider=resolved.provider,
        model_name=resolved.model_name,
        user_id=user_id,
        provider_type=getattr(resolved, "provider_type", None),
        # usage_report.config_id 只接受 llm_user_config.id；系统预设调用按契约传 NULL。
        config_id=(getattr(resolved, "config_id", None) if resolved.source == "user" else None),
    )


async def abuild_vision_client(user_id: int) -> "ProviderVisionClient":
    """按发起用户 VISION 默认配置构造图片增强 client（增强开启时校验默认模型已配）。

    图片增强不在数据集层选择模型，统一用发起用户 VISION 能力的默认 LLM 配置（含其模型名）。
    用户未配置 VISION 默认模型时回退 LinkRag 系统默认预设；两层都未命中时抛
    :class:`EnhancementModelMissingError`，不静默跳过（与表格增强对称）。
    """
    try:
        resolved = await _resolve_user_model("VISION", user_id=user_id)
    except LLMConfigMissingError as exc:
        raise EnhancementModelMissingError("vision") from exc
    return ProviderVisionClient(
        provider=resolved.provider,
        model_name=resolved.model_name,
        user_id=user_id,
        provider_type=getattr(resolved, "provider_type", None),
        # usage_report.config_id 只接受 llm_user_config.id；系统预设调用按契约传 NULL。
        config_id=(getattr(resolved, "config_id", None) if resolved.source == "user" else None),
    )


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
        user_id: int | None = None,
        provider_type: str | None = None,
        config_id: int | None = None,
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
        self._model_name = resolved_model_name
        # 用量归属上下文：DB 系统预设仍归属发起用户，但 config_id 按 MQ 契约传 None。
        self._user_id = user_id
        self._provider_type = provider_type
        self._config_id = config_id

    def describe_tables(self, tables, source_file=None):
        raise RuntimeError("ProviderTableClient only supports async usage. Please call `adescribe_tables`.")

    async def adescribe_tables(self, tables: list[str], source_file: str | None = None) -> dict[str, str]:
        results: dict[str, str] = {}
        prompt_tokens_sum = 0
        completion_tokens_sum = 0
        total_tokens_sum = 0
        resolved_model = self._model_name
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
            usage = getattr(response, "usage", None)
            if usage is not None:
                prompt_tokens_sum += int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens_sum += int(getattr(usage, "completion_tokens", 0) or 0)
                total_tokens_sum += int(getattr(usage, "total_tokens", 0) or 0)
            resolved_model = getattr(response, "model", None) or resolved_model
            description = _clean_llm_text(response.content if response else "")
            if description:
                results[table] = description

        # 用量上报（旁路）：表格增强是文本生成，prompt/completion 均真实计入；按本次调用
        # （= 本文档全部表格）聚合一条。仅在按用户构造且确有 token 时上报。
        _report_enhancement_usage(
            user_id=self._user_id,
            provider_type=self._provider_type,
            model_name=resolved_model,
            config_id=self._config_id,
            operation="table",
            prompt_tokens=prompt_tokens_sum,
            completion_tokens=completion_tokens_sum,
            total_tokens=total_tokens_sum,
        )
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
        user_id: int | None = None,
        provider_type: str | None = None,
        config_id: int | None = None,
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
        # 用量归属上下文：DB 系统预设仍归属发起用户，但 config_id 按 MQ 契约传 None。
        self._user_id = user_id
        self._provider_type = provider_type
        self._config_id = config_id
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
        triples = await asyncio.gather(*tasks)

        # 聚合本次调用（= 本文档全部图片）各图的 token，按 vision 一条上报。
        prompt_tokens_sum = 0
        completion_tokens_sum = 0
        total_tokens_sum = 0
        resolved_model = self._model_name
        for _url, _desc, usage in triples:
            if usage is not None:
                prompt_tokens_sum += int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens_sum += int(getattr(usage, "completion_tokens", 0) or 0)
                total_tokens_sum += int(getattr(usage, "total_tokens", 0) or 0)
        _report_enhancement_usage(
            user_id=self._user_id,
            provider_type=self._provider_type,
            model_name=resolved_model,
            config_id=self._config_id,
            operation="vision",
            prompt_tokens=prompt_tokens_sum,
            completion_tokens=completion_tokens_sum,
            total_tokens=total_tokens_sum,
        )

        return {
            image_url: description
            for image_url, description, _usage in triples
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
    ) -> tuple[str, str | None, object | None]:
        async with semaphore:
            try:
                if image_bytes_by_url and image_url in image_bytes_by_url:
                    image_bytes, mime_type = image_bytes_by_url[image_url]
                else:
                    image_bytes, mime_type = await asyncio.to_thread(
                        _load_image_bytes,
                        image_url,
                        source_file,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.bind(
                    event="image_enhancement_failed",
                    outcome="skipped",
                    stage="image_load",
                    image_ref=fingerprint_log_value(image_url),
                    image_location=sanitize_url_for_log(image_url),
                    error_type=type(exc).__name__,
                    error_message=truncate_log_value(exc),
                    stack_trace=safe_exception_stack(exc),
                ).warning(
                    "图片增强加载失败，已跳过: image_ref={}",
                    fingerprint_log_value(image_url),
                )
                return image_url, None, None

            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            prompt = self._prompt_template.format(source_context=source_context)
            analyze_kwargs = {"model": self._model_name} if self._model_name else {}
            if mime_type:
                # 透传真实图片 mime（PNG/webp…），不让 provider 写死 jpeg 而被 Anthropic/Google 拒图。
                analyze_kwargs["media_type"] = mime_type
            try:
                response = await self._provider.analyze_image(
                    image_base64=image_base64,
                    prompt=prompt,
                    **analyze_kwargs,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.bind(
                    event="image_enhancement_failed",
                    outcome="skipped",
                    stage="vision_call",
                    image_ref=fingerprint_log_value(image_url),
                    image_location=sanitize_url_for_log(image_url),
                    model_name=self._model_name or "",
                    error_type=type(exc).__name__,
                    error_message=truncate_log_value(exc),
                    stack_trace=safe_exception_stack(exc),
                ).warning(
                    "图片增强模型调用失败，已跳过: image_ref={}",
                    fingerprint_log_value(image_url),
                )
                return image_url, None, None

            description = _clean_llm_text(response.content if response else "")
            return image_url, description or None, getattr(response, "usage", None)

    @staticmethod
    def _normalize_concurrency(value: int | str | None) -> int:
        try:
            return max(1, int(value if value is not None else 1))
        except (TypeError, ValueError):
            logger.warning(
                "图片增强并发配置非法，回退为 1: configured_value={}",
                value,
            )
            return 1


def build_default_table_client() -> ProviderTableClient:
    return ProviderTableClient()


def build_default_vision_client() -> ProviderVisionClient:
    return ProviderVisionClient()
