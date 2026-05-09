<div align="center">

# LinkRag

面向企业知识库场景的完整 RAG 系统。

</div>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white">
  <img alt="Kafka" src="https://img.shields.io/badge/Kafka-MQ-231F20?logo=apachekafka&logoColor=white">
  <img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-Vector%20Store-DC244C">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-blue">
</p>



## LinkRag 是什么？

`LinkRag` 是一个面向企业知识库场景的完整 RAG 系统，目标是覆盖从文档接入、解析、分片、向量化、检索到生成问答的全链路能力。

当前版本优先打磨 RAG 系统中最关键的知识入库链路：将复杂文档解析为结构化 Markdown，通过层次化语义分片形成可检索的知识单元，再完成 Embedding 与向量索引构建。后续可在此基础上扩展检索、重排、上下文组装和问答生成能力。

## 主要功能

### 高质量文档理解

- 支持 PDF、Word、HTML 等常见文档接入。
- PDF 解析后端可插拔，默认接入 MinerU API。
- 解析结果统一沉淀为 Markdown，便于审计、增强和复用。

### 层次化语义分片

- 结合文档结构和语义边界进行 Chunk 切分。
- 保留标题、表格、图片、代码块等上下文信息。
- 兼顾可解释性、召回质量和后续上下文组装。

### 向量化与索引构建

- 支持 Embedding 批处理和向量索引写入。
- 使用 MySQL 维护 Chunk 状态，便于失败补偿和一致性恢复。
- 当前以 Qdrant 作为主要向量检索存储。

### 企业级异步集成

- 通过 Kafka / RabbitMQ 接入业务系统。
- 支持解析任务投递、终态通知、缓存同步和用量上报。
- 提供 FastAPI 接口，便于调试、联调和二次集成。

## 系统架构

```text
业务系统 / Java 管理端
        |
        | MQ 解析任务
        v
toLink-Rag
        |
        | 文档解析 -> Markdown -> 分片 -> Embedding
        v
MySQL + Qdrant + 对象存储
        |
        | MQ 终态通知
        v
业务系统 / Java 管理端
```

`toLink-Rag` 的目标是成为可嵌入企业业务系统的 RAG 基础平台。当前阶段以文档理解、知识入库和索引构建为核心，后续可继续扩展检索、重排、上下文组装和问答生成能力。

## 快速开始

### 前提条件

- Python `3.10+`
- Docker 与 Docker Compose
- MySQL、Redis、MinIO、Kafka 或 RabbitMQ、Qdrant
- 可用的 LLM / Embedding 服务
- 可选：MinerU API 服务

### 启动依赖

```bash
docker compose up -d
```

### 安装项目

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 准备配置

```bash
cp .env.example .env
```

根据实际环境修改 `.env` 中的数据库、对象存储、MQ、Qdrant、LLM 和 PDF 解析配置。

> 不要将真实密钥、Token、密码提交到仓库。

### 初始化数据库

```bash
mysql -h 127.0.0.1 -P 3306 -u root -p tolink_rag_db < scripts/db/init.sql
```

### 启动服务

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问：

- Swagger UI: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

## 配置说明

常用配置集中在 `.env` 与 `src/config.py`：

- 应用服务：端口、日志、运行环境
- 数据库与缓存：MySQL、Redis
- 对象存储：MinIO / S3 兼容存储
- 消息队列：Kafka / RabbitMQ
- 模型服务：LLM、Embedding、Rerank、OCR
- PDF 解析：MinerU、OpenDataLoader、本地解析回退
- 向量索引：Qdrant collection 与分桶策略

数据库结构以 `scripts/db/init.sql` 为准。

## 源码启动

开发环境推荐直接通过 Uvicorn 启动：

```bash
source .venv/bin/activate
uvicorn src.main:app --reload
```

如果需要完整链路联调，请确认：

- 依赖服务已启动。
- `.env` 中的连接地址可访问。
- MQ topic / queue 已由业务侧或部署流程创建。
- 对象存储中存在待解析文件。
- LLM / Embedding / MinerU 配置可用。

## 测试

运行单元测试：

```bash
.venv/bin/pytest tests/unit -q
```

运行全部测试：

```bash
.venv/bin/pytest tests -q
```

部分集成测试依赖真实外部服务。运行前请阅读 `tests/README.md`，并确认对应环境变量已经配置。

## 技术文档

- [项目架构](./docs/architecture)
- [文件解析模块](./docs/architecture/file_parser_module.md)
- [分片模块](./docs/architecture/chunking_module.md)
- [向量化模块](./docs/architecture/vectorization_module.md)
- [API 约定](./docs/reference/api_contracts.md)
- [错误码](./docs/reference/error_codes.md)
- [数据模型](./docs/reference/data_models.md)
- [命名约定](./docs/conventions/naming_conventions.md)

## 贡献指南

欢迎提交 Issue 和 Pull Request。提交前建议先阅读：

- `AGENTS.md`
- `docs/architecture`
- `docs/conventions`
- `tests/README.md`

请确保新增配置、API、数据结构或模块边界变化时，同步更新相关文档。

## 许可证

本项目基于 MIT License 开源。
