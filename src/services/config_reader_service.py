"""
ConfigReaderService 配置读取服务
从数据库读取 LLM 配置，支持 Redis 缓存
"""
import json
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.cache.cache_manager import CacheManager, cache_manager
from src.core.llm.encryption import decrypt_api_key as decrypt_api_key_util
from src.models.db_models import SystemProviderDB, UserLLMConfigDB


def _parse_json_field(value: Union[str, dict, list, None]) -> Optional[Any]:
    """解析 JSON 字段，兼容字符串和已转换的字典类型"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


class ConfigReaderService:
    """LLM 配置读取服务

    职责：
    - 从 MySQL 读取 llm_user_config 表
    - 从 MySQL 读取 llm_system_provider 表
    - 维护 Redis 缓存
    - 配置变更时主动失效缓存

    缓存通过依赖注入实现：
    - 生产环境：使用全局 cache_manager（Redis 后端）
    - 测试环境：可注入使用 NullCacheBackend 的 CacheManager
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        cache: Optional[CacheManager] = None,
    ):
        """初始化服务

        Args:
            db: 可选的数据库 Session，用于依赖注入
            cache: 可选的缓存管理器，默认使用全局 cache_manager
        """
        self._db: Optional[AsyncSession] = db
        self._cache: CacheManager = cache or cache_manager

    def set_db(self, db: AsyncSession) -> None:
        """设置数据库 Session"""
        self._db = db

    @staticmethod
    def _config_to_dict(cfg: UserLLMConfigDB) -> Dict[str, Any]:
        """将用户配置 ORM 对象转换为调用侧配置字典。"""
        provider = cfg.provider
        return {
            "id": cfg.id,
            "user_id": cfg.user_id,
            "provider_id": cfg.provider_id,
            "provider_type": cfg.provider_type or (provider.provider_type if provider else None),
            "provider_name": cfg.provider_name or (provider.provider_name if provider else None),
            "config_name": cfg.config_name,
            "api_key": cfg.api_key,
            "custom_api_base_url": cfg.custom_api_base_url,
            "model_name": cfg.model_name,
            "priority": cfg.priority,
            "is_active": cfg.is_active,
            "is_default": cfg.is_default,
            "timeout_ms": cfg.timeout_ms,
            "max_retries": cfg.max_retries,
            "stream_enabled": cfg.stream_enabled,
            "extra_config": _parse_json_field(cfg.extra_config),
            "capability": cfg.capability,
            "is_system_preset": cfg.user_id == 0,
        }

    async def get_user_configs(
        self, user_id: int, use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """获取用户的所有 LLM 配置

        Args:
            user_id: 用户 ID
            use_cache: 是否使用缓存

        Returns:
            用户配置列表
        """
        cache_key = self._cache.user_configs_key(str(user_id))

        # 先查缓存
        if use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # 缓存未命中，从数据库查询
        if self._db is None:
            return []

        stmt = (
            select(UserLLMConfigDB)
            .options(selectinload(UserLLMConfigDB.provider))
            .where(UserLLMConfigDB.user_id == user_id)
            .where(UserLLMConfigDB.is_active == True)
            .order_by(UserLLMConfigDB.priority.desc())
        )
        result = await self._db.execute(stmt)
        configs_db = result.scalars().all()

        configs = [self._config_to_dict(cfg) for cfg in configs_db]

        # 回填缓存
        if use_cache:
            await self._cache.set(cache_key, configs)

        return configs

    async def get_user_default_config_by_capability(
        self,
        user_id: int,
        capability: str,
        provider_type: Optional[str] = None,
        use_cache: bool = True
    ) -> Optional[Dict[str, Any]]:
        """获取用户指定能力的默认 LLM 配置

        Args:
            user_id: 用户 ID
            capability: 能力类型（CHAT/EMBEDDING/RERANK/OCR/VISION）
            provider_type: 可选，指定 provider 类型
            use_cache: 是否使用缓存

        Returns:
            该能力的默认配置，未设置则返回 None
        """
        capability_upper = capability.upper()
        cache_key = f"llm:user:{user_id}:default:{capability_upper}"
        if provider_type:
            cache_key = f"{cache_key}:{provider_type}"

        # 先查缓存
        if use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # 缓存未命中，从数据库查询
        if self._db is None:
            return None

        stmt = (
            select(UserLLMConfigDB)
            .options(selectinload(UserLLMConfigDB.provider))
            .where(UserLLMConfigDB.user_id == user_id)
            .where(UserLLMConfigDB.capability == capability_upper)
            .where(UserLLMConfigDB.is_default == True)
            .where(UserLLMConfigDB.is_active == True)
        )
        if provider_type:
            stmt = stmt.where(UserLLMConfigDB.provider_type == provider_type)

        result = await self._db.execute(stmt)
        cfg = result.scalar_one_or_none()
        config = self._config_to_dict(cfg) if cfg else None

        if config is None:
            config = await self._get_system_preset_default_config(
                capability_upper,
                provider_type=provider_type,
                use_cache=use_cache,
            )

        if config is None:
            return None

        # 回填缓存
        if use_cache:
            await self._cache.set(cache_key, config)

        return config

    async def _get_system_preset_default_config(
        self,
        capability: str,
        provider_type: Optional[str] = None,
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """获取 user_id=0 的系统预设默认配置。"""
        capability_upper = capability.upper()
        cache_key = f"llm:user:0:default:{capability_upper}"
        if provider_type:
            cache_key = f"{cache_key}:{provider_type}"

        if use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        if self._db is None:
            return None

        stmt = (
            select(UserLLMConfigDB)
            .options(selectinload(UserLLMConfigDB.provider))
            .where(UserLLMConfigDB.user_id == 0)
            .where(UserLLMConfigDB.capability == capability_upper)
            .where(UserLLMConfigDB.is_default == True)
            .where(UserLLMConfigDB.is_active == True)
        )
        if provider_type:
            stmt = stmt.where(UserLLMConfigDB.provider_type == provider_type)

        result = await self._db.execute(stmt)
        cfg = result.scalar_one_or_none()
        if cfg is None:
            return None

        config = self._config_to_dict(cfg)
        if use_cache:
            await self._cache.set(cache_key, config)
        return config

    async def get_user_config_by_id(
        self, user_id: int, config_id: int, use_cache: bool = True
    ) -> Optional[Dict[str, Any]]:
        """根据 ID 获取用户特定配置

        Args:
            user_id: 用户 ID
            config_id: 配置 ID
            use_cache: 是否使用缓存

        Returns:
            配置详情，未找到则返回 None
        """
        cache_key = self._cache.user_config_key(str(user_id), str(config_id))

        # 先查缓存
        if use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # 缓存未命中，从数据库查询
        if self._db is None:
            return None

        stmt = (
            select(UserLLMConfigDB)
            .options(selectinload(UserLLMConfigDB.provider))
            .where(UserLLMConfigDB.id == config_id)
            .where(or_(UserLLMConfigDB.user_id == user_id, UserLLMConfigDB.user_id == 0))
            .where(UserLLMConfigDB.is_active == True)
        )
        result = await self._db.execute(stmt)
        cfg = result.scalar_one_or_none()

        if cfg is None:
            return None

        config = self._config_to_dict(cfg)

        # 回填缓存
        if use_cache:
            await self._cache.set(cache_key, config)

        return config

    async def get_user_configs_by_capability(
        self,
        user_id: int,
        capability: str,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """获取用户指定能力的所有配置

        Args:
            user_id: 用户 ID
            capability: 能力类型（CHAT/EMBEDDING/RERANK/OCR/VISION）
            use_cache: 是否使用缓存

        Returns:
            该能力的所有配置列表
        """
        capability_upper = capability.upper()
        cache_key = f"llm:user:{user_id}:configs:{capability_upper}"

        # 先查缓存
        if use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # 缓存未命中，从数据库查询
        if self._db is None:
            return []

        stmt = (
            select(UserLLMConfigDB)
            .options(selectinload(UserLLMConfigDB.provider))
            .where(UserLLMConfigDB.user_id == user_id)
            .where(UserLLMConfigDB.capability == capability_upper)
            .where(UserLLMConfigDB.is_active == True)
            .order_by(UserLLMConfigDB.priority.desc())
        )
        result = await self._db.execute(stmt)
        configs_db = result.scalars().all()

        configs = [self._config_to_dict(cfg) for cfg in configs_db]

        # 回填缓存
        if use_cache:
            await self._cache.set(cache_key, configs)

        return configs

    async def get_system_providers(
        self, provider_type: Optional[str] = None, use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """获取系统级厂商列表

        Args:
            provider_type: 可选，按类型过滤
            use_cache: 是否使用缓存

        Returns:
            系统厂商列表
        """
        if provider_type:
            cache_key = self._cache.system_provider_key(provider_type)
        else:
            cache_key = self._cache.system_providers_key()

        # 先查缓存
        if use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # 缓存未命中，从数据库查询
        if self._db is None:
            return []

        stmt = select(SystemProviderDB).where(SystemProviderDB.is_active == True)
        if provider_type:
            stmt = stmt.where(SystemProviderDB.provider_type == provider_type)
        stmt = stmt.order_by(SystemProviderDB.priority.desc())

        result = await self._db.execute(stmt)
        providers_db = result.scalars().all()

        providers = []
        for p in providers_db:
            providers.append({
                "id": p.id,
                "provider_type": p.provider_type,
                "provider_name": p.provider_name,
                "api_base_url": p.api_base_url,
                "supported_capabilities": _parse_json_field(p.supported_capabilities) or [],
                "config_schema": _parse_json_field(p.config_schema),
                "is_active": p.is_active,
                "priority": p.priority,
            })

        # 回填缓存
        if use_cache:
            await self._cache.set(cache_key, providers)

        return providers

    async def get_system_provider_by_type(
        self, provider_type: str, use_cache: bool = True
    ) -> Optional[Dict[str, Any]]:
        """根据类型获取系统厂商

        Args:
            provider_type: 厂商类型
            use_cache: 是否使用缓存

        Returns:
            厂商详情
        """
        providers = await self.get_system_providers(provider_type=provider_type, use_cache=use_cache)
        return providers[0] if providers else None

    async def clear_cache(self, user_id: Optional[str] = None) -> None:
        """清除缓存

        Args:
            user_id: 如果指定，只清除该用户的缓存；否则清除所有
        """
        if user_id:
            await self._cache.clear_user_cache(user_id)
        else:
            await self._cache.clear_all_user_cache()
            await self._cache.clear_system_cache()

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
