# Configuration

所有运行时配置通过 [src/config.py](../../src/config.py) 的 `Settings` 加载，源头是 `.env` 文件。本文按域解读 [.env.example](../../.env.example) 中的配置项，标注**必填**与典型值。

> 不要硬编码密钥，不要把真实 `.env` 提交到仓库。

## 配置分组速览

| 分组 | 关键变量前缀 | 何时关心 |
| --- | --- | --- |
| 应用 | `APP_*`, `LOG_LEVEL` | 始终 |
| 数据库 | `DB_*` | 始终 |
| 缓存 | `REDIS_*` | 始终 |
| 安全 | `API_KEY_ENCRYPTION_SECRET` | 始终（必须与 Java 管理端一致） |
| 系统级 LLM | `SYSTEM_LLM_*` | 始终（兜底 LLM 调用） |
| Markdown 增强 | `MARKDOWN_PARSER_*` | 调整解析增强行为时 |
| 分块策略 | `CHUNKING_*` | 调整分块参数时 |
| 向量存储 | `VECTOR_STORE_TYPE`, `QDRANT_*`, `ES_*`, `CHUNK_INDEX_*`, `SPARSE_VECTOR_*` | 始终（选择 Qdrant 或 ES，并配置稀疏向量） |
| 对象存储 | `STORAGE_TYPE`, `MINIO_*`, `LOCAL_DOCS_PATH` | 始终 |
| 解析临时目录 | `PARSE_TEMP_DIR` | 始终（流式下载落盘目录） |
| PDF 解析 | `PDF_PARSER_*`, `MINERU_*`, `DOCLING_*` | 处理 PDF 时 |
| MQ | `MQ_VENDOR`, `KAFKA_*`, `RABBITMQ_*`, `*_TOPIC` | 始终 |
| CORS | `CORS_ORIGINS` | 前端跨域时 |

## 必填配置

启动前必须设置以下项（无默认或默认值不可用）：

| 变量 | 说明 |
| --- | --- |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接 |
| `REDIS_HOST` / `REDIS_PORT` | Redis 连接 |
| `API_KEY_ENCRYPTION_SECRET` | API Key 加密 Secret，必须与 Java 管理端一致；64 位 hex，解码后 32 字节，用于 AES-256-GCM |
| `SYSTEM_LLM_PROVIDER` / `SYSTEM_LLM_API_KEY` / `SYSTEM_LLM_API_BASE` | 系统级兜底 LLM |
| `KAFKA_BOOTSTRAP_SERVERS` 等（若 `MQ_VENDOR=kafka`） | Kafka 接入信息 |
| `MINIO_*`（若 `STORAGE_TYPE=minio`） | 对象存储凭据 |
| `QDRANT_HOST` 或 `ES_HOST`（取决于 `VECTOR_STORE_TYPE`） | 向量存储 |

## 关键开关

| 开关 | 默认 | 含义 |
| --- | --- | --- |
| `MQ_VENDOR` | `kafka` | 切换 Kafka / RabbitMQ |
| `VECTOR_STORE_TYPE` | `qdrant` | 切换 Qdrant / Elasticsearch |
| `SPARSE_VECTOR_ENABLED` | `true` | 是否在向量化阶段同步生成 BGE-M3 稀疏向量；关闭后保持旧 dense-only 语义 |
| `STORAGE_TYPE` | `minio` | 切换 MinIO / 本地存储 |
| `PARSE_TEMP_DIR` | `/tmp/tolink-rag-parse` | 解析任务源文件临时落盘目录。流式下载在此创建临时文件；解析为 markdown 后立即清理；worker 启动时清空兜底。不预设最小容量，沿用部署机系统盘大小；写满会归类为 `TEMP_DISK_FULL` 错误码。扩消费者时容量需要 ≥ 单文件上限 × 并发数 |
| `PDF_PARSER_BACKEND` | `mineru` | PDF 解析后端：`auto` / `mineru` / `opendataloader` / `naive` |
| `PDF_PARSER_FALLBACKS` | 空 | 逗号分隔回退链，空表示不回退 |
| `PDF_IMAGE_UPLOAD_ASYNC` | `true` | PDF 图片是否异步上传，关闭后主链路同步等待 |
| `INIT_KAFKA_TOPICS_ON_STARTUP` | `false` | 应用启动时是否自动建 topic，生产建议保持 false |
| `TOLINK_RUN_REAL_VECTOR_STORAGE_TESTS` | `false` | 是否运行真实 MySQL+Qdrant 集成测试 |
| `MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT` | `true` | 是否启用表格 LLM 增强 |
| `MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT` | `true` | 是否启用图片 LLM 增强 |
| `MARKDOWN_PARSER_VISION_CONCURRENCY` | `24` | 图片视觉增强最大并发数，可降为 `16` / `8` / `1` 控制限流风险 |
| `CHUNKING_ENABLE_ADVANCED_PIPELINE` | `true` | 是否启用进阶分块流水线 |

