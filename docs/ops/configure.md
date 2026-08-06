# Configuration

所有运行时配置通过 [src/config.py](../../src/config.py) 的 `Settings` 加载，默认读取项目根目录 `.env`；也可以用 `TOLINK_ENV_FILE=/path/to/env` 显式指定配置文件。若同目录存在 `<配置文件>.local`，加载器会在基础配置之后自动叠加该本机文件，例如 `.env.development` + `.env.development.local`，或 `.env.production` + `.env.production.local`。基础配置可以进入 Git，本机覆盖文件只保存账号、密码、JWT 和 API Key，必须保持忽略。Docker 部署层按顺序加载 `RAG_ENV_FILE` 与 `RAG_SECRET_ENV_FILE`，后者覆盖前者；单服务生产部署默认使用 `.env.production` + `.env.production.local`。不要把环境 IP 写进代码。本文按域解读 [.env.example](../../.env.example) 中的配置项，标注**必填**与典型值。

> 不要硬编码密钥，不要把真实 `.env` 提交到仓库。

## 配置分组速览

| 分组 | 关键变量前缀 | 何时关心 |
| --- | --- | --- |
| 应用 | `APP_*`, `LOG_LEVEL`, `LOG_*` | 始终 |
| 数据库 | `DB_*` | 始终 |
| 缓存 | `REDIS_*` | 始终 |
| 安全 | `API_KEY_ENCRYPTION_SECRET` | 始终（必须与 Java 管理端一致） |
| LLM runtime cache | `LLM_RUNTIME_CACHE_*` | 可选缓存旁路；MySQL 仍是事实源 |
| Dataset 原始快照缓存 | `DATASET_PARSE_CONFIG_CACHE_*` | Java/Python 共用；仅在 Java CDC health READY 后开启 |
| Markdown 增强 | `MARKDOWN_PARSER_*` | 调整解析增强行为时 |
| 分块策略 | `CHUNKING_*` | 调整分块参数时 |
| 流程编排 | `WORKFLOW_*` | 使用轻量流程编排引擎时 |
| 向量存储 | `VECTOR_STORE_TYPE`, `QDRANT_*`, `CHUNK_INDEX_*`, `SPARSE_VECTOR_*` | 始终（当前固定使用 Qdrant） |
| 索引写入互斥 | `INDEX_MUTATION_*` | 调整写入失败同步清理的锁等待时 |
| 对象存储 | `STORAGE_TYPE`, `MINIO_*` | 始终 |
| 解析临时目录 | `PARSE_TEMP_DIR` | 始终（流式下载落盘目录） |
| PDF 解析 | `PDF_PARSER_*`, `MINERU_*` | 处理 PDF 时 |
| MQ | `MQ_VENDOR`, `KAFKA_*`, `RABBITMQ_*`, `*_TOPIC` | 始终 |
| CORS | `CORS_ORIGINS` | 前端跨域时 |

## 必填配置

启动前必须设置以下项（无默认或默认值不可用）：

| 变量 | 说明 |
| --- | --- |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接 |
| `REDIS_HOST` / `REDIS_PORT` | Redis 连接 |
| `API_KEY_ENCRYPTION_SECRET` | API Key 加密 Secret，必须与 Java 管理端一致；64 位 hex，解码后 32 字节，用于 AES-256-GCM |
| `LLM_RUNTIME_CACHE_ENABLED` / `LLM_RUNTIME_CACHE_TTL_SECONDS` | 全局 `config_id` runtime cache 开关与 TTL |
| `DATASET_PARSE_CONFIG_CACHE_ENABLED` / `DATASET_PARSE_CONFIG_CACHE_TTL_SECONDS` | `dataset_parse_config` 共享原始快照开关与 TTL；默认关闭，正常值默认 7 天 |
| `DATASET_PARSE_CONFIG_NEGATIVE_TTL_SECONDS` | 数据集当前没有配置行时的 NOT_FOUND TTL，默认 60 秒 |
| `RABBITMQ_URL`（若 `MQ_VENDOR=rabbitmq`） | RabbitMQ AMQP URL，生产使用独立用户与 vhost |
| `MINIO_*`（若 `STORAGE_TYPE=minio`） | 对象存储凭据 |
| `MINIO_RAW_BUCKET`（若 `STORAGE_TYPE=minio`） | 原文件桶：用户上传的源文件，由 Java 写入，Python 只读；默认 `tolink-rag-raw`，需在 MinIO 控制台预建 |
| `QDRANT_URL` / `QDRANT_HOST` / `QDRANT_PORT` / `QDRANT_HTTPS` / `QDRANT_API_KEY` | 向量存储地址、显式协议与认证；优先使用带 scheme 的 `QDRANT_URL`，`QDRANT_HTTPS` 需与服务端 TLS 状态一致，非空 API key 不代表自动启用 HTTPS |

## 关键开关

