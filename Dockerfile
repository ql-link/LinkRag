# syntax=docker/dockerfile:1

# Python 3.11：infinity-sdk 等依赖要求 >=3.11
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# 不设 PIP_NO_CACHE_DIR：配合下方 BuildKit 缓存挂载，让 pip 复用已下载的 wheel

WORKDIR /app

# opencv-python-headless 等需要的系统库
# 换国内 apt 镜像（清华），避免 deb.debian.org 在国内龟速
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true; \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 先只装依赖：用占位 src 满足 setuptools 构建后端，使「依赖层」独立缓存。
# 这样日常改业务代码不会让 pip 那层失效、不再重装依赖。
COPY pyproject.toml README.md ./
RUN mkdir -p src && touch src/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install . -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120

# 再拷入真实源码与其余文件（迁移、脚本、alembic 配置等）；
# 这层变动不影响上面的依赖层缓存。运行时 uvicorn 从 /app/src 直接加载。
COPY . .

# NLTK 数据：构建时下载到镜像内固定目录，固化进镜像层。
# 运行时由 src.nltk_bootstrap 读取 NLTK_DATA 优先命中，避免依赖用户家目录或运行时联网下载。
ENV NLTK_DATA=/app/nltk_data
# 经 GitHub 加速代理下载 NLTK 数据，避免直连 raw.githubusercontent 国内超时；失败自动回退官方源
ENV NLTK_GH_PROXY=https://gh-proxy.com/
RUN python scripts/setup_nltk_data.py

EXPOSE 8000

# 生产不开 --reload；如需多 worker 改为 gunicorn -k uvicorn.workers.UvicornWorker
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
