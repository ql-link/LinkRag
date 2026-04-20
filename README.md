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

## 文档解析（PDF 后端）

`PDF` 支持多后端解析与回退链（见 `src/config.py` / `.env.example`）：

- `PDF_PARSER_BACKEND`: `naive` / `docling`
- `PDF_PARSER_FALLBACKS`: 逗号分隔的回退链（例如 `docling,naive`）

图片处理：

- `docling` 会优先产出页面图 / 图形图 / 表格图资产并上传到 MinIO
- 当 `docling` 资产缺失时，回退到 `PyMuPDF` 提取内嵌图；若仍无图则回退为整页渲染图
- Markdown 中会将图片占位符替换为 MinIO URL 引用
- 可通过 `DOCLING_IMAGES_SCALE` 与 `DOCLING_FORCE_FULL_PAGE_OCR` 调整 `docling` 解析策略

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
