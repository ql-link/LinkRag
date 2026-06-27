import os
from typing import List, Optional, Union

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS = frozenset({"noop", "semantic_depth_window"})
MARKDOWN_HEADING_LLM_CONTEXT_TOKEN_MIN = 2048
MARKDOWN_HEADING_LLM_CONTEXT_TOKEN_MAX = 262144
MARKDOWN_HEADING_LLM_MAX_OUTPUT_TOKEN_MIN = 512
MARKDOWN_HEADING_LLM_MAX_OUTPUT_TOKEN_MAX = 65536


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
    # 召回执行配置 (Recall Pipeline)
    # ==========================================
    # 召回融合 pipeline 的通用执行参数，两条召回链路共用。
    # 单次召回最大执行时间（毫秒）；超过即以 SSE error RECALL_TIMEOUT 终止。
    # 仅覆盖召回 + rerank 阶段；LLM 生成阶段另由 RECALL_GENERATION_TIMEOUT_MS 约束。
    RECALL_STREAM_TIMEOUT_MS: int = 60000
    # LLM 生成阶段最大执行时间（毫秒），与召回超时解耦（chat-stream-resilient-persist R6）。
    # 后台续跑场景下生成不再被连接断开兜底，需独立超时防孤儿任务无限烧 token；
    # 取值远大于召回超时以容纳长回答，超时即落 FAILED + GENERATION_TIMEOUT。
    RECALL_GENERATION_TIMEOUT_MS: int = 300000
    # 会话首轮标题生成的独立超时（毫秒）。标题任务与召回+生成并行起跑、用本轮对话模型。
    # 取值需覆盖**推理模型**（如 mimo：先思考十余秒才吐标题）的耗时，否则超时回落首问截断；
    # 因与答案生成并行、且答案同模型同样耗时，终态 await 通常不额外增加感知延迟。超时即回落兜底。
    TITLE_GENERATION_TIMEOUT_MS: int = 25000
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
    # 对外会话鉴权配置 (RAG 流 / 纯召回 JSON / LINK-40, LINK-131)
    # ==========================================
    # 前端凭 Java 签发的短期 session token 直连 Python 对外端点
    # `POST /api/v1/rag/stream`（RAG 问答流）与 `POST /api/v1/recall`（纯召回 JSON）。
    # 详见 docs/internals/recall_http_api.md。
    RECALL_SESSION_AUTH_ENABLED: bool = True
    RECALL_SESSION_JWT_ISSUER: str = "tolink-java"
    # 前端面凭证独立受众标识，避免与其他 token 混用。
    RECALL_SESSION_JWT_AUDIENCE: str = "tolink-rag-frontend"
    RECALL_SESSION_JWT_SCOPE: str = "recall:stream"
    # 独立 HS256 密钥：前端面 token 疑似泄露时可单独轮转。
    # 默认值仅供本地联调，生产必须用环境变量覆盖。
    RECALL_SESSION_JWT_SECRET: str = (
        "3f8c1d6a90b74e2f8a5c0d1e7b3f9a26c4d8e0f1a2b3c4d5e6f7081929a3b4c5d"
    )
    # 单用户最大并发召回流数。token 短期可复用、不做一次性，此为资源滥用的主闸门。
    RECALL_SESSION_MAX_CONCURRENT: int = 3

    # ==========================================
    # 召回后 LLM 答案生成 (Recall Answer Generation)
    # ==========================================
    # 召回融合并回填片段正文后，拼装生成上下文的 token 预算上限。片段按融合分数
    # 从高到低纳入，累计超过该预算即截断尾部低分片段（见 recall_stream_runtime 生成段）。
    RECALL_GENERATION_CONTEXT_TOKEN_BUDGET: int = 4000

    # ==========================================
    # 召回后重排 (Post-Recall Rerank / LINK-130)
    # ==========================================
    # 重排模块输出的候选条数兜底默认值。调用方未显式传 top_n 时生效；
    # 调用方传入则以传入为准。值参考业界 rerank top_n（RAGFlow 默认 6，本项目放宽到 8）。
    RERANK_DEFAULT_TOP_N: int = 8

    # ==========================================
    # 系统级兜底 LLM 配置 (Platform Default Fallback LLMs)
    # ==========================================
    SYSTEM_LLM_PROVIDER: str = "qwen"
    SYSTEM_LLM_API_KEY: Optional[str] = None
    SYSTEM_LLM_API_BASE: Optional[str] = None

    SYSTEM_LLM_MODEL_CHAT: str = "qwen3.5-flash"
    SYSTEM_LLM_MODEL_EMBEDDING: str = "text-embedding-v4"
    # RERANK 不走系统兜底：必须由用户在 RERANK 能力配置里显式指定 provider + rerank 模型
    # （如硅基流动 BAAI/bge-reranker-v2-m3）。置空后 get_system_fallback_config_by_capability("RERANK")
    # 返回 None，召回链路 allow_system_fallback=False 时即抛 UserModelConfigMissingError（必配不兜底）。
    SYSTEM_LLM_MODEL_RERANK: Optional[str] = None
    SYSTEM_LLM_MODEL_VISION: Optional[str] = None
    MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT: bool = True
    MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT: bool = True
    MARKDOWN_PARSER_TABLE_MODEL: Optional[str] = None
    MARKDOWN_PARSER_VISION_MODEL: Optional[str] = None
    MARKDOWN_PARSER_LLM_TIMEOUT_MS: int = 60000
    MARKDOWN_PARSER_VISION_CONCURRENCY: int = 24
    MARKDOWN_PARSER_ENABLE_HEADING_HIERARCHY: bool = False
    MARKDOWN_PARSER_HEADING_NO_HEADING_MIN_TOKENS: int = 512
    MARKDOWN_PARSER_HEADING_FLAT_MIN_HEADINGS: int = 5
    MARKDOWN_PARSER_HEADING_SPARSE_TOKENS_PER_HEADING: int = 1536
    MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET: int = 65536
    MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS: int = 4096
    CHUNKING_STAGE_ONE_ALGORITHM: str = "candidate_boundary"
    CHUNKING_STAGE_TWO_ALGORITHM: str = "noop"
    CHUNKING_HEADING_BREAK_LEVEL: int = 5
    CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS: int = 128
    CHUNKING_OVERLAP_TOKENS: int = 64
    # Stage 2 语义细分（semantic_depth_window）三层 token 阈值与 overlap 开关。
    # 软目标：普通打包上限；硬上限：不可拆 atom（代码/公式）的绝对上限，超过即按行截断。
    CHUNKING_MAX_CHUNK_TOKENS: int = 512
    CHUNKING_HARD_MAX_TOKENS: int = 1024
    # 含 protected 元素的最终 chunk 是否参与 pipeline 后置 neighbor overlap（仅文本边缘）。
    CHUNKING_PROTECTED_NEIGHBOR_OVERLAP: bool = False

    @field_validator("CHUNKING_STAGE_ONE_ALGORITHM")
    @classmethod
    def validate_chunking_stage_one_algorithm(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in {"candidate_boundary"}:
            raise ValueError("CHUNKING_STAGE_ONE_ALGORITHM must be 'candidate_boundary'")
        return normalized

    @field_validator("CHUNKING_STAGE_TWO_ALGORITHM")
    @classmethod
    def validate_chunking_stage_two_algorithm(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS:
            supported = ", ".join(sorted(SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS))
            raise ValueError(
                "CHUNKING_STAGE_TWO_ALGORITHM must be one of the registered "
                f"Stage 2 algorithms: {supported}"
            )
        return normalized

    @field_validator("MARKDOWN_PARSER_HEADING_NO_HEADING_MIN_TOKENS")
    @classmethod
    def validate_markdown_heading_no_heading_min_tokens(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("MARKDOWN_PARSER_HEADING_NO_HEADING_MIN_TOKENS must be positive")
        return v

    @field_validator("MARKDOWN_PARSER_HEADING_FLAT_MIN_HEADINGS")
    @classmethod
    def validate_markdown_heading_flat_min_headings(cls, v: int) -> int:
        if v < 5:
            raise ValueError("MARKDOWN_PARSER_HEADING_FLAT_MIN_HEADINGS must be >= 5")
        return v

    @field_validator("MARKDOWN_PARSER_HEADING_SPARSE_TOKENS_PER_HEADING")
    @classmethod
    def validate_markdown_heading_sparse_tokens_per_heading(cls, v: int) -> int:
        if v < 1024:
            raise ValueError("MARKDOWN_PARSER_HEADING_SPARSE_TOKENS_PER_HEADING must be >= 1024")
        return v

    @field_validator("MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET")
    @classmethod
    def validate_markdown_heading_llm_context_token_budget(cls, v: int) -> int:
        if v < MARKDOWN_HEADING_LLM_CONTEXT_TOKEN_MIN or v > MARKDOWN_HEADING_LLM_CONTEXT_TOKEN_MAX:
            raise ValueError(
                "MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET must be between "
                f"{MARKDOWN_HEADING_LLM_CONTEXT_TOKEN_MIN} and "
                f"{MARKDOWN_HEADING_LLM_CONTEXT_TOKEN_MAX}"
            )
        return v

    @field_validator("MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS")
    @classmethod
    def validate_markdown_heading_llm_max_output_tokens(cls, v: int) -> int:
        if (
            v < MARKDOWN_HEADING_LLM_MAX_OUTPUT_TOKEN_MIN
            or v > MARKDOWN_HEADING_LLM_MAX_OUTPUT_TOKEN_MAX
        ):
            raise ValueError(
                "MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS must be between "
                f"{MARKDOWN_HEADING_LLM_MAX_OUTPUT_TOKEN_MIN} and "
                f"{MARKDOWN_HEADING_LLM_MAX_OUTPUT_TOKEN_MAX}"
            )
        return v

    @field_validator("CHUNKING_OVERLAP_TOKENS")
    @classmethod
    def validate_chunking_overlap_tokens(cls, v: int) -> int:
        if v < 0 or v > 64:
            raise ValueError("CHUNKING_OVERLAP_TOKENS must be between 0 and 64")
        return v

    @field_validator("CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS")
    @classmethod
    def validate_chunking_min_candidate_chunk_tokens(cls, v: int) -> int:
        if v < 128 or v > 256:
            raise ValueError("CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS must be between 128 and 256")
        return v

    @field_validator("CHUNKING_MAX_CHUNK_TOKENS")
    @classmethod
    def validate_chunking_max_chunk_tokens(cls, v: int) -> int:
        if v < 256 or v > 2048:
            raise ValueError("CHUNKING_MAX_CHUNK_TOKENS must be between 256 and 2048")
        return v

    @field_validator("CHUNKING_HARD_MAX_TOKENS")
    @classmethod
    def validate_chunking_hard_max_tokens(cls, v: int) -> int:
        if v < 512 or v > 8192:
            raise ValueError("CHUNKING_HARD_MAX_TOKENS must be between 512 and 8192")
        return v

    @model_validator(mode="before")
    @classmethod
    def validate_chunking_token_bounds_before(cls, data):
        if not isinstance(data, dict):
            return data

        def resolve_int(name: str) -> int | None:
            if name not in data:
                return None
            try:
                return int(data[name])
            except (TypeError, ValueError):
                return None

        min_candidate = resolve_int("CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS")
        max_chunk = resolve_int("CHUNKING_MAX_CHUNK_TOKENS")
        hard_max = resolve_int("CHUNKING_HARD_MAX_TOKENS")
        if min_candidate is not None and max_chunk is not None and max_chunk < min_candidate:
            raise ValueError(
                "CHUNKING_MAX_CHUNK_TOKENS must be >= CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS"
            )
        if hard_max is not None and max_chunk is not None and hard_max < max_chunk:
            raise ValueError("CHUNKING_HARD_MAX_TOKENS must be >= CHUNKING_MAX_CHUNK_TOKENS")
        return data

    @model_validator(mode="after")
    def validate_chunking_token_bounds(self) -> "Settings":
        if self.CHUNKING_MAX_CHUNK_TOKENS < self.CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS:
            raise ValueError(
                "CHUNKING_MAX_CHUNK_TOKENS must be >= CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS"
            )
        if self.CHUNKING_HARD_MAX_TOKENS < self.CHUNKING_MAX_CHUNK_TOKENS:
            raise ValueError("CHUNKING_HARD_MAX_TOKENS must be >= CHUNKING_MAX_CHUNK_TOKENS")
        return self

    # ==========================================
    # 轻量流程编排引擎配置 (Workflow Engine)
    # ==========================================
    WORKFLOW_MAX_CONCURRENCY: int = 8
    # 解析任务编排引擎选择：True=并行 DAG（dense∥sparse∥es，默认）；
    # False=串行 StagePipeline（保留作稳定回退，代码不删）。两者复用同一套
    # StageServices 业务，权威状态源都是 document_parse_pipeline。出问题置 False 秒回滚。
    PARSE_USE_WORKFLOW_DAG: bool = True

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
    QDRANT_TIMEOUT_SECONDS: int = 20

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

    # Sparse vector
    # 稀疏向量的「用哪个模型 / 连哪个端点」已统一按发起用户配置经 (protocol, capability)
    # adapter 解析（必配不兜底），不再有系统级 provider / 模型 / 连接配置。以下仅保留与
    # 具体 provider 无关的全局策略：开关、Qdrant named vector 名、清洗规则、外层批大小。
    SPARSE_VECTOR_ENABLED: bool = True
    # Qdrant named sparse vector 字段名；写入与召回共用。
    SPARSE_VECTOR_QDRANT_VECTOR_NAME: str = "sparse_text"
    # Qdrant named dense vector 字段名；写入与召回共用。
    # dense 从匿名默认向量改为 named 向量后，point 的创建不再绑定 dense（可先建只含
    # payload 的空点），dense 与 sparse 各自 update_vectors 独立写入、可并行。
    # 旧 collection（匿名默认向量）需迁移后才能被新代码召回，详见迁移脚本。
    DENSE_VECTOR_QDRANT_VECTOR_NAME: str = "dense"
    # 全局清洗规则（各 provider 复用，保证召回侧表现一致）。
    SPARSE_VECTOR_TOP_K: int = 256
    SPARSE_VECTOR_MIN_WEIGHT: float = 0.0
    # 稀疏索引外层批大小：一次从 DB 取多少 chunk 原文喂给编码器（provider 内部请求批策略各自决定）。
    SPARSE_VECTOR_BATCH_SIZE: int = 32
    # doubao_vision 稀疏 adapter 的逐条请求并发上限：多模态端点一次只融合出一个向量，
    # 必须逐条发请求，本值限制同一批文本并发发出的请求数（参照 MARKDOWN_PARSER_VISION_CONCURRENCY）。
    SPARSE_VECTOR_DOUBAO_CONCURRENCY: int = 16

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
    # MinIO 桶与 Java 端（LinkRag-Service）两桶模型对齐：
    # 私有桶 = RAG 文档 + Python 解析产物；公开桶 = 博客 + 反馈附件（Java 写入，需匿名读）。
    # 原博客专用桶 tolink-blog 已并入公开桶，MINIO_BLOG_BUCKET 配置项废弃。
    MINIO_PRIVATE_BUCKET: str = "tolink-rag-docs"
    MINIO_PUBLIC_BUCKET: str = "tolink-public"
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

    # 删除链路（LINK-55）：dataset 范围按 dataset_id 分页枚举名下文件逐个清理，
    # 每页文件数。超大数据集靠分页避免一次性载入全部 chunk_id 导致 OOM / 超时。
    DOCUMENT_DELETE_PAGE_SIZE: int = 200

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
