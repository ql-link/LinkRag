# Deployment

部署 toLink-Rag 涉及一个 FastAPI 服务进程和一组外部依赖。本文聚焦 README 快速开始之外的细节：依赖服务清单、启动顺序、健康检查、生产部署注意事项。

完整环境变量解读见 [configuration.md](configure.md)。

## 依赖服务清单

根目录 `docker-compose.yml` 提供主机服务器中间件栈：

| 服务 | 镜像 | 主机端口 | 用途 | 必需 |
| --- | --- | --- | --- | --- |
| `mysql` | `mysql:8.0` | 3306 | 用户、LLM 配置、用量记录、Chunk 状态 | ✅ |
| `redis` | `redis:7.2-alpine` | 6379 | 召回 session 并发槽位等原子协调能力 | ✅ |
| `minio` | `minio/minio` | 9000 / 9001 | 原始文档、解析产物的对象存储 | 二选一¹ |
| `qdrant` | `qdrant/qdrant` | 6333 / 6334 | 稠密 / 稀疏 / BM25 索引存储 | ✅ |
| `manticore` | `manticoresearch/manticore:27.1.5` | 9306 / 9308 | 可选 BM25 全文索引；迁移期与 Qdrant 双写 | 按需 |
| `zookeeper` | `bitnami/zookeeper:3.9` | 2181 | Kafka 协调 | 当 MQ 为 Kafka 时必需 |
| `kafka` | `bitnami/kafka:3.7` | 9092 | 异步消息中台 | 当 `MQ_VENDOR=kafka` 时必需 |
| `kafka-ui` | `provectuslabs/kafka-ui` | 9081 | Kafka 调试 UI | 可选 |
| `loki` | `grafana/loki:2.9.8` | 3100 | 集中日志存储与查询 | ✅ |

注 1：`STORAGE_TYPE=minio` 使用 MinIO，`STORAGE_TYPE=local` 使用 `LOCAL_DOCS_PATH` 本地目录。
注 2：当前生产固定使用 Qdrant，不再部署 Elasticsearch。BM25 通过 Qdrant sparse vector + `Modifier.IDF` 承载。

## Compose 文件分层

| 文件 | 用途 |
| --- | --- |
| `docker-compose.yml` | 主机服务器中间件栈，作为当前主机部署入口 |
| `deploy/host-server/docker-compose.yml` | 主机服务器中间件栈的 deploy 目录版本 |
| `deploy/cloud-server/docker-compose.yml` | 云服务器应用栈：Java、Python RAG、Web、Promtail |
| `deploy/docker-compose.yml` | 保留的 Python RAG 单服务部署入口 |
| `deploy/test-server/docker-compose.yml` | Primary 测试栈：隔离的 MySQL、Redis、Kafka、Qdrant、Manticore、Loki，以及 dev 应用 |

Promtail 必须部署在产生日志文件的云服务器上；Loki 部署在主机服务器中间件栈中。

## Primary 测试环境

测试环境通过 `deploy/test-server/docker-compose.yml` 部署，所有容器、网络、端口和数据卷均使用
`tolink-test-*` 命名，不修改生产栈。测试 MySQL、Redis、Kafka、Qdrant、Manticore 和 Loki 独立运行；
MinIO 仍复用主机实例，但必须使用独立测试账号和 `tolink-test-*` bucket。
测试账号的策略只允许访问 `tolink-test-raw`、`tolink-test-docs` 和 `tolink-test-public`。

测试端口只绑定 Tailscale 地址 `100.86.10.52`，不得通过 FRP 或公网安全组暴露。首次部署时从
`.env.test.example` 生成服务器本地 `.env.test`，随机密钥不得提交到 Git：

```bash
cd /opt/tolink/test
docker compose --env-file .env.test up -d mysql redis kafka qdrant manticore loki
docker compose --env-file .env.test --profile apps up -d
```

开发服务使用各项目既有的开发 profile：Python 设置 `APP_ENV=development`，并从
`/opt/tolink/test/config/rag/.env.development` 加载可提交的基础配置，再由权限为 `600` 的
`.env.development.local` 注入账号、密码、JWT 与 API Key。Java 设置
`SPRING_PROFILES_ACTIVE=dev`，挂载 `/opt/tolink/test/config/service/`，其中
`application-dev.yml` 是可提交基础配置，`application-dev-local.yml` 只保存敏感字段并由前者导入。
Compose 和构建迁移任务都按“基础配置 → 本机密钥覆盖”的顺序加载，两个 `.local` 文件不得进入
Git 或 Docker 镜像。测试环境的基础配置固定指向 `tolink-test-*` 隔离资源，避免误连生产环境。

当前业务 topic 和 consumer group 由代码常量固定，因此测试环境使用独立 Kafka broker，不能只依赖
topic 前缀与生产共用 broker。测试 Loki 独立保存日志并保留 7 天。

Cloud Jenkins 使用三个独立 dev 作业：`linkrag-rag-dev`、`linkrag-service-dev`、
`linkrag-web-dev`。Jenkins 只负责调度和保留日志，三个作业均通过 Tailscale SSH 在 Primary
拉取对应仓库的 `dev` 分支、构建镜像并部署，镜像使用 `test-dev-b<build>` 标签；现有 `master`
生产作业保持不变。Primary 通过构建锁避免三个测试作业同时占用 Docker 构建资源。
Java 测试镜像使用 `deploy/test-server/Dockerfile.service` 构建；Maven 下载设置请求超时，Docker
构建失败时最多自动重试三次，并复用 BuildKit 的 `.m2` 缓存，避免单条公网连接长期挂起。
Web 构建把 npm 缓存持久化到 `/opt/tolink/test/jenkins/npm-cache`，`npm ci` 设置超时并最多重试三次；
安装失败会立即终止，不再继续执行 typecheck、测试和打包。
公网源码下载不稳定时，可将完整 tar 包预置到
`/opt/tolink/test/jenkins/incoming/<workspace>-dev.tgz`；下一次对应构建会校验并消费该文件，随后仍在
Primary 完成镜像构建。

