# Deployment

部署 toLink-Rag 涉及一个 FastAPI 服务进程和一组外部依赖。本文聚焦 README 快速开始之外的细节：依赖服务清单、启动顺序、健康检查、生产部署注意事项。

完整环境变量解读见 [configuration.md](configure.md)。

## 依赖服务清单

`docker-compose.yml` 提供本地全套依赖：

| 服务 | 镜像 | 主机端口 | 用途 | 必需 |
| --- | --- | --- | --- | --- |
| `mysql` | `mysql:8.0` | 3306 | 用户、LLM 配置、用量记录、Chunk 状态 | ✅ |
| `redis` | `redis:7.2-alpine` | 6379 | 用户 LLM 配置缓存、共享下发 | ✅ |
| `minio` | `minio/minio` | 9000 / 9001 | 原始文档、解析产物的对象存储 | 二选一¹ |
| `qdrant` | `qdrant/qdrant` | 6333 / 6334 | 向量索引存储（默认） | 二选一² |
| `elasticsearch` | `elasticsearch:8.11.3` | 9200 | 向量索引存储（备选） | 二选一² |
| `zookeeper` | `bitnami/zookeeper:3.9` | 2181 | Kafka 协调 | 当 MQ 为 Kafka 时必需 |
| `kafka` | `bitnami/kafka:3.7` | 9092 | 异步消息中台 | 当 `MQ_VENDOR=kafka` 时必需 |
| `kafka-ui` | `provectuslabs/kafka-ui` | 9081 | Kafka 调试 UI | 可选 |

注 1：`STORAGE_TYPE=minio` 使用 MinIO，`STORAGE_TYPE=local` 使用 `LOCAL_DOCS_PATH` 本地目录。
注 2：`VECTOR_STORE_TYPE` 决定使用 `qdrant` 还是 `elasticsearch`。

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
| Swagger | 访问 `http://localhost:8000/docs` | 看到所有路由 |
| MySQL | `docker compose exec mysql mysqladmin ping -uroot -p` | `mysqld is alive` |
| Kafka | `docker compose ps kafka` | `healthy` |
| MinIO | `curl http://localhost:9000/minio/health/live` | 200 |

常见失败：

- **应用启动卡在 Kafka**：通常是 `KAFKA_BOOTSTRAP_SERVERS` 配置错或 broker 未起来。本地用 docker-compose 时此地址应为 `127.0.0.1:9092`（容器内部连接用 `tolink-kafka:29092`）。
- **API 调用 LLM 报解密失败**：`API_KEY_ENCRYPTION_SECRET` 必须与 Java 管理端的加密 Secret 一致，否则 `llm_user_config` 表中的密文无法解密。
- **解析任务消费不到**：检查 `INIT_KAFKA_TOPICS_ON_STARTUP` 是否被关闭，且 topic（`PARSE_TASK_TOPIC` 默认 `tolink-document-pares`）是否已存在。

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

## Python 依赖变更

HTML 解析采用 trafilatura（正文定位/去样板/空内容识别）混合方案：

- 主依赖新增 `trafilatura>=2.0.0`（纯 Python，依赖 lxml，已为现有传递依赖）。
- 移除曾短期引入的 `readability-lxml`（已废弃方案，不再使用）。

Word（.docx）解析采用 mammoth → 复用 HTML 渲染引擎混合方案：

- 主依赖新增 `mammoth>=1.6.0`（纯 Python 轻依赖）。

部署/CI 需 `pip install -e ".[dev]"` 重新安装依赖，确保镜像内含 trafilatura 与
mammoth；否则 HTML / Word 文件解析会在导入期失败。无需额外系统库或二进制。

## 数据库初始化

`migrations/db.sql`（0001 baseline）是冷启动建库入口。首次部署或重置：

```bash
mysql -h ${DB_HOST} -P ${DB_PORT} -u ${DB_USER} -p${DB_PASSWORD} ${DB_NAME} < migrations/db.sql
```

> 建库后按需 `alembic stamp 0001` → `alembic upgrade head` 应用后续迁移。叠加全部迁移后的当前完整结构可查阅 `scripts/db/init.sql`。

应用进程**不会**自动建表，必须先执行 DDL。

## 相关文档

- 配置项详解：[configuration.md](configure.md)
- MQ 接入对接：[mq_integration.md](../api/mq_contracts.md)
- 项目架构：[../architecture](../architecture)