| 开关 | 默认 | 含义 |
| --- | --- | --- |
| `MQ_VENDOR` | `rabbitmq` | 当前默认 RabbitMQ；`kafka` 仅保留回滚兼容 |
| `VECTOR_STORE_TYPE` | `qdrant` | 当前唯一支持 Qdrant；readiness 据此决定是否执行 Qdrant 探测 |
| `SPARSE_VECTOR_ENABLED` | `true` | 是否在向量化阶段同步生成稀疏向量；关闭后保持旧 dense-only 语义 |
| `STORAGE_TYPE` | `minio` | 对象存储实现；当前可用实现为 MinIO，OSS 适配器仍为占位 |
| `MINIO_RAW_BUCKET` | `tolink-rag-raw` | 用户上传原文件桶，由 Java 写入；Python 解析时从此桶下载源文件，不写入。需在 MinIO 控制台预先创建 |
| `MINIO_PUBLIC_ENDPOINT` | 空 | 可选公网对象访问入口；为空时复用 `MINIO_ENDPOINT`。用于给 MinerU 等云端解析器生成可访问 URL，SDK 读写仍走 `MINIO_ENDPOINT` |
| `PARSE_TEMP_DIR` | `/tmp/tolink-rag-parse` | 解析任务源文件临时落盘目录。流式下载在此创建临时文件；解析为 markdown 后立即清理；worker 启动时清空兜底。不预设最小容量，沿用部署机系统盘大小；写满会归类为 `TEMP_DISK_FULL` 错误码。扩消费者时容量需要 ≥ 单文件上限 × 并发数 |
| `PDF_PARSER_BACKEND` | `mineru` | PDF 解析后端：`auto` / `mineru` / `opendataloader` / `naive` |
| `PDF_PARSER_FALLBACKS` | 空 | 逗号分隔回退链，空表示不回退 |
| `PDF_IMAGE_UPLOAD_ASYNC` | `true` | PDF 图片是否异步上传，关闭后主链路同步等待 |
| `INIT_KAFKA_TOPICS_ON_STARTUP` | `false` | 应用启动时是否自动建 topic，生产建议保持 false |
| `TOLINK_RUN_REAL_VECTOR_STORAGE_TESTS` | `false` | 是否运行真实 MySQL+Qdrant 集成测试 |
| `MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT` | `true` | 是否启用表格 LLM 增强 |
| `MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT` | `true` | 是否启用图片 LLM 增强 |
| `MARKDOWN_PARSER_VISION_CONCURRENCY` | `24` | 图片视觉增强最大并发数，可降为 `16` / `8` / `1` 控制限流风险 |
| `RAW_MARKDOWN_IMAGE_MAX_BYTES` | `20971520` | Java v1 RAW Markdown 单张图片读取上限，必须大于0且部署值不得高于 Java 上传侧上限 |
| `RAW_MARKDOWN_IMAGE_BATCH_SIZE` | `4` | RAW 图片 Vision 批大小，范围 `1..20`；每批结束释放图片字节 |
| `RAW_MARKDOWN_IMAGE_DOWNLOAD_CONCURRENCY` | `4` | RAW 图片流式下载并发，范围 `1..20` |
| `MARKDOWN_PARSER_ENABLE_HEADING_HIERARCHY` | `false` | 是否启用 Markdown 标题层级后处理；默认关闭；开启且门禁命中时按用户默认 → LinkRag 系统默认预设解析 `CHAT` 模型 |
| `MARKDOWN_PARSER_HEADING_NO_HEADING_MIN_TOKENS` | `512` | 全文无 heading 时进入标题生成门禁的最小 token 数 |
| `MARKDOWN_PARSER_HEADING_FLAT_MIN_HEADINGS` | `5` | 全篇只有同级 heading 时进入扁平标题门禁的最小 heading 数；下限为 `5` |
| `MARKDOWN_PARSER_HEADING_SPARSE_TOKENS_PER_HEADING` | `1536` | 多级 heading 但数量太少时的密度阈值；下限为 `1024` |
| `MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET` | `65536` | 标题生成器单次输入 token 预算；预算内发送带行号全文，超预算时发送压缩结构摘要；允许范围 `2048` - `262144` |
| `MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS` | `4096` | 标题生成器输出插入计划的 token 上限；允许范围 `512` - `65536` |
| `CHUNKING_STAGE_ONE_ALGORITHM` | `candidate_boundary` | splitter 第一阶段算法名；当前支持 `candidate_boundary`，未知值启动失败 |
| `CHUNKING_STAGE_TWO_ALGORITHM` | `noop` | splitter 第二阶段算法名；支持 `noop` / `semantic_depth_window`，未知值启动失败 |
| `WORKFLOW_MAX_CONCURRENCY` | `8` | 轻量流程编排引擎单轮 run 中同时运行的节点数上限 |

> splitter 不再保留 `CHUNKING_ENABLE_ADVANCED_PIPELINE` 布尔开关，也不再回退到旧规则分片器。第二阶段默认使用 `noop`；`noop` 只做结构透传，不保证 final chunk token 数不超过 `CHUNKING_HARD_MAX_TOKENS`。如需启用 TextTiling depth valley 语义细分与 hard max 保障，显式配置 `CHUNKING_STAGE_TWO_ALGORITHM=semantic_depth_window`。

