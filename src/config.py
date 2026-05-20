import os
from typing import Optional, List, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # ==========================================
    # 核心系统配置 (Application Config)
    # ==========================================
    APP_NAME: str = "toLink-Rag"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    APP_ENV: str = "development"

    # ==========================================
    # 存储 & 缓存配置 (Storage & Cache)
    # ==========================================
    # Database (MySQL)
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "tolink_rag_db"
    
    # 支持直接从 env 读取 DATABASE_URL，如果不存在则由上述字段构建
    DATABASE_URL: Optional[str] = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, v: Optional[str], info) -> str:
        if isinstance(v, str) and v:
            return v
        values = info.data
        return f"mysql+pymysql://{values.get('DB_USER')}:{values.get('DB_PASSWORD')}@{values.get('DB_HOST')}:{values.get('DB_PORT')}/{values.get('DB_NAME')}"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    
    # 支持直接从 env 读取 REDIS_URL
    REDIS_URL: Optional[str] = None

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def assemble_redis_url(cls, v: Optional[str], info) -> str:
        if isinstance(v, str) and v:
            return v
        values = info.data
        host = values.get("REDIS_HOST")
        port = values.get("REDIS_PORT")
        db = values.get("REDIS_DB")
        pw = values.get("REDIS_PASSWORD")
        auth = f":{pw}@" if pw else ""
        return f"redis://{auth}{host}:{port}/{db}"

    # ==========================================
    # 安全配置 (Security)
    # ==========================================
    API_KEY_ENCRYPTION_SECRET: str = "default-secret"

    # ==========================================
    # 系统级兜底 LLM 配置 (Platform Default Fallback LLMs)
    # ==========================================
    SYSTEM_LLM_PROVIDER: str = "qwen"
    SYSTEM_LLM_API_KEY: Optional[str] = None
    SYSTEM_LLM_API_BASE: Optional[str] = None

    SYSTEM_LLM_MODEL_CHAT: str = "qwen3.5-flash"
    SYSTEM_LLM_MODEL_EMBEDDING: str = "text-embedding-v4"
    SYSTEM_LLM_MODEL_RERANK: Optional[str] = "qwen3-vl-rerank"
    SYSTEM_LLM_MODEL_VISION: Optional[str] = None
    MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT: bool = True
    MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT: bool = True
    MARKDOWN_PARSER_TABLE_MODEL: Optional[str] = None
    MARKDOWN_PARSER_VISION_MODEL: Optional[str] = None
    MARKDOWN_PARSER_LLM_TIMEOUT_MS: int = 60000
    CHUNKING_ENABLE_ADVANCED_PIPELINE: bool = True
    CHUNKING_HEADING_BREAK_LEVEL: int = 3
    CHUNKING_SEMANTIC_PERCENTILE: float = 95.0
    CHUNKING_MIN_CHUNK_TOKENS: int = 150
    CHUNKING_MAX_CHUNK_TOKENS: int = 512
    CHUNKING_OVERLAP_TOKENS: int = 64
    CHUNKING_MIN_DISTANCE_GATE: float = 0.25
    CHUNKING_EMBED_BATCH_SIZE: int = 32

    # ==========================================
    # 向量数据库配置 (Vector Store)
    # ==========================================
    # 可选值: qdrant / elasticsearch
    VECTOR_STORE_TYPE: str = "qdrant"

    # Qdrant
    QDRANT_HOST: str = "43.138.176.52"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_COLLECTION_NAME: str = "tolink_rag_collection"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_TIMEOUT_SECONDS: int = 5

    # Chunk indexing / vector storage
    CHUNK_INDEX_BUCKET_COUNT: int = 128
    CHUNK_INDEX_COLLECTION_PREFIX: str = "kb_bucket"
    CHUNK_INDEX_EMBED_BATCH_SIZE: int = 32
    CHUNK_INDEX_RETRY_LIMIT: int = 3
    CHUNK_INDEX_RETRY_INTERVAL_SECONDS: int = 300
    CHUNK_INDEX_INDEXING_STALE_SECONDS: int = 900

    # Elasticsearch
    ES_HOST: str = "http://localhost:9200"
    ES_USER: Optional[str] = None
    ES_PASSWORD: Optional[str] = None
    ES_INDEX_NAME: str = "tolink_rag_index"
    ES_INDEX_SHARDS: int = 3
    ES_INDEX_REPLICAS: int = 1
    ES_MAX_DOCUMENT_BYTES: int = 131072
    ES_MAX_TOKEN_BATCH_BYTES: int = 5242880
    ES_MAX_TOKEN_BATCH_CHUNKS: int = 500
    ES_BULK_REQUEST_TIMEOUT_SECONDS: int = 30
    ES_SMOKE_ENABLED: bool = False
    TOLINK_RUN_REAL_ES_INDEX_TESTS: bool = False

    # ==========================================
    # 存储 & 资源配置 (Storage & Resources)
    # ==========================================
    # 解析任务源文件临时落盘目录：流式下载在此创建临时文件，markdown 拿到后立即清理；
    # worker 启动时由 src/main.py lifespan 调用 temp_workspace.ensure_clean_on_startup 清空兜底。
    PARSE_TEMP_DIR: str = "/tmp/tolink-rag-parse"

    STORAGE_TYPE: str = "minio"  # minio / local
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "tolink-rag-docs"
    MINIO_USE_SSL: bool = False
    LOCAL_DOCS_PATH: str = "./data/documents"
    PDF_PARSER_BACKEND: str = "mineru"  # auto / mineru / opendataloader / naive
    PDF_PARSER_FALLBACKS: str = ""
    PDF_IMAGE_UPLOAD_ASYNC: bool = True  # 是否后台异步上传 PDF 图片资产
    PDF_IMAGE_ENHANCEMENT_MEMORY_MAX_IMAGES: int = 20  # 图片增强最多使用多少张内存图片
    PDF_IMAGE_ENHANCEMENT_MEMORY_MAX_BYTES: int = 50 * 1024 * 1024  # 图片增强内存图片总量上限
    MINERU_API_URL: str = ""  # MinerU 官方云端 V4 API 地址
    MINERU_API_KEY: Optional[str] = None  # MinerU 云服务专属 Token
    MINERU_TIMEOUT: int = 300  # MinerU API 请求超时（秒）
    MINERU_MODEL_VERSION: str = "vlm"  # pipeline / vlm / MinerU-HTML


    # ==========================================
    # MQ 消息中台配置 (Message Queue)
    # ==========================================
    # 可选值: kafka / rabbitmq
    MQ_VENDOR: str = "kafka"

    # --- Kafka 配置 ---
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_SASL_MECHANISM: Optional[str] = None
    KAFKA_SASL_USERNAME: Optional[str] = None
    KAFKA_SASL_PASSWORD: Optional[str] = None
    KAFKA_SECURITY_PROTOCOL: str = "PLAINTEXT"
    KAFKA_MAX_POLL_INTERVAL_MS: int = 900000
    INIT_KAFKA_TOPICS_ON_STARTUP: bool = False

    # --- RabbitMQ 配置 ---
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    RABBITMQ_EXCHANGE_NAME: str = ""
    RABBITMQ_EXCHANGE_TYPE: str = "direct"
    RABBITMQ_PREFETCH_COUNT: int = 10

    # --- MQ 失败兜底（恒启用死信，不提供关闭开关）---
    # 业务回调抛 RetriableError 子类时，最多重试 MQ_MAX_RETRIES 次，每次之间固定
    # 退避 MQ_RETRY_BACKOFF_SECONDS；达上限或非 RetriableError 异常一律进入死信目标
    # `<原 topic> + MQ_DLQ_SUFFIX`，并精确按 (topic, partition) 提交位点。
    MQ_MAX_RETRIES: int = 3
    MQ_RETRY_BACKOFF_SECONDS: float = 1.0
    MQ_DLQ_SUFFIX: str = ".DLT"

    # ==========================================
    # 杂项配置 (Misc)
    # ==========================================
    CORS_ORIGINS: Union[List[str], str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
