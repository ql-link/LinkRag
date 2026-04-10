# toLink-Rag 项目架构文档

## 1. 项目概述

**项目名称**: toLink-Rag
**项目类型**: Retrieval Augmented Generation (RAG) 系统
**技术栈**: Python 3.10+ / FastAPI / LangChain / ChromaDB / OpenAI
**项目目标**: 提供文档检索增强生成能力，支持上传文档、构建向量索引、语义检索和问答

---

## 2. 推荐项目结构

```
toLink-Rag/
├── README.md                      # 项目说明文档
├── ARCHITECTURE.md                # 本文档
├── CLAUDE.md                      # Claude Code 项目上下文
├── requirements.txt               # Python 依赖
├── pyproject.toml                 # 项目元数据和构建配置
├── .env.example                   # 环境变量示例
├── .gitignore                     # Git 忽略配置
│
├── src/                           # 源代码目录
│   ├── __init__.py
│   ├── main.py                    # FastAPI 应用入口
│   ├── config.py                  # 配置管理
│   │
│   ├── api/                       # API 层
│   │   ├── __init__.py
│   │   ├── routes/                # 路由模块
│   │   │   ├── __init__.py
│   │   │   ├── documents.py       # 文档管理接口
│   │   │   ├── embeddings.py      # Embedding 接口
│   │   │   └── chat.py            # 问答聊天接口
│   │   ├── deps.py                # 依赖注入
│   │   └── schemas.py             # Pydantic 数据模型
│   │
│   ├── core/                      # 核心业务逻辑
│   │   ├── __init__.py
│   │   ├── llm/                   # 多 LLM 接入
│   │   │   ├── base.py
│   │   │   ├── openai_llm.py
│   │   │   ├── anthropic_llm.py
│   │   │   └── factory.py
│   │   ├── document_parser/       # 文档解析
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   └── parsers/
│   │   ├── splitter/              # 文本分片
│   │   │   ├── base.py
│   │   │   ├── recursive_splitter.py
│   │   │   └── semantic_splitter.py
│   │   ├── embedding/             # Embedding 引擎
│   │   ├── vector_store/           # 向量存储
│   │   ├── retrieval/             # 检索器
│   │   └── graphrag/              # GraphRag (可选)
│   │
│   ├── services/                  # 服务层
│   │   ├── __init__.py
│   │   ├── document_service.py    # 文档服务
│   │   ├── index_service.py       # 索引服务
│   │   ├── search_service.py      # 搜索服务
│   │   └── chat_service.py        # 问答服务
│   │
│   ├── models/                    # 数据模型
│   │   ├── __init__.py
│   │   ├── document.py
│   │   ├── chunk.py
│   │   └── conversation.py
│   │
│   └── utils/                     # 工具函数
│       ├── __init__.py
│       └── logger.py
│
├── tests/                         # 测试目录
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api/
│   │   ├── __init__.py
│   │   ├── test_documents.py
│   │   └── test_chat.py
│   └── test_core/
│       ├── __init__.py
│       ├── test_llm/
│       ├── test_document_parser/
│       └── test_splitter/
│
└── docs/                          # 技术文档目录
    └── *.md
```

---

## 3. 模块设计

### 3.1 API 层 (`api/`)

| 模块 | 功能 | 主要接口 |
|------|------|----------|
| `documents.py` | 文档管理 | POST /documents/upload, GET /documents/{id}, DELETE /documents/{id} |
| `embeddings.py` | Embedding 管理 | POST /embeddings/build, GET /embeddings/status |
| `chat.py` | 问答对话 | POST /chat/ask, GET /chat/history |

### 3.2 核心逻辑层 (`core/`)

| 模块 | 功能 | 依赖库 |
|------|------|--------|
| `document_loader.py` | 加载 PDF/TXT/DOCX/HTML 等格式文档 | langchain, unstructured |
| `text_splitter.py` | 将长文本分割成小块 | langchain |
| `embedding_engine.py` | 生成文本向量 | openai / sentence-transformers |
| `vector_store.py` | 向量存储和相似度检索 | chromadb / faiss |
| `retriever.py` | 检索器，支持混合检索 | langchain |

### 3.3 服务层 (`services/`)

| 模块 | 功能 |
|------|------|
| `document_service.py` | 文档上传、存储、状态管理 |
| `index_service.py` | 构建和维护向量索引 |
| `search_service.py` | 语义搜索封装 |
| `chat_service.py` | RAG 问答流程编排 |

---

## 4. 技术选型

### 4.1 核心依赖

