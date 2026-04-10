# toLink-Rag

Retrieval Augmented Generation (RAG) 系统，提供文档检索增强生成能力。

## 功能特性

- 文档上传与管理（支持 PDF、TXT、DOCX、HTML 等格式）
- 语义检索与向量相似度匹配
- 基于上下文的 RAG 问答
- 异步索引构建
- RESTful API 接口

## 技术栈

- **框架**: FastAPI
- **RAG**: LangChain
- **向量数据库**: ChromaDB
- **Embedding**: OpenAI / Sentence-Transformers

## 快速开始

### 安装依赖

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -e .
```

### 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

### 启动服务

```bash
cd src
uvicorn main:app --reload --port 8000
```

### 运行测试

```bash
pytest tests/ -v
```

## API 文档

启动服务后访问: http://localhost:8000/docs

## 目录结构

```
toLink-Rag/
├── src/                    # 源代码
│   ├── api/                # API 层
│   ├── core/               # 核心逻辑
│   ├── services/           # 服务层
│   ├── models/             # 数据模型
│   └── utils/              # 工具函数
├── tests/                  # 测试
├── data/                   # 数据存储
└── logs/                   # 日志
```

## License

MIT
