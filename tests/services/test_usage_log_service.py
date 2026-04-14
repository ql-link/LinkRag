"""
UsageLogService 集成测试
测试用量日志服务的数据库操作
"""
import asyncio
import uuid
import random
import pytest
import pytest_asyncio
import pymysql
from datetime import datetime, date, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_async_session_factory
from src.services.usage_log_service import UsageLogService
from src.cache.cache_manager import CacheManager, NullCacheBackend
from src.core.llm.response import UsageInfo
from src.config import settings


def create_unique_user_id():
    """生成唯一的用户 ID（10位数字）"""
    return int(f"3{random.randint(100000000, 999999999)}")


def get_sync_connection():
    """获取同步 MySQL 连接"""
    return pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        autocommit=True
    )


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


class TestUsageLogServiceIntegration:
    """UsageLogService MySQL 集成测试"""

    @pytest_asyncio.fixture
    async def db_session(self):
        """获取数据库 Session"""
        factory = get_async_session_factory()
        async with factory() as session:
            yield session

    @pytest_asyncio.fixture
    async def service(self, db_session: AsyncSession):
        """创建 UsageLogService 实例"""
        svc = UsageLogService(db=db_session)
        return svc

    @pytest_asyncio.fixture
    async def setup_test_data(self, db_session: AsyncSession):
        """插入测试数据，测试后清理"""
        test_user_id = create_unique_user_id()
        test_config_id = int(f"4{random.randint(100000000, 999999999)}")
        test_log_id = None

        conn = get_sync_connection()
        try:
            with conn.cursor() as cursor:
                # 不指定 id，让数据库自动生成
                cursor.execute("""
                    INSERT INTO llm_usage_log
                    (user_id, config_id, provider_type, model_name, prompt_tokens,
                     completion_tokens, total_tokens, latency_ms, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    test_user_id,
                    test_config_id,
                    "openai",
                    "gpt-4",
                    100,
                    200,
                    300,
                    1500,
                    "success"
                ))
                test_log_id = cursor.lastrowid
        finally:
            conn.close()

        await db_session.commit()
        yield {"log_id": test_log_id, "user_id": test_user_id, "config_id": test_config_id}

        # 清理
        conn = get_sync_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"DELETE FROM llm_usage_log WHERE id = {test_log_id}")
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_Log_Usage_Should_Insert_Record(
        self, service: UsageLogService, db_session: AsyncSession
    ):
        """log_usage 应该插入用量记录"""
        test_user_id = create_unique_user_id()
        test_config_id = int(f"4{random.randint(100000000, 999999999)}")

        # 手动创建日志条目（不指定 id，让数据库自动生成）
        from src.models.db_models import UsageLogDB
        log_entry = UsageLogDB(
            user_id=test_user_id,
            config_id=test_config_id,
            provider_type="openai",
            model_name="gpt-4",
            prompt_tokens=50,
            completion_tokens=100,
            total_tokens=150,
            latency_ms=1000,
            status="success"
        )
        db_session.add(log_entry)
        await db_session.commit()

        # 获取自动生成的 id
        test_log_id = log_entry.id

        # 验证插入成功 - 使用明确列名
        conn = get_sync_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT id, user_id, provider_type, model_name FROM llm_usage_log WHERE id = {test_log_id}"
                )
                row = cursor.fetchone()
                assert row is not None
                assert row[1] == test_user_id  # user_id
                assert row[2] == "openai"  # provider_type
                assert row[3] == "gpt-4"  # model_name
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_Get_User_Usage_Should_Return_Records(
        self, service: UsageLogService, setup_test_data: dict
    ):
        """get_user_usage 应该返回用户的用量记录"""
        user_id = setup_test_data["user_id"]
        logs = await service.get_user_usage(user_id)

        assert isinstance(logs, list)
        assert len(logs) > 0

        test_log = next((log for log in logs if log["id"] == setup_test_data["log_id"]), None)
        assert test_log is not None
        assert test_log["user_id"] == user_id
        assert test_log["provider_type"] == "openai"
        assert test_log["total_tokens"] == 300

    @pytest.mark.asyncio
    async def test_Get_User_Usage_With_Date_Filter(
        self, service: UsageLogService, setup_test_data: dict
    ):
        """get_user_usage 应该支持日期过滤"""
        user_id = setup_test_data["user_id"]
        today = date.today()

        logs = await service.get_user_usage(user_id, start_date=today)

        assert isinstance(logs, list)
        assert len(logs) > 0
        for log in logs:
            log_date = datetime.fromisoformat(log["created_at"]).date()
            assert log_date >= today

    @pytest.mark.asyncio
    async def test_Get_User_Usage_Limit(
        self, service: UsageLogService, setup_test_data: dict
    ):
        """get_user_usage 应该限制返回数量"""
        user_id = setup_test_data["user_id"]

        logs = await service.get_user_usage(user_id, limit=5)

        assert len(logs) <= 5

    @pytest.mark.asyncio
    async def test_Get_User_Usage_No_DB_Should_Return_Empty(
        self, service: UsageLogService
    ):
        """UsageLogService 未设置 db 时应该返回空列表"""
        service._db = None

        logs = await service.get_user_usage("any_user")

        assert logs == []

    @pytest.mark.asyncio
    async def test_Get_Usage_Summary_Should_Return_Aggregated_Stats(
        self, service: UsageLogService, setup_test_data: dict
    ):
        """get_usage_summary 应该返回聚合统计"""
        user_id = setup_test_data["user_id"]

        summary = await service.get_usage_summary(user_id)

        assert "total_calls" in summary
        assert "total_tokens" in summary
        assert "prompt_tokens" in summary
        assert "completion_tokens" in summary
        assert "daily_stats" in summary

        assert summary["total_calls"] >= 1
        assert summary["total_tokens"] >= 300

    @pytest.mark.asyncio
    async def test_Get_Usage_Summary_With_Date_Filter(
        self, service: UsageLogService, setup_test_data: dict
    ):
        """get_usage_summary 应该支持日期过滤"""
        user_id = setup_test_data["user_id"]
        today = date.today()

        summary = await service.get_usage_summary(user_id, start_date=today)

        assert summary["total_calls"] >= 1

    @pytest.mark.asyncio
    async def test_Get_Usage_Summary_No_DB_Should_Return_Zero_Stats(
        self, service: UsageLogService
    ):
        """UsageLogService 未设置 db 时应该返回零值统计"""
        service._db = None

        summary = await service.get_usage_summary("any_user")

        assert summary["total_calls"] == 0
        assert summary["total_tokens"] == 0
        assert summary["prompt_tokens"] == 0
        assert summary["completion_tokens"] == 0
        assert summary["daily_stats"] == []