> 注：当前生产不再部署 Elasticsearch，Qdrant BM25 也已下线。BM25 固定由 Manticore
> 按 dataset 物理建表并使用 coarse-only 原生 `bm25a` 承载。`docker-compose.yml`
> 提供 Manticore 服务，SQL 协议端口 `MANTICORE_PORT` 默认 `9306`。

BM25 配置：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BM25_K1` / `BM25_B` | `1.2` / `0.75` | Manticore `bm25a` 参数 |
| `BM25_TYPE_MULT` | 见环境样例 | chunk 类型乘法重排权重 |
| `MANTICORE_POOL_MAXSIZE` | `10` | 单进程最大 SQL 连接；服务端连接上限需覆盖副本数乘以该值及迁移任务 |
| `MANTICORE_MAX_DOCUMENT_BYTES` | `131072` | 单 chunk 的 coarse 预分词 UTF-8 字节上限 |
| `MANTICORE_SSL_ENABLED` | `false` | 跨主机生产连接应开启并配置 CA；cert/key 成对配置时启用双向 TLS |

## 日志

日志系统基于 Loguru，统一在 [src/observability/logging.py](../../src/observability/logging.py) 配置。运行时**始终输出到 stdout**（容器 / 本地通用）；开启文件落盘后，额外按 Java 端约定写入按日期归档的 JSON Lines 本地文件。

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | 控制台与全量日志文件的级别下限；ERROR 文件固定只收 ERROR 及以上，不受此项影响 |
| `LOG_FILE_ENABLED` | `true` | 是否写本地文件。纯容器环境若靠 `docker logs` 采集，可设 `false` 只保留 stdout |
| `LOG_DIR` | `logs` | 日志根目录；相对路径会解析到项目根目录下，避免从 `src/` 等不同目录启动时生成多份日志 |
| `LOG_SERVICE_NAME` | `tolink-rag` | 日志服务名与文件名前缀；Java 服务使用 `tolink-service`，Python RAG 服务使用 `tolink-rag` |
| `LOG_RETENTION_DAYS` | `7` | 日志保留天数，超过自动清理旧日期目录 |

落盘结构（每天 0 点切分，按日期目录归档，对齐 Java 端）：

```
logs/
├── 2026-06-07/
│   ├── tolink-rag-<pid>.log          # 当天全量（>= LOG_LEVEL）
│   └── tolink-rag-error-<pid>.log    # 当天 ERROR 及以上
├── 2026-06-08/
│   ├── tolink-rag-<pid>.log
│   └── tolink-rag-error-<pid>.log
└── ...
```

实现要点：文件名中的日期由 Loguru 在创建新文件时求值，配合 `rotation="00:00"` 每天 0 点切分，自然落入新的日期目录；写入开启 `enqueue` 队列，异步刷盘不阻塞业务。文件 sink 使用 `serialize=True`，每行是一条 JSON 日志；采集侧应按 JSON 解析，而不是按旧的管道分隔文本解析。

常用采集字段对应关系：

| 语义字段 | JSON 路径 |
| --- | --- |
| `time` | `record.time` |
| `level` | `record.level.name` |
| `service` | `record.extra.service` |
| `host` | `record.extra.host` |
| `pid` | `record.extra.pid` |
| `trace_id` | `record.extra.trace_id` |
| `logger_name` | `record.extra.logger_name` |
| `message` | `record.message` |
| `exception` | `record.exception` |

HTTP 请求链路通过 `X-Trace-Id` 头串联：请求带该头时沿用；未带时 Python 端生成 UUID 并在响应头回显。MQ 发送和消费会通过可选 `X-Trace-Id` 消息头透传当前 trace id。

服务名约定：Java 业务服务日志使用 `service=tolink-service`，Python RAG 服务日志使用 `service=tolink-rag`。部署环境可以覆盖 `LOG_SERVICE_NAME`，但必须保持 Java / Python 服务名不同，否则集中采集到 Loki 后无法通过 `service` 标签区分筛选。

`LOG_DIR` 支持绝对路径和相对路径。相对路径统一以项目根目录为基准，例如默认 `LOG_DIR=logs` 始终写入项目根目录的 `logs/`，不会因为进程从 `src` 目录启动而改写到该目录下的 `logs/`。

保留清理按 **日期目录整体删除**：删除 `<LOG_DIR>/<YYYY-MM-DD>/` 中日期早于 `LOG_RETENTION_DAYS`（当前 **7 天**）的目录，在进程启动时与每天 0 点切分时各执行一次。之所以不用 Loguru 自带 `retention`：日志文件名带 PID，Loguru 的清理 glob 会带上字面 PID，只能清掉当前进程写的文件，进程重启（部署 / 崩溃 / 扩缩容）后旧 PID 的日期目录无人回收、会无限堆积。按日期目录清理与 PID 无关，重启与多 worker 场景都能正确回收（非 `YYYY-MM-DD` 命名的目录不受影响）。

文件名带 **PID** 后缀（`<pid>` 为进程号）：多 worker（gunicorn）部署时各进程写各自文件，避免多进程共写同一文件导致的写入交错与 0 点切分/清理竞争；单进程部署同样安全，仅文件名多一段 PID。每行日志同时携带进程号（控制台格式的 `{process}` 字段），多 worker 共写 stdout 时也能区分来源进程。
> 注意：PID 在 `setup_logger()` 调用时求值。gunicorn 若启用 `--preload`，需在 `post_fork` 钩子里重新调用 `setup_logger()`，否则各 worker 会复用 master 的 PID 写到同一文件。

### 统一日志管道（标准库 logging 桥接）

项目自身代码统一用 Loguru。新代码优先从 `src.observability.logging` 引入；历史代码中的 `from src.utils.logger import logger` 仍由兼容层转发。uvicorn、SQLAlchemy、kafka 等第三方库以及少数遗留模块仍走 Python 标准库 `logging`，[src/observability/logging.py](../../src/observability/logging.py) 通过 `InterceptHandler` 把标准库 logging 全量桥接进 Loguru，使运行时**只有一条输出管道**：所有日志（无论来自 Loguru、标准库或第三方库）都进同一份日期文件、同一种 JSON 结构、由 `LOG_LEVEL` 统一过滤。

要点：

- 日志在 [src/main.py](../../src/main.py) 顶部**显式初始化**（`setup_logger()`），不依赖 import 副作用；放在其余模块导入之前，确保导入期日志也被捕获。
- `uvicorn`/`uvicorn.access`/`uvicorn.error`/`gunicorn` 等自带 handler 的 logger 会被显式接管（清空其 handler、打开 propagate），其访问日志与未捕获异常的 500 堆栈因此也进入日期文件。`uvicorn.run` 传 `log_config=None`，不再安装 uvicorn 自己的日志配置。
- 异常诊断使用安全双字段：`error_message` 先压平、常见敏感赋值脱敏并限制长度；
  `stack_trace` 只记录文件、行号和函数调用链，不包含异常原文、源码变量值或请求正文。
  URL 进入日志前移除用户密码、query 和 fragment；图片等不宜明文记录的资源使用稳定短指纹。
- `truncate_log_value()` 会遮蔽常见 `api_key/password/secret/access_token/authorization/
  credential/signature` 赋值、Bearer token 和 URL 用户密码。外部 HTTP/CLI 响应只记录
  定长摘要，禁止记录完整 prompt、query、answer、Markdown、MQ body 或模型响应正文。
- 全局未捕获异常由 [src/main.py](../../src/main.py) 的 `Exception` handler 兜底：带请求方法 / 路径记录脱敏错误摘要和安全调用栈，再返回统一 500 错误体 `{code, message, data}`。
- 解析任务使用结构化事件 `parse_task_started` / `parse_task_finished` /
  `parse_task_crashed` 以及 `parse_stage_started/succeeded/skipped/failed/crashed`。
  可在 Loki 中按 `event`、`task_id`、`user_id`、`dataset_id`、`stage`、`engine`、
  `outcome` 和 `failure_reason` 检索；文件名与对象 key 只记录稳定短指纹，原始坐标仅
  在 DEBUG 日志出现。字段契约见
  [parse_task_pipeline.md §解析任务结构化日志](../internals/parse_task_pipeline.md#解析任务结构化日志)。
- MQ 使用 `mq_http_send_failed`、`mq_consume_retry`、`mq_consume_terminal`、
  `mq_dlq_published`、`mq_dlq_publish_failed`、`kafka_offset_commit_failed`；
  可按 topic、partition、offset、delivery_tag、retry_count 检索。
- 召回与增强使用 `recall_source_failed`、`recall_generation_failed`、
  `rerank_model_failed`、`markdown_enhancement_failed`、`image_enhancement_failed`；
  只记录数量、模型标识和资源指纹，不记录查询、回答、chunk 正文或图片签名 URL。
- 应用关闭（lifespan shutdown）时 `await logger.complete()`，等待 `enqueue` 队列里的日志全部落盘，避免退出丢尾部日志。
- 约定：**应用代码新增日志一律用 Loguru**；遗留的标准库 logging 会被自动桥接，无需改写，但不要再新增标准库 logging 用法。

### 集中日志部署（Loki + Promtail）

生产环境按分布式拓扑部署：Loki 放在中间件服务器，Promtail 放在产生日志文件的应用服务器。Promtail 需要直接读取本机日志文件，不建议通过远程挂载读取另一台机器上的日志。

Promtail 只采集 Java/Python 的全量主日志文件，不再采集独立的 `*-error*.log`，避免同一
条 ERROR 在 Loki 和前端出现两次；同时从 JSON 日志中提取业务原始时间作为 Loki
timestamp，避免首次启动或位置文件丢失后把历史日志错误显示为当前时间。

```text
应用服务器（Java / Python）
  ├─ toLink-Service 写本机 Java 日志
  ├─ toLink-Rag 写本机 Python 日志
  └─ Promtail 读取本机日志并推送到 Loki

