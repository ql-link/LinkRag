import pytest
from src.utils.logger import logger
from src.config import settings

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
            connect_timeout=5
        )
        conn.close()
        logger.success("MySQL 连接成功!")
    except Exception as e:
        pytest.fail(f"MySQL 连接失败: {e}")


def test_redis():
    """测试 Redis 连通性"""
    redis = pytest.importorskip("redis", reason="未安装 redis，跳过 Redis 测试")
    
    logger.info(f"正在测试 Redis 连通性: {settings.REDIS_HOST}:{settings.REDIS_PORT} (DB: {settings.REDIS_DB})")
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            socket_timeout=5
        )
        assert r.ping() is True, "Redis ping 未返回 True"
        logger.success("Redis 连接成功!")
    except Exception as e:
        pytest.fail(f"Redis 连接失败: {e}")


@pytest.mark.skipif(settings.VECTOR_STORE_TYPE != "milvus", reason="当前环境未配置使用 Milvus 作为向量库")
def test_milvus():
    """测试 Milvus 连通性"""
    pymilvus = pytest.importorskip("pymilvus", reason="未安装 pymilvus，跳过 Milvus 测试")
    
    logger.info(f"正在测试 Milvus 连通性: {settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
    try:
        test_alias = "milvus_test_conn_pytest"
        
        if test_alias in pymilvus.connections.list_connections():
            pymilvus.connections.disconnect(test_alias)
            
        pymilvus.connections.connect(
            alias=test_alias,
            host=settings.MILVUS_HOST,
            port=str(settings.MILVUS_PORT),
            user=settings.MILVUS_USER,
            password=settings.MILVUS_PASSWORD,
            timeout=5
        )
        
        server_version = pymilvus.utility.get_server_version(using=test_alias)
        pymilvus.connections.disconnect(test_alias)
        
        assert server_version, "获取到的 Server Version 为空"
        logger.success(f"Milvus 连接成功! Server Version: {server_version}")
    except Exception as e:
        pytest.fail(f"Milvus 连接失败: {e}")


@pytest.mark.skipif(not settings.ES_HOST, reason="当前环境未配置 ES_HOST")
def test_elasticsearch():
    """测试 Elasticsearch 连通性"""
    elasticsearch = pytest.importorskip("elasticsearch", reason="未安装 elasticsearch，跳过 Elasticsearch 测试")
    
    logger.info(f"正在测试 Elasticsearch 连通性: {settings.ES_HOST}")
    try:
        es = elasticsearch.Elasticsearch(
            [settings.ES_HOST],
            basic_auth=(settings.ES_USER, settings.ES_PASSWORD) if settings.ES_USER else None,
            request_timeout=5
        )
        assert es.ping() is True, "Elasticsearch ping 失败"
        logger.success("Elasticsearch 连接成功!")
    except Exception as e:
        pytest.fail(f"Elasticsearch 连接失败: {e}")


@pytest.mark.skipif(settings.STORAGE_TYPE != "minio", reason="当前环境存储组件未配置使用 MinIO")
def test_minio():
    """测试 MinIO 连通性"""
    boto3 = pytest.importorskip("boto3", reason="未安装 boto3/botocore，跳过 MinIO 测试")
    from botocore.config import Config
    
    logger.info(f"正在测试 MinIO 连通性: {settings.MINIO_ENDPOINT}")
    try:
        endpoint_url = f"http://{settings.MINIO_ENDPOINT}" if not settings.MINIO_ENDPOINT.startswith("http") else settings.MINIO_ENDPOINT
        s3 = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=Config(signature_version='s3v4', connect_timeout=5, retries={'max_attempts': 0}),
            use_ssl=settings.MINIO_USE_SSL
        )
        
        # 尝试列出 bucket 作为联通标志
        response = s3.list_buckets()
        assert 'Buckets' in response, "返回结构中缺失 Buckets 信息"
        logger.success("MinIO 连接成功!")
    except Exception as e:
        pytest.fail(f"MinIO 连接失败: {e}")
