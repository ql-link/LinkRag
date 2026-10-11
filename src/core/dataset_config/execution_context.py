"""Dataset 模型执行上下文。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.llm.exceptions import (
    DatasetModelBindingRequiredError,
    LLMConfigCapabilityMismatchError,
)
from src.core.llm.providers.doubao_vision import DoubaoVisionProvider
from src.core.llm.runtime_repository import RuntimeConfigRepository
from src.core.llm.user_model_resolver import ResolvedModel, aresolve_model

from .models import DatasetParseConfigBundle
from .service import DatasetConfigService


class DatasetExecutionPurpose(str, Enum):
    PARSE = "PARSE"
    RECALL = "RECALL"


@dataclass(frozen=True)
class DatasetExecutionContext:
    user_id: int
    dataset_id: int
    purpose: DatasetExecutionPurpose
    config: DatasetParseConfigBundle
    dense_embedding: ResolvedModel
    sparse_embedding: ResolvedModel
    enhancement_chat: ResolvedModel | None = None
    enhancement_vision: ResolvedModel | None = None
    rerank: ResolvedModel | None = None


class DatasetExecutionContextLoader:
    """在 provider 调用前一次验证所需绑定，并对重复 ID 只解析一次。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        config_service: DatasetConfigService | None = None,
        repository: RuntimeConfigRepository | None = None,
    ) -> None:
        self._db = db
        self._config_service = config_service or DatasetConfigService()
        self._repository = repository or RuntimeConfigRepository(db=db)

    @staticmethod
    def _required(
        config: DatasetParseConfigBundle, purpose: DatasetExecutionPurpose
    ) -> list[tuple[str, int | None, str]]:
        bindings = config.model_bindings
        required: list[tuple[str, int | None, str]] = [
            ("dense_embedding_config_id", bindings.dense_embedding_config_id, "EMBEDDING"),
            (
                "sparse_embedding_config_id",
                bindings.sparse_embedding_config_id,
                "SPARSE_EMBEDDING",
            ),
        ]
        if purpose is DatasetExecutionPurpose.PARSE:
            if (
                config.enhancement.enable_table_enhancement
                or config.enhancement.enable_heading_hierarchy
            ):
                required.append(
                    (
                        "enhancement_chat_config_id",
                        bindings.enhancement_chat_config_id,
                        "CHAT",
                    )
                )
            if config.enhancement.enable_image_enhancement:
                required.append(
                    (
                        "enhancement_vision_config_id",
                        bindings.enhancement_vision_config_id,
                        "VISION",
                    )
                )
        elif config.recall.enable_rerank:
            required.append(("rerank_config_id", bindings.rerank_config_id, "RERANK"))
        return required

    async def load(
        self,
        user_id: int,
        dataset_id: int,
        purpose: DatasetExecutionPurpose,
        *,
        task_id: str | None = None,
    ) -> DatasetExecutionContext:
        config = await self._config_service.get_config(user_id, dataset_id, self._db)
        required = self._required(config, purpose)
        missing = [field for field, config_id, _ in required if config_id is None]
        if missing:
            raise DatasetModelBindingRequiredError(dataset_id, missing)

        resolved_by_id: dict[int, tuple[str, ResolvedModel]] = {}
        field_models: dict[str, ResolvedModel] = {}
        for field, raw_id, capability in required:
            assert raw_id is not None  # missing 已在上方整体拒绝
            config_id = int(raw_id)  # missing 已在上方整体拒绝
            cached = resolved_by_id.get(config_id)
            if cached is None:
                resolved = await aresolve_model(
                    user_id=user_id,
                    config_id=config_id,
                    capability=capability,
                    db=self._db,
                    repository=self._repository,
                )
                resolved_by_id[config_id] = (capability, resolved)
            else:
                resolved_capability, resolved = cached
                if resolved_capability != capability:
                    # 一条可执行配置只有一个 capability。同一 ID 被绑到
                    # 两种用途是 Dataset 坏数据；本地直接产生统一错误，
                    # 不第二次读 repository，保证 distinct configId 只解析一次。
                    raise LLMConfigCapabilityMismatchError(
                        config_id=config_id,
                        expected=capability,
                        actual=resolved_capability,
                    )
            field_models[field] = resolved

        dense = field_models["dense_embedding_config_id"]
        sparse = field_models["sparse_embedding_config_id"]
        # 两个 capability 的配置 ID 保持独立、分别完成权限校验；只有请求身份
        # 完全相同时共享本执行上下文的 provider，不改变任何数据库绑定。
        if (
            isinstance(dense.provider, DoubaoVisionProvider)
            and isinstance(sparse.provider, DoubaoVisionProvider)
            and dense.model_name == sparse.model_name
            and dense.provider.api_base_url == sparse.provider.api_base_url
            and dense.provider.api_key == sparse.provider.api_key
        ):

            def report_joint_usage(model, usage):
                from src.services.usage_reporter import report_usage_nowait

                if usage.total_tokens > 0:
                    report_usage_nowait(
                        user_id=user_id,
                        provider_type=dense.provider_type,
                        model_name=model,
                        config_id=dense.config_id,
                        stage="parse" if purpose is DatasetExecutionPurpose.PARSE else "recall",
                        operation="embed",
                        task_id=task_id,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=0,
                        total_tokens=usage.total_tokens,
                    )

            dense.provider.enable_joint_reuse(report_joint_usage)
            field_models["sparse_embedding_config_id"] = replace(sparse, provider=dense.provider)

        return DatasetExecutionContext(
            user_id=user_id,
            dataset_id=dataset_id,
            purpose=purpose,
            config=config,
            dense_embedding=field_models["dense_embedding_config_id"],
            sparse_embedding=field_models["sparse_embedding_config_id"],
            enhancement_chat=field_models.get("enhancement_chat_config_id"),
            enhancement_vision=field_models.get("enhancement_vision_config_id"),
            rerank=field_models.get("rerank_config_id"),
        )

    async def load_many(
        self,
        user_id: int,
        dataset_ids: list[int],
        purpose: DatasetExecutionPurpose,
    ) -> dict[int, DatasetExecutionContext]:
        # 各 Dataset 拥有独立 binding map；repository 物理缓存可自然共享。
        result: dict[int, DatasetExecutionContext] = {}
        joint_providers: dict[tuple[str, str | None, str], DoubaoVisionProvider] = {}
        for dataset_id in dict.fromkeys(dataset_ids):
            context = await self.load(user_id, dataset_id, purpose)
            provider = context.dense_embedding.provider
            if (
                isinstance(provider, DoubaoVisionProvider)
                and context.sparse_embedding.provider is provider
            ):
                # 一个多数据集请求内，同一 query 无需为等价绑定再次推理。
                # 每个 Dataset 已独立完成配置与权限验证；池仅在本次 load_many 内存活。
                key = (context.dense_embedding.model_name, provider.api_base_url, provider.api_key)
                shared = joint_providers.setdefault(key, provider)
                context = replace(
                    context,
                    dense_embedding=replace(context.dense_embedding, provider=shared),
                    sparse_embedding=replace(context.sparse_embedding, provider=shared),
                )
            result[dataset_id] = context
        return result
