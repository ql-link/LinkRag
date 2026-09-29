# Java 接口迁移：本地全量请求验收（2026-09-29）

> 后续修复记录：本报告保留首次验收时的原始结果。之后 B5 Markdown 图片资源包上传的 503 缺口已在本工作树修复；本地前端代理连接 Dev MySQL、MinIO 和 MQ 的命中图片资源包上传、manifest 读取、规范化 Markdown 下载与解析至 `parse_success` 已复测通过。缺图 409 和显式忽略缺图已复测；最新代码回归为 35/35 项断言通过。额外验证了 5000 个 `assetInventoryPaths` 字段的 multipart 上传及异步落盘，测试记录与 RAW 对象已清理。B3 临时厂商连接真实 models.dev 完成同步、候选审核及单/批量发布，15 项断言通过，相关数据已清理。按相同口径，98 个路由中已有 96 个成功路径证据；管理员全量排序仍只测了非法列表，固定缺失对象预览路径按预期为 404。单元测试 1337 项通过；修复旧集成测试的执行上下文、Qdrant 认证与固定 PDF 夹具后，使用本地 tokenizer 依赖完整复测为 32 passed、34 skipped、0 failed。首次失败结果仍按下文保留作追溯。

本次使用本地 Python 后端 `127.0.0.1:8080`、本地 LinkRag-Web 前端代理 `127.0.0.1:3001`，连接开发环境 MySQL、Redis、RabbitMQ、MinIO、Qdrant、Loki 和模型服务。没有启动 Java 后端。测试账号、数据库记录及上传对象在测试后按精确标识清理。

## 验收结论

从 Java Controller 提取的 98 个 HTTP 方法与路径，在 Python OpenAPI 中均有对应路由，并均完成匿名与带身份请求，共 196 次探测。逐接口业务流程中，92 个路由有 200 成功路径证据；其余 6 个仅有预期错误或缺失对象的响应证据，详见下表。路由探测的 400/404 只证明请求进入目标路由及校验逻辑，不能视为业务成功。

本次不能判定“全量迁移验收通过”：`POST /api/v1/datasets/{datasetId}/files` 的普通文件分支完成上传、MQ 解析与删除，但 Markdown 图片资源包分支返回 503，尚未切流。模型目录同步与候选审核发布的成功路径没有在共享开发环境执行；`/api/v1/oss-files/public/__missing__` 是 Java 中固定的缺失对象探测路径，按预期返回 404，公开预览的成功路径已用真实对象另行验证。

## 执行结果

- 单元测试：`python3 -m pytest -q tests/unit`，1327 passed。
- 开发环境连通性集成测试：`TOLINK_ENV_FILE=.env.development python3 -m pytest -q --run-integration tests/integration/test_connectivity.py`，4 passed、1 skipped。首次完整集成套件结果为 20 passed、34 skipped、12 failed：10 个 DAG 解析测试未像生产入口那样注入数据集模型执行上下文，2 个 PDF 测试依赖不存在的固定 MinIO 源文件；后续复测还发现 DAG 校验辅助客户端缺少 Qdrant API key。修正测试后，使用 `PYTHONPATH=/private/tmp/linkrag-infinity:. TOLINK_ENV_FILE=.env.development python3 -m pytest -q tests/integration --run-integration --tb=short --show-capture=no` 得到 32 passed、34 skipped。首次未加载开发环境配置的运行结果不作为判定依据。
- B1/B8/B9/B10 真实流程：45/45 预期断言通过，覆盖注册登录、角色与禁用、配置写入恢复、Loki、博客发布与撤回、反馈、退出登录。
- B2 上传补测：13/13 预期断言通过，覆盖六类通用上传、真实对象预览字节校验、管理员厂商图标、用户头像；8 个对象已删除。
- B3 真实流程：40/40 预期断言通过，覆盖厂商与模型增删改、启停、用户和系统配置、默认值、权限与错误路径。外部模型目录同步和候选发布尚无成功路径证据。
- B4–B7 真实流程：43/43 脚本预期断言通过，覆盖数据集、解析配置、会话、文件、内部下载、MQ 解析至 `parse_success`、真实 RAG SSE 至 `answer_done`、用量查询及删除。其中资源包上传的 503 被脚本当作**已知缺口的预期响应**，绝不算迁移通过。RAG 首次受本地缺少锁定的 `infinity-sdk` 依赖影响返回 500；离线补齐到临时目录并重启后复测通过。
- 完成后本地前后端均返回 HTTP 200。

