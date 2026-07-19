# -*- coding: utf-8 -*-
"""数据集级配置读取服务。

按 ``(user_id, dataset_id)`` 只读 ``dataset_parse_config`` 表，反序列化为四类 Pydantic
配置组成的 :class:`DatasetParseConfigBundle`。

**职责边界**：纯只读。无配置行时返回绑定为空的内存 bundle（不写库）；
DB 读取失败向上抛出，不得伪装成“没有绑定”或运维默认。配置行的增删改全部由 Java 侧负责。

DB 读取失败和 JSON 内容非法均向上传播；执行面不把基础设施故障
伪装成“无配置”或运维默认。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ChunkingConfig,
    DatasetModelBindingConfig,
    DatasetParseConfigBundle,
    EnhancementConfig,
    PDFConfig,
    RecallConfig,
)
from .repository import DatasetParseConfigRepository

logger = logging.getLogger(__name__)


def _load_enhancement_config(value) -> EnhancementConfig:
    """读取增强配置；空对象表示数据集未开启任何增强。

    Java 在数据集创建时会写入 ``{}``。该值必须与「无配置行」区分：无配置行仍使用
    Settings 系统默认，而显式存在的空对象表示该数据集没有开启表格、图片或标题层级增强。
    非空对象继续按原契约叠加 Settings，使部分覆盖保持向后兼容。
    """
    overrides = value
    if overrides == {}:
        return EnhancementConfig(
            enable_table_enhancement=False,
            enable_image_enhancement=False,
            enable_heading_hierarchy=False,
        )
    return EnhancementConfig.model_validate(
        {
            **EnhancementConfig.from_settings().model_dump(),
            **overrides,
        }
    )


class DatasetConfigService:
    """数据集解析/检索配置只读服务。"""

    def __init__(self, repository: DatasetParseConfigRepository | None = None) -> None:
        self._repository = repository or DatasetParseConfigRepository()

    async def get_vector_model_binding(
        self, user_id: int, dataset_id: int, db: AsyncSession
    ) -> DatasetModelBindingConfig:
        """读取数据集绑定的 dense/sparse 向量模型配置 ID。

        与 ``get_config`` 的 JSON 配置不同，向量模型绑定不允许回退到系统默认：
        无配置行、历史空字段或 DB 读取失败都返回空绑定或向上抛错，由消费点形成
        包含 ``dataset_id`` 与字段名的明确失败。
        """
        snapshot = await self._repository.get(user_id, dataset_id, db)
        if snapshot is None:
            return DatasetModelBindingConfig()
        return DatasetModelBindingConfig(
            sparse_embedding_config_id=snapshot.sparse_embedding_config_id,
            dense_embedding_config_id=snapshot.dense_embedding_config_id,
            enhancement_chat_config_id=snapshot.enhancement_chat_config_id,
            enhancement_vision_config_id=snapshot.enhancement_vision_config_id,
            rerank_config_id=snapshot.rerank_config_id,
        )

    async def get_config(
        self, user_id: int, dataset_id: int, db: AsyncSession
    ) -> DatasetParseConfigBundle:
        """按 ``(user_id, dataset_id)`` 读取配置；无行返回绑定为空的默认 bundle。

        Args:
            user_id: 发起方用户 ID。
            dataset_id: 数据集 ID。
            db: 异步会话。

        Returns:
            四类配置聚合的 :class:`DatasetParseConfigBundle`。

        Raises:
            pydantic.ValidationError: 已读到配置行但 JSON 字段类型非法（不静默降级）。
        """
        snapshot = await self._repository.get(user_id, dataset_id, db)

        if snapshot is None:
            # 无配置行：返回内存默认，不写库（行的写入由 Java 侧负责）。
            return DatasetParseConfigBundle.defaults()

        # 已读到行：以系统 Settings 为 L1 基线，叠加数据集 JSON 覆盖字段。数据集只存显式设置的
        # key，未覆盖字段跟随运行期系统默认（而非锁死的静态默认）。JSON 内容非法时 ValidationError
        # 向上传播，不静默降级。
        return DatasetParseConfigBundle(
            chunking=ChunkingConfig.model_validate(
                {
                    **ChunkingConfig.from_settings().model_dump(),
                    **snapshot.chunking_config,
                }
            ),
            enhancement=_load_enhancement_config(snapshot.enhancement_config),
            pdf=PDFConfig.model_validate(
                {**PDFConfig.from_settings().model_dump(), **snapshot.pdf_config}
            ),
            recall=RecallConfig.model_validate(
                {
                    **RecallConfig.from_settings().model_dump(),
                    **snapshot.recall_config,
                }
            ),
            model_bindings=DatasetModelBindingConfig(
                sparse_embedding_config_id=snapshot.sparse_embedding_config_id,
                dense_embedding_config_id=snapshot.dense_embedding_config_id,
                enhancement_chat_config_id=snapshot.enhancement_chat_config_id,
                enhancement_vision_config_id=snapshot.enhancement_vision_config_id,
                rerank_config_id=snapshot.rerank_config_id,
            ),
        )
