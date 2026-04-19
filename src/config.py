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

    # ==========================================
    # 向量数据库配置 (Vector Store)
    # ==========================================
    # 可选值: qdrant / elasticsearch
    VECTOR_STORE_TYPE: str = "qdrant"

    # Qdrant
    QDRANT_HOST: str = "36.213.180.176"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_COLLECTION_NAME: str = "tolink_rag_collection"

    # Elasticsearch
    ES_HOST: str = "http://localhost:9200"
    ES_USER: Optional[str] = None
    ES_PASSWORD: Optional[str] = None
    ES_INDEX_NAME: str = "tolink_rag_index"

    # ==========================================
    # 存储 & 资源配置 (Storage & Resources)
    # ==========================================
    STORAGE_TYPE: str = "minio"  # minio / local
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "tolink-rag-docs"
    MINIO_USE_SSL: bool = False
    LOCAL_DOCS_PATH: str = "./data/documents"
    PDF_PARSER_BACKEND: str = "auto"  # auto / mineru / marker / docling / naive
    PDF_PARSER_FALLBACKS: str = "naive"
    MINERU_API_URL: str = ""  # mineru-api 服务地址，例如 http://localhost:8010 或云服务地址
    MINERU_API_KEY: Optional[str] = None  # MinerU 云服务专属 Token (如需)
    MINERU_TIMEOUT: int = 300  # MinerU API 请求超时（秒）


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

    # --- RabbitMQ 配置 ---
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    RABBITMQ_EXCHANGE_NAME: str = ""
    RABBITMQ_EXCHANGE_TYPE: str = "direct"
    RABBITMQ_PREFETCH_COUNT: int = 10

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