| 用途 | 库 | 说明 |
|------|-----|------|
| Web 框架 | FastAPI | 高性能异步 API |
| 数据验证 | Pydantic | 类型安全的数据模型 |
| 文档处理 | LangChain | RAG 流程编排 |
| 文档解析 | unstructured | 多格式文档解析 |
| 向量数据库 | ChromaDB | 轻量级向量存储 |
| Embedding | OpenAI text-embedding-3 / Sentence-Transformers | 文本向量化 |
| LLM | OpenAI GPT-4 / Claude / 本地模型 | 生成回答 |
| 异步任务 | Celery + Redis | 异步索引构建 |

### 4.2 开发依赖

| 用途 | 库 |
|------|-----|
| 测试 | pytest, pytest-asyncio, httpx |
| 代码格式 | black, isort |
| 类型检查 | mypy |
| 文档 | mkdocs, mkdocstrings |

---

## 5. API 设计

### 5.1 文档管理

```
POST   /api/v1/documents/upload     # 上传文档
GET    /api/v1/documents            # 列出所有文档
GET    /api/v1/documents/{id}       # 获取文档详情
DELETE /api/v1/documents/{id}       # 删除文档
```

### 5.2 索引管理

```
POST   /api/v1/index/build          # 构建索引
GET    /api/v1/index/status         # 查看索引状态
POST   /api/v1/index/rebuild        # 重建索引
```

### 5.3 问答

```
POST   /api/v1/chat/ask             # 提问
GET    /api/v1/chat/history/{session_id}  # 获取对话历史
```

---

## 6. 数据流

```
用户上传文档
    ↓
document_service (文件暂存)
    ↓
S3/MinIO (存储原始文件)
    ↓
document_parser (解析内容)
    ↓
text_splitter (切分文本)
    ↓
embedding_engine (生成向量)
    ↓
    ├──→ ChromaDB (向量 + 原文)
    ├──→ ES (全文索引)
    └──→ PostgreSQL (元数据: document, tags)
    ↓
用户提问
    ↓
chat_service (检索)
    ↓
    ├──→ ES (关键词召回)
    └──→ ChromaDB (向量召回)
    ↓
reranker (重排序)
    ↓
LLM (基于上下文生成回答)
    ↓
返回答案
```

---

## 7. 配置管理

所有配置通过 `src/config.py` 集中管理，支持从环境变量读取：

```python
# 环境变量
# LLM 配置
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4

# Embedding 配置
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536

# 存储配置
POSTGRES_URL=postgresql+asyncpg://user:pass@localhost:5432/tolink_rag
REDIS_URL=redis://localhost:6379/0
CHROMA_PERSIST_DIR=/data/chroma  # ChromaDB 持久化目录

# 对象存储
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=xxx
S3_SECRET_KEY=xxx
S3_BUCKET=tolink-documents

# ES 配置
ES_URL=http://localhost:9200
```

---

## 8. 部署架构

### 8.1 存储层说明

| 存储类型 | 用途 | 选型 |
|----------|------|------|
| **PostgreSQL** | 文档元数据、用户数据、标签 | 主数据存储 |
| **ChromaDB / Milvus** | 向量存储、相似度检索 | 核心向量数据库 |
| **Elasticsearch** | 全文索引、关键词检索、多路召回 | 搜索引擎 |
| **S3 / MinIO** | 原始文档文件存储 | 对象存储 |
| **Redis** | 缓存、消息队列、Session | 缓存层 |

### 8.2 开发环境
```
FastAPI (uvicorn)
    ↓
PostgreSQL (SQLite mode)  ← 开发用简化
ChromaDB (持久化)
Elasticsearch (Docker)
```

### 8.3 生产环境
```
Nginx
    ↓
FastAPI (gunicorn + uvicorn workers)
    ↓
Celery Workers (异步任务)
    ↓
Redis (消息队列)
        │
        ├──→ ChromaDB / Milvus (向量数据库)
        ├──→ PostgreSQL (元数据)
        ├──→ Elasticsearch (全文索引)
        └──→ S3 / MinIO (原始文件)
```

---

## 9. 开发指南

### 9.1 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 复制环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 启动服务
cd src
uvicorn main:app --reload --port 8000
```

### 9.2 运行测试

```bash
pytest tests/ -v
```

---

## 10. 后续规划

- [ ] 多 LLM 接入模块
- [ ] 文档解析 + 分片模块
- [ ] 向量存储 + 检索模块
- [ ] 多路召回模块
- [ ] 元数据 + 标签体系
- [ ] 索引管理
- [ ] QA 问答对生成
- [ ] 评估体系
- [ ] GraphRag
- [ ] 缓存层
- [ ] 权限管理

---

*文档版本: 1.0.0*
*创建日期: 2026-04-09*
