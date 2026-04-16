"""
ConfigReaderService 集成测试 - 真实 MySQL 数据库
测试 get_system_providers 等方法的实际数据库读取

采用缓存后端抽象：
- 测试时注入 NullCacheBackend，不依赖 Redis
- 生产时使用 RedisCacheBackend
"""
import asyncio
import json
import uuid
import pytest
import pytest_asyncio
import pymysql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_async_session_factory, get_async_engine
from src.services.config_reader_service import ConfigReaderService
from src.cache.cache_manager import CacheManager, NullCacheBackend
from src.config import settings


# 固定测试用户 ID（bigint）- 每次测试使用不同的用户ID避免冲突
def create_unique_user_id():
    """生成唯一的用户 ID"""
    import random
    return int(f"2{random.randint(100000000, 999999999)}")  # 以2开头的10位数字


def get_sync_connection():
    """获取同步 MySQL 连接（用于测试数据准备）"""
    return pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        autocommit=True
    )


def create_unique_provider_type():
    """生成唯一的 provider_type"""
    return f"openai_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="function", autouse=True)
def reset_db_engine():
    """每个测试前重置数据库引擎连接池"""
    import src.database as db_module
    if db_module._async_engine is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(db_module._async_engine.dispose())
            else:
                loop.run_until_complete(db_module._async_engine.dispose())
        except Exception:
            pass
        db_module._async_engine = None
        db_module._async_session_factory = None
    yield
    try:
        if db_module._async_engine is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(db_module._async_engine.dispose())
                else:
                    loop.run_until_complete(db_module._async_engine.dispose())
            except Exception:
                pass
            db_module._async_engine = None
            db_module._async_session_factory = None
    except Exception:
        pass


# 创建测试用的缓存管理器（使用 NullCacheBackend，不依赖 Redis）
test_cache_manager = CacheManager(backend=NullCacheBackend())