> 注：ES 入库失败即终态，无 ES 内部自动重试配置。原 `ES_INDEXING_MAX_RETRY` 已移除（用户侧重试由 `document_parse_pipeline.retry_count` 记录，触发路径待后续需求接线）。

## MQ 失败兜底（重试 + 死信）

消费框架对业务回调异常做有限退避重试 + 死信兜底；详细行为见 [mq.md §4.1](../internals/mq.md#41-失败兜底重试--死信)。

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `MQ_MAX_RETRIES` | `3` | 业务回调抛 `RetriableError` 子类时最多重试次数；超限后进死信 |
| `MQ_RETRY_BACKOFF_SECONDS` | `1.0` | 重试之间固定退避秒数；单条消息最长阻塞 ≈ 此值 × `MQ_MAX_RETRIES` |
| `MQ_DLQ_SUFFIX` | `.DLT` | 死信目标命名后缀（原 topic / queue + 后缀） |

> 死信兜底恒启用，不提供关闭开关。死信目标在应用启动时由 `ensure_topics()`（Kafka）或 `RabbitMQReceiver.start()`（RabbitMQ）幂等创建。

## MQ Topic 命名

应用启动时需要这些 topic 存在或被自动创建（见 [mq_integration.md](../api/mq_contracts.md)）：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `PARSE_TASK_TOPIC` | `tolink-document-pares` | 解析任务入队 |
| `PARSE_RESULT_TOPIC` | `tolink.rag.parse_result` | 解析终态通知 |

> 注意默认值中的 `pares`（非 `parse`）是历史遗留，业务方对接时以实际配置为准。

## 分块参数建议

| 变量 | 默认 | 调整方向 |
| --- | --- | --- |
| `CHUNKING_MIN_CHUNK_TOKENS` | 150 | 短文档可减小 |
| `CHUNKING_MAX_CHUNK_TOKENS` | 512 | 长上下文模型可加大 |
| `CHUNKING_OVERLAP_TOKENS` | 64 | 提升召回时加大 |
| `CHUNKING_HEADING_BREAK_LEVEL` | 3 | 提升结构敏感性时减小 |
| `CHUNKING_SEMANTIC_PERCENTILE` | 95 | 调整语义边界严格度 |
| `CHUNKING_SEMANTIC_UNIT` | `sentence` | 语义相似度计算粒度：`sentence` / `paragraph` |
| `CHUNKING_EMBED_BATCH_SIZE` | 32 | 受向量服务并发上限约束 |

详细分块策略见 [chunking.md](../internals/chunking.md)。

## 稀疏向量配置

稀疏向量首期使用本地 `BAAI/bge-m3`，与稠密向量在同一个 chunk 向量化阶段执行。模型输入是 chunk 原文，不使用 ES 分词结果。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SPARSE_VECTOR_ENABLED` | `true` | 是否启用稀疏向量；关闭后只执行旧稠密向量流程 |
| `SPARSE_VECTOR_PROVIDER` | `bge_m3` | 稀疏向量提供方；首期仅支持 `bge_m3` |
| `SPARSE_VECTOR_MODEL_NAME` | `BAAI/bge-m3` | Hugging Face 模型名或本地模型目录 |
| `SPARSE_VECTOR_MODEL_CACHE_DIR` | 空 | 模型缓存目录，空值使用默认 Hugging Face 缓存 |
| `SPARSE_VECTOR_LOCAL_FILES_ONLY` | `false` | 是否只使用本地已有模型文件 |
| `SPARSE_VECTOR_DEVICE` | `auto` | 推理设备：`auto` / `cpu` / `cuda` / `cuda:n`；CPU 固定 fp32，CUDA 固定 fp16 |
| `SPARSE_VECTOR_BATCH_SIZE` | `12` | BGE-M3 稀疏编码批大小 |
| `SPARSE_VECTOR_MAX_LENGTH` | `8192` | 输入文本最大 token 长度 |
| `SPARSE_VECTOR_QDRANT_VECTOR_NAME` | `sparse_text` | Qdrant named sparse vector 名称 |
| `SPARSE_VECTOR_TOP_K` | `256` | 每条稀疏向量最多保留的非零 token 数；`0` 表示不截断 |
| `SPARSE_VECTOR_MIN_WEIGHT` | `0.0` | 过滤低权重 token 的阈值 |
| `TOLINK_RUN_REAL_SPARSE_VECTOR_TESTS` | `false` | 是否运行真实 BGE-M3 smoke 测试 |

不再提供 `SPARSE_VECTOR_USE_FP16` 配置。推理精度只由 `SPARSE_VECTOR_DEVICE` 决定：CPU 使用 fp32，CUDA 使用 fp16。

## 稀疏向量配置

稀疏向量首期使用本地 `BAAI/bge-m3`，与稠密向量在同一个 chunk 向量化阶段执行。模型输入是 chunk 原文，不使用 ES 分词结果。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SPARSE_VECTOR_ENABLED` | `true` | 是否启用稀疏向量；关闭后只执行旧稠密向量流程 |
| `SPARSE_VECTOR_PROVIDER` | `bge_m3` | 稀疏向量提供方；首期仅支持 `bge_m3` |
| `SPARSE_VECTOR_MODEL_NAME` | `BAAI/bge-m3` | Hugging Face 模型名或本地模型目录 |
| `SPARSE_VECTOR_MODEL_CACHE_DIR` | 空 | 模型缓存目录，空值使用默认 Hugging Face 缓存 |
| `SPARSE_VECTOR_LOCAL_FILES_ONLY` | `false` | 是否只使用本地已有模型文件 |
| `SPARSE_VECTOR_DEVICE` | `auto` | 推理设备：`auto` / `cpu` / `cuda` / `cuda:n`；CPU 固定 fp32，CUDA 固定 fp16 |
| `SPARSE_VECTOR_BATCH_SIZE` | `12` | BGE-M3 稀疏编码批大小 |
| `SPARSE_VECTOR_MAX_LENGTH` | `8192` | 输入文本最大 token 长度 |
| `SPARSE_VECTOR_QDRANT_VECTOR_NAME` | `sparse_text` | Qdrant named sparse vector 名称 |
| `SPARSE_VECTOR_TOP_K` | `256` | 每条稀疏向量最多保留的非零 token 数；`0` 表示不截断 |
| `SPARSE_VECTOR_MIN_WEIGHT` | `0.0` | 过滤低权重 token 的阈值 |
| `TOLINK_RUN_REAL_SPARSE_VECTOR_TESTS` | `false` | 是否运行真实 BGE-M3 smoke 测试 |

不再提供 `SPARSE_VECTOR_USE_FP16` 配置。推理精度只由 `SPARSE_VECTOR_DEVICE` 决定：CPU 使用 fp32，CUDA 使用 fp16。

## 内部召回 API 配置

内部多路召回 SSE 接口 `POST /api/v1/internal/recall/stream` 的配置。详见
[docs/internals/recall_http_api.md](../internals/recall_http_api.md)。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RECALL_INTERNAL_AUTH_ENABLED` | `true` | 是否启用内部 JWT 校验；**生产必须为 true** |
| `RECALL_INTERNAL_JWT_ISSUER` | `tolink-java` | 期望的 JWT `iss` |
| `RECALL_INTERNAL_JWT_AUDIENCE` | `tolink-rag` | 期望的 JWT `aud` |
| `RECALL_INTERNAL_JWT_SCOPE` | `recall:execute` | 期望的 JWT `scope` |
| `RECALL_INTERNAL_JWT_SECRET` | 本地联调占位值 | HS256 共享密钥；Java 签发端与 Python 验签端必须一致，**生产务必用环境变量覆盖为强随机值** |
| `RECALL_STREAM_TIMEOUT_MS` | `60000` | 单次召回最大执行时间（毫秒）；超时以 SSE `error` RECALL_TIMEOUT 终止 |
| `RECALL_STRICT_DEFAULT` | `false` | pipeline 严格模式默认；false=宽松，允许单路失败降级 |
| `RECALL_RESULT_LIMIT` | `20` | 服务端固定返回候选上限（同时作为各路执行期 `top_k`）|
| `RECALL_ENABLED_SOURCES` | `bm25,sparse,dense` | 启用的召回路（逗号分隔）。本期默认开启三路；运维侧可显式 set `bm25,sparse` 暂时回退到 dev 旧行为；未登记的 source 出现在配置中装配期 `ValueError` |
| `SPARSE_RETRIEVAL_TOP_K` | `10` | sparse 召回 facade 直调时的兜底 top_k；pipeline 路径下被 `RECALL_RESULT_LIMIT` 覆盖 |
| `SPARSE_RETRIEVAL_SCORE_THRESHOLD` | `0.0` | sparse 召回默认 score 阈值（0.0 = 不过滤；详见 [vectorization.md §9.4](../internals/vectorization.md)） |
| `DENSE_RETRIEVAL_TOP_K` | `10` | dense 召回 facade 直调时的兜底 top_k；pipeline 路径下被 `RECALL_RESULT_LIMIT` 覆盖 |
| `DENSE_RETRIEVAL_SCORE_THRESHOLD` | `0.0` | dense 召回默认 score 阈值（cosine 上界 [0, 1]，0.0 = 不过滤；facade 入口校验 `> 1.0` 早死） |

### 对外直连召回 SSE 配置（LINK-40）

对外直连召回 SSE 接口 `POST /api/v1/recall/stream` 的配置。前端凭 Java 签发的短期
session token 直连，**独立密钥**与内部端点隔离。详见
[recall_http_api.md](../internals/recall_http_api.md)。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RECALL_SESSION_AUTH_ENABLED` | `true` | 是否启用 session token 验签；**生产必须为 true** |
| `RECALL_SESSION_JWT_ISSUER` | `tolink-java` | 期望的 session JWT `iss` |
| `RECALL_SESSION_JWT_AUDIENCE` | `tolink-rag-frontend` | 期望的 session JWT `aud`（与内部端点 `tolink-rag` 区分）|
| `RECALL_SESSION_JWT_SCOPE` | `recall:stream` | 期望的 session JWT `scope` |
| `RECALL_SESSION_JWT_SECRET` | 本地联调占位值 | **独立** HS256 密钥，与 `RECALL_INTERNAL_JWT_SECRET` 物理隔离、可单独轮转；**生产务必覆盖** |
| `RECALL_SESSION_MAX_CONCURRENT` | `3` | 单用户最大并发召回流数；token 短期可复用，此为资源滥用主闸门，超限返回 `429` |
| `CORS_ORIGINS` | `["*"]` | **生产对外环境必须收敛为前端可信域名清单**（不可用 `*`，否则带 `Authorization` 头的跨域预检失败）|

> token 短期可复用：Python 只校验 `exp`（建议 Java 签发 30s，仅够建连），不做一次性 /
> 防重放 / 撤销；连上后流的存活由 `RECALL_STREAM_TIMEOUT_MS` 控制。并发计数依赖 Redis，
> Redis 不可用时 fail-open（放行，因限流是资源保护非鉴权）。

### 远程 BGE-M3 推理服务（`remote_bge_m3` provider）

`SPARSE_VECTOR_PROVIDER` 除已有 `bge_m3`（本地）/ `bge_m3_http`（早期 bge-m3-server）
外，新增 `remote_bge_m3`：对接独立部署的 ``bge-m3-service``，单次 `/encode` 同时
拿到 dense（1024 维）+ sparse lexical weights，并在客户端做超时 + 重试。详见
[docs/internals/vectorization.md §6.6](../internals/vectorization.md)。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BGE_M3_SERVICE_URL` | 空 | ``bge-m3-service`` 根地址（如 `http://127.0.0.1:7997`），尾部 `/` 会被忽略；provider=`remote_bge_m3` 时必填 |
| `BGE_M3_TIMEOUT_SECONDS` | `30.0` | 单次 `/encode` 请求超时（秒） |
| `BGE_M3_MAX_RETRIES` | `3` | 网络错误 / 5xx 的重试次数（不含首次请求；`0` = 不重试；4xx 直接抛错不重试） |

## 配置加载与覆盖

- `.env` 由 [src/config.py](../../src/config.py) 通过 `Settings`（pydantic-settings）加载。
- 运行时环境变量**优先级高于** `.env`（部署时通过容器环境变量注入即可覆盖）。
- 新增配置必须在 `Settings` 中声明，并在 [.env.example](../../.env.example) 补充示例值。

## 相关文档

- 部署步骤：[deployment.md](deploy.md)
- MQ 集成：[mq_integration.md](../api/mq_contracts.md)
