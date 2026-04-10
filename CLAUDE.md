# Claude Code 项目上下文

## 项目概述

- **项目名称**: toLink-Rag
- **类型**: RAG (Retrieval Augmented Generation) 系统
- **Python 版本**: 3.10+

## 项目结构

```
toLink-Rag/
├── src/                    # 源代码
│   ├── api/               # FastAPI 路由层
│   │   └── routes/       # API 路由模块
│   ├── core/             # 核心业务逻辑
│   │   ├── llm/         # 多 LLM 接入
│   │   ├── document_parser/  # 文档解析
│   │   ├── splitter/     # 文本分片
│   │   ├── embedding/    # Embedding 引擎
│   │   ├── vector_store/ # 向量存储
│   │   └── retrieval/    # 检索器
│   ├── services/         # 服务层
│   ├── models/           # 数据模型
│   └── utils/            # 工具函数
├── tests/                # 测试目录
└── docs/                 # 技术文档
```

## 技术栈

- FastAPI (Web 框架)
- LangChain (RAG 编排)
- ChromaDB / Milvus (向量数据库)
- Elasticsearch (全文索引)
- PostgreSQL (元数据)
- S3 / MinIO (对象存储)
- Redis (缓存/队列)
- Pydantic (数据验证)

## 核心模块

| 模块 | 路径 | 说明 |
|------|------|------|
| main.py | src/main.py | FastAPI 应用入口 |
| documents.py | src/api/routes/documents.py | 文档管理接口 |
| chat.py | src/api/routes/chat.py | 问答接口 |

## 环境变量

参考 `.env.example`:
- `OPENAI_API_KEY` - OpenAI API Key
- `OPENAI_BASE_URL` - OpenAI API 地址
- `EMBEDDING_MODEL` - Embedding 模型
- `LLM_MODEL` - LLM 模型

## 开发命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
cd src && uvicorn main:app --reload

# 运行测试
pytest tests/ -v
```

## 注意事项

- 所有配置通过环境变量管理，不硬编码敏感信息
- 使用 Pydantic 进行数据验证和类型安全
- 遵循 RESTful API 设计规范
