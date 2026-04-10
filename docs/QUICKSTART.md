# toLink-Rag 快速上手指南 (Quickstart)

本文档旨在帮助开发人员从零开始，快速在本地环境中拉取项目、配置依赖与环境变量，并通过连通性测试脚本验证基础设施配置。

## 1. 代码拉取与准备 (Pull Project)

首先，将代码仓库拉取到本地开发机：

```bash
git clone <repository_url> toLink-Rag
cd toLink-Rag
```
*(注意：请将 `<repository_url>` 替换为实际的 Git 仓库地址)*

## 2. 虚拟环境与依赖管理 (Environment Setup)

我们推荐使用 Python 的 `venv` 模块来隔离项目的依赖环境，避免包版本冲突。（建议 Python >= 3.10）

### 2.1 创建并激活虚拟环境

**Mac / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows:**
```bash
python -m venv .venv
.\.venv\Scripts\activate
```
*(激活成功后，命令行提示符前通常会显示 `(.venv)`)*

### 2.2 安装项目依赖库

我们在 `pyproject.toml` 中配置了所有的依赖。使用 `pip` 安装项目所需的基础库以及测试所用的 `dev` 依赖：

```bash
# 升级 pip 以获得更好的依赖解析
pip install --upgrade pip

# 以可编辑模式安装项目核心与开发依赖
pip install -e ".[dev]"
```

## 3. 环境变量配置 (Environment Configuration)

项目中使用了各类中间件与数据库，所有连接信息通过环境变量或者 `.env` 文件进行配置。

### 3.1 创建 `.env` 文件

在项目根目录下创建一个 `.env` 文件：

```bash
cp .env.example .env 
```
*(如果没有 `.env.example`，请直接新建一个名为 `.env` 的文件)*

### 3.2 修改环境变量配置

根据您的具体开发环境或远端基础设施，编辑 `.env` 文件。核心需要关注的服务连通性配置如下：

```dotenv
# MySQL 数据库
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=your_mysql_user
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=your_database

# Redis 缓存
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Milvus 向量数据库
MILVUS_URI=http://127.0.0.1:19530
MILVUS_USER=root
MILVUS_PASSWORD=

# Elasticsearch
ELASTICSEARCH_URL=http://127.0.0.1:9200
ELASTICSEARCH_USER=elastic
ELASTICSEARCH_PASSWORD=

# MinIO 对象存储
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=your_access_key
MINIO_SECRET_KEY=your_secret_key
MINIO_SECURE=false
```
*(请将凭证信息替换为实际值。如果您在本地通过 `docker-compose.yml` 运行了基础设施，可以使用 `localhost` 或者本地 IP)*

## 4. 运行连通性测试 (Connectivity Verification)

完成上述配置后，运行项目中自带的连通性测试，以验证你的 Python 环境是否能正确访问这些基础设施服务。

进入项目根目录，在激活的虚拟环境中运行：

```bash
pytest tests/test_connectivity.py -v -s
```

如果看到所有测试用例均为 `PASSED`，即代表环境已配置成功（如下所示）：

```text
tests/test_connectivity.py::test_mysql ... PASSED
tests/test_connectivity.py::test_redis ... PASSED
tests/test_connectivity.py::test_milvus ... PASSED
tests/test_connectivity.py::test_elasticsearch ... PASSED
tests/test_connectivity.py::test_minio ... PASSED
```

