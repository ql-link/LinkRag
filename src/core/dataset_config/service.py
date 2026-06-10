# -*- coding: utf-8 -*-
"""数据集级配置读取服务。

按 ``(user_id, dataset_id)`` 只读 ``dataset_parse_config`` 表，反序列化为四类 Pydantic
配置组成的 :class:`DatasetParseConfigBundle`。

**职责边界**：纯只读。无配置行时返回内存默认 bundle（不写库），DB 读取失败时降级到内存
默认并记录 warning，不阻断解析 / 召回。配置行的增删改全部由 Java 侧负责。

**失败语义区分**：
- DB 读取失败（连接 / 查询异常）→ 降级为系统默认，任务继续；
- 已读到行但 JSON 内容非法（字段类型不符）→ Pydantic ``ValidationError`` 向上传播，由解析
  链路收敛为任务失败，**不静默降级**（明确失败优于错误配置生效）。
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.dataset_parse_config import DatasetParseConfig

from .models import (
    ChunkingConfig,
    DatasetParseConfigBundle,
    EnhancementConfig,
    PDFConfig,
    RecallConfig,
)

logger = logging.getLogger(__name__)


def _load_json_column(value) -> dict:
    """把 JSON 列原始值归一化为 dict。

    SQLAlchemy 的 JSON 列通常已反序列化为 dict；个别驱动 / 历史数据可能返回字符串，
    此处兜底解析。``None`` / 空值返回空 dict，让 Pydantic 填默认值。
    """
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return value


class DatasetConfigService:
    """数据集解析/检索配置只读服务。"""

    async def get_config(
        self, user_id: int, dataset_id: int, db: AsyncSession
    ) -> DatasetParseConfigBundle:
        """按 ``(user_id, dataset_id)`` 读取配置；无行 / 读取失败返回系统默认。

        Args:
            user_id: 发起方用户 ID。
            dataset_id: 数据集 ID。
            db: 异步会话。

        Returns:
            四类配置聚合的 :class:`DatasetParseConfigBundle`。

        Raises:
            pydantic.ValidationError: 已读到配置行但 JSON 字段类型非法（不静默降级）。
        """
        try:
            stmt = select(DatasetParseConfig).where(
                DatasetParseConfig.user_id == user_id,
                DatasetParseConfig.dataset_id == dataset_id,
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001
            # DB 读取失败：降级为系统默认，不阻断任务。
            logger.warning(
                "failed to load dataset config (user_id=%s dataset_id=%s): %s",
                user_id,
                dataset_id,
                exc,
            )
            return DatasetParseConfigBundle.defaults()

        if row is None:
            # 无配置行：返回内存默认，不写库（行的写入由 Java 侧负责）。
            return DatasetParseConfigBundle.defaults()

        # 已读到行：以系统 Settings 为 L1 基线，叠加数据集 JSON 覆盖字段。数据集只存显式设置的
        # key，未覆盖字段跟随运行期系统默认（而非锁死的静态默认）。JSON 内容非法时 ValidationError
        # 向上传播，不静默降级。
        return DatasetParseConfigBundle(
            chunking=ChunkingConfig.model_validate(
                {**ChunkingConfig.from_settings().model_dump(), **_load_json_column(row.chunking_config)}
            ),
            enhancement=EnhancementConfig.model_validate(
                {
                    **EnhancementConfig.from_settings().model_dump(),
                    **_load_json_column(row.enhancement_config),
                }
            ),
            pdf=PDFConfig.model_validate(
                {**PDFConfig.from_settings().model_dump(), **_load_json_column(row.pdf_config)}
            ),
            recall=RecallConfig.model_validate(
                {**RecallConfig.from_settings().model_dump(), **_load_json_column(row.recall_config)}
            ),
        )
