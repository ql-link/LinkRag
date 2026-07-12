import math
import os
from typing import List, Optional, Union

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS = frozenset({"noop", "semantic_depth_window"})
SUPPORTED_RECALL_FUSION_STRATEGIES = frozenset({"rrf", "weighted_score"})
SUPPORTED_BM25_BACKENDS = frozenset({"qdrant", "manticore"})
MARKDOWN_HEADING_LLM_CONTEXT_TOKEN_MIN = 2048
MARKDOWN_HEADING_LLM_CONTEXT_TOKEN_MAX = 262144
MARKDOWN_HEADING_LLM_MAX_OUTPUT_TOKEN_MIN = 512
MARKDOWN_HEADING_LLM_MAX_OUTPUT_TOKEN_MAX = 65536
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


def _settings_env_file() -> str:
    return os.getenv("TOLINK_ENV_FILE") or os.path.join(PROJECT_ROOT, ".env")


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
    LOG_SERVICE_NAME: str = "tolink-rag"
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
    # 融合后候选池窗口，作为 rerank 输入池；参考 RAGFlow _rerank_window ~64。
    RECALL_RESULT_LIMIT: int = 64
    # RAG pipeline 三路执行期召回深度。来源简述：
    # dense=100: Sentence Transformers retrieve-and-rerank top-100；
    # sparse=50: 参考常见 semantic ranker 的 50-candidate 窗口；
    # bm25=100: BEIR BM25 top-100 rerank。
    RECALL_DENSE_TOP_K: int = 100
    RECALL_SPARSE_TOP_K: int = 50
    RECALL_BM25_TOP_K: int = 100
    # 启用的召回路（逗号分隔）。dense/sparse query 编码按数据集绑定模型配置解析，
    # 与 bm25 并行后做融合；如需暂时回退，运维侧 set RECALL_ENABLED_SOURCES=bm25,sparse 重启。
    RECALL_ENABLED_SOURCES: str = "bm25,sparse,dense"
    # 召回融合策略：默认 RRF，weighted_score 作为可选策略在三路召回后、rerank 前生效。
    RECALL_FUSION_STRATEGY: str = "rrf"
    # RRF rank constant，影响排名贡献衰减；仅 RECALL_FUSION_STRATEGY=rrf 时使用。
    RECALL_RRF_K: int = 60
    # weighted_score 三路权重。单项允许为 0；active source 权重和为 0 在运行期拒绝。
    RECALL_FUSION_BM25_WEIGHT: float = 0.2
    RECALL_FUSION_SPARSE_WEIGHT: float = 0.3
    RECALL_FUSION_DENSE_WEIGHT: float = 0.5

    @field_validator("RECALL_FUSION_STRATEGY")
    @classmethod
    def validate_recall_fusion_strategy(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in SUPPORTED_RECALL_FUSION_STRATEGIES:
            supported = ", ".join(sorted(SUPPORTED_RECALL_FUSION_STRATEGIES))
            raise ValueError(f"RECALL_FUSION_STRATEGY must be one of: {supported}")
        return normalized

    @field_validator("RECALL_RRF_K")
    @classmethod
    def validate_recall_rrf_k(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("RECALL_RRF_K must be a positive int")
        return v

    @field_validator(
        "RECALL_FUSION_BM25_WEIGHT",
        "RECALL_FUSION_SPARSE_WEIGHT",
        "RECALL_FUSION_DENSE_WEIGHT",
    )
    @classmethod
    def validate_recall_fusion_weight(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError("recall fusion weights must be finite floats >= 0")
        return v

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
    # 解析任务编排引擎选择：True=并行 DAG（dense∥sparse∥BM25，默认）；
    # False=串行 StagePipeline（保留作稳定回退，代码不删）。两者复用同一套
    # StageServices 业务，权威状态源都是 document_parse_pipeline。出问题置 False 秒回滚。
    PARSE_USE_WORKFLOW_DAG: bool = True

    # ==========================================
    # 向量数据库配置 (Vector Store)
    # ==========================================
    # 当前仅支持 qdrant。
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
    # Deprecated: automatic orphan cleanup must never infer inactivity from a
    # shared chunk update timestamp. It remains temporarily for compatibility.
    CHUNK_INDEX_INDEXING_STALE_SECONDS: int = 900

    # 同一文档、同一索引分支的外部写入和失败清理共用 MySQL advisory lock。
    INDEX_MUTATION_LOCK_TIMEOUT_SECONDS: int = 10

    @field_validator("INDEX_MUTATION_LOCK_TIMEOUT_SECONDS")
    @classmethod
    def validate_positive_index_mutation_lock_timeout(cls, v: int, info) -> int:
        if v <= 0:
            raise ValueError(f"{info.field_name} must be a positive int")
        return v

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
    # 仅作 facade 直调兜底；RAG pipeline 使用 RECALL_SPARSE_TOP_K。
    # 调用方可任意 per-call 覆盖；运维可改 .env 全局收紧。
    SPARSE_RETRIEVAL_TOP_K: int = 10
    SPARSE_RETRIEVAL_SCORE_THRESHOLD: float = 0.0

    # Dense retrieval defaults (called by VectorStorageFacade.search_dense_chunks).
    # 与 SPARSE_RETRIEVAL_* 严格对仗：top_k=10（先广召回后精排），threshold=0.0
    # （cosine 上界 [0, 1]，不过滤、由 top_k 兜底）；阈值校准待评测 harness follow-up。
    # 仅作 facade 直调（脚本 / 评测 harness）兜底；RAG pipeline 使用 RECALL_DENSE_TOP_K。
    DENSE_RETRIEVAL_TOP_K: int = 10
    DENSE_RETRIEVAL_SCORE_THRESHOLD: float = 0.0

    # BM25 全文检索后端选择：qdrant / manticore。
    # manticore 是实验性新后端（coarse-only 原生 BM25，按 dataset 物理建表，见下方配置）。
    # 开关只影响 BM25 一路，dense / sparse 召回不受影响。
    # 详见 docs/internals/parse_task_pipeline.md。
    BM25_BACKEND: str = "qdrant"
    # 迁移期写后端（逗号分隔）。空值表示只写 BM25_BACKEND；双写示例：qdrant,manticore。
    # 读后端必须包含在写后端中，保证切换后新写入的数据一定可读。
    BM25_WRITE_BACKENDS: str = ""
    # 影子读只记录与主读的 top-k 重合度，不返回影子结果、不增加主链路成功依赖。
    BM25_SHADOW_BACKEND: Optional[str] = None
    BM25_SHADOW_SAMPLE_RATE: float = 0.0
    BM25_SHADOW_TIMEOUT_SECONDS: float = 10.0

    @field_validator("BM25_BACKEND")
    @classmethod
    def validate_bm25_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_BM25_BACKENDS:
            supported = ", ".join(sorted(SUPPORTED_BM25_BACKENDS))
            raise ValueError(f"BM25_BACKEND must be one of: {supported}")
        return normalized

    @field_validator("BM25_WRITE_BACKENDS")
    @classmethod
    def validate_bm25_write_backends(cls, value: str) -> str:
        backends = list(
            dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip())
        )
        invalid = [backend for backend in backends if backend not in SUPPORTED_BM25_BACKENDS]
        if invalid:
            raise ValueError(f"BM25_WRITE_BACKENDS contains unsupported backends: {invalid}")
        return ",".join(backends)

    @field_validator("BM25_SHADOW_BACKEND", mode="before")
    @classmethod
    def validate_bm25_shadow_backend(cls, value: object) -> str | None:
        if value is None or not str(value).strip():
            return None
        normalized = str(value).strip().lower()
        if normalized not in SUPPORTED_BM25_BACKENDS:
            raise ValueError(f"unsupported BM25_SHADOW_BACKEND: {normalized}")
        return normalized

    @field_validator("BM25_SHADOW_SAMPLE_RATE")
    @classmethod
    def validate_bm25_shadow_sample_rate(cls, value: float) -> float:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("BM25_SHADOW_SAMPLE_RATE must be between 0 and 1")
        return value

    @field_validator("BM25_SHADOW_TIMEOUT_SECONDS")
    @classmethod
    def validate_bm25_shadow_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("BM25_SHADOW_TIMEOUT_SECONDS must be finite and > 0")
        return value

    # ---- Qdrant BM25 后端（仅 BM25_BACKEND=qdrant 时生效）----
    # 以 sparse vector + Modifier.IDF 实现真 BM25（路 A：客户端补算 TF 部分，IDF 服务端补），
    # 召回用 Formula Query 表达「BM25 主分 × chunk_type 乘数」的乘法类型加权。
    # BM25 独立 collection（单 collection + payload filter 隔离租户）。
    QDRANT_BM25_COLLECTION: str = "tolink_rag_bm25"
    # BM25 专用 named sparse vector 名（带 Modifier.IDF），与 BGE-M3 sparse_text 并存。
    # 装 coarse + fine 双段 token（各占隔离 hash 维度空间，单向量单次点积即双路 BM25）。
    QDRANT_BM25_VECTOR_NAME: str = "bm25_text"
    # Formula 重排前先用 BM25 sparse 召回的候选数（prefetch）。需 > 最终 top_k，
    # 以便类型乘法能把候选内的 heading/table 抬进最终结果；过大增加重排开销。
    BM25_PREFETCH_LIMIT: int = 200
    # BM25 参数（对齐 Lucene 默认）。k1 控词频饱和强度，b 控长度归一强度。
    BM25_K1: float = 1.2
    BM25_B: float = 0.75
    # 长度归一所需的全库平均文档长度。coarse / fine 两段各自归一，故分开配。默认值用真实
    # Markdown 语料（177 篇文档）走完整生产 chunking pipeline（MarkdownParser +
    # CandidateBoundaryChunker + 默认 noop stage two）产出 1951 个真实 chunk 校准得出
    # （mean coarse=180.6 / fine=188.5，实测中文技术文档 fine 仅略大于 coarse，并非数量级
    # 差异）；仍是单一语料来源、非全量生产数据，规模更大时建议用
    # scripts/dev/calibrate_bm25_avgdl.py --from-db 重新校准。avgdl 写入时冻结，变更只对
    # 之后写入的 chunk 生效，存量需重灌才完全对齐——见 docs/internals/parse_task_pipeline.md。
    BM25_AVGDL: float = 181.0
    BM25_AVGDL_FINE: float = 188.0
    # query 侧 coarse 段权重：query 词在
    # coarse 段 value=该值、fine 段 value=1，点积即 coarse_boost×coarse_BM25 + fine_BM25。
    BM25_COARSE_BOOST: float = 2.0
    # 乘法类型权重（Qdrant Formula 用）：命中该 chunk_type 时 BM25 主分 ×倍数。
    # 建议从温和权重（1.1~1.5）起步，
    # 再用召回评测扫参；别从 ×3 开始（会变成「类型碾压相关性」）。取值 <1.0 表示降权
    # （见 store._build_formula：乘数 = 1.0 + Σ(mult−1)·[chunk_type 命中]）。
    # heading/list/paragraph/blockquote 在自动链路里几乎不
    # 可达（splitter 正文分片必然收敛成 mixed），不配权重；table/code_block/math_block/image
    # 走 derived_element 稳定单独成块，front_matter 走 isolated source chunk 稳定单独成块，
    # 这几种才是实际打得到的类型。
    BM25_TYPE_MULT: dict[str, float] = Field(
        default_factory=lambda: {
            "table": 1.2,
            "code_block": 1.15,
            "math_block": 1.15,
            "image": 1.1,
            "front_matter": 0.7,
        }
    )

    # ---- Manticore BM25 后端（仅 BM25_BACKEND=manticore 时生效）----
    # 用原生 bm25a(k1, b) 对 coarse 预分词字段计分。真实召回评测表明，把 fine 字段混进
    # 同一 BM25F 分数会明显拉低中文召回，因此 v2 只保留 coarse；fine 后续作为独立召回路。
    # 按 dataset 物理建表（一个 dataset 一张表，表名 f"{prefix}_{dataset_id}"），IDF 与
    # avgdl 天然只统计这个 dataset 自己的语料，不需要额外的 tenant filter 或旁路统计基础
    # 设施；相应地也不复用 Qdrant 那套 BucketRouter（那是按 user 哈希分桶，这里是按
    # dataset 精确建表，两回事）。avgdl 走 Manticore 动态计算（index_field_lengths，
    # 每张表天然只含一个 dataset 的文档，动态平均值等价于"按 dataset 计算"，不需要
    # bm25a() 的常量覆盖参数）；k1/b/type_mult 复用上面 BM25_* 通用配置，coarse_boost
    # 只用于 Qdrant 双段编码，不参与 Manticore v2 coarse-only 计分。
    # 中文字符必须显式加进 charset_table，Manticore 默认字符集表不认 CJK，会把中文词
    # 当分隔符丢弃（实测踩过：charset_table 不配置时，中文 chunk 基本等于没索引）。
    MANTICORE_HOST: str = "localhost"
    # SQL 协议端口（MySQL wire protocol），不是 HTTP(S) 的 9308。
    MANTICORE_PORT: int = 9306
    # 单条 SQL 操作截止时间；不再只充当 connect_timeout。
    MANTICORE_TIMEOUT_SECONDS: float = 10.0
    MANTICORE_CONNECT_TIMEOUT_SECONDS: float = 5.0
    MANTICORE_POOL_ACQUIRE_TIMEOUT_SECONDS: float = 5.0
    MANTICORE_POOL_MINSIZE: int = 1
    MANTICORE_POOL_MAXSIZE: int = 10
    MANTICORE_POOL_RECYCLE_SECONDS: int = 300
    MANTICORE_WRITE_BATCH_SIZE: int = 500
    MANTICORE_WRITE_BATCH_BYTES: int = 5 * 1024 * 1024
    # 单个 coarse 预分词字段的 UTF-8 字节上限，提前拒绝异常巨型 chunk，避免撑爆 SQL 包和内存。
    MANTICORE_MAX_DOCUMENT_BYTES: int = 128 * 1024
    # Manticore 开启鉴权时使用；本地默认保持空账号/密码。
    MANTICORE_USER: str = ""
    MANTICORE_PASSWORD: str = ""
    # 跨主机生产连接应启用 TLS；CA 校验服务端，cert/key 可选用于双向 TLS。
    MANTICORE_SSL_ENABLED: bool = False
    MANTICORE_SSL_CA: Optional[str] = None
    MANTICORE_SSL_CERT: Optional[str] = None
    MANTICORE_SSL_KEY: Optional[str] = None
    MANTICORE_SSL_CHECK_HOSTNAME: bool = True
    # 表名前缀：真实表名 = f"{MANTICORE_BM25_TABLE_PREFIX}_{dataset_id}"。
    # v2 是 coarse-only + 显式 IDF 语义的索引代际，避免旧 BM25F 表被静默复用。
    MANTICORE_BM25_TABLE_PREFIX: str = "bm25_ds_v2"

    @field_validator(
        "MANTICORE_TIMEOUT_SECONDS",
        "MANTICORE_CONNECT_TIMEOUT_SECONDS",
        "MANTICORE_POOL_ACQUIRE_TIMEOUT_SECONDS",
    )
    @classmethod
    def validate_manticore_positive_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Manticore timeout values must be finite and > 0")
        return value

    @model_validator(mode="after")
    def validate_manticore_pool_and_batch(self) -> "Settings":
        write_backends = (
            set(self.BM25_WRITE_BACKENDS.split(","))
            if self.BM25_WRITE_BACKENDS
            else {self.BM25_BACKEND}
        )
        if self.BM25_BACKEND not in write_backends:
            raise ValueError("BM25_BACKEND must be included in BM25_WRITE_BACKENDS")
        if self.BM25_SHADOW_BACKEND is not None:
            if self.BM25_SHADOW_BACKEND == self.BM25_BACKEND:
                raise ValueError("BM25_SHADOW_BACKEND must differ from BM25_BACKEND")
            if self.BM25_SHADOW_BACKEND not in write_backends:
                raise ValueError("BM25_SHADOW_BACKEND must be included in BM25_WRITE_BACKENDS")
        if self.MANTICORE_POOL_MINSIZE < 0:
            raise ValueError("MANTICORE_POOL_MINSIZE must be >= 0")
        if self.MANTICORE_POOL_MAXSIZE <= 0:
            raise ValueError("MANTICORE_POOL_MAXSIZE must be > 0")
        if self.MANTICORE_POOL_MINSIZE > self.MANTICORE_POOL_MAXSIZE:
            raise ValueError("MANTICORE_POOL_MINSIZE must be <= MANTICORE_POOL_MAXSIZE")
        if self.MANTICORE_POOL_RECYCLE_SECONDS <= 0:
            raise ValueError("MANTICORE_POOL_RECYCLE_SECONDS must be > 0")
        if self.MANTICORE_WRITE_BATCH_SIZE <= 0:
            raise ValueError("MANTICORE_WRITE_BATCH_SIZE must be > 0")
        if self.MANTICORE_WRITE_BATCH_BYTES <= 0:
            raise ValueError("MANTICORE_WRITE_BATCH_BYTES must be > 0")
        if self.MANTICORE_MAX_DOCUMENT_BYTES <= 0:
            raise ValueError("MANTICORE_MAX_DOCUMENT_BYTES must be > 0")
        if self.MANTICORE_MAX_DOCUMENT_BYTES > self.MANTICORE_WRITE_BATCH_BYTES:
            raise ValueError("MANTICORE_MAX_DOCUMENT_BYTES must be <= MANTICORE_WRITE_BATCH_BYTES")
        if bool(self.MANTICORE_SSL_CERT) != bool(self.MANTICORE_SSL_KEY):
            raise ValueError("MANTICORE_SSL_CERT and MANTICORE_SSL_KEY must be configured together")
        return self

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
    # MinIO 三桶模型（与 Java 端 LinkRag-Service 对齐）：
    # · 原文件桶（RAW）  = 用户上传的源文件，由 Java 写入，Python 只读；
    # · 私有桶（DOCS）   = Python 解析产物（Markdown + 图片），不对外匿名读；
    # · 公开桶（PUBLIC） = 博客 + 反馈附件，Java 写入，需匿名读。
    # 原博客专用桶 tolink-blog 已并入公开桶，MINIO_BLOG_BUCKET 配置项废弃。
    MINIO_RAW_BUCKET: str = "tolink-rag-raw"
    MINIO_PRIVATE_BUCKET: str = "tolink-rag-docs"
    MINIO_PUBLIC_BUCKET: str = "tolink-public"
    MINIO_USE_SSL: bool = False
    # Optional external/public HTTP(S) endpoint used only when generating object URLs
    # for cloud parsers and browser-facing resources. S3 SDK traffic still uses
    # MINIO_ENDPOINT.
    MINIO_PUBLIC_ENDPOINT: Optional[str] = None
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
    # 公网/跨机房部署时建议调大这两个值（broker 端 group.max.session.timeout.ms 须 ≥ 此值）
    KAFKA_SESSION_TIMEOUT_MS: int = 45000
    KAFKA_HEARTBEAT_INTERVAL_MS: int = 15000
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
        env_file=_settings_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