中间件服务器
  └─ Loki 集中存储日志并提供 LogQL 查询
```

中间件服务器启动 Loki：

```bash
docker compose up -d loki
curl http://127.0.0.1:3100/ready
```

应用服务器启动 Promtail：

```bash
HOST_VPN_IP=<loki-vpn-host> docker compose -f deploy/cloud-server/docker-compose.yml up -d promtail
```

当前仓库根目录 [docker-compose.yml](../../docker-compose.yml) 只保留主机服务器中间件，包含 `loki`，不包含 `promtail`。Promtail 跟随云服务器应用栈部署，配置见 [deploy/cloud-server/docker-compose.yml](../../deploy/cloud-server/docker-compose.yml)。

安全要求：Loki `3100` 不应直接暴露公网；跨服务器访问应走 VPN、内网或受控反向代理，并只允许应用服务器和 Java 查询代理访问。

## MQ 失败兜底（重试 + 死信）

消费框架对业务回调异常做有限退避重试 + 死信兜底；详细行为见 [mq.md §4.1](../internals/mq.md#41-失败兜底重试--死信)。

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `MQ_MAX_RETRIES` | `3` | 业务回调抛 `RetriableError` 子类时最多重试次数；超限后进死信 |
| `MQ_RETRY_BACKOFF_SECONDS` | `1.0` | 重试之间固定退避秒数；单条消息最长阻塞 ≈ 此值 × `MQ_MAX_RETRIES` |
| `MQ_DLQ_SUFFIX` | `.DLT` | 死信目标命名后缀（原 topic / queue + 后缀） |

> 死信兜底恒启用，不提供关闭开关。RabbitMQ Sender/Receiver 会用完全相同的参数幂等声明 Queue、DLX 与 DLT；Kafka 的 `ensure_topics()` 仅用于回滚兼容模式。

## MQ 逻辑目标命名

RabbitMQ 使用同名 Queue；Kafka 回滚模式使用同名 topic（见 [mq_contracts.md](../api/mq_contracts.md)）：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `PARSE_TASK_TOPIC` | `tolink.rag.parse_task` | 解析任务入队 |

> `PARSE_RESULT_TOPIC` 已随终态回传 MQ 下线删除（LINK-166）：解析终态只写 DB（`document_parse_pipeline`），前端轮询 Java 查询读取，不再有 parse_result 回传 topic。
>
> 这些变量只决定启动时**自动创建**哪些 Kafka topic。实际收发的 topic 名由消息类的 `MQ_NAME` 常量固定（`tolink.rag.parse_task`），改它不会改变 Python 端实际订阅/投递的 topic。

## 分块参数建议

| 变量 | 默认 | 调整方向 |
| --- | --- | --- |
| `CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS` | 128 | 第一阶段候选边界粗分片软下限，范围 `128..256`；调大可减少短 chunk |
| `CHUNKING_MAX_CHUNK_TOKENS` | 512 | `semantic_depth_window` 普通 final chunk 软目标，范围 `256..2048`；必须 `>= CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS` |
| `CHUNKING_HARD_MAX_TOKENS` | 1024 | `semantic_depth_window` 绝对硬上限，范围 `512..8192`；必须 `>= CHUNKING_MAX_CHUNK_TOKENS`；`noop` 不保证该上限；不可拆 protected 超过时优先按完整行截断并标记 |
| `CHUNKING_OVERLAP_TOKENS` | 64 | overlap token 数，范围 `0..64`；`0` 表示关闭 |
| `CHUNKING_PROTECTED_NEIGHBOR_OVERLAP` | false | 含 protected 元素的 final chunk 是否参与后置 neighbor overlap；默认关闭，避免 overlap 进入表格/代码等结构块 |
| `CHUNKING_HEADING_BREAK_LEVEL` | 5 | heading trail 与动态标题边界保护的最大层级；最多保护到 5 级 |

详细分块策略见 [chunking.md](../internals/chunking.md)。

## 稀疏向量配置

稀疏向量与稠密向量在同一个 chunk 向量化阶段执行，模型输入是 chunk 原文，不使用 ES 分词结果。

稀疏/稠密编码模型由 `dataset_parse_config.sparse_embedding_config_id` /
`dense_embedding_config_id` 精确指向全局 `llm_model_config.id`。表格/标题、图片与 rerank 分别使用
`enhancement_chat_config_id`、`enhancement_vision_config_id`、`rerank_config_id`。必需字段缺失或配置无效时明确失败，不回退默认。

当前可选的稀疏 provider 为 `doubao_vision`（火山方舟 doubao-embedding-vision 多模态端点）/ `bge_m3`（自部署 `bge-m3-service` 端点）。原先用 `SPARSE_VECTOR_PROVIDER` 在本地 / HTTP / 远程 BGE-M3 间切换的整套机制已移除。详见 [vectorization.md §6.6](../internals/vectorization.md) 与 [sparse_vector.md](../internals/sparse_vector.md)。

下表是仍保留的系统级配置项，均与具体 provider 无关，是全局开关与清洗 / 命名规则：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SPARSE_VECTOR_ENABLED` | `true` | 稀疏向量总开关；关闭后只执行旧稠密向量流程 |
| `SPARSE_VECTOR_QDRANT_VECTOR_NAME` | `sparse_text` | Qdrant named sparse vector 名称，写入与召回共用 |
| `SPARSE_VECTOR_TOP_K` | `256` | 每条稀疏向量最多保留的非零 token 数；`0` 表示不截断。全局清洗规则，各 provider 复用 |
| `SPARSE_VECTOR_MIN_WEIGHT` | `0.0` | 过滤低权重 token 的阈值。全局清洗规则，各 provider 复用 |
| `SPARSE_VECTOR_BATCH_SIZE` | `32` | 稀疏索引外层批大小：一次从 DB 取多少 chunk 原文喂给编码器；编码器内部批大小由 provider 自行决定，不随之变化 |

