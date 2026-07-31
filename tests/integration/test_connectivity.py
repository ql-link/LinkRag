import asyncio

import pytest

from src.config import settings
from src.utils.logger import logger


def test_mysql():
    """测试 MySQL 连通性"""
    pymysql = pytest.importorskip("pymysql", reason="未安装 pymysql，跳过 MySQL 测试")

    logger.info(f"正在测试 MySQL 连通性: {settings.DB_HOST}:{settings.DB_PORT}")
    try:
        conn = pymysql.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            connect_timeout=5,
        )
        conn.close()
        logger.success("MySQL 连接成功!")
    except Exception as e:
        pytest.fail(f"MySQL 连接失败: {e}")


def test_redis():
    """测试 Redis 连通性"""
    redis = pytest.importorskip("redis", reason="未安装 redis，跳过 Redis 测试")

    logger.info(
        f"正在测试 Redis 连通性: {settings.REDIS_HOST}:{settings.REDIS_PORT} (DB: {settings.REDIS_DB})"
    )
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            socket_timeout=5,
        )
        assert r.ping() is True, "Redis ping 未返回 True"
        logger.success("Redis 连接成功!")
    except Exception as e:
        pytest.fail(f"Redis 连接失败: {e}")


@pytest.mark.skipif(settings.MQ_VENDOR.lower() != "kafka", reason="当前环境 MQ_VENDOR 不是 Kafka")
@pytest.mark.asyncio
async def test_kafka():
    """测试 Kafka 连通性（启动握手，不写入消息）"""
    try:
        from aiokafka import AIOKafkaProducer
    except ImportError as e:
        pytest.fail(
            f"未安装 aiokafka，无法测试 Kafka 连通性: {e}（建议执行: pip install aiokafka）"
        )

    logger.info(f"正在测试 Kafka 连通性: {settings.KAFKA_BOOTSTRAP_SERVERS}")
    producer = None
    try:
        kwargs = {
            "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "client_id": "tolink-rag-connectivity-test",
            "security_protocol": getattr(settings, "KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
        }
        sasl_mechanism = getattr(settings, "KAFKA_SASL_MECHANISM", None)
        if sasl_mechanism:
            kwargs.update(
                {
                    "sasl_mechanism": sasl_mechanism,
                    "sasl_plain_username": getattr(settings, "KAFKA_SASL_USERNAME", None),
                    "sasl_plain_password": getattr(settings, "KAFKA_SASL_PASSWORD", None),
                }
            )

        producer = AIOKafkaProducer(**kwargs)
        await asyncio.wait_for(producer.start(), timeout=5)
        logger.success("Kafka 连接成功!")
    except Exception as e:
        pytest.fail(f"Kafka 连接失败: {e}")
    finally:
        if producer is not None:
            try:
                await asyncio.wait_for(producer.stop(), timeout=5)
            except Exception:
                pass


@pytest.mark.skipif(
    settings.VECTOR_STORE_TYPE != "qdrant", reason="当前环境未配置使用 Qdrant 作为向量库"
)
@pytest.mark.asyncio
async def test_qdrant():
    """通过产品 Store 的协议和认证装配测试 Qdrant 连通性。"""
    grpc = pytest.importorskip("grpc", reason="未安装 grpc，跳过 Qdrant 测试")

    logger.info(f"正在测试 Qdrant 连通性: {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")
    try:
        from src.core.storage.qdrant import QdrantIndexStore

        store = QdrantIndexStore(timeout=5)
        client = await store._get_client()
        collections = await client.get_collections()
        assert collections is not None, "获取 Collections 失败"

        logger.success(f"Qdrant 连接成功! Collections: {[c.name for c in collections.collections]}")
        await store.close()
    except Exception as e:
        pytest.fail(f"Qdrant 连接失败: {e}")


@pytest.mark.skipif(settings.STORAGE_TYPE != "minio", reason="当前环境存储组件未配置使用 MinIO")
def test_minio():
    """测试 MinIO 连通性"""
    boto3 = pytest.importorskip("boto3", reason="未安装 boto3/botocore，跳过 MinIO 测试")
    from botocore.config import Config

    logger.info(f"正在测试 MinIO 连通性: {settings.MINIO_ENDPOINT}")
    try:
        endpoint_url = (
            f"http://{settings.MINIO_ENDPOINT}"
            if not settings.MINIO_ENDPOINT.startswith("http")
            else settings.MINIO_ENDPOINT
        )
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4", connect_timeout=5, retries={"max_attempts": 0}),
            use_ssl=settings.MINIO_USE_SSL,
        )

        # 尝试列出 bucket 作为联通标志
        response = s3.list_buckets()
        assert "Buckets" in response, "返回结构中缺失 Buckets 信息"
        logger.success("MinIO 连接成功!")
    except Exception as e:
        pytest.fail(f"MinIO 连接失败: {e}")
