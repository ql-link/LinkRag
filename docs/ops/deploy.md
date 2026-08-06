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
| `qdrant` | `qdrant/qdrant:v1.17.1` | 6333 / 6334 | 稠密 / learned sparse 向量存储 | ✅ |
| `manticore` | `manticoresearch/manticore:27.1.5` | 9306 / 9308 | BM25 全文索引 | ✅ |
| `loki` | `grafana/loki:2.9.8` | 3100 | 集中日志存储与查询 | ✅ |

注 1：当前可用对象存储实现为 `STORAGE_TYPE=minio`；OSS 适配器仍为占位实现。
注 2：当前生产固定使用 Qdrant 承载 dense / learned sparse；BM25 由 Manticore 承载。

## Compose 文件分层

| 文件 | 用途 |
| --- | --- |
| `docker-compose.yml` | 主机服务器中间件栈，作为当前主机部署入口 |
| `deploy/host-server/docker-compose.yml` | 主机服务器中间件栈的 deploy 目录版本 |
| `deploy/cloud-server/docker-compose.yml` | 云服务器生产栈：RabbitMQ、Java、Python RAG、Web、Promtail |
| `deploy/cloud-server/data-compose.yml` | 云服务器生产数据栈：MySQL、Redis、MinIO、Qdrant、Manticore、Loki |
| `deploy/docker-compose.yml` | 保留的 Python RAG 单服务部署入口 |
| `deploy/dev-server/docker-compose.yml` | Primary 开发栈：隔离的 MySQL、Redis、RabbitMQ、Qdrant、Manticore、Loki，以及 dev 应用 |

Promtail 必须部署在产生日志文件的云服务器上；Loki 部署在主机服务器中间件栈中。

## 生产 Jenkins 与容器配置注入

生产部署采用两层配置：仓库中的 `.env.production` 只包含可提交配置，云服务器上的
`/opt/tolink/toLink-Rag/.env.production.local` 只包含账号、密码、JWT 与 API Key。
Jenkins 每次部署会自动更新基础配置和 `deploy/docker-compose.yml`，但不会覆盖密钥文件；
Compose 按基础文件、密钥文件的顺序加载，后者覆盖前者中的空值。

生产 `master` 作业构建新镜像后、启动新容器前，会先用该镜像执行一次
`python -m alembic upgrade head`，并通过 `python -m alembic current` 输出最终 revision。
迁移容器固定加载 `.env.production` + `.env.production.local`；迁移失败会立即终止本次部署，
不会把新镜像切换为运行实例。迁移过程具有幂等性，数据库已经在 `head` 时不会重复执行 DDL。
执行前还会校验目标必须是 `production / tolink-mysql:3306 / tolink_rag_db`，避免密钥文件或
`DATABASE_URL` 覆盖错误导致生产任务串到开发库。

云服务器首次部署只需创建一次密钥文件并限制权限：

```bash
install -m 0600 /path/to/.env.production.local \
  /opt/tolink/toLink-Rag/.env.production.local
```

缺少密钥文件或权限不是 `600` 时，Jenkins 会在启动容器之前直接失败，避免以空密码启动。
Java 的 `application-prod.yml` 随镜像发布，并通过 `spring.config.import` 加载服务器上的
`application-prod-local.yml`；Cloud Compose 只读挂载该密钥文件，不再用服务器目录覆盖镜像中的
基础配置。

生产 RAG 通过 Cloud `tolink-app-net` 内的容器 DNS `tolink-qdrant:6333` 访问独立 Qdrant，
Qdrant 不映射宿主机端口。RabbitMQ 与生产应用同机部署，容器名 `tolink-rabbitmq`。管理端口只绑定 Cloud 回环地址；AMQP
端口仅绑定 Cloud 的 Tailscale 地址 `100.77.31.79:5672`，供本地 `prod` profile 调试，不发布到公网。
Broker 与应用凭据分别保存在 `/opt/tolink/rabbitmq/broker.env` 和
`/opt/tolink/rabbitmq/app.env`，权限均为 `600`。
当前环境统一使用 RabbitMQ；Kafka 配置仅保留代码级回滚兼容，部署密钥层不再写入 Kafka
账号或密码。Python `Settings` 在缺少环境文件时也默认选择 `rabbitmq`。