## 98 个接口逐项记录

“成功路径”列的“是”表示在本次独立业务流程脚本中收到 200；“否”表示仅有下列探测状态或预期错误。探测状态取带身份请求的 HTTP 状态，管理员日志一项在修正本地 Loki 地址后复测为 200。所有路径均在 Python OpenAPI 中匹配。

| # | 方法 | Java 路径 | 带身份探测 | 成功路径 |
| ---: | --- | --- | ---: | --- |
| 1 | `GET` | `/api/v1/admin/users` | 200 | 是 |
| 2 | `GET` | `/api/v1/admin/users/dashboard` | 200 | 是 |
| 3 | `PATCH` | `/api/v1/admin/users/{id}/status` | 400 | 是 |
| 4 | `PATCH` | `/api/v1/admin/users/{id}/role` | 400 | 是 |
| 5 | `GET` | `/api/v1/admin/providers` | 200 | 是 |
| 6 | `GET` | `/api/v1/admin/document-file-config` | 200 | 是 |
| 7 | `PUT` | `/api/v1/admin/document-file-config` | 400 | 是 |
| 8 | `POST` | `/api/v1/admin/providers` | 400 | 是 |
| 9 | `POST` | `/api/v1/admin/providers/icon` | 400 | 是 |
| 10 | `PATCH` | `/api/v1/admin/providers/{id}` | 404 | 是 |
| 11 | `PUT` | `/api/v1/admin/providers/order` | 400 | 否 |
| 12 | `DELETE` | `/api/v1/admin/providers/{id}` | 404 | 是 |
| 13 | `PATCH` | `/api/v1/admin/providers/{id}/active` | 400 | 是 |
| 14 | `GET` | `/api/v1/admin/provider-models` | 200 | 是 |
| 15 | `POST` | `/api/v1/admin/providers/{providerId}/models` | 400 | 是 |
| 16 | `DELETE` | `/api/v1/admin/provider-models/{id}` | 404 | 是 |
| 17 | `PATCH` | `/api/v1/admin/provider-models/{id}` | 404 | 是 |
| 18 | `PATCH` | `/api/v1/admin/provider-models/{id}/active` | 400 | 是 |
| 19 | `POST` | `/api/v1/admin/providers/{providerId}/model-sync` | 404 | 否 |
| 20 | `GET` | `/api/v1/admin/model-sync-jobs` | 200 | 是 |
| 21 | `GET` | `/api/v1/admin/model-sync-candidates` | 200 | 是 |
| 22 | `POST` | `/api/v1/admin/model-sync-candidates/{id}/publish` | 404 | 否 |
| 23 | `POST` | `/api/v1/admin/model-sync-candidates/publish` | 400 | 否 |
| 24 | `PATCH` | `/api/v1/admin/model-sync-candidates/{id}/review` | 400 | 否 |
| 25 | `GET` | `/api/v1/admin/feedback` | 200 | 是 |
| 26 | `GET` | `/api/v1/admin/feedback/{id}` | 404 | 是 |
| 27 | `PATCH` | `/api/v1/admin/feedback/{id}/status` | 400 | 是 |
| 28 | `PATCH` | `/api/v1/admin/feedback/{id}/priority` | 400 | 是 |
| 29 | `PATCH` | `/api/v1/admin/feedback/{id}/reply` | 400 | 是 |
| 30 | `GET` | `/api/v1/admin/llm/configs` | 200 | 是 |
| 31 | `POST` | `/api/v1/admin/llm/configs` | 400 | 是 |
| 32 | `PUT` | `/api/v1/admin/llm/configs/{configId}` | 404 | 是 |
| 33 | `PATCH` | `/api/v1/admin/llm/configs/{configId}/active` | 400 | 是 |
| 34 | `POST` | `/api/v1/admin/llm/configs/{configId}/emergency-disable` | 404 | 是 |
| 35 | `DELETE` | `/api/v1/admin/llm/configs/{configId}` | 404 | 是 |
| 36 | `GET` | `/api/v1/admin/logs` | 502 → 200 复测 | 是 |
| 37 | `GET` | `/api/v1/admin/logs/labels` | 200 | 是 |
| 38 | `POST` | `/api/v1/auth/login` | 400 | 是 |
| 39 | `POST` | `/api/v1/auth/register` | 400 | 是 |
| 40 | `POST` | `/api/v1/auth/logout` | 200 | 是 |
| 41 | `GET` | `/api/v1/admin/blog/posts` | 200 | 是 |
| 42 | `GET` | `/api/v1/admin/blog/posts/{postId}` | 404 | 是 |
| 43 | `POST` | `/api/v1/admin/blog/posts` | 400 | 是 |
| 44 | `PATCH` | `/api/v1/admin/blog/posts/{postId}` | 404 | 是 |
| 45 | `POST` | `/api/v1/admin/blog/posts/{postId}/content/import` | 400 | 是 |
| 46 | `POST` | `/api/v1/admin/blog/posts/{postId}/content` | 400 | 是 |
| 47 | `PUT` | `/api/v1/admin/blog/posts/{postId}/content` | 400 | 是 |
| 48 | `POST` | `/api/v1/admin/blog/posts/{postId}/publish` | 404 | 是 |
| 49 | `POST` | `/api/v1/admin/blog/posts/{postId}/unpublish` | 404 | 是 |
| 50 | `DELETE` | `/api/v1/admin/blog/posts/{postId}` | 404 | 是 |
| 51 | `GET` | `/api/v1/admin/blog/posts/{postId}/assets` | 404 | 是 |
| 52 | `POST` | `/api/v1/admin/blog/posts/{postId}/assets` | 400 | 是 |
| 53 | `DELETE` | `/api/v1/admin/blog/posts/{postId}/assets/{assetId}` | 404 | 是 |
| 54 | `GET` | `/api/v1/blog/posts` | 200 | 是 |
| 55 | `GET` | `/api/v1/blog/posts/{slug}` | 400 | 是 |
| 56 | `POST` | `/api/v1/chat/conversations` | 400 | 是 |
| 57 | `GET` | `/api/v1/chat/conversations` | 200 | 是 |
| 58 | `GET` | `/api/v1/chat/conversations/{id}/messages` | 404 | 是 |
| 59 | `PATCH` | `/api/v1/chat/conversations/{id}` | 404 | 是 |
| 60 | `DELETE` | `/api/v1/chat/conversations/{id}` | 404 | 是 |
| 61 | `GET` | `/api/v1/llm/configs` | 200 | 是 |
| 62 | `POST` | `/api/v1/llm/configs/setup-provider` | 400 | 是 |
| 63 | `PATCH` | `/api/v1/llm/configs/{configId}/active` | 400 | 是 |
| 64 | `POST` | `/api/v1/llm/configs/{configId}/emergency-disable` | 400 | 是 |
| 65 | `DELETE` | `/api/v1/llm/configs/{configId}` | 404 | 是 |
| 66 | `GET` | `/api/v1/llm/defaults` | 200 | 是 |
| 67 | `GET` | `/api/v1/llm/defaults/{capability}` | 200 | 是 |
| 68 | `PUT` | `/api/v1/llm/defaults/{capability}` | 400 | 是 |
| 69 | `DELETE` | `/api/v1/llm/defaults/{capability}` | 200 | 是 |
| 70 | `POST` | `/api/v1/datasets` | 400 | 是 |
| 71 | `GET` | `/api/v1/datasets` | 200 | 是 |
| 72 | `GET` | `/api/v1/datasets/{datasetId}` | 404 | 是 |
| 73 | `PATCH` | `/api/v1/datasets/{datasetId}` | 400 | 是 |
| 74 | `DELETE` | `/api/v1/datasets/{datasetId}` | 404 | 是 |
| 75 | `GET` | `/api/v1/datasets/{datasetId}/parse-config` | 404 | 是 |
| 76 | `PUT` | `/api/v1/datasets/{datasetId}/parse-config` | 400 | 是 |
| 77 | `POST` | `/api/v1/datasets/{datasetId}/files` | 404 | 是 |
| 78 | `GET` | `/api/v1/document-file-capabilities` | 200 | 是 |
| 79 | `GET` | `/api/v1/datasets/{datasetId}/files` | 404 | 是 |
| 80 | `GET` | `/api/v1/files/recent` | 200 | 是 |
| 81 | `GET` | `/api/v1/files/{fileId}` | 404 | 是 |
| 82 | `POST` | `/api/v1/files/{fileId}/parse` | 404 | 是 |
| 83 | `DELETE` | `/api/v1/files/{fileId}` | 404 | 是 |
| 84 | `GET` | `/api/v1/datasets/{datasetId}/files/parse-results` | 404 | 是 |
| 85 | `POST` | `/api/v1/feedback` | 400 | 是 |
| 86 | `GET` | `/api/v1/internal/files/{fileId}/content` | 401 | 是 |
| 87 | `POST` | `/api/v1/knowledge/chunks/batch` | 400 | 是 |
| 88 | `GET` | `/api/v1/oss-files/public/__missing__` | 404 | 否 |
| 89 | `POST` | `/api/v1/oss-files/{bizType}` | 400 | 是 |
| 90 | `GET` | `/api/v1/llm/providers` | 200 | 是 |
| 91 | `GET` | `/api/v1/llm/usage/summary` | 400 | 是 |
| 92 | `GET` | `/api/v1/llm/usage/daily` | 400 | 是 |
| 93 | `GET` | `/api/v1/llm/usage/logs` | 400 | 是 |
| 94 | `GET` | `/api/v1/llm/usage/by-model` | 400 | 是 |
| 95 | `GET` | `/api/v1/llm/usage/trend` | 400 | 是 |
| 96 | `GET` | `/api/v1/user/profile` | 200 | 是 |
| 97 | `PATCH` | `/api/v1/user/profile` | 200 | 是 |
| 98 | `POST` | `/api/v1/user/avatar` | 400 | 是 |