> 已移除的稀疏向量配置项（不再生效，配置也无效果）：`SPARSE_VECTOR_PROVIDER`、`SPARSE_VECTOR_MODEL_NAME`、`SPARSE_VECTOR_MODEL_CACHE_DIR`、`SPARSE_VECTOR_LOCAL_FILES_ONLY`、`SPARSE_VECTOR_DEVICE`、`SPARSE_VECTOR_MAX_LENGTH`、`SPARSE_VECTOR_HTTP_ENDPOINT` / `SPARSE_VECTOR_HTTP_TIMEOUT` / `SPARSE_VECTOR_HTTP_BATCH_SIZE`、`BGE_M3_SERVICE_URL` / `BGE_M3_TIMEOUT_SECONDS` / `BGE_M3_MAX_RETRIES`、`SPARSE_VECTOR_RETRY_LIMIT` / `SPARSE_VECTOR_INDEXING_STALE_SECONDS`、`TOLINK_RUN_REAL_SPARSE_VECTOR_TESTS`，以及更早的 `SPARSE_VECTOR_USE_FP16`。

## 索引写入互斥配置

MySQL 是业务真值。正常写入与写入失败后的同步清理对同一 `(doc_id, branch)` 共用 advisory lock；系统不启动后台补偿，不自动重建，失败任务由用户重试。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INDEX_MUTATION_LOCK_TIMEOUT_SECONDS` | `10` | 获取文档分支 advisory lock 的最长等待时间；超时使当前解析失败，不绕过互斥执行 |

## 召回执行配置

召回融合 pipeline 的通用执行参数（RAG 问答流与纯召回 JSON 两端点共用）。详见
[docs/internals/recall_http_api.md](../internals/recall_http_api.md)。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RECALL_STREAM_TIMEOUT_MS` | `60000` | 召回、正文读取与本地/远程排序共享的总预算（毫秒）；超时 RAG 流以 SSE `error` RECALL_TIMEOUT 终止，纯召回 JSON 返回 `504` RECALL_TIMEOUT。**不含 LLM 生成阶段**（见 `RECALL_GENERATION_TIMEOUT_MS`） |
| `RECALL_GENERATION_TIMEOUT_MS` | `300000` | LLM 生成阶段最大执行时间（毫秒），与召回超时解耦。RAG 生成跑在独立后台任务、断连不取消，需独立超时防孤儿任务无限烧 token；超时落 `FAILED` + `GENERATION_TIMEOUT`（保留半截答案）。取值远大于召回超时以容纳长回答 |
| `RECALL_STRICT_DEFAULT` | `false` | pipeline 严格模式默认；false=宽松，允许单路失败降级 |
| `RECALL_RESULT_LIMIT` | `64` | 对外融合窗口与旧 rerank 输入池；LTR 使用门禁后的完整内部候选池，不受该截断影响 |
| `RECALL_DENSE_TOP_K` | `100` | `off` 与纯召回 JSON 的 dense 路系统默认；LTR RAG 流改用 Blind v5 Query 分型深度 |
| `RECALL_SPARSE_TOP_K` | `50` | `off` 与纯召回 JSON 的 sparse 路系统默认；LTR RAG 流改用 Blind v5 Query 分型深度 |
| `RECALL_BM25_TOP_K` | `100` | `off` 与纯召回 JSON 的 bm25 路系统默认；LTR RAG 流改用 Blind v5 Query 分型深度 |
| `WIKI_SEARCH_PAGE_SIZE` | `15` | Wiki 顶层搜索与单标题直属 Chunk 展开的服务端固定页大小；必须为正整数，客户端不能覆盖 |
| `WIKI_BM25_TOP_K_PER_DATASET` | `50` | Wiki mixed 分支对每个有效知识库独立读取的 BM25 候选上限；必须为正整数，不读取知识库个性 `bm25_top_k` |
| `RECALL_ENABLED_SOURCES` | `bm25,sparse,dense` | 启用的召回路（逗号分隔）。本期默认开启三路；运维侧可显式 set `bm25,sparse` 暂时回退到 dev 旧行为；未登记的 source 出现在配置中装配期 `ValueError` |
| `RECALL_LTR_MODE` | `active` | 默认由本地 LambdaMART 主排并跳过远程 rerank；`off` 保持旧 rerank；`shadow` 旁路比较但不改结果；`baseline` 主动回滚到 weighted score 并跳过 rerank |
| `RECALL_LTR_MODEL_DIR` | `models/ltr/candidate-difference-v3-20260728-final33` | 版本化生产模型包；应用启动时由 worker thread 预加载并校验 LightGBM 版本、模型/文件 SHA-256、特征签名、候选生成契约、Alias=false 和 3 个测试向量 |
| `RECALL_LTR_SHADOW_SAMPLE_RATE` | `0.1` | Shadow 稳定抽样比例 `[0,1]`，按 `request_id` 哈希；仅 `shadow` 模式生效 |
| `RECALL_LTR_SHADOW_MAX_CONCURRENCY` | `4` | 单进程同时执行的 Shadow 冻结候选召回与排序上限 |
| `RECALL_LTR_SHADOW_MAX_PENDING` | `16` | 单进程 Shadow 等待容量；并发与等待都满时直接丢弃样本，不等待主链 |
| `RECALL_LTR_SHADOW_TIMEOUT_MS` | `5000` | Shadow 独立请求的总预算，覆盖候选召回、正文读取和推理 |
| `RECALL_LTR_SHADOW_SHUTDOWN_TIMEOUT_MS` | `3000` | 服务关闭时等待 Shadow 任务的最长时间，超过后取消 observer |
| `RECALL_LTR_INFERENCE_MAX_CONCURRENCY` | `4` | LambdaMART 专用 executor 容量；超时线程真正退出前不释放容量，避免默认 executor 无界积压 |
| `RECALL_FUSION_BM25_WEIGHT` | `0.15` | 固定 weighted score 的 BM25 路权重；允许为 0，active source 权重和为 0 时本次融合失败 |
| `RECALL_FUSION_SPARSE_WEIGHT` | `0.15` | 固定 weighted score 的 sparse 路权重；允许为 0，active source 权重和为 0 时本次融合失败 |
| `RECALL_FUSION_DENSE_WEIGHT` | `0.70` | 固定 weighted score 的 dense 路权重；允许为 0，active source 权重和为 0 时本次融合失败 |
| `SPARSE_RETRIEVAL_TOP_K` | `10` | sparse 召回 facade 直调时调用方未传 `top_k` 的兜底值；完整 RAG pipeline 不读取它作为 sparse 深召回默认 |
| `SPARSE_RETRIEVAL_SCORE_THRESHOLD` | `0.0` | sparse 召回默认 score 阈值（0.0 = 不过滤；详见 [vectorization.md §9.4](../internals/vectorization.md)） |
| `DENSE_RETRIEVAL_TOP_K` | `10` | dense 召回 facade 直调时调用方未传 `top_k` 的兜底值；完整 RAG pipeline 不读取它作为 dense 深召回默认 |
| `DENSE_RETRIEVAL_SCORE_THRESHOLD` | `0.0` | dense 召回默认 score 阈值（cosine 上界 [0, 1]，0.0 = 不过滤；facade 入口校验 `> 1.0` 早死） |
| `RECALL_GENERATION_CONTEXT_TOKEN_BUDGET` | `4000` | 召回后 LLM 生成拼装上下文的 token 预算上限；命中片段按融合分数从高到低纳入，累计超预算即截断尾部低分片段（仅 RAG 问答流的生成阶段生效） |
| `RERANK_DEFAULT_TOP_N` | `10` | 旧 rerank/off 链路的输出候选条数兜底；LTR RAG 流固定输出 Top10，与 Blind v5 指标口径一致 |

