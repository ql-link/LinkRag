# 部署目录说明

`deploy/` 保存 LinkRag 各环境的容器编排、镜像构建、配置模板和 Jenkins 部署入口。
它描述的是部署边界与运行时装配方式；具体环境变量含义和完整运维流程见
[部署文档](../docs/ops/deploy.md) 与 [配置文档](../docs/ops/configure.md)。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `docker-compose.yml` | 保留的 Python RAG 单服务部署入口 |
| `host-server/` | 主机服务器的共享中间件编排 |
| `cloud-server/` | 云服务器生产应用、数据和日志组件编排 |
| `dev-server/` | Primary 开发环境的独立编排、构建脚本和配置模板 |
| `observability/` | Loki、Promtail 等观测配置的公共模板 |

## 开发环境

`dev-server/` 面向开发主机 `primary-host`，使用独立的 Compose 网络、容器、数据卷、
数据库和对象存储资源，不应连接或覆盖生产环境。

主要入口如下：

- `docker-compose.yml`：开发中间件和应用编排。
- `build-component-on-primary.sh`：被 Jenkins 的 RAG、Java Service、Web 三个 Dev 作业调用，
  负责拉取源码、构建镜像、执行必要迁移并部署组件。
- `configure-dev-env.sh`：根据开发主机上的配置和密钥生成运行时配置；生成的密钥文件不得提交到 Git。
- `generate-dev-llm-migration-inputs.py`：为开发环境迁移生成 dev-only 的加密输入。
- `jenkins-*-dev.xml`：三个开发 Jenkins Pipeline 的 Job 定义。
- `Dockerfile.service`：Java Service 开发镜像的构建文件。

开发环境的 `.env`、`.local`、`secrets/` 内容只应保存在开发主机，并使用 `600` 权限；不要把真实
密码、API Key、JWT Secret 或加密密钥写入仓库或镜像。

## 生产环境

- `cloud-server/docker-compose.yml`：云服务器生产应用栈，包括 RabbitMQ、Java、Python RAG、Web 和 Promtail。
- `cloud-server/data-compose.yml`：生产数据与基础设施栈，包括 MySQL、Redis、MinIO、Qdrant、Manticore 和 Loki。
- `host-server/docker-compose.yml`：主机服务器共享中间件编排。
- 根目录 `Jenkinsfile` 使用 `deploy/docker-compose.yml` 作为生产 RAG 的单服务部署入口。

生产密钥使用服务器上的 `.env.production.local` 或独立配置文件注入，不能用开发环境的配置替代。
生产部署前应确认 Compose 网络、数据卷、端口绑定和密钥挂载路径，避免误操作开发或生产资源。

## 修改约定

1. 先确认目标环境：`dev-server/` 只服务开发，`cloud-server/` 和生产 Jenkins 流程服务生产。
2. 修改部署脚本或 Compose 后，运行对应的 Shell/Python 语法检查和相关测试。
3. 不提交服务器生成的 `.local`、`secrets/`、日志、迁移密文和真实配置。
4. 任何会重建容器、迁移数据库或影响数据卷的操作，都必须先核对目标环境和服务名称。