## 未通过和未覆盖项

1. Markdown 图片资源包上传返回 503。当前路由对 `matchMode`、`documentPath`、`assets` 等字段直接拒绝；这是实际迁移功能缺口，不是测试环境问题。
2. 厂商全量排序只测试了非法不完整列表的 400；有效排序会改写全部现有厂商的优先级，本次未对共享开发数据执行。
3. `models.dev` 外部目录同步、单条及批量候选发布、候选审核仅验证了不存在或非法输入的错误路径。要验证成功路径，应使用隔离的模型目录数据或可回滚的开发数据快照；本次没有把共享目录批量写入当作无害测试。
4. 公开资源固定路径 `/api/v1/oss-files/public/__missing__` 按预期 404；另一个真实上传对象的公开预览返回 200 且内容字节一致。
5. 首次完整集成套件有 12 个失败，原因是旧 DAG 测试缺少生产入口传入的执行上下文，旧 PDF 测试依赖固定 MinIO 对象。后续已修复并完整复测为 32 passed、34 skipped。没有同时运行旧 Java 服务进行同一输入的双端结果对比，因此不能凭本次测试断言两端行为逐字段完全一致。

## 数据处理

测试共清理 5 个临时用户、2 个数据集、2 个原始文件记录、1 个临时厂商及其模型、配置与相关登录/用量记录；B2 的 8 个 MinIO 测试对象已删除。解析和删除使用了真实 MQ；删除消息按现有异步流程处理。测试脚本和原始 JSON 结果保存在本机 `/private/tmp/`，没有提交测试密钥。