## Primary 开发环境

开发环境通过 `deploy/dev-server/docker-compose.yml` 部署，所有容器、网络、端口和数据卷均使用
`tolink-dev-*` 命名，不修改生产栈。开发 MySQL、Redis、RabbitMQ、Qdrant、
Manticore 和 Loki 独立运行；Primary 上的开发 MinIO 使用 `tolink-dev-minio` 名称，并加入
`tolink-dev-net`，同时使用独立开发账号和 `tolink-dev-*` bucket。
开发账号的策略只允许访问 `tolink-dev-raw`、`tolink-dev-docs` 和 `tolink-dev-public`。

开发端口只绑定 Tailscale 地址 `100.86.10.52`；RabbitMQ AMQP 使用 `100.86.10.52:5672`，
本地与 `dev` profile 共用该入口，不得通过 FRP 或公网安全组暴露。首次部署时从
`.env.dev.example` 生成服务器本地 `.env.dev`，随机密钥不得提交到 Git：

```bash
cd /opt/tolink/dev
docker compose --env-file .env.dev up -d mysql redis rabbitmq qdrant manticore loki
docker compose --env-file .env.dev --profile apps up -d
```

开发服务使用各项目既有的开发 profile：Python 设置 `APP_ENV=development`，并从
`/opt/tolink/dev/config/rag/.env.development` 加载可提交的基础配置，再由权限为 `600` 的
`.env.development.local` 注入账号、密码、JWT 与 API Key。Java 设置
`SPRING_PROFILES_ACTIVE=dev`，挂载 `/opt/tolink/dev/config/service/`，其中
`application-dev.yml` 是可提交基础配置，`application-dev-local.yml` 只保存敏感字段并由前者导入。
Compose 和构建迁移任务都按“基础配置 → 本机密钥覆盖”的顺序加载，两个 `.local` 文件不得进入
Git 或 Docker 镜像。开发环境的基础配置固定指向 `tolink-dev-*` 隔离资源，避免误连生产环境。
部署时 Compose 会把 RAG/Java 的非密钥连接地址覆盖为开发网络内的容器 DNS；本地 IDE 仍可使用
`.env.development` / `application-dev.yml` 中的 Tailscale 地址与开发端口。

当前业务 Queue 名由代码常量固定。开发环境使用独立 vhost `/tolink-dev` 与独立 RabbitMQ 数据卷，
生产使用 `/tolink-prod`，两套环境不共享 Broker 或凭据。开发 Loki 独立保存日志并保留 7 天。

Cloud Jenkins 使用三个独立 dev 作业：`linkrag-rag-dev`、`linkrag-service-dev`、
`linkrag-web-dev`。Jenkins 只负责调度和保留日志，三个作业均通过 Tailscale SSH 在 Primary
拉取对应仓库的 `dev` 分支、构建镜像并部署，镜像使用 `dev-b<build>` 标签；现有 `master`
生产作业保持不变。Primary 通过构建锁避免三个开发作业同时占用 Docker 构建资源。
其中 `linkrag-rag-dev` 在启动新 RAG 容器前自动执行 Alembic，固定加载
`.env.development` + `.env.development.local`，并输出最终 revision；迁移失败时不会部署新镜像。
执行前会校验迁移容器实际连接目标必须是
`development / tolink-dev-mysql:3306 / tolink_rag_dev`，不满足时直接阻断。宿主机暴露的
`100.86.10.52:13306` 只用于 Tailscale 客户端访问，不是容器内 Alembic 的连接地址。
0036 升级时优先复用库内已有的六类系统密文；只有全新开发库或能力不完整时，才使用部署任务
自动生成的 dev-only 密文，避免日常 dev 发布覆盖已有可用 Key。
Java 开发镜像使用 `deploy/dev-server/Dockerfile.service` 构建；Maven 下载设置请求超时，Docker
构建失败时最多自动重试三次，并复用 BuildKit 的 `.m2` 缓存，避免单条公网连接长期挂起。
Web 构建把 npm 缓存持久化到 `/opt/tolink/dev/jenkins/npm-cache`，`npm ci` 设置超时并最多重试三次；
安装失败会立即终止，不再继续执行 typecheck、测试和打包。
公网源码下载不稳定时，可将完整 tar 包预置到
`/opt/tolink/dev/jenkins/incoming/<workspace>-dev.tgz`；下一次对应构建会校验并消费该文件，随后仍在
Primary 完成镜像构建。

