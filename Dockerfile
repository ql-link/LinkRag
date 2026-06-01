# syntax=docker/dockerfile:1

# Python 3.11：infinity-sdk 等依赖要求 >=3.11
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# 不设 PIP_NO_CACHE_DIR：配合下方 BuildKit 缓存挂载，让 pip 复用已下载的 wheel

WORKDIR /app

# opencv-python-headless 等需要的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（package 安装需要源码在场，故连同 src 一起拷入做缓存层）
COPY pyproject.toml README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install . -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120

# 拷入其余运行所需文件（迁移、脚本、alembic 配置等）
COPY . .

# NLTK 数据：构建时下载到镜像内固定目录，固化进镜像层。
# 运行时由 src.nltk_bootstrap 读取 NLTK_DATA 优先命中，避免依赖用户家目录或运行时联网下载。
ENV NLTK_DATA=/app/nltk_data
RUN python scripts/setup_nltk_data.py

EXPOSE 8000

# 生产不开 --reload；如需多 worker 改为 gunicorn -k uvicorn.workers.UvicornWorker
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
