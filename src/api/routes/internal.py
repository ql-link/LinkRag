"""
内部接口路由
供 Java 管理端查询配置和用量（不暴露给外部）
"""
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.llm.response import APIResponse
from src.core.llm.encryption import mask_api_key
from src.services.config_reader_service import ConfigReaderService
from src.services.usage_log_service import UsageLogService
from src.database import get_db

router = APIRouter(prefix="/api/v1/internal/llm", tags=["internal"])


@router.get("/providers")
async def get_system_providers(
    provider_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """获取系统级厂商列表（内部接口）

    Args:
        provider_type: 可选，按类型过滤
        db: 数据库 Session

    Returns:
        系统厂商列表
    """
    try:
        config_service = ConfigReaderService(db)
        providers = await config_service.get_system_providers(provider_type)

        items = [
            {
                "provider_type": p.get("provider_type"),
                "provider_name": p.get("provider_name"),
                "api_base_url": p.get("api_base_url"),
                "supported_capabilities": p.get("supported_capabilities", []),
                "config_schema": p.get("config_schema"),
                "is_active": p.get("is_active", True),
            }
            for p in providers
        ]

        return APIResponse(
            code=200,
            message="success",
            data={"items": items},
        )

    except Exception as e:
        return APIResponse(code=500, message=str(e), data=None)


@router.get("/configs")
async def get_user_configs(
    x_user_id: str = Header(..., alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """获取用户的 LLM 配置列表（内部接口）

    Args:
        x_user_id: 用户 ID
        db: 数据库 Session

    Returns:
        用户配置列表
    """
    try:
        config_service = ConfigReaderService(db)
        configs = await config_service.get_user_configs(x_user_id)

        items = [
            {
                "id": c.get("id"),
                "config_name": c.get("config_name"),
                "provider_type": c.get("provider_type"),
                "provider_name": c.get("provider_name"),
                "model_name": c.get("model_name"),
                "api_key_masked": mask_api_key(c.get("api_key", "")),
                "custom_api_base_url": c.get("custom_api_base_url"),
                "priority": c.get("priority"),
                "is_active": c.get("is_active"),
                "is_default": c.get("is_default"),
                "stream_enabled": c.get("stream_enabled"),
                "capability": c.get("capability"),
                "extra_config": c.get("extra_config"),
            }
            for c in configs
        ]

        return APIResponse(
            code=200,
            message="success",
            data={"items": items},
        )

    except Exception as e:
        return APIResponse(code=500, message=str(e), data=None)


@router.get("/usage")
async def get_user_usage(
    x_user_id: str = Header(..., alias="X-User-Id"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """获取用户用量统计（内部接口）

    Args:
        x_user_id: 用户 ID
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        db: 数据库 Session

    Returns:
        用量统计
    """
    try:
        from datetime import date

        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

        usage_service = UsageLogService(db)
        summary = await usage_service.get_usage_summary(x_user_id, start, end)

        return APIResponse(
            code=200,
            message="success",
            data=summary,
        )

    except Exception as e:
        return APIResponse(code=500, message=str(e), data=None)