## 启动顺序

应用 startup 钩子依赖以下服务**已就绪**（见 [src/main.py](../../src/main.py)）：

1. Redis（缓存层初始化）
2. MySQL（连接池建立）
3. RabbitMQ 连接建立，幂等声明 Queue / DLX / DLT
4. RabbitMQ 消费者启动（订阅 `tolink.rag.parse_task` 与 `tolink.rag.document_delete`）

任何一项未就绪都会导致 `uvicorn` 启动失败。推荐顺序：

```bash
# 1. 起依赖
docker compose up -d

# 2. 等核心依赖 healthy（mysql/redis/rabbitmq 有 healthcheck）
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
| RabbitMQ | `docker compose ps rabbitmq` | `healthy` |
| MinIO | `curl http://localhost:9000/minio/health/live` | 200 |
| Manticore | `docker compose ps manticore` | `healthy` |

常见失败：

- **应用启动卡在 RabbitMQ**：检查 `MQ_VENDOR=rabbitmq`、`RABBITMQ_URL` 的 vhost URL 编码、Java `RABBITMQ_*` 配置和 Broker health；容器内使用 Compose DNS，不走宿主机管理端口。
- **API 调用 LLM 报解密失败**：`API_KEY_ENCRYPTION_SECRET` 必须与 Java 管理端的加密 Secret 一致，否则 `llm_model_config.api_key` 密文无法解密。
- **解析任务消费不到**：运行 `rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers`，确认同名 Queue 已声明且消费者数大于 0。

## 生产部署注意事项

根目录 `docker-compose.yml` 只覆盖主机服务器中间件，且使用本地数据卷和示例配置，不能直接作为完整生产拓扑使用：

- 所有密码硬编码为 `ql354210`，生产必须替换。
- MySQL/Redis/MinIO 用 root/默认账号且无 TLS，生产应改用专用账户与加密连接。
- RabbitMQ AMQP 端口仅绑定对应服务器的 Tailscale 地址；本地跨主机调试依赖 Tailscale 加密隧道，
  不得将 `5672` 暴露到公网。正式公网跨主机访问必须改用 TLS（AMQPS）。
- 数据卷为本地 docker volume，生产应挂载持久化存储或使用托管服务。

生产环境建议：

1. **外部依赖托管化**：MySQL、RabbitMQ、MinIO/S3、Qdrant 使用云厂商托管或独立部署，应用容器只跑 FastAPI 进程。
2. **配置外部化**：`.env` 通过 Secret Manager（如 K8s Secret、Vault）注入，不打进镜像。
3. **多副本与扩缩容**：FastAPI 进程可水平扩展；RabbitMQ 同一 Queue 的多个消费者采用竞争消费，使用 prefetch 控制单消费者在途任务数。
4. **拓扑初始化**：Java/Python 使用完全一致的 durable Queue、DLX 和 DLT 参数幂等声明，禁止单独手工创建参数不同的同名 Queue。
5. **Manticore 高可用**：BM25 固定依赖 Manticore；根 Compose 仅为单节点，不具备生产 HA。生产部署前必须另行完成副本/备份、故障恢复演练与容量压测。
6. **Qdrant 单 collection 切换**：历史向量无需保留时，先停止写入并删除旧 bucket collections，再部署使用 `CHUNK_INDEX_COLLECTION_NAME` 的应用，由首次 dense/sparse 写入创建统一业务 collection。操作后需验证 Qdrant、Manticore、RAG readiness 和一次真实解析/召回链路。

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
>
> 0036 会自动复用旧 `llm_system_preset` 中六类系统配置的加密 API Key，存量库不需要额外的
> preflight 或授权文件。全新空库没有可复用密钥时，需通过
> `TOLINK_LLM_SEED_CIPHERTEXT_FILE` 指定包含六类能力密文的 JSON 文件。

应用进程**不会**自动建表，必须先执行 DDL。

## 相关文档

- 配置项详解：[configuration.md](configure.md)
- MQ 接入对接：[mq_integration.md](../api/mq_contracts.md)
- 项目架构：[docs/internals/project_structure.md](../internals/project_structure.md)