LambdaMART 当前默认以 `active` 运行。新模型版本发布时仍按 `shadow → active` 验证：Shadow 至少
观察 `recall_ltr_shadow_completed` 的 `top10_changed` / `top10_overlap`、`rank_mode`、
`duration_ms` 和失败事件，确认业务反馈后再切换该新版本。`fallback_*` 比例或 p95 超过 250ms 时，
把 `RECALL_LTR_MODE` 改为 `baseline` 并重启，即可在不加载模型、不调用远程 rerank 的情况下回滚到
frozen weighted score。当前模型包已完成离线契约验证；后续新模型不得跳过 Shadow 验证。

当 `RECALL_LTR_MODE` 为 `active` / `baseline` 时，**RAG 问答主链**冻结 Blind v5
候选契约；`shadow` 主链与 `off` 完全一致，仅在有界后台任务中另起一次冻结候选请求。冻结契约启用
`bm25,sparse,dense`，阈值全为 `0.0`，权重固定为
`0.15 / 0.15 / 0.70`，最终 Top10，并按 Query 分型选择三路深度：

| Query 档位 | Dense | Sparse | BM25 |
| --- | ---: | ---: | ---: |
| `short_keyword` | 300 | 100 | 225 |
| `exact_identifier` | 150 | 50 | 100 |
| `number_time` | 275 | 50 | 200 |
| `long_multi` | 125 | 50 | 75 |
| `natural_default` | 150 | 50 | 225 |

