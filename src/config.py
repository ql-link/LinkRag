import os
from typing import List, Optional, Union

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

    # 日志文件落盘（对齐 Java 端：logs/<YYYY-MM-DD>/<service>.log + <service>-error.log）。
    # 每天 0 点切分，按目录归档；保留 LOG_RETENTION_DAYS 天后自动清理。
    LOG_FILE_ENABLED: bool = True
    LOG_DIR: str = "logs"
    LOG_SERVICE_NAME: str = "tolink-service"
    LOG_RETENTION_DAYS: int = 7

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
    # 64-character hex string; decoded to 32 bytes for AES-256-GCM.
    # Local placeholder only; production must override it with the Java-side secret.
    API_KEY_ENCRYPTION_SECRET: str = (
        "0000000000000000000000000000000000000000000000000000000000000000"
    )

    # ==========================================
    # 内部召回 API 配置 (Internal Recall API)
    # ==========================================
    # 外部用户态 Recall API 归属 Java；Python 只暴露内部 recall runtime，
    # 校验 Java 签发的短期内部 JWT(HS256)。详见 docs/internals/recall.md。
    RECALL_INTERNAL_AUTH_ENABLED: bool = True
    RECALL_INTERNAL_JWT_ISSUER: str = "tolink-java"
    RECALL_INTERNAL_JWT_AUDIENCE: str = "tolink-rag"
    RECALL_INTERNAL_JWT_SCOPE: str = "recall:execute"
    # HS256 共享密钥：Java 签发端与 Python 验签端必须一致。
    # 默认值仅用于本地联调，生产必须通过环境变量 / 密钥管理系统覆盖。
    RECALL_INTERNAL_JWT_SECRET: str = (
        "9780df1524906ac133898a8cc74280c512f0334d32d795786c021059ec09b5da"
    )
    # 单次召回最大执行时间（毫秒）；超过即以 SSE error RECALL_TIMEOUT 终止。
    RECALL_STREAM_TIMEOUT_MS: int = 60000
    # pipeline 严格模式默认值：False=宽松，允许单路失败降级。
    RECALL_STRICT_DEFAULT: bool = False
    # 服务端固定返回候选数上限（同时作为各路执行期 top_k）。
    RECALL_RESULT_LIMIT: int = 20
    # 启用的召回路（逗号分隔）。dense 是远程 system embedding HTTP 调用，与 sparse
    # 本地 BGE-M3 推理路径互补；本期默认开启 dense（GitHub issue ql-link/LinkRag#53）。
    # 升级影响：未显式 set env 的部署在升级后自动开启 dense 召回，system embedding
    # HTTP 流量增加；如需暂时回退，运维侧 set RECALL_ENABLED_SOURCES=bm25,sparse 重启。
    RECALL_ENABLED_SOURCES: str = "bm25,sparse,dense"

    # ==========================================
    # 对外直连召回 SSE 配置 (Recall Direct SSE / LINK-40)
    # ==========================================
    # 前端凭 Java 签发的短期 session token 直连 Python `POST /api/v1/recall/stream`。
    # 与内部端点(RECALL_INTERNAL_*)的核心差异：面向浏览器、密钥独立、受众独立。
    # 详见 docs/internals/recall_http_api.md「对外直连 SSE」。
    RECALL_SESSION_AUTH_ENABLED: bool = True
    RECALL_SESSION_JWT_ISSUER: str = "tolink-java"
    # 受众与内部端点(tolink-rag)区分：前端面凭证独立标识，避免内部 token 误用到对外端点。
    RECALL_SESSION_JWT_AUDIENCE: str = "tolink-rag-frontend"
    RECALL_SESSION_JWT_SCOPE: str = "recall:stream"
    # 独立 HS256 密钥：与 RECALL_INTERNAL_JWT_SECRET 物理隔离，前端面 token 疑似泄露时
    # 可单独轮转、不牵连 Java 内部调用。默认值仅供本地联调，生产必须用环境变量覆盖。
    RECALL_SESSION_JWT_SECRET: str = (
        "3f8c1d6a90b74e2f8a5c0d1e7b3f9a26c4d8e0f1a2b3c4d5e6f7081929a3b4c5d"
    )
    # 单用户最大并发召回流数。token 短期可复用、不做一次性，此为资源滥用的主闸门。
    RECALL_SESSION_MAX_CONCURRENT: int = 3

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
    MARKDOWN_PARSER_VISION_CONCURRENCY: int = 24
    CHUNKING_ENABLE_ADVANCED_PIPELINE: bool = True
    CHUNKING_HEADING_BREAK_LEVEL: int = 3
    CHUNKING_SEMANTIC_PERCENTILE: float = 95.0
    CHUNKING_SEMANTIC_UNIT: str = "sentence"
    CHUNKING_MIN_CHUNK_TOKENS: int = 150
    CHUNKING_MAX_CHUNK_TOKENS: int = 512
    CHUNKING_OVERLAP_ENABLED: bool = True
    CHUNKING_OVERLAP_TOKENS: int = 64
    CHUNKING_MIN_DISTANCE_GATE: float = 0.25
    CHUNKING_EMBED_BATCH_SIZE: int = 32

    @field_validator("CHUNKING_SEMANTIC_UNIT")
    @classmethod
    def validate_chunking_semantic_unit(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in {"sentence", "paragraph"}:
            raise ValueError("CHUNKING_SEMANTIC_UNIT must be 'sentence' or 'paragraph'")
        return normalized

    @field_validator("CHUNKING_OVERLAP_TOKENS")
    @classmethod
    def validate_chunking_overlap_tokens(cls, v: int) -> int:
        if v < 0 or v > 64:
            raise ValueError("CHUNKING_OVERLAP_TOKENS must be between 0 and 64")
        return v

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
    # 稠密向量系统统一维度（方案 A：写入按用户解析 embedder，但所有用户共享 per-bucket
    # collection、维度首次建表即固定）。写入前校验用户 EMBEDDING 模型输出维度必须等于此值，
    # 不一致则任务失败（EMBEDDING_DIMENSION_UNSUPPORTED），避免写入既有 collection 时维度冲突。
    DENSE_VECTOR_DIMENSION: int = 1024
    CHUNK_INDEX_RETRY_LIMIT: int = 3
    CHUNK_INDEX_RETRY_INTERVAL_SECONDS: int = 300
    CHUNK_INDEX_INDEXING_STALE_SECONDS: int = 900

    # Sparse vector / BGE-M3
    # SPARSE_VECTOR_PROVIDER 切换推理实现：
    #   bge_m3        → 本地进程内加载模型（下方 MODEL/CACHE/DEVICE/BATCH 等生效）
    #   bge_m3_http   → 调用早期 bge-m3-server（下方 SPARSE_VECTOR_HTTP_* 生效）
    #   remote_bge_m3 → 调用独立 bge-m3-service（下方 BGE_M3_* 生效，dense + sparse 同出）
    SPARSE_VECTOR_ENABLED: bool = True
    SPARSE_VECTOR_PROVIDER: str = "bge_m3"
    SPARSE_VECTOR_MODEL_NAME: str = "BAAI/bge-m3"
    SPARSE_VECTOR_MODEL_CACHE_DIR: Optional[str] = None
    SPARSE_VECTOR_LOCAL_FILES_ONLY: bool = False
    SPARSE_VECTOR_DEVICE: str = "auto"
    SPARSE_VECTOR_BATCH_SIZE: int = 12
    SPARSE_VECTOR_MAX_LENGTH: int = 8192
    # 远程 bge-m3-server（仅 SPARSE_VECTOR_PROVIDER=bge_m3_http 时生效）
    SPARSE_VECTOR_HTTP_ENDPOINT: Optional[str] = None
    SPARSE_VECTOR_HTTP_TIMEOUT: float = 30.0
    SPARSE_VECTOR_HTTP_BATCH_SIZE: Optional[int] = None
    # 独立 bge-m3-service（仅 SPARSE_VECTOR_PROVIDER=remote_bge_m3 时生效）
    # 同时返回 dense（1024 维）+ sparse；带超时 / 重试。
    BGE_M3_SERVICE_URL: Optional[str] = None
    BGE_M3_TIMEOUT_SECONDS: float = 30.0
    BGE_M3_MAX_RETRIES: int = 3
    SPARSE_VECTOR_QDRANT_VECTOR_NAME: str = "sparse_text"
    SPARSE_VECTOR_TOP_K: int = 256
    SPARSE_VECTOR_MIN_WEIGHT: float = 0.0
    SPARSE_VECTOR_RETRY_LIMIT: int = 3
    SPARSE_VECTOR_INDEXING_STALE_SECONDS: int = 900
    TOLINK_RUN_REAL_SPARSE_VECTOR_TESTS: bool = False

    # Sparse retrieval defaults (called by VectorStorageFacade.search_sparse_chunks).
    # 默认值依据：业界保守占位（Dify "score threshold disabled = 0.0"、
    # Qdrant "先广召回后精排"），本项目无评测 harness 时不盲设阈值。
    # 调用方可任意 per-call 覆盖；运维可改 .env 全局收紧。完整调研依据见
    # docs/internals/vectorization.md §9 与 PR 描述。
    SPARSE_RETRIEVAL_TOP_K: int = 10
    SPARSE_RETRIEVAL_SCORE_THRESHOLD: float = 0.0

    # Dense retrieval defaults (called by VectorStorageFacade.search_dense_chunks).
    # 与 SPARSE_RETRIEVAL_* 严格对仗：top_k=10（先广召回后精排），threshold=0.0
    # （cosine 上界 [0, 1]，不过滤、由 top_k 兜底）；阈值校准待评测 harness follow-up。
    # 注意：pipeline 路径下实际生效的 top_k 是 RECALL_RESULT_LIMIT；
    # DENSE_RETRIEVAL_TOP_K 仅作 facade 直调（脚本 / 评测 harness）的兜底默认。
    DENSE_RETRIEVAL_TOP_K: int = 10
    DENSE_RETRIEVAL_SCORE_THRESHOLD: float = 0.0

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
        extra="ignore",
    )


settings = Settings()
