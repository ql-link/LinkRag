"""
UsageLogService 用量日志服务
异步记录 LLM 调用用量，用于计费和统计
"""
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.llm.response import UsageInfo
from src.models.db_models import UsageLogDB


class UsageLogService:
    """LLM 用量日志服务

    职责：
    - 异步写入用量记录到 MySQL
    - 查询用户的用量统计
    - 生成用量汇总报表
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        """初始化服务

        Args:
            db: 可选的数据库 Session，用于依赖注入
        """
        self._db: Optional[AsyncSession] = db

    def set_db(self, db: AsyncSession) -> None:
        """设置数据库 Session"""
        self._db = db

    async def log_usage(self, record: Dict[str, Any]) -> None:
        """记录一次 LLM 调用用量

        Args:
            record: 用量记录，包含：
                - user_id: 用户 ID
                - config_id: 配置 ID
                - provider_type: 厂商类型
                - model_name: 模型名称
                - usage: UsageInfo
                - latency_ms: 延迟
                - status: success/failed/partial
                - error_message: 错误信息（可选）
                - fallback_config_id: 触发 fallback 的原配置 ID（可选）
        """
        if self._db is None:
            return

        usage: UsageInfo = record.get("usage", UsageInfo())
        log_entry = UsageLogDB(
            id=str(uuid.uuid4()),
            user_id=record["user_id"],
            config_id=record["config_id"],
            provider_type=record.get("provider_type", "unknown"),
            model_name=record.get("model_name", "unknown"),
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            total_tokens=usage.total_tokens or 0,
            latency_ms=record.get("latency_ms"),
            status=record.get("status", "success"),
            error_message=record.get("error_message"),
            fallback_config_id=record.get("fallback_config_id"),
            created_at=datetime.now(),
        )
        self._db.add(log_entry)
        # 由调用方负责 commit

    async def get_user_usage(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """获取用户用量记录

        Args:
            user_id: 用户 ID
            start_date: 开始日期
            end_date: 结束日期
            limit: 最大返回条数

        Returns:
            用量记录列表
        """
        if self._db is None:
            return []

        stmt = (
            select(UsageLogDB)
            .where(UsageLogDB.user_id == user_id)
            .order_by(UsageLogDB.created_at.desc())
            .limit(min(limit, 1000))  # 最多返回 1000 条
        )

        if start_date:
            stmt = stmt.where(UsageLogDB.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            stmt = stmt.where(UsageLogDB.created_at <= datetime.combine(end_date, datetime.max.time()))

        result = await self._db.execute(stmt)
        logs = result.scalars().all()

        return [
            {
                "id": log.id,
                "user_id": log.user_id,
                "config_id": log.config_id,
                "provider_type": log.provider_type,
                "model_name": log.model_name,
                "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens,
                "total_tokens": log.total_tokens,
                "latency_ms": log.latency_ms,
                "status": log.status,
                "error_message": log.error_message,
                "fallback_config_id": log.fallback_config_id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ]

    async def get_usage_summary(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """获取用户用量汇总

        Args:
            user_id: 用户 ID
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            汇总数据：
            {
                "total_calls": 100,
                "total_tokens": 50000,
                "prompt_tokens": 30000,
                "completion_tokens": 20000,
                "daily_stats": [...]
            }
        """
        if self._db is None:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "daily_stats": []
            }

        # 基础过滤条件
        base_filter = [UsageLogDB.user_id == user_id]
        if start_date:
            base_filter.append(UsageLogDB.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            base_filter.append(UsageLogDB.created_at <= datetime.combine(end_date, datetime.max.time()))

        # 聚合查询总数
        count_stmt = select(
            func.count(UsageLogDB.id).label("total_calls"),
            func.sum(UsageLogDB.total_tokens).label("total_tokens"),
            func.sum(UsageLogDB.prompt_tokens).label("prompt_tokens"),
            func.sum(UsageLogDB.completion_tokens).label("completion_tokens"),
        ).where(*base_filter)
        count_result = await self._db.execute(count_stmt)
        count_row = count_result.one()

        total_calls = count_row.total_calls or 0
        total_tokens = count_row.total_tokens or 0
        prompt_tokens = count_row.prompt_tokens or 0
        completion_tokens = count_row.completion_tokens or 0

        # 按日统计
        daily_stmt = (
            select(
                func.date(UsageLogDB.created_at).label("date"),
                func.count(UsageLogDB.id).label("calls"),
                func.sum(UsageLogDB.total_tokens).label("tokens"),
            )
            .where(*base_filter)
            .group_by(func.date(UsageLogDB.created_at))
            .order_by(func.date(UsageLogDB.created_at).desc())
        )
        daily_result = await self._db.execute(daily_stmt)
        daily_rows = daily_result.all()

        daily_stats = [
            {
                "date": str(row.date) if row.date else None,
                "calls": row.calls or 0,
                "tokens": row.tokens or 0,
            }
            for row in daily_rows
        ]

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "daily_stats": daily_stats,
        }