该契约写入模型目录的 `serving_contract.json`，加载时与代码内契约逐字段校验。`off` 模式
仍尊重 Dataset 级配置；`POST /api/v1/recall` 纯召回 JSON 不被全局 LTR 模式改写，始终按
Dataset/系统配置执行。冻结契约缺少任一路装配或任一路执行失败时 fail closed，不允许把残缺候选
送入 LTR。Shadow 抽样的独立召回、完整候选正文读取与模型推理均在有界后台任务中完成，不阻塞
旧线上排序和答案生成。模型文件读取、LightGBM 导入、Booster 构造及测试向量校验在 FastAPI
startup 阶段通过 worker thread 完成；请求期只读取固化的模型或 baseline 状态。
`GET /health` 的 `ltr` 字段暴露 `preload_completed`、实际 `serving_strategy`、模型版本、契约版本、加载错误、降级计数和
p50/p95/p99 推理延迟。服务完成启动后若 active/shadow 出现 `loaded=false`，应结合
`last_load_error` 按模型预加载失败告警，而不是等待真实请求再次加载。

默认值来源说明：

- `RECALL_RESULT_LIMIT=64`：参考 [RAGFlow `rag/nlp/search.py::_rerank_window`](https://github.com/infiniflow/ragflow/blob/main/rag/nlp/search.py) 将 rerank 候选池控制在约 64 的 provider-friendly 窗口；该值是 source-backed baseline，不是本项目评测结论。
- `RECALL_DENSE_TOP_K=100`：参考 [Sentence Transformers retrieve-and-rerank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html) / [Cross-Encoder 文档](https://www.sbert.net/examples/cross_encoder/applications/README.html)，先用 Bi-Encoder 取 top-100，再交 Cross-Encoder 重排。
- `RECALL_SPARSE_TOP_K=50`：参考 [Azure AI Search semantic ranker](https://learn.microsoft.com/en-us/azure/search/semantic-search-overview) 对 top 50 的重排窗口。
- `RECALL_BM25_TOP_K=100`：参考 [BEIR BM25 + Cross-Encoder reranking 示例](https://github.com/beir-cellar/beir/blob/main/examples/retrieval/evaluation/reranking/evaluate_bm25_ce_reranking.py) 对 BM25 top-100 做 rerank。

配置边界：`RECALL_*_TOP_K` 驱动 `off` RAG 流和纯召回 JSON 的三路召回深度；LTR RAG 流由上述候选契约动态路由。`DENSE_RETRIEVAL_TOP_K` / `SPARSE_RETRIEVAL_TOP_K` 只在直接调用 `VectorStorageFacade.search_*_chunks()` 且调用方未传 `top_k` 时兜底。
Wiki 标题搜索只复用 `RECALL_STRICT_DEFAULT` 与 `RECALL_STREAM_TIMEOUT_MS`；分页游标固定 10 分钟有效，单 Chunk 搜索位置固定最多 10 条，两者均为模块内部常量，不增加环境变量。Wiki 不使用 Redis。

### 对外会话鉴权配置（RAG 流 / 纯召回 JSON）

对外端点 `POST /api/v1/rag/stream`（RAG 问答流）与 `POST /api/v1/recall`（纯召回 JSON）的
会话鉴权配置。前端凭 Java 签发的短期 session token 直连，使用**独立专用密钥**验签。并发限流
（`RECALL_SESSION_MAX_CONCURRENT`）**仅 RAG 流生效**，纯召回不限流。详见
[recall_http_api.md](../internals/recall_http_api.md)。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RECALL_SESSION_AUTH_ENABLED` | `true` | 是否启用 session token 验签；**生产必须为 true** |
| `RECALL_SESSION_JWT_ISSUER` | `tolink-java` | 期望的 session JWT `iss` |
| `RECALL_SESSION_JWT_AUDIENCE` | `tolink-rag-frontend` | 期望的 session JWT `aud` |
| `RECALL_SESSION_JWT_SCOPE` | `recall:stream` | 期望的 session JWT `scope` |
| `RECALL_SESSION_JWT_SECRET` | 本地联调占位值 | **独立专用** HS256 密钥，可单独轮转；**生产务必覆盖** |
| `RECALL_SESSION_MAX_CONCURRENT` | `3` | 单用户最大并发召回流数；token 短期可复用，此为资源滥用主闸门，超限返回 `429` |
| `CORS_ORIGINS` | `["*"]` | **生产对外环境必须收敛为前端可信域名清单**（不可用 `*`，否则带 `Authorization` 头的跨域预检失败）|

> token 短期可复用：Python 只校验 `exp`（建议 Java 签发 30s，仅够建连），不做一次性 /
> 防重放 / 撤销。RAG 生成跑在独立后台任务、断连不取消，并发名额绑任务生命周期释放（非连接）；
> 任务存活由召回超时 `RECALL_STREAM_TIMEOUT_MS` + 生成超时 `RECALL_GENERATION_TIMEOUT_MS` 共同约束，
> 名额安全 TTL 取二者较大值兜底。并发计数依赖 Redis，Redis 不可用时 fail-open（放行，因限流是资源保护非鉴权）。

## 配置加载与覆盖

- `.env` 由 [src/config.py](../../src/config.py) 通过 `Settings`（pydantic-settings）加载。
- 运行时环境变量**优先级高于** `.env`（部署时通过容器环境变量注入即可覆盖）。
- 新增配置必须在 `Settings` 中声明，并在 [.env.example](../../.env.example) 补充示例值。

## 相关文档

- 部署步骤：[deployment.md](deploy.md)
- MQ 集成：[mq_integration.md](../api/mq_contracts.md)
