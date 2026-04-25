"""
CacheSyncService 单元测试
测试缓存同步服务的核心功能
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.services.cache_sync_service import CacheSyncService


class TestCacheSyncServiceInit:
    """CacheSyncService 初始化测试"""

    def test_Init_Should_Create_Instances(self):
        """初始化应该创建 ConfigReaderService 和 ModelFactory 实例"""
        service = CacheSyncService()

        assert service._config_service is not None
        assert service._model_factory is not None
        assert service._is_listening is False
        assert service._redis_subscriber is None


class TestCacheSyncServiceSyncConfigChange:
    """sync_config_change 测试"""

    @pytest.mark.asyncio
    async def test_Sync_Update_User_Cache_Should_Clear_User_Cache(self):
        """sync_config_change(update) 应该清除用户缓存"""
        service = CacheSyncService()

        # Mock 依赖
        service._config_service.clear_cache = AsyncMock()
        service._model_factory.clear_cache = MagicMock()

        await service.sync_config_change(user_id="user123", event_type="update")

        service._config_service.clear_cache.assert_called_once_with("user123")
        service._model_factory.clear_cache.assert_called_once_with("user123")

    @pytest.mark.asyncio
    async def test_Sync_Create_User_Cache_Should_Clear_Config_List(self):
        """sync_config_change(create) 应该清除用户配置列表缓存"""
        service = CacheSyncService()

        service._config_service.clear_cache = AsyncMock()

        await service.sync_config_change(user_id="user123", event_type="create")

        service._config_service.clear_cache.assert_called_once_with("user123")

    @pytest.mark.asyncio
    async def test_Sync_Delete_Should_Clear_Specific_Config_Cache(self):
        """sync_config_change(delete) 应该清除特定配置缓存"""
        service = CacheSyncService()

        service._model_factory.clear_cache = MagicMock()
        service._clear_config_cache = AsyncMock()

        await service.sync_config_change(
            user_id="user123",
            config_id="config456",
            event_type="delete"
        )

        service._clear_config_cache.assert_called_once()
        service._model_factory.clear_cache.assert_called_once_with("user123")


class TestCacheSyncServiceInvalidateCache:
    """invalidate_cache 测试"""

    @pytest.mark.asyncio
    async def test_Invalidate_User_Config_Should_Clear_User_Cache(self):
        """invalidate_cache(user_config) 应该清除用户缓存"""
        service = CacheSyncService()
        service._config_service.clear_cache = AsyncMock()

        await service.invalidate_cache(cache_type="user_config", user_id="user123")

        service._config_service.clear_cache.assert_called_once_with("user123")

    @pytest.mark.asyncio
    async def test_Invalidate_System_Provider_Should_Clear_System_Cache(self):
        """invalidate_cache(system_provider) 应该清除系统缓存"""
        service = CacheSyncService()
        service._config_service.clear_cache = AsyncMock()

        await service.invalidate_cache(cache_type="system_provider")

        service._config_service.clear_cache.assert_called_once_with()  # 无参数，清除所有

    @pytest.mark.asyncio
    async def test_Invalidate_Client_Should_Clear_Client_Cache(self):
        """invalidate_cache(client) 应该清除客户端缓存"""
        service = CacheSyncService()
        service._model_factory.clear_cache = MagicMock()

        await service.invalidate_cache(cache_type="client", user_id="user123")

        service._model_factory.clear_cache.assert_called_once_with("user123")

    @pytest.mark.asyncio
    async def test_Invalidate_All_Should_Clear_All_Caches(self):
        """invalidate_cache(all) 应该清除所有缓存"""
        service = CacheSyncService()
        service._config_service.clear_cache = AsyncMock()
        service._model_factory.clear_cache = MagicMock()

        await service.invalidate_cache(cache_type="all")

        service._config_service.clear_cache.assert_called_once_with()
        service._model_factory.clear_cache.assert_called_once_with()  # 无参数


class TestCacheSyncServiceListening:
    """缓存监听测试"""

    @pytest.mark.asyncio
    async def test_Start_Listening_Should_Set_Flag(self):
        """start_listening 应该设置监听标志"""
        service = CacheSyncService()

        await service.start_listening()

        assert service._is_listening is True

    @pytest.mark.asyncio
    async def test_Start_Listening_Twice_Should_Be_Idempotent(self):
        """start_listening 调用两次应该幂等"""
        service = CacheSyncService()

        await service.start_listening()
        await service.start_listening()  # 第二次调用

        assert service._is_listening is True

    @pytest.mark.asyncio
    async def test_Stop_Listening_Should_Clear_Flag(self):
        """stop_listening 应该清除监听标志"""
        service = CacheSyncService()
        service._is_listening = True

        await service.stop_listening()

        assert service._is_listening is False

    @pytest.mark.asyncio
    async def test_Stop_Listening_With_Subscriber_Should_Unsubscribe(self):
        """stop_listening 有订阅者时应该取消订阅"""
        service = CacheSyncService()
        service._is_listening = True
        mock_subscriber = MagicMock()
        mock_subscriber.unsubscribe = AsyncMock()
        service._redis_subscriber = mock_subscriber

        await service.stop_listening()

        mock_subscriber.unsubscribe.assert_called_once()
        assert service._redis_subscriber is None