class TestConfigReaderServiceIntegration:
    """ConfigReaderService MySQL 集成测试"""

    @pytest_asyncio.fixture
    async def db_session(self):
        """获取数据库 Session - 每个测试独立"""
        factory = get_async_session_factory()
        async with factory() as session:
            yield session

    @pytest_asyncio.fixture
    async def service(self, db_session: AsyncSession):
        """创建 ConfigReaderService 实例（注入测试用缓存管理器）"""
        svc = ConfigReaderService(db=db_session, cache=test_cache_manager)
        return svc

    @pytest_asyncio.fixture
    async def setup_test_data(self, db_session: AsyncSession):
        """使用同步 pymysql 插入测试数据，测试后清理"""
        provider_type = create_unique_provider_type()
        test_user_id = create_unique_user_id()
        test_ids = {}
        conn = get_sync_connection()
        try:
            with conn.cursor() as cursor:
                # 插入测试 SystemProvider
                cursor.execute("""
                    INSERT INTO llm_system_provider
                    (provider_type, provider_name, api_base_url, supported_models, config_schema, is_active, priority)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    provider_type,
                    "OpenAI Test",
                    "https://api.openai.com/v1",
                    json.dumps({"gpt-4": ["CHAT", "OCR"], "gpt-3.5-turbo": ["CHAT"]}),
                    json.dumps({"temperature": {"type": "float", "default": 0.7}}),
                    1,
                    100
                ))
                test_ids["provider_id"] = cursor.lastrowid
                test_ids["provider_type"] = provider_type

                # 插入测试 UserLLMConfig（带 capability 字段）
                cursor.execute("""
                    INSERT INTO llm_user_config
                    (user_id, provider_id, provider_type, provider_name, config_name, api_key, model_name, priority, is_active, is_default, timeout_ms, max_retries, stream_enabled, capability)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    test_user_id,
                    test_ids["provider_id"],
                    provider_type,
                    "OpenAI Test",
                    "Test GPT-4 Config",
                    "encrypted_test_key",
                    "gpt-4",
                    50,
                    1,
                    1,
                    60000,
                    3,
                    1,
                    "CHAT"  # 新增 capability 字段
                ))
                test_ids["config_id"] = cursor.lastrowid
                test_ids["user_id"] = test_user_id
        finally:
            conn.close()

        await db_session.commit()
        yield test_ids

        # 测试结束后清理
        conn = get_sync_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"DELETE FROM llm_user_config WHERE id = {test_ids['config_id']}")
                cursor.execute(f"DELETE FROM llm_system_provider WHERE id = {test_ids['provider_id']}")
        finally:
            conn.close()

    @pytest_asyncio.fixture
    async def setup_multi_capability_test_data(self, db_session: AsyncSession):
        """创建多种 capability 的测试数据"""
        import random
        provider_type1 = create_unique_provider_type()
        provider_type2 = f"anthropic_test_{uuid.uuid4().hex[:8]}"
        test_user_id = create_unique_user_id()
        test_ids = {}

        conn = get_sync_connection()
        try:
            with conn.cursor() as cursor:
                # 插入两个测试 SystemProvider
                cursor.execute("""
                    INSERT INTO llm_system_provider
                    (provider_type, provider_name, api_base_url, supported_models, is_active, priority)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    provider_type1,
                    "OpenAI Test",
                    "https://api.openai.com/v1",
                    json.dumps({"gpt-4": ["CHAT"], "text-embedding-3": ["EMBEDDING"]}),
                    1,
                    100
                ))
                provider_id1 = cursor.lastrowid

                cursor.execute("""
                    INSERT INTO llm_system_provider
                    (provider_type, provider_name, api_base_url, supported_models, is_active, priority)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    provider_type2,
                    "Anthropic Test",
                    "https://api.anthropic.com",
                    json.dumps({"claude-3": ["CHAT", "VISION"]}),
                    1,
                    90
                ))
                provider_id2 = cursor.lastrowid

                # 插入 CHAT 配置（默认）
                cursor.execute("""
                    INSERT INTO llm_user_config
                    (user_id, provider_id, provider_type, provider_name, config_name, api_key, model_name, priority, is_active, is_default, timeout_ms, max_retries, stream_enabled, capability)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    test_user_id,
                    provider_id1,
                    provider_type1,
                    "OpenAI Test",
                    "Chat Config",
                    "encrypted_key_1",
                    "gpt-4",
                    50,
                    1,
                    1,  # is_default
                    60000,
                    3,
                    1,
                    "CHAT"
                ))
                chat_config_id = cursor.lastrowid

                # 插入 EMBEDDING 配置
                cursor.execute("""
                    INSERT INTO llm_user_config
                    (user_id, provider_id, provider_type, provider_name, config_name, api_key, model_name, priority, is_active, is_default, timeout_ms, max_retries, stream_enabled, capability)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    test_user_id,
                    provider_id1,
                    provider_type1,
                    "OpenAI Test",
                    "Embedding Config",
                    "encrypted_key_2",
                    "text-embedding-3",
                    40,
                    1,
                    1,  # is_default for EMBEDDING
                    60000,
                    3,
                    1,
                    "EMBEDDING"
                ))
                embedding_config_id = cursor.lastrowid

                # 插入 RERANK 配置
                cursor.execute("""
                    INSERT INTO llm_user_config
                    (user_id, provider_id, provider_type, provider_name, config_name, api_key, model_name, priority, is_active, is_default, timeout_ms, max_retries, stream_enabled, capability)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    test_user_id,
                    provider_id2,
                    provider_type2,
                    "Anthropic Test",
                    "Rerank Config",
                    "encrypted_key_3",
                    "claude-3-rerank",
                    30,
                    1,
                    1,  # is_default for RERANK
                    60000,
                    3,
                    1,
                    "RERANK"
                ))
                rerank_config_id = cursor.lastrowid

                test_ids = {
                    "user_id": test_user_id,
                    "provider_id1": provider_id1,
                    "provider_id2": provider_id2,
                    "provider_type1": provider_type1,
                    "provider_type2": provider_type2,
                    "chat_config_id": chat_config_id,
                    "embedding_config_id": embedding_config_id,
                    "rerank_config_id": rerank_config_id,
                }
        finally:
            conn.close()

        await db_session.commit()
        yield test_ids

        # 清理测试数据
        conn = get_sync_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"DELETE FROM llm_user_config WHERE user_id = {test_user_id}")
                cursor.execute(f"DELETE FROM llm_system_provider WHERE id IN ({provider_id1}, {provider_id2})")
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_GetSystemProviders_Should_Return_All_Active_Providers(
        self, service: ConfigReaderService, setup_test_data
    ):
        """get_system_providers 应返回所有活跃的系统厂商"""
        providers = await service.get_system_providers()

        assert isinstance(providers, list)
        assert len(providers) > 0

        test_provider_type = setup_test_data["provider_type"]
        test_provider = next(
            (p for p in providers if p["provider_type"] == test_provider_type), None
        )
        assert test_provider is not None, f"测试厂商 {test_provider_type} 未找到"
        assert test_provider["provider_name"] == "OpenAI Test"
        assert test_provider["is_active"] is True

    @pytest.mark.asyncio
    async def test_GetSystemProviders_FilterByType_Should_Return_Filtered_Providers(
        self, service: ConfigReaderService, setup_test_data
    ):
        """get_system_providers(provider_type=TEST_PROVIDER_TYPE) 应只返回过滤后的厂商"""
        provider_type = setup_test_data["provider_type"]
        providers = await service.get_system_providers(provider_type=provider_type)

        assert isinstance(providers, list)
        for p in providers:
            assert p["provider_type"] == provider_type

    @pytest.mark.asyncio
    async def test_GetSystemProviders_SupportedModels_Should_Be_Parsed_Correctly(
        self, service: ConfigReaderService, setup_test_data
    ):
        """get_system_providers 返回的 supported_models 应正确解析为 dict"""
        providers = await service.get_system_providers()

        provider_type = setup_test_data["provider_type"]
        test_provider = next(
            (p for p in providers if p["provider_type"] == provider_type), None
        )
        assert test_provider is not None

        supported_models = test_provider["supported_models"]
        assert isinstance(supported_models, dict)
        assert "gpt-4" in supported_models
        assert "CHAT" in supported_models["gpt-4"]
        assert "OCR" in supported_models["gpt-4"]

    @pytest.mark.asyncio
    async def test_GetSystemProviderByType_Should_Return_Single_Provider(
        self, service: ConfigReaderService, setup_test_data
    ):
        """get_system_provider_by_type 应返回指定类型的单个厂商"""
        provider_type = setup_test_data["provider_type"]
        provider = await service.get_system_provider_by_type(provider_type)

        assert provider is not None
        assert provider["provider_type"] == provider_type

    @pytest.mark.asyncio
    async def test_GetSystemProviderByType_NonExistent_Should_Return_None(
        self, service: ConfigReaderService, setup_test_data
    ):
        """get_system_provider_by_type 查询不存在的类型应返回 None"""
        provider = await service.get_system_provider_by_type("non_existent_provider_xyz")

        assert provider is None

    @pytest.mark.asyncio
    async def test_GetUserConfigs_Should_Return_User_Configs(
        self, service: ConfigReaderService, setup_test_data: dict
    ):
        """get_user_configs 应返回指定用户的配置列表"""
        user_id = setup_test_data["user_id"]
        configs = await service.get_user_configs(user_id)

        assert isinstance(configs, list)
        assert len(configs) > 0

        test_config = next(
            (c for c in configs if c["id"] == setup_test_data["config_id"]), None
        )
        assert test_config is not None, f"测试配置 {setup_test_data['config_id']} 未找到"
        assert test_config["user_id"] == user_id
        assert test_config["provider_id"] == setup_test_data["provider_id"]
        assert test_config["model_name"] == "gpt-4"
        assert test_config["is_default"] is True

    @pytest.mark.asyncio
    async def test_GetUserDefaultConfig_Should_Return_Default_Config(
        self, service: ConfigReaderService, setup_test_data
    ):
        """get_user_default_config 应返回用户的默认配置"""
        user_id = setup_test_data["user_id"]
        config = await service.get_user_default_config(user_id)

        assert config is not None
        assert config["user_id"] == user_id
        assert config["is_default"] is True
        assert config["model_name"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_GetUserConfigById_Should_Return_Specific_Config(
        self, service: ConfigReaderService, setup_test_data: dict
    ):
        """get_user_config_by_id 应返回指定 ID 的配置"""
        user_id = setup_test_data["user_id"]
        config = await service.get_user_config_by_id(user_id, setup_test_data["config_id"])

        assert config is not None
        assert config["id"] == setup_test_data["config_id"]
        assert config["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_GetUserConfigById_WrongUser_Should_Return_None(
        self, service: ConfigReaderService, setup_test_data: dict
    ):
        """get_user_config_by_id 用户 ID 不匹配时应返回 None"""
        config = await service.get_user_config_by_id(99999, setup_test_data["config_id"])

        assert config is None

    @pytest.mark.asyncio
    async def test_Service_NoDB_Should_Return_Empty(self):
        """ConfigReaderService 未设置 db 时应返回空列表"""
        service = ConfigReaderService(db=None, cache=test_cache_manager)

        providers = await service.get_system_providers()
        configs = await service.get_user_configs(12345)

        assert providers == []
        assert configs == []

    @pytest.mark.asyncio
    async def test_GetUserDefaultConfigByCapability_Should_Return_Matching_Config(
        self, service: ConfigReaderService, setup_multi_capability_test_data: dict
    ):
        """get_user_default_config_by_capability 应返回指定能力的默认配置"""
        user_id = setup_multi_capability_test_data["user_id"]

        # 查询 CHAT 配置
        chat_config = await service.get_user_default_config_by_capability(user_id, "CHAT")
        assert chat_config is not None
        assert chat_config["capability"] == "CHAT"
        assert chat_config["model_name"] == "gpt-4"
        assert chat_config["is_default"] is True

        # 查询 EMBEDDING 配置
        embedding_config = await service.get_user_default_config_by_capability(user_id, "EMBEDDING")
        assert embedding_config is not None
        assert embedding_config["capability"] == "EMBEDDING"
        assert embedding_config["model_name"] == "text-embedding-3"

        # 查询 RERANK 配置
        rerank_config = await service.get_user_default_config_by_capability(user_id, "RERANK")
        assert rerank_config is not None
        assert rerank_config["capability"] == "RERANK"
        assert rerank_config["model_name"] == "claude-3-rerank"

    @pytest.mark.asyncio
    async def test_GetUserDefaultConfigByCapability_WithProviderType_Should_Filter(
        self, service: ConfigReaderService, setup_multi_capability_test_data: dict
    ):
        """get_user_default_config_by_capability 按 provider_type 过滤应正确工作"""
        user_id = setup_multi_capability_test_data["user_id"]

        # 查询 CHAT 配置，指定错误的 provider_type 应返回 None
        config_wrong_provider = await service.get_user_default_config_by_capability(
            user_id, "CHAT", provider_type="non_existent_provider"
        )
        assert config_wrong_provider is None

        # 查询 CHAT 配置，指定正确的 provider_type
        config_correct_provider = await service.get_user_default_config_by_capability(
            user_id, "CHAT", provider_type=setup_multi_capability_test_data["provider_type1"]
        )
        assert config_correct_provider is not None
        assert config_correct_provider["provider_type"] == setup_multi_capability_test_data["provider_type1"]

    @pytest.mark.asyncio
    async def test_GetUserDefaultConfigByCapability_NonExistent_Should_Return_None(
        self, service: ConfigReaderService, setup_multi_capability_test_data: dict
    ):
        """get_user_default_config_by_capability 查询不存在的能力应返回 None"""
        user_id = setup_multi_capability_test_data["user_id"]

        config = await service.get_user_default_config_by_capability(user_id, "VISION")
        assert config is None

    @pytest.mark.asyncio
    async def test_GetUserConfigsByCapability_Should_Return_All_Matching_Configs(
        self, service: ConfigReaderService, setup_multi_capability_test_data: dict
    ):
        """get_user_configs_by_capability 应返回指定能力的所有配置（按优先级排序）"""
        user_id = setup_multi_capability_test_data["user_id"]

        # 查询所有 CHAT 配置
        chat_configs = await service.get_user_configs_by_capability(user_id, "CHAT")
        assert isinstance(chat_configs, list)
        assert len(chat_configs) > 0
        for config in chat_configs:
            assert config["capability"] == "CHAT"

        # 查询所有 EMBEDDING 配置
        embedding_configs = await service.get_user_configs_by_capability(user_id, "EMBEDDING")
        assert isinstance(embedding_configs, list)
        assert len(embedding_configs) > 0
        for config in embedding_configs:
            assert config["capability"] == "EMBEDDING"

        # 查询不存在的能力应返回空列表
        vision_configs = await service.get_user_configs_by_capability(user_id, "VISION")
        assert vision_configs == []

    @pytest.mark.asyncio
    async def test_GetUserConfigsByCapability_Should_Order_By_Priority(
        self, service: ConfigReaderService, setup_multi_capability_test_data: dict
    ):
        """get_user_configs_by_capability 返回的配置应按优先级降序排列"""
        user_id = setup_multi_capability_test_data["user_id"]

        configs = await service.get_user_configs_by_capability(user_id, "CHAT")

        # 验证按优先级降序排列
        if len(configs) > 1:
            for i in range(len(configs) - 1):
                assert configs[i]["priority"] >= configs[i + 1]["priority"]
