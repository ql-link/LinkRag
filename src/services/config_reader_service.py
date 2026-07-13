"""ConfigReaderService 配置读取服务。

Java 管理端负责写入 LLM 配置，Python 只读取运行时生效配置：
先读用户自己的 ``llm_user_config`` 默认配置；未命中时读 LinkRag 系统默认预设。
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.llm.encryption import decrypt_api_key as decrypt_api_key_util
from src.models.db_models import SystemPresetDB, SystemProviderDB, UserLLMConfigDB


def _user_config_to_dict(cfg: UserLLMConfigDB) -> Dict[str, Any]:
    """将 ORM 用户配置行转换为运行时配置字典。"""
    return {
        "id": cfg.id,
        "user_id": cfg.user_id,
        "provider_id": cfg.provider_id,
        "provider_type": cfg.provider_type,
        "protocol": cfg.protocol,
        "api_key": cfg.api_key,
        "api_base_url": cfg.api_base_url,
        "model_name": cfg.model_name,
        "display_name": cfg.model_name,
        "capability": cfg.capability,
        "is_active": cfg.is_active,
        "is_default": cfg.is_default,
        "is_system_preset": cfg.is_system_preset,
        "config_source": "USER",
        "source": "USER",
    }


def _system_preset_to_dict(cfg: SystemPresetDB) -> Dict[str, Any]:
    """将 ORM 系统预设行转换为运行时配置字典。"""
    return {
        "id": cfg.id,
        "user_id": "system",
        "provider_id": cfg.provider_id,
        "provider_type": cfg.provider_type,
        "protocol": cfg.protocol,
        "api_key": cfg.api_key,
        "api_base_url": cfg.api_base_url,
        "model_name": cfg.model_name,
        "display_name": cfg.display_name or cfg.model_name,
        "capability": cfg.capability,
        "is_active": cfg.is_active,
        "is_default": cfg.is_default,
        "is_system_preset": True,
        "config_source": "SYSTEM",
        "source": "SYSTEM",
    }


class ConfigReaderService:
    """LLM 配置读取服务

    职责：
    - 从 MySQL 读取 llm_user_config 表
    - 从 MySQL 读取 llm_system_preset 表中 LinkRag 默认预设
    - 从 MySQL 读取 llm_system_provider 表
    所有数据库配置读取均以 MySQL 为唯一事实来源。
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
    ):
        """初始化服务

        Args:
            db: 可选的数据库 Session，用于依赖注入
        """
        self._db: Optional[AsyncSession] = db

    def set_db(self, db: AsyncSession) -> None:
        """设置数据库 Session"""
        self._db = db

    async def get_user_configs(self, user_id: int) -> List[Dict[str, Any]]:
        """获取用户的所有 LLM 配置

        Args:
            user_id: 用户 ID
        Returns:
            用户配置列表
        """
        if self._db is None:
            return []

        stmt = (
            select(UserLLMConfigDB)
            .where(UserLLMConfigDB.user_id == user_id)
            .where(UserLLMConfigDB.is_active == True)
            .where(UserLLMConfigDB.is_system_preset == False)
            .order_by(UserLLMConfigDB.id.desc())
        )
        result = await self._db.execute(stmt)
        configs_db = result.scalars().all()

        return [_user_config_to_dict(cfg) for cfg in configs_db]

    async def get_user_default_config_by_capability(
        self,
        user_id: int,
        capability: str,
        provider_type: Optional[str] = None,
        allow_linkrag_default: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """获取用户指定能力的生效默认 LLM 配置

        读取顺序：
        1. 用户自己的 ``llm_user_config`` 默认配置；
        2. 未命中、未指定 ``provider_type`` 且允许时，回退到 LinkRag 系统默认预设。

        Args:
            user_id: 用户 ID
            capability: 能力类型（CHAT/EMBEDDING/SPARSE_EMBEDDING/RERANK/VISION）
            provider_type: 可选，指定 provider 类型
            allow_linkrag_default: 用户默认缺失时是否允许读取 LinkRag 系统默认预设

        Returns:
            该能力的生效默认配置，未设置则返回 None
        """
        capability_upper = capability.upper()
        if self._db is None:
            return None

        # 默认配置的业务唯一性由 Java 管理端保证；为防脏数据，查询侧用 limit(1)
        # 确定性取最新一条，
        # 不让 MultipleResultsFound 冒泡成「读取失败(可重试)」误判。
        stmt = (
            select(UserLLMConfigDB)
            .where(UserLLMConfigDB.user_id == user_id)
            .where(UserLLMConfigDB.capability == capability_upper)
            .where(UserLLMConfigDB.is_default == True)
            .where(UserLLMConfigDB.is_active == True)
            .where(UserLLMConfigDB.is_system_preset == False)
        )
        if provider_type:
            stmt = stmt.where(UserLLMConfigDB.provider_type == provider_type)

        stmt = stmt.order_by(UserLLMConfigDB.id.desc()).limit(1)
        result = await self._db.execute(stmt)
        cfg = result.scalars().first()

        if cfg is None:
            if provider_type or not allow_linkrag_default:
                return None
            return await self.get_default_linkrag_system_preset_by_capability(capability_upper)
        return _user_config_to_dict(cfg)

    async def get_user_config_by_id(
        self, user_id: int, config_id: int
    ) -> Optional[Dict[str, Any]]:
        """根据 ID 获取用户特定配置

        Args:
            user_id: 用户 ID
            config_id: 配置 ID

        Returns:
            配置详情，未找到则返回 None
        """
        if self._db is None:
            return None

        stmt = (
            select(UserLLMConfigDB)
            .where(UserLLMConfigDB.id == config_id)
            .where(UserLLMConfigDB.user_id == user_id)
            .where(UserLLMConfigDB.is_active == True)
            .where(UserLLMConfigDB.is_system_preset == False)
        )
        result = await self._db.execute(stmt)
        cfg = result.scalar_one_or_none()

        if cfg is None:
            return None

        return _user_config_to_dict(cfg)

    async def get_user_configs_by_capability(
        self, user_id: int, capability: str
    ) -> List[Dict[str, Any]]:
        """获取用户指定能力的所有配置

        Args:
            user_id: 用户 ID
            capability: 能力类型（CHAT/EMBEDDING/SPARSE_EMBEDDING/RERANK/VISION）

        Returns:
            该能力的所有配置列表
        """
        capability_upper = capability.upper()
        if self._db is None:
            return []

        stmt = (
            select(UserLLMConfigDB)
            .where(UserLLMConfigDB.user_id == user_id)
            .where(UserLLMConfigDB.capability == capability_upper)
            .where(UserLLMConfigDB.is_active == True)
            .where(UserLLMConfigDB.is_system_preset == False)
            .order_by(UserLLMConfigDB.id.desc())
        )
        result = await self._db.execute(stmt)
        configs_db = result.scalars().all()

        return [_user_config_to_dict(cfg) for cfg in configs_db]

    async def get_system_providers(
        self, provider_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取系统级厂商列表

        Args:
            provider_type: 可选，按类型过滤

        Returns:
            系统厂商列表
        """
        if self._db is None:
            return []

        stmt = (
            select(SystemProviderDB)
            .options(selectinload(SystemProviderDB.provider_models))
            .where(SystemProviderDB.is_active == True)
        )
        if provider_type:
            stmt = stmt.where(SystemProviderDB.provider_type == provider_type)
        stmt = stmt.order_by(SystemProviderDB.priority.desc())

        result = await self._db.execute(stmt)
        providers_db = result.scalars().all()

        providers = []
        for p in providers_db:
            models: Dict[str, List[str]] = {}
            model_options_by_name: Dict[str, Dict[str, Any]] = {}
            for model in p.provider_models:
                if not model.is_active:
                    continue
                models.setdefault(model.model_name, []).append(model.capability)
                option = model_options_by_name.setdefault(
                    model.model_name,
                    {
                        "model_name": model.model_name,
                        "display_name": model.display_name or model.model_name,
                        "capabilities": [],
                        "protocol": model.protocol,
                        "api_base_url": model.api_base_url,
                    },
                )
                option["capabilities"].append(model.capability)
            providers.append(
                {
                    "id": p.id,
                    "provider_type": p.provider_type,
                    "provider_name": p.provider_name,
                    "api_base_url": p.api_base_url,
                    "models": models,
                    "model_options": list(model_options_by_name.values()),
                    "is_active": p.is_active,
                    "priority": p.priority,
                }
            )

        return providers

    async def get_system_provider_by_type(
        self, provider_type: str
    ) -> Optional[Dict[str, Any]]:
        """根据类型获取系统厂商

        Args:
            provider_type: 厂商类型

        Returns:
            厂商详情
        """
        providers = await self.get_system_providers(provider_type=provider_type)
        return providers[0] if providers else None

    async def get_system_preset_by_id(
        self, config_id: int
    ) -> Optional[Dict[str, Any]]:
        """根据 ID 获取系统预设配置。

        仅供 Java 返回 ``source=SYSTEM`` 时按 ``source + configId`` 精确定位。
        """
        if self._db is None:
            return None

        stmt = (
            select(SystemPresetDB)
            .where(SystemPresetDB.id == config_id)
            .where(SystemPresetDB.is_active == True)
            .where(SystemPresetDB.is_default == True)
            .where(SystemPresetDB.provider_type == "linkrag")
            .limit(1)
        )
        result = await self._db.execute(stmt)
        cfg = result.scalars().first()

        if cfg is None:
            return None

        return _system_preset_to_dict(cfg)

    async def get_default_linkrag_system_preset_by_capability(
        self, capability: str
    ) -> Optional[Dict[str, Any]]:
        """获取指定能力的 LinkRag 系统默认预设。"""
        capability_upper = capability.upper()
        if self._db is None:
            return None

        stmt = (
            select(SystemPresetDB)
            .where(SystemPresetDB.provider_type == "linkrag")
            .where(SystemPresetDB.capability == capability_upper)
            .where(SystemPresetDB.is_default == True)
            .where(SystemPresetDB.is_active == True)
            .order_by(SystemPresetDB.id.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        cfg = result.scalars().first()

        if cfg is None:
            return None

        return _system_preset_to_dict(cfg)

    async def decrypt_api_key(self, encrypted_key: str) -> str:
        """解密 API Key

        Args:
            encrypted_key: 加密的 API Key

        Returns:
            解密后的 API Key
        """
        if not encrypted_key:
            return ""
        return decrypt_api_key_util(encrypted_key)

    def get_system_fallback_config_by_capability(self, capability: str) -> Optional[Dict[str, Any]]:
        """获取从系统环境变量中读取的兜底 LLM 配置"""
        from src.config import settings

        if not settings.SYSTEM_LLM_API_KEY:
            return None

        model_name = None
        cap_upper = capability.upper()
        if cap_upper == "CHAT":
            model_name = settings.SYSTEM_LLM_MODEL_CHAT
        elif cap_upper == "EMBEDDING":
            model_name = settings.SYSTEM_LLM_MODEL_EMBEDDING
        elif cap_upper == "RERANK":
            model_name = settings.SYSTEM_LLM_MODEL_RERANK
        elif cap_upper == "VISION":
            model_name = settings.SYSTEM_LLM_MODEL_VISION

        if not model_name:
            return None

        # 系统级 LLM 固定走 openai 兼容协议；env 配的是 base，按能力补 openai 后缀成完整 URL。
        base = (settings.SYSTEM_LLM_API_BASE or "").rstrip("/")
        suffix = "/embeddings" if cap_upper == "EMBEDDING" else "/chat/completions"
        full_url = f"{base}{suffix}" if base else settings.SYSTEM_LLM_API_BASE

        return {
            "id": "system-default",
            "user_id": "system",
            "provider_id": "system",
            "provider_type": settings.SYSTEM_LLM_PROVIDER,
            "protocol": "openai",
            "api_key": settings.SYSTEM_LLM_API_KEY,
            "api_base_url": full_url,
            "model_name": model_name,
            "is_active": True,
            "is_default": True,
            "capability": cap_upper,
            "is_system_preset": False,
            "is_system_fallback": True,  # 特殊标识，免于解密
        }