## 启动顺序

应用 startup 钩子依赖以下服务**已就绪**（见 [src/main.py](../../src/main.py)）：

1. Redis（缓存层初始化）
2. MySQL（连接池建立）
3. Kafka topic（若 `INIT_KAFKA_TOPICS_ON_STARTUP=true`，应用启动时创建 topic）
4. Kafka 消费者启动（订阅 `PARSE_TASK_TOPIC`）

任何一项未就绪都会导致 `uvicorn` 启动失败。推荐顺序：

```bash
# 1. 起依赖
docker compose up -d

# 2. 等核心依赖 healthy（mysql/redis/kafka 有 healthcheck）
docker compose ps

# 3. 起应用
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## 健康检查与排查

| 检查 | 命令 | 期望 |
| --- | --- | --- |
| 应用存活 | `curl http://localhost:8000/health` | 返回 JSON，含已加载模块 |
| 应用就绪 | `curl http://localhost:8000/ready` | Manticore 启用时实际执行 `SELECT 1`，失败返回 503 |
| Swagger | 访问 `http://localhost:8000/docs` | 看到所有路由 |
| MySQL | `docker compose exec mysql mysqladmin ping -uroot -p` | `mysqld is alive` |
| Kafka | `docker compose ps kafka` | `healthy` |
| MinIO | `curl http://localhost:9000/minio/health/live` | 200 |
| Manticore | `docker compose ps manticore` | `healthy` |

常见失败：

- **应用启动卡在 Kafka**：通常是 `KAFKA_BOOTSTRAP_SERVERS` 配置错或 broker 未起来。本地用 docker-compose 时此地址应为 `127.0.0.1:9092`（容器内部连接用 `tolink-kafka:29092`）。
- **API 调用 LLM 报解密失败**：`API_KEY_ENCRYPTION_SECRET` 必须与 Java 管理端的加密 Secret 一致，否则 `llm_model_config.api_key` 密文无法解密。
- **解析任务消费不到**：检查 `INIT_KAFKA_TOPICS_ON_STARTUP` 是否被关闭，且 topic（`tolink.rag.parse_task`）是否已存在。

## 生产部署注意事项

`docker-compose.yml` 是**开发用编排**，不适合直接用于生产：

- 所有密码硬编码为 `ql354210`，生产必须替换。
- MySQL/Redis/MinIO 用 root/默认账号且无 TLS，生产应改用专用账户与加密连接。
- Kafka 用 SASL_PLAINTEXT，生产建议 SASL_SSL。
- 数据卷为本地 docker volume，生产应挂载持久化存储或使用托管服务。

生产环境建议：

1. **外部依赖托管化**：MySQL、Kafka、MinIO/S3、Qdrant 使用云厂商托管或独立部署，应用容器只跑 FastAPI 进程。
2. **配置外部化**：`.env` 通过 Secret Manager（如 K8s Secret、Vault）注入，不打进镜像。
3. **多副本与扩缩容**：FastAPI 进程可水平扩展；Kafka 消费者通过 consumer group 自动分配 partition，消费侧扩缩容时关注 `PARSE_TASK_PARTITIONS` 是否足够。
4. **初始化 topic**：生产环境建议把 `INIT_KAFKA_TOPICS_ON_STARTUP=false`，topic 由部署流程或运维侧显式创建，避免应用启动时副作用。
5. **Manticore 高可用**：根 Compose 仅为单节点，不具备生产 HA。切主读前必须另行完成副本/备份、故障恢复演练与容量压测；迁移步骤见 [Manticore BM25 上线手册](manticore_bm25_migration.md)。

## Python 依赖变更

HTML 解析采用 trafilatura（正文定位/去样板/空内容识别）混合方案：

- 主依赖新增 `trafilatura>=2.0.0`（纯 Python，依赖 lxml，已为现有传递依赖）。
- 移除曾短期引入的 `readability-lxml`（已废弃方案，不再使用）。

Word（.docx）解析采用 mammoth → 复用 HTML 渲染引擎混合方案：

- 主依赖新增 `mammoth>=1.6.0`（纯 Python 轻依赖）。

部署/CI 需 `pip install -e ".[dev]"` 重新安装依赖，确保镜像内含 trafilatura 与
mammoth；否则 HTML / Word 文件解析会在导入期失败。无需额外系统库或二进制。

## 数据库初始化

`migrations/db.sql`（0001 baseline 冻结快照，禁止修改）由 0001 迁移脚本自动执行。首次部署或重置，直接运行：

```bash
alembic upgrade head
```

该命令一步完成 0001 baseline 和后续增量迁移。**Alembic migration 是生产 DDL 与种子数据的唯一权威源**；
`scripts/db/init.sql` 只是叠加全部迁移后的逻辑/测试快照，不得作为部署入口。

> 对于已有表的存量库（老库升级）：先 `alembic stamp 0001` 标记基线，再 `alembic upgrade head`。

应用进程**不会**自动建表，必须先执行 DDL。

## 相关文档

- 配置项详解：[configuration.md](configure.md)
- MQ 接入对接：[mq_integration.md](../api/mq_contracts.md)
- 项目架构：[docs/internals/project_structure.md](../internals/project_structure.md)
