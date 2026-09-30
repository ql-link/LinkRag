# API Contracts

本文档记录当前项目 HTTP API 约定。实现来源以 `src/api/routes` 和 `src/api/schemas` 为准。

## 1. 通用约定

- API 前缀按模块划分：`/api/v1/parser`、`/api/v1/mq`、`/api/v1/llm`、`/api/v1/internal/llm`、`/api/v1/rag`、`/api/v1/recall`、`/api/v1/wiki`、`/api/v1/auth`、`/api/v1/user`、`/api/v1/admin/users`、`/api/v1/apps`（接入应用服务端，见 §8）。

- 所有 HTTP 请求可带 `X-Trace-Id` 请求头；未携带时 Python 端生成 UUID。响应会回显本次请求使用的 `X-Trace-Id`，日志上下文同步写入该值。
- 普通 JSON 响应通常使用 `{code, message, data}` 或模块自定义响应模型。
- 解析和 MQ 路由异常通常返回 HTTP `500`，`detail` 为异常文本。
- LLM 路由在业务异常中多返回 `APIResponse(code=500, message=..., data=null)`。
- 路由鉴权覆盖由 `tests/unit/api/test_route_auth_coverage.py` 强制：每条路由必须挂载鉴权依赖，或登记在匿名白名单中。
- `/api/v1/llm/{generate,generate/stream,embed,rerank,ocr}` 要求 `Authorization: Bearer <access-token>`，用户身份只取自 token；不再接受自报的 `X-User-Id`。
- `/api/v1/internal/llm/*` 仅供服务端调用：要求 `Authorization: Bearer <INTERNAL_API_TOKEN>`，未配置令牌时一律 `401`；令牌通过后才信任 `X-User-Id`。公网 nginx 对 `/api/v1/internal/` 返回 `404`。
- `/api/v1/apps/*` 仅接受接入应用凭证（见 §8），公网 nginx 返回 `404`。
- `/api/v1/parser/*`、`/api/v1/mq/*` 为联调调试入口：`DEBUG_ENDPOINTS_ENABLED=false`（默认）时返回 `404`；开启后仍要求 ADMIN 的 `Authorization: Bearer <access-token>`。

### B1 身份与用户接口（按路径切流）

这些路由在 Python 已注册，使用整数 `code` 的 `{code,message,data}` 响应。受保护请求从 `satoken` 请求头读取 Java/Python RS256 access JWT，验签后还要验证会话状态与 `sys_user` 当前角色/状态。未配置 Java 会话桥接或 Python 签发开关时，对应路由会明确拒绝请求；注册路由不代表已切换前端流量。

| Method | Path | 身份 | `data` / 行为 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | 匿名 | `{account,password}`；返回 `accessToken,tokenType,expiresIn,userId`。仅 Java 受保护路由已退场并显式启用 Python 签发后可用。 |
| POST | `/api/v1/auth/register` | 匿名 | `{username,password,email}`；创建 `USER` 后自动登录，响应同上。 |
| POST | `/api/v1/auth/refresh` | 登录用户 | 滑动续期：用仍有效的 `satoken` 换取新 access token（响应同登录），旧 token 随即撤销。需启用 Python 签发。 |
| POST | `/api/v1/auth/logout` | 可匿名调用 | 无效或缺失 token 幂等返回成功；有效 token 撤销本次登录态，`data:null`，Java 旧会话还通过 Java 登出接口撤销。 |
| GET / PATCH | `/api/v1/user/profile` | 登录用户 | 读取/更新当前用户资料；可修改 `nickname,email,phone,avatarUrl,bio(≤200),team(≤64)`（`bio`/`team` 传空白串即清空），响应分别为资料对象/`null`。 |
| POST | `/api/v1/user/password` | 登录用户 | `{currentPassword,newPassword(≥8)}`；当前密码错误 `20008`（400），新旧相同 `20009`（400）。成功后该用户**此前签发的全部 token 失效**（Redis `auth:access:not-before:{user_id}`，按 JWT `iat` 判断，同一秒内签发的旧 token 可能保留至下一秒），并返回为当前客户端新签发的 token（响应同登录）。需启用 Python 签发。 |
| POST | `/api/v1/user/avatar` | 登录用户 | multipart `file`；按文件后缀允许 jpg/jpeg/png/gif/webp，最大 5 MiB，返回更新后的资料对象；格式/大小错误码 40001，上传失败码 50002。 |
| POST | `/api/v1/oss-files/{bizType}` | 登录用户（`satoken`；Java 旧行为为匿名，Python 已收紧）；入口默认关闭 | multipart `file`；六类规则见对象存储内部文档。PUBLIC 返回公开 URL，RAW/PRIVATE 返回 key。需确认权限矩阵后设置 `B2_GENERIC_UPLOAD_ENABLED=true` 并按路径切流；关闭时返回 503。 |
| GET | `/api/v1/oss-files/public/{objectKey}` | 匿名，仅 PUBLIC 桶 | Python 接管此路径且启用 `B2_PUBLIC_PREVIEW_ENABLED` 时，经现有 MinIO 适配器读取公开桶；返回原字节、后缀对应 Content-Type 和 30 天缓存头。非法或不存在 key 返回 404，存储故障返回 503；关闭时返回 503。RAW/PRIVATE 不可由此读取。 |
| GET | `/api/v1/admin/users` | ADMIN | `page` 默认 1、`size` 默认 10；返回 `items,total,page,pageSize,totalPages`。 |
| GET | `/api/v1/admin/users?keyword=&role=&status=&sort=&withStats=true` | ADMIN | 管理台列表：`keyword` 匹配用户名 / 昵称 / 邮箱，纯数字或 `#数字` 同时匹配 ID；`role` ADMIN/USER；`status` 0/1；`sort` `created`（默认）/`lastLogin`；`appCode` 默认 `tolink`，传接入应用编码（如 `linkresume`）查看其影子用户。所有列表项含 `appCode`。带任一筛选或 `withStats=true` 时项额外含 `lastLoginAt,datasetCount,tokens30d`（未删除知识库数、近 30 天总 Token）。 |
| GET | `/api/v1/admin/users/{user_id}` | ADMIN | 资料 + `lastLoginAt` + `stats{datasetCount,fileCount,fileBytes,conversationCount,conversations30d,promptTokens30d,completionTokens30d,tokens30d,modelConfigCount,modelProviders[]}` + `datasets[{id,name,status,fileCount,fileBytes,updatedAt}]` + `recentLogins[{time,success,source,reason,ip,userAgent}]`（最近 10 条，成功事件与失败记录按时间合并；`reason` 为 `BAD_PASSWORD`/`DISABLED`；0043 未迁移时仅成功事件且无 IP/UA）。不存在返回 404 / 20001。 |
| POST | `/api/v1/admin/users/{user_id}/password/reset` | ADMIN | 可选 `{newPassword}`（8–64 位）；不传时生成 12 位临时密码，`data:{temporaryPassword}` 只返回这一次（指定密码时为 null）。该用户此前签发的全部令牌立即失效。与状态修改同受 `B1_JAVA_PROTECTED_ROUTES_RETIRED` 控制，关闭时 503。 |
| PATCH | `/api/v1/admin/users/{user_id}/status` | ADMIN | `{status:0|1}`；`data:null`。Java 受保护路由退场前返回 503，避免禁用状态与旧会话不一致。 |
| PATCH | `/api/v1/admin/users/{user_id}/role` | ADMIN | `{role:"ADMIN"|"USER"}`；`data:null`。 |

资料对象字段为 `id,username,nickname,email,phone,avatarUrl,role,status,bio,team,createdAt`，不包含密码哈希。用户管理看板仍属 B8。身份模块边界与切流条件见 [identity_users.md](../internals/identity_users.md)。

### B3–B5 管理与知识文件迁移接口（实施中）

以下 Python 路由已注册，统一使用 B1 当前用户、数据库角色/归属与 `{code,message,data}`。注册不表示网关已切流；写入开关默认关闭。B3 旧 API Key 无法解密时配置读取返回 503，不能用空密钥替代。

| 范围 | 已实现路径 | 当前限制 |
| --- | --- | --- |
| B3 USER | `GET /api/v1/llm/providers`、`GET /api/v1/llm/configs`、`POST /api/v1/llm/configs/setup-provider`、`PATCH/POST/DELETE /api/v1/llm/configs/{id}/*`、`GET/PUT/DELETE /api/v1/llm/defaults*` | 写入依赖 `B3_CONTROL_WRITES_ENABLED`；现有 Python runtime config cache 写后 fence 失效。 |
| B3 ADMIN | `/api/v1/admin/llm/configs*`、`/api/v1/admin/providers*`、`/api/v1/admin/provider-models*`、`/api/v1/admin/model-sync-*` | ADMIN 身份从数据库读取；图标上传复用 B2。候选只在审核发布后进入正式目录；0040 尚未在 Dev 执行。 |
| B4 数据集 | `GET/POST /api/v1/datasets`、`GET/PATCH/DELETE /api/v1/datasets/{id}`、`GET/PUT /api/v1/datasets/{id}/parse-config` | 创建/更新依赖 `B4_DATASET_WRITES_ENABLED`；删除另依赖 `B5_DELETE_WRITES_ENABLED`。列表与详情每项附 `stats:{fileCount,uploadingCount,failedCount,storageBytes,chunkCount}`（未删除文件与 ACTIVE 分块，列表按当前页批量聚合）。PATCH 可传 `status:"ACTIVE"|"DISABLED"` 启停：停用后 RAG / 召回 / Wiki 按既有 `status` 过滤排除该数据集，管理端仍可见可操作。 |
| B5 文件 | `GET /api/v1/document-file-capabilities`、`GET/POST /api/v1/datasets/{id}/files`、`GET /api/v1/files/recent`、`GET/POST/DELETE /api/v1/files/{id}`、`GET /api/v1/datasets/{id}/files/parse-results` | 上传与解析依赖 `B5_FILE_WRITES_ENABLED`，删除依赖 `B5_DELETE_WRITES_ENABLED`。普通 Markdown 无本地图片引用时按 RAW 原件上传。资源包请求接收 `matchMode`（`FULL_PATH`/`SHALLOW_BASENAME`）、`documentPath`、重复的 `assets`、对应的 `assetRelativePaths` 和可选 `assetInventoryPaths`；响应含 `assetSummary`。上传成功后原件、规范化 Markdown、命中图片和 v1 manifest 均在 RAW 桶，解析仍通过 MQ。能力接口只在文件写入开关启用时宣告资源包支持。 |
| B5 内部内容 | `GET /api/v1/internal/files/{id}/content` | 仅接受独立服务 Bearer token；浏览器 access JWT 不能代替。 |

B5 解析和删除消息使用 0041 `management_mq_outbox` 同事务记账，再由现有 `MQService` 投递；Broker 确认不确定时可能按同一业务 ID 重发。目标环境未执行 0040/0041、未配内部文件 token/URL 或旧 Java 仍写同一路径时，不能打开对应写入开关。状态与缺口见[迁移进度](../internals/java_python_migration_progress.md)。

### B6–B8 新接入路由（待 Dev 对照与切流）

这些路由使用 F0 的 `{code,message,data}` 响应和 B1 登录态；对话与用量只按当前登录用户查询，管理运维只允许 `ADMIN`。

| 范围 | 路径 | 行为 |
| --- | --- | --- |
| B6 会话 | `POST/GET /api/v1/chat/conversations`、`GET /api/v1/chat/conversations/{id}/messages`、`PATCH/DELETE /api/v1/chat/conversations/{id}` | 创建、分页、标题/置顶更新和删除；轮次由 RAG 运行时直接持久化。 |
| B6 引用 | `POST /api/v1/knowledge/chunks/batch` | 请求 `{chunkIds:[...]}`；仅返回当前用户可见的 ACTIVE Chunk。 |
| B6 文件分块 | `GET /api/v1/knowledge/chunks?fileId=&page=&pageSize=` | 按文件分页列出 ACTIVE 分块（`chunk_index` 升序，`pageSize` ≤100）；文件须归当前用户且未删除，否则 404。项字段 `chunkId,fileId,datasetId,index,chunkType,startLine,endLine,content,updatedAt`。 |
| B7 用量 | `GET /api/v1/llm/usage/{summary,daily,logs,by-model,trend}` | 必传 `startDate,endDate`；前三项 `stage` 默认 `chat`，`all` 表示全链路；日志分页用 `page,pageSize`。 |
| B8 看板 | `GET /api/v1/admin/users/dashboard?days=7\|30\|90` | 默认 30 日，返回角色/状态分布、新增/活跃与逐日趋势。 |
| B8 总览 | `GET /api/v1/admin/overview` | 管理台首页计数：`users{total,newThisMonth,active7d{current,previous,growthRate}}`、`models{providers,activeProviderModels,platformConfigs}`、`blog{published,drafts,staleDrafts}`（超过 30 天未更新的草稿）、`feedback{pending}`、`sync{pendingCandidates,failedJobs7d,lastFailure,recentJobs[5]}`；模型同步表未迁移时 `sync` 为 null。 |
| B8 上传配置 | `GET/PUT /api/v1/admin/document-file-config` | PUT 完整覆盖 `{maxSizeBytes,allowedSuffixes}`；写入默认关闭，需切流后设置 `B8_DOCUMENT_CONFIG_WRITES_ENABLED=true` 且默认指纹一致，Redis 写入成功后生效。 |
| B8 日志 | `GET /api/v1/admin/logs`、`GET /api/v1/admin/logs/labels` | 日志筛选参数 `service,level,trace_id,keyword,start_time,end_time,page,page_size`；代理 Loki。 |

实现与切流边界见 [B6–B8 迁移说明](../internals/b6_b8_migration.md)。

### B9 博客与 B10 反馈（代码已接入，待切流）

| 范围 | 路径 | 行为 |
| --- | --- | --- |
| B9 管理 | `GET/POST /api/v1/admin/blog/posts`、`GET/PATCH/DELETE /api/v1/admin/blog/posts/{id}` | 仅 ADMIN；文章列表、草稿创建、详情、元数据更新和软删。写操作依赖 `B9_BLOG_WRITES_ENABLED`。 |
| B9 正文 | `PUT /api/v1/admin/blog/posts/{id}/content`、`POST /api/v1/admin/blog/posts/{id}/content/import`（兼容 `/content`） | 保存 Markdown 或上传 UTF-8 Markdown；对象写入现有 PUBLIC 桶。支持内联 data URI 图片入库；远程 HTTP(S) 图片在安全和大小校验通过时转存，失败时保留原链接。 |
| B9 发布 | `POST /api/v1/admin/blog/posts/{id}/publish`、`/unpublish` | 发布前校验正文对象存在；首次发布记录时间；撤回后公开接口返回 404。 |
| B9 资源 | `GET/POST /api/v1/admin/blog/posts/{id}/assets`、`DELETE /api/v1/admin/blog/posts/{id}/assets/{assetId}` | COVER/CONTENT_IMAGE 图片上传、列表与删除；被正文引用的图片不可删除。 |
| B9 公开 | `GET /api/v1/blog/posts`、`GET /api/v1/blog/posts/{slug}` | 匿名读取仅已发布文章；详情支持 ETag、`If-None-Match` 和 304。 |
| B10 提交 | `POST /api/v1/feedback` | 匿名 multipart `type,title,content,file?`；附件复用 B2 feedback 上传规则及 PUBLIC 桶，DB 失败补偿删除对象。依赖 `B10_FEEDBACK_WRITES_ENABLED`。 |
| B10 管理 | `GET /api/v1/admin/feedback`、`GET/PATCH /api/v1/admin/feedback/{id}/*` | 仅 ADMIN；按状态/类型分页与详情，更新 `status`、`priority`、`reply`。写操作依赖 `B10_FEEDBACK_WRITES_ENABLED`。 |

两项写入开关默认关闭。启用前应保证 Java 对应写入口已退场，并核验共享数据库、PUBLIC 桶访问及公开 URL。

## 2. Parser API

路由前缀：`/api/v1/parser`

| Method | Path | 用途 | 请求 | 响应 |
| --- | --- | --- | --- | --- |
| `POST` | `/extract_sync` | 上传文件并同步解析为 Markdown，仅用于测试或联调 | `multipart/form-data` | `code/message/data/time_cost_ms` |
| `POST` | `/task/submit` | 提交异步解析任务，经 MQ 投递后台消费 | `TaskSubmitRequest` | `TaskSubmitResponse` |

### POST /api/v1/parser/extract_sync

表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | file | 是 | 待解析文件 |
| `file_type` | string | 是 | `pdf/docx/doc/html/htm` 等 |
| `parser_backend` | string | 否 | PDF 解析器，默认 `mineru` |
| `docling_force_ocr` | bool | 否 | 仅兼容旧 PDF 参数 |
| `image_bucket` | string | 否 | PDF 图片输出 bucket |
| `image_prefix` | string | 否 | PDF 图片输出 key 前缀 |
| `source_file_url` | string | 否 | MinerU 精准解析 API 使用的源文件 URL；选择 `parser_backend=mineru` 时必须可被 MinerU 云端访问 |
| `mineru_model_version` | string | 否 | MinerU 精准解析模型，默认 `vlm` |

响应 `data`：

- `file_type`
- `pdf_parser_backend`
- `markdown`
- `metadata`
- `warning`

### POST /api/v1/parser/task/submit

请求模型：`TaskSubmitRequest`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string | 必填 | 文档解析任务唯一标识 |
| `original_file_id` | int | 必填 | 原始文件表主键 |
| `document_parse_task_id` | int | 必填 | 历史兼容字段名，对应 `document_parse_file.id` |
| `user_id` | int | 必填 | 文件所属用户 |
| `dataset_id` | int | 必填 | 文件所属数据集 |
| `file_type` | string | 必填 | 文件格式 |
| `source_bucket` | string | 必填 | 原始文件 bucket |
| `source_object_key` | string | 必填 | 原始文件对象 key |
| `source_filename` | string | 必填 | 原始文件名 |
| `md_bucket` | string | 必填 | 历史兼容字段；Python 侧 Markdown 输出 bucket 使用 `MINIO_PRIVATE_BUCKET` |
| `md_object_key` | string | 必填 | Markdown 输出对象 key |
| `trigger_mode` | string | `upload_auto` | 触发方式 |
| `pdf_parser_backend` | string | `mineru` | PDF 解析器 |
| `docling_force_ocr` | bool | `false` | 兼容旧参数；当前内置 PDF 后端不使用 Docling |
| `image_bucket` | string/null | `null` | 图片输出 bucket |
| `image_prefix` | string/null | `null` | 图片输出前缀 |

响应：

```json
{
  "code": 200,
  "message": "Task accepted and queued via MQ",
  "data": {
    "task_id": "...",
    "status": "created"
  }
}
```

## 3. MQ API

路由前缀：`/api/v1/mq`

| Method | Path | 用途 | 请求 | 响应 |
| --- | --- | --- | --- | --- |
| `POST` | `/send/parse-task` | 发送文档解析任务 MQ 消息 | `SendParseTaskRequest` | `MQResponse` |
| `POST` | `/send/usage-report` | 发送 LLM 用量上报消息（全链路归属：新增必填 `stage`/`operation`，详见下注） | `SendUsageReportRequest` | `MQResponse` |
| `POST` | `/send/raw` | 向指定 topic/queue 发送原始消息 | `SendRawMessageRequest` | `MQResponse` |
| `GET` | `/vendor/info` | 查询当前 MQ vendor 和可用 vendor | 无 | `MQVendorInfoResponse` |

MQ 发送失败统一返回不含底层连接地址和异常文本的 `500` 通用说明；服务端通过
`mq_http_send_failed` 结构化日志记录 topic、业务锚点、消息字节数、脱敏异常摘要和安全调用栈。
`/send/raw` 不会把 `request.message` 写入日志。

`MQResponse`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `success` | bool | 操作是否成功 |
| `message` | string | 描述信息 |

重要 MQ 名称：

| 消息 | Topic/Name | 说明 |
| --- | --- | --- |
| ParseTask | `tolink.rag.parse_task` | Java/Python 解析任务输入 |
| UsageReport | `tolink.rag.usage_report` | 用量上报 |

> `SendUsageReportRequest`（用量上报全链路归属）：必填 `user_id` / `provider_type` / `model_name` / `stage` / `operation` /
> 正整数全局 `config_id`；token 计数默认 0。可选 `task_id` / `latency_ms` / `status`。字段语义与 MQ 载荷一致。

> parse_result 终态回传 topic 已下线（LINK-166）：终态只写 DB，前端通过 Python 管理接口轮询读取，见下方「解析终态读取」。

### 解析终态读取

parse_result 终态回传 MQ 已下线（LINK-166）。整体任务状态的权威单源是 `document_parse_pipeline.pipeline_status`；前端通过 Python 的 `GET /api/v1/datasets/{dataset_id}/files/parse-results?fileIds=...` 读取。

`SUCCESS` 表示解析+上传、分片、向量化、预分词与 ES 入库均完成；任一阶段失败写 `FAILED`，并在 `failure_reason` 中携带业务化原因。

> **数据库权威单源**：整体任务状态以 `document_parse_pipeline.pipeline_status` 为准；`document_parsed_log.task_status` / `failure_reason` 已下线（migration 0007）。Python 管理接口据此读取：
> - 整体任务是否成功 → `document_parse_pipeline.pipeline_status == SUCCESS`
> - markdown 是否已上传 → `document_parsed_log.parsed_object_key IS NOT NULL`
> - 失败原因 → `document_parse_pipeline.failure_reason`

## 4. LLM API

路由前缀：`/api/v1/llm`

所有接口需要请求头：

| Header | 说明 |
| --- | --- |
| `Authorization` | `Bearer <access-token>`；用户身份取自已验证 token 的 `sub`，用于读取用户 LLM 配置。缺失或无效返回 `401` |

配置解析规则：

- 请求体必须携带正整数 `config_id`，精确读取 `llm_model_config.id`。
- 不再接受 `config_source`、`model`、`override_model` 等旧路由/覆盖字段，未知字段返回 `422`。
- resolver 统一校验存在、启用、SYSTEM 或归属当前 token 用户，以及 capability 匹配；不读默认指针或环境变量兜底。

| Method | Path | 用途 | 请求 |
| --- | --- | --- | --- |
| `POST` | `/generate` | 非流式文本生成 | `GenerateRequest` |
| `POST` | `/generate/stream` | SSE 流式文本生成 | `GenerateRequest` |
| `POST` | `/embed` | 文本向量化 | `EmbedRequest` |
| `POST` | `/rerank` | 文档重排 | `RerankRequest` |
| `POST` | `/ocr` | 图片文字提取（兼容旧 endpoint）。OCR 不再是独立能力，内部统一走 VISION（`analyze_image`）：读 `VISION` 配置、按 base64 嗅探的真实 mime 传图、未带 `prompt` 时用默认文字提取提示词；返回 `content/model/usage`，与原结构一致 | `OcrRequest` |

`GenerateRequest`：

- `config_id`: 必填正整数，全局配置 ID。
- `prompt`: 必填提示词。
- `temperature`: 默认 `0.7`，范围 `0-2`。
- `max_tokens`: 可选，最小 `1`。
- `system_prompt`: 可选系统提示词。
- `tools`: 可选工具定义。

`EmbedRequest`：

- `config_id`: 必填正整数，全局配置 ID。
- `input`: string 或 string 列表。

`RerankRequest`：

- `config_id`: 必填正整数，全局配置 ID。
- `query`: 检索查询。
- `documents`: 待重排文档列表。
- `top_n`: 可选。

`OcrRequest`：

- `config_id`: 必填正整数，全局配置 ID。
- `image_base64`: 图片 base64。
- `prompt`: 可选提示词。

## 5. Internal LLM API

路由前缀：`/api/v1/internal/llm`

| Method | Path | 用途 | 参数 |
| --- | --- | --- | --- |
| `GET` | `/providers` | 查询系统级 LLM 厂商 | `provider_type` 可选 |
| `GET` | `/configs` | 查询用户 LLM 配置 | Header `X-User-Id` |
| `GET` | `/usage` | 查询用户用量统计 | Header `X-User-Id`，`start_date/end_date` 可选 |

所有接口要求 `Authorization: Bearer <INTERNAL_API_TOKEN>`；未配置令牌或令牌不匹配时返回 `401`。

日期参数格式：`YYYY-MM-DD`。

`GET /providers` 兼容保留 `models: { [model_name]: capability[] }`。新管理端展示模型时优先使用
`model_options[]`：每项包含 `model_name`（真实调用 ID）、`display_name`（短展示名）、
`capabilities`、`protocol`、`api_base_url`；提交配置仍应使用 `model_name`。

## 6. RAG / Recall API（对外）

**面向浏览器前端**：前端凭登录返回的同一枚 **access JWT** 直连 Python。
本地统一后端模式下，现有前端仍调用 `POST /api/v1/recall/sessions`；该 Python 兼容入口
先核验 `satoken` 和显式非空的 `datasetIds` 归属，再返回同一枚有效 access JWT、
`streamUrl=/api/v1/rag/stream`、已验证的数据集 ID 和剩余有效秒数。它不签发另一种令牌。
旧短期 session token 不再接受。
两个端点拆分语义（LINK-131）——`/api/v1/rag/stream` 承接「召回 + LLM 流式生成」的完整 RAG
问答（SSE），`/api/v1/recall` 是纯召回 JSON（一次性返回 hits，不生成）。运行时与会话鉴权细节见
[docs/internals/recall_http_api.md](../internals/recall_http_api.md)。

> 历史背景：早期 `/api/v1/recall/stream` 曾以 `recall` 之名承载完整 RAG 问答（SSE），语义已超出
> 召回；LINK-131 拆为 `/api/v1/rag/stream`（RAG 问答流）与 `/api/v1/recall`（纯召回 JSON），旧
> `/api/v1/recall/stream` 删除、不留兼容。更早还存在一条 Java Recall Gateway → Python 内部端点
> `/api/v1/internal/recall/stream` 的网关链路（纯召回、无生成），已随直连方案废弃清理（LINK-122）。

| Method | Path | 用途 | 返回 | 鉴权 |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/rag/stream` | 召回 + LLM 流式生成的完整 RAG 问答 | `text/event-stream` | Header `Authorization: Bearer <access-token>` |
| `POST` | `/api/v1/recall` | 纯召回，一次性返回融合候选（预留实现） | `application/json` | Header `Authorization: Bearer <access-token>` |
| `POST` | `/api/v1/recall/sessions` | 兼容浏览器现有召回握手，校验当前数据集归属 | `Result<{token,streamUrl,datasetIds,expiresIn}>` | Header `satoken: <access-token>` |

### POST /api/v1/rag/stream

前端以 fetch 流式（`ReadableStream`）建连，**不使用** `EventSource`（无法设鉴权头）。
请求头：`Authorization: Bearer <access-token>`、`Content-Type: application/json`、可选
`Origin`（CORS）、`X-Request-Id`。

access token 在双端过渡期由 Java 登录签发；本地 Java 退场模式由 Python 签发并登记 Redis 会话。
两种模式都以 RS256 私钥签名、公钥验签；
claims 至少包含 `iss=tolink-java`、`aud` 含 `tolink-rag-api`、`token_use=access`、
`sub`、`iat`、`exp`、`jti`。Python 不回调 Java，也不解析 Sa-Token Redis。
access token 不携带 `dataset_ids`；用户状态、角色和数据集归属均读取当前 MySQL 事实。
Python 只接受上述 RS256 access JWT，不支持 HS256 recall session token。本地 Python 签发模式
还会逐次校验 Redis 会话有效性，注销后管理、RAG 与 Wiki 请求均会被拒绝。

请求体（仅以下字段；出现 `user_id` / `top_k` / `sources` / `strict` / `doc_ids` 等任何未知
字段返回 `422`）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | string | 是 | 用户问题，不能为空或纯空白 |
| `config_id` | int (>0) | 是 | 本次生成所用 CHAT 全局配置 ID。缺失/非正数 `422`；非 CHAT、已停用、不存在或 USER 配置不属本用户时在召回前失败 |
| `conversation_id` | int | 是 | 本轮所属对话 id（Java 预先创建），作为对话落库挂载锚点。缺失 `422`，不进入召回生成、不发对话轮次消息 |
| `turn_id` | string | 是 | 本轮落库幂等键：前端每轮生成的稳定 UUID（断连重连不变）。缺失 `422`。Java 据此 upsert 同一行，断连续跑/重连不重复落库 |
| `is_first_turn` | bool | 否 | 是否会话首条用户消息，默认 `false`。为 `true` 时触发服务端基于 `query` 生成会话标题（SSE `conversation_title` 即时回前端 + `chat_turn.title` 落库），见下文 |
| `dataset_ids` | list[int] | 否 | 本次查询的数据集**子集选择**；必须全部属于当前用户且 ACTIVE/未删除，省略/空则查询本人全部有效数据集 |

> 生成跑在**独立后台任务**（断连不取消）：任务起点发一条 `tolink.rag.chat_turn`（`status=GENERATING`），终态再发 `COMPLETED`/`FAILED`，同 `turn_id`，供 Java upsert 落库对话内容（空召回也发 `COMPLETED` 占位）。客户端断连只停 SSE 转发、生成续跑到落库；本轮 generate 的 token 用量另走 `tolink.rag.usage_report`（LINK-191）。契约见 [mq_contracts.md §对话轮次上报](mq_contracts.md#对话轮次上报pythonjava)。

**身份只取 token claims**——body 不含 `user_id`，前端自报一律不信任。融合候选池窗口 / 三路执行期 top_k / 召回分数阈值 /
召回路 / 固定融合权重 / 容错模式 / rerank 条数均由服务端配置控制。`off` 与纯召回 JSON 按数据集配置（`dataset_parse_config.recall_config`：
`recall_result_limit` / `bm25_top_k` / `sparse_top_k` / `dense_top_k` / `sparse_score_threshold` / `dense_score_threshold` / `recall_enabled_sources` /
`fusion_bm25_weight` / `fusion_sparse_weight` / `fusion_dense_weight` /
`recall_strict` / `rerank_top_n`；多数据集混合取首个 dataset，无数据集配置回退
`RECALL_RESULT_LIMIT` / `RECALL_BM25_TOP_K` / `RECALL_SPARSE_TOP_K` / `RECALL_DENSE_TOP_K` /
`SPARSE_RETRIEVAL_SCORE_THRESHOLD` / `DENSE_RETRIEVAL_SCORE_THRESHOLD` / `RECALL_ENABLED_SOURCES` /
`RECALL_FUSION_*_WEIGHT` /
`RECALL_STRICT_DEFAULT` / `RERANK_DEFAULT_TOP_N` 等系统默认）；RAG 主链在 `active` /
`baseline` 下固定使用模型的 Blind v5 候选契约：`bm25,sparse,dense`、零阈值、
`0.15/0.15/0.70` 权重、Query 分型 TopK 和最终 Top10。`shadow` 主链与 `off` 一致，后台另起
冻结候选请求。以上参数均不接受
请求覆盖。其中 `off`/纯召回配置的 `recall_enabled_sources` **只能在系统已装配的召回路集合内收窄**（不能启用系统未
装配的路）。模型按 `(user_id, capability, config_id)` 精确解析，SYSTEM / USER 配置使用同一 ID 空间。

并发：按 `user_id` 限并发流数（`RAG_MAX_CONCURRENT_PER_USER`），超限返回 `429`。

**召回即包含排序 + LLM 答案生成**：召回前置先校验模型；`active` 默认使用本地 LambdaMART，
失败回退 frozen weighted score 且不调用远程 rerank；`off` 保留旧 rerank，`shadow` 旁路比较但不改结果。
排序后回填片段正文、按 token 预算（数据集 `recall_config.recall_context_token_budget`，
无数据集配置回退 `RECALL_GENERATION_CONTEXT_TOKEN_BUDGET`）拼装上下文，用所选模型
流式生成答案。SSE 事件：

```
event: stream_started
data: {"conversation_id": 123, "request_id": "<本次请求 ID>"}

event: answer_delta
data: {"text": "<增量 token>"}

event: answer_done
data: {"answer": "<完整答案>", "hits": [...], "rerank_applied": false, "ranking_diagnostics": {"strategy":"lambdamart","mode":"ltr","model_version":"candidate-difference-v3-20260728-final33","candidate_contract_version":"blind_v5_candidate_routing_v1","candidate_contract_status":"complete","required_sources":["bm25","sparse","dense"],"actual_sources":["bm25","sparse","dense"],"duration_ms":12.3,"reason":null}, "failed_sources": [], "recall_diagnostics": {...}}
```

- `stream_started`：建流后的**首个事件**，在模型校验、召回、rerank 与生成之前发出；前端收到后将
  `conversation_id` 对应的会话标记为“回复中”，`request_id` 用于链路关联；
- `answer_delta`：流式增量 token，可 0 到多帧；
- `answer_done`：生成结束终态，`hits` 为当前发布模式排序后的最终候选（含正文 `content`），发送后关闭流；
- **空命中 / 全部片段缺正文**：不生成，发 `recall_done`（`hits` 可空，同带 `rerank_applied`；全部缺正文时各 hit `content` 为空串）；
- **生成阶段失败**：整请求失败，发 `error` `RECALL_GENERATION_FAILED`，不返回部分召回片段。

**进度事件**（增量兼容，旧客户端可忽略；用于前端展示「检索 → 生成」步骤与提前展示引用）：

```
event: recall_started
data: {}

event: recall_hits
data: {"hits": [{"chunk_id": "...", "doc_id": 1, "dataset_id": 1, "file_name": "a.pdf", "content": "...", ...}], "rerank_applied": false}

event: generation_started
data: {}
```

- `recall_started`：模型校验通过、开始召回前发出；
- `recall_hits`：召回与排序完成、生成之前发出，`hits` 与随后终态的 `hits` 相同（含 `content`）；
- `generation_started`：调用模型流式生成前发出（空命中 / 全部缺正文 / 已被停止时不发）。

各 hit（`recall_hits` / `answer_done` / `recall_done` / `answer_stopped`）新增 `file_name`：来源文件原始文件名，查不到为 `null`。

**停止生成**：`POST /api/v1/rag/stream/{turn_id}/cancel`（同 `Authorization: Bearer`）。本轮须属于当前用户，否则 404
`TURN_NOT_FOUND`；已处于终态时幂等返回 `{"code":"OK","data":{"stopped":false}}`，否则写入 Redis 取消标记
`rag:cancel:{turn_id}`（跨 worker 生效）并返回 `stopped:true`；Redis 不可用 503。后台生成在生成前与帧间（约 300ms
节流）检查标记，命中后发终态：

```
event: answer_stopped
data: {"answer": "<已生成的部分答案>", "usage": {...}, "hits": [...], "rerank_applied": false}
```

并以 `STOPPED` 落库（保留部分答案；终态不再被覆盖，用量按实际消耗记为 success）。召回阶段不响应取消。

事件顺序为 `stream_started` → 零到多个中间事件（进度事件 / `answer_delta` / `conversation_title`）→ 恰好一个
终态（`answer_done` / `recall_done` / `answer_stopped` / `error`）。终态是最后一个业务事件；客户端收到任一终态或检测到
连接关闭时，必须清除该 `conversation_id` 的“回复中”状态。新增事件遵循增量兼容：消费者应忽略未知
事件，旧的 `answer_delta` / `answer_done` / `recall_done` / `error` payload 保持不变。

**会话标题事件 `conversation_title`**（仅 `is_first_turn=true` 的会话首轮）：

```
event: conversation_title
data: {"title": "<会话标题>"}
```

服务端用本轮对话模型基于 `query` 生成短标题，标题任务**与召回 + 答案生成并行**，不串行增加问答耗时；一旦算好即在 `answer_delta` 间隙插发本事件（LLM 比答案慢时在本轮终态前补发），前端据此即时刷新侧栏/会话头标题，无需轮询。同一标题随首轮终态的 `chat_turn.title` 上报落库（标题为空/默认「新对话」时由 Java 写入 `chat_conversation.title`，不覆盖用户手改）。标题生成失败/超时回落首问截断兜底（首轮一定命名会话），不影响答案与落库；**生成失败（FAILED）的首轮**仅落库截断标题、不发本事件。非首轮无本事件。

终态 `hits` 单项在融合字段基础上补 rerank 字段与 chunk 正文 `content`：

```json
{"chunk_id": "...", "doc_id": 10, "dataset_id": 1, "fused_score": 0.033,
 "scores": {"bm25": 10.16, "sparse": 0.05}, "rerank_score": 0.87, "rerank_rank": 1,
 "content": "<chunk 正文，供前端展示召回片段>"}
```

- `rerank_applied`（顶层 bool）：仅表示旧远程 rerank 是否实际生效。`active` / `baseline` 下固定为
  `false`，不能据此判断 LambdaMART 是否生效，应读取 `ranking_diagnostics`。`off` / Shadow 线上旧链路中，**未配置 RERANK 模型 / 调用失败 / 返回不可用
  一律降级**为当前融合顺序候选（best-effort：rag/stream 不因 rerank 不可用而整条失败），此时该字段为
  `false`，每个 hit 的 `rerank_score` / `rerank_rank` 为 `null`；
- rerank **生效**时（`rerank_applied=true`）：`hits` 按 `rerank_rank` 升序（即 rerank 相关性降序），
  长度 ≤ `rerank_top_n`（数据集 `recall_config.rerank_top_n`，无数据集配置回退 `RERANK_DEFAULT_TOP_N`）；
  个别未被模型打分的候选 `rerank_score` / `rerank_rank` 可为 `null`，排在已打分候选之后；
- 旧 rerank **降级**时（`rerank_applied=false`）：`hits` 为当前融合顺序（按 `fused_score` 降序），
  截断到 `rerank_top_n`；
- `ranking_diagnostics`（可选顶层对象）：active/baseline 的实际排序诊断。包含
  `candidate_contract_version`、`candidate_contract_status`、`required_sources` 与
  `actual_sources`，可与 `/health.ltr` 和模型 serving contract 交叉核验。`strategy` 为
  `lambdamart` 或 `weighted_score`，`mode` 表达正常 LTR、短 Query 低置信度 Hybrid、超时/异常/延迟预算
  降级或主动 baseline，另含 `model_version`、`duration_ms` 与可选 `reason`。这是新增兼容字段，客户端应忽略未知字段；
- active/baseline 的 `hits` 最多 10 条，与 Blind v5 的 Hit@10/MRR@10 验收口径一致；shadow 仍使用 Dataset TopN；
- `fused_score` / `scores` 为当前融合策略解释信息，原样保留；`scores` 键集合等于本次生效的召回路。
  active/baseline RAG 主链固定三路；`off`/shadow/纯召回则是数据集 `recall_enabled_sources` 在已装配路集合内收窄后的结果。
- `content` 为该 chunk 的正文（与生成阶段上下文同源、一次性回填，无需另起反查）；某候选正文缺失
  时为空串。仅 rag/stream 终态 `hits` 含此字段，纯召回 JSON 端点（下文 `/api/v1/recall`）不含。

`failed_sources` 表达「降级成功」（如 bm25 成功、sparse 失败），空列表表示无失败路。失败终态
`error` 发送后关闭流，`message` 不含内部堆栈。错误码见
[error_codes.md §5](error_codes.md#5-recall-错误码对外-rag-流--纯召回-json)。

`recall_diagnostics` 是召回来源结构诊断（LINK-195），在三路 `bm25` / `sparse` / `dense`
均启用且结果可归入四态时返回：

```json
{
  "source_mode": "bm25_only",
  "degraded": true,
  "active_sources": ["bm25", "sparse", "dense"],
  "per_source_counts": {"bm25": 12, "sparse": 0, "dense": 0},
  "empty_sources": ["sparse", "dense"],
  "failed_sources": []
}
```

`source_mode` 取值为 `hybrid` / `bm25_only` / `missing_sparse` / `missing_dense`。
`empty_sources` 表示成功执行但 0 命中的路；`failed_sources` 仍只表示异常失败路。BM25-only
不是错误，不改变 rerank、prompt 或生成策略。首版不返回 `reason` 字段。

> CORS：本端点暴露给浏览器，生产环境必须把 `CORS_ORIGINS` 收敛为前端可信域名清单
> （不可用 `*`）。

### POST /api/v1/recall

纯召回 JSON：一次性返回融合候选，**不调 CHAT 模型、不回填正文、不建立 SSE、不做并发限流**。
当前阶段为接口预留实现，前端暂不真正接入。请求头：`Authorization: Bearer <access-token>`、
`Content-Type: application/json`、可选 `Origin`（CORS）、`X-Request-Id`。

会话鉴权与 `dataset_ids` scope 校验同 `/api/v1/rag/stream`。请求体（仅以下字段；出现 `config_id` /
`user_id` / `top_k` / `sources` / `strict` / `doc_ids` / `fusion_strategy` / `fusion_weights` /
`recall_fusion_strategy` / `rrf_k` / `fusion_*_weight` 等任何未知字段返回 `422`）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | string | 是 | 检索词，不能为空或纯空白 |
| `dataset_ids` | list[int] | 否 | 数据集**子集选择**；按当前用户数据库归属实时解析 |

**不要求 `config_id`**（纯召回不生成）。成功返回 `200`。**纯召回不经 rerank**，`hits` 为当前融合策略
融合候选、**不含** `rerank_score` / `rerank_rank` 字段，也无顶层 `rerank_applied`（与 RAG 流的
终态 `hits` 区别在此）：

```json
{ "hits": [ {"chunk_id": "...", "doc_id": 10, "dataset_id": 1, "fused_score": 0.92, "scores": {"bm25": 8.7, "sparse": 0.76}} ], "failed_sources": [], "recall_diagnostics": {...} }
```

`hits` 按 `fused_score` 降序、不含正文，长度 ≤ 数据集 `recall_config.recall_result_limit`（无数据集
配置回退 `RECALL_RESULT_LIMIT`）；`failed_sources` 表达异常失败路；`recall_diagnostics` 与
RAG SSE 成功终态同构。三路执行期 top_k / 分数阈值 / 融合策略的数据集级
解析与 `/api/v1/rag/stream` 完全一致（LINK-148）。
执行期错误走 **HTTP 状态码**（区别于 SSE error 帧）：无默认 EMBEDDING 配置 `422`、全路失败 `500`、
召回超时 `504`、未预期异常 `500`，错误体为 `{code, message, data}`，`message` 不含内部堆栈。错误码见
[error_codes.md §5](error_codes.md#5-recall-错误码对外-rag-流--纯召回-json)。

## 7. Wiki API（对外）

四个端点均使用 `/api/v1/wiki` 前缀和 `Authorization: Bearer <access-token>`，鉴权契约与 §6 相同。成功响应为 JSON，并回显/生成 `X-Request-Id`；两个 POST 请求体中的未知字段一律 422，ID 必须为正整数。身份只取已验签的 `sub`，用户状态、角色和资源范围读取当前数据库事实。两个 POST 的运行时 OpenAPI `requestBody` 直接由对应 Pydantic 请求模型生成并标记为必填，与本节字段契约保持同源。

| Method | Path | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/wiki/search` | exact 标题或 prefix + BM25 混合搜索 |
| `GET` | `/api/v1/wiki/documents/{doc_id}/headings/{heading_key}/chunks` | 分页展开一个标题的直属 Chunk |
| `POST` | `/api/v1/wiki/chunk-locations` | 批量定位 Chunk 的全部直接标题路径 |
| `GET` | `/api/v1/wiki/documents/{doc_id}/tree` | 读取授权且就绪文档的完整标题树 |

### POST /api/v1/wiki/search

请求：

```json
{"query":"快速 开始","dataset_ids":[10,20],"doc_ids":[10001],"cursor":"optional"}
```

`query` 必填；`dataset_ids`、`doc_ids`、`cursor` 可省略。ID 数组去重后排序。客户端不能提交 `page_size`、`top_k`、`strict` 或 sources。续页必须重复同一 query 和范围；无状态 HMAC 游标绑定用户、规范 query、有效 scope 和 exact/mixed 分支，10 分钟过期。

成功体：

```json
{
  "results":[
    {"result_type":"HEADING","source":"title_prefix","heading":{
      "heading_key":"<64-hex>","doc_id":10001,"dataset_id":10,"title":"快速开始",
      "heading_level":2,"path":[{"heading_key":"<64-hex>","title":"指南","heading_level":1}],
      "direct_chunk_count":2,"direct_chunk_preview_id":"C1","direct_chunks_has_more":true,
      "next_direct_chunk_cursor":"<signed>"
    },"chunk_id":null,"bm25_score":null},
    {"result_type":"CHUNK","source":"bm25","heading":null,"chunk_id":"C2","bm25_score":8.31}
  ],
  "chunks":[{"chunk_id":"C1","doc_id":10001,"dataset_id":10,"content":"完整 Chunk 正文",
    "chunk_type":"paragraph","start_line":10,"end_line":20,
    "positions":[{"path":[{"heading_key":"<64-hex>","title":"快速开始","heading_level":2}]}],
    "position_count":1,"positions_truncated":false}],
  "failed_sources":[],"page_size":15,"has_more":true,"next_cursor":"<signed>"
}
```

`results` 是以 `result_type` 为判别字段的严格联合类型，也是分页与顺序的权威数组：`HEADING` 只允许 `source=exact_title|title_prefix`、非空 `heading` 及空 `chunk_id/bm25_score`；`CHUNK` 只允许 `source=bm25`、空 `heading` 及非空 `chunk_id/bm25_score`。其他来源或交叉字段组合不属于响应契约，并会被服务端 Schema 拒绝。HEADING 以物理节点唯一，CHUNK 以 `chunk_id` 唯一。`chunks` 是按 `chunk_id` 去重的正文展开区。每个标题最多预览一个直属 Chunk；若 BM25 候选同时是本次查询任意匹配标题的首个可见直属 Chunk，则在分页前固定归标题预览所有并从 BM25 流移除，后项按原顺序补位，保证数据不变时跨页不重复。BM25 候选还会在配额和分页前批量校验当前 MySQL 真值：候选产生后因并发重解析或删除而失效的 ID 被丢弃并由有界池后项按原顺序补位，池耗尽时返回 HTTP 200 短页或空页，不返回 403/409/500；真正的 SQL 或连接失败仍返回 500。响应中的每个结果 Chunk/标题预览都必然存在于同一响应的 `chunks`。每个搜索 Chunk 最多内嵌前 10 个稳定标题位置。exact 结果的全部续页不调用 prefix/BM25；mixed 默认目标配额 5/10，任一路不足由另一条补位。`has_more=false` 时省略 `next_cursor`。

### GET /api/v1/wiki/documents/{doc_id}/headings/{heading_key}/chunks

`heading_key` 是 64 位小写十六进制。查询参数 `cursor` 可选：不传时从首个直属 Chunk 开始；提交搜索结果的 `next_direct_chunk_cursor` 时从预览后的第二个开始。展开游标绑定用户、标题当前所属数据集、`doc_id`、`heading_key` 和 `heading_chunks` 分支，不绑定来源搜索可能覆盖的多数据集集合；接口会先按 `doc_id` 重新授权和解析当前数据集归属，再执行验签，因此跨数据集搜索签发的游标可以展开所属文档。对于仍可授权解析但资源身份不符的文档、数据集或标题，旧游标返回 422；越权资源仍在验签前返回 403。响应字段为 `doc_id`、`heading_key`、去重后的完整 `chunks`、`page_size`、`direct_chunks_has_more` 及可选 `next_direct_chunk_cursor`。只读取当前标题的直属 CHUNK_REF，不进入子标题或其他搜索结果。服务端固定前瞻最多 `2 * page_size` 个直属引用；最终水合时刚失效的内部 Chunk 被跳过并由后项补位，仍不足时返回 200 短页，标题本身失效或越权仍整体 403。每个返回 Chunk 的 `positions` 最多内嵌前 10 个稳定标题位置，并以 `position_count/positions_truncated` 表示完整数量和是否截断；需要全部位置时调用 Chunk 定位端点。

### POST /api/v1/wiki/chunk-locations

请求 `{"chunk_ids":["C1","C2"],"dataset_ids":[10,20]}`。`chunk_ids` 为 1～100 个，去重后保持首次出现顺序；`dataset_ids` 可省略。响应 `locations[]` 逐项包含 `chunk_id`、`doc_id`、`dataset_id`、`positions[]`，每个 position 含从文档根标题到直接标题的完整 `path`。本端点不截断位置；它与服务端内部候选水合不同，保持严格全有或全无语义，任一 Chunk 缺失、越权、非 ACTIVE 或文档未就绪时整体 403，且不返回其他有效 ID 的部分位置。

### GET /api/v1/wiki/documents/{doc_id}/tree

响应包含 `doc_id`、`dataset_id`、`original_filename`、递归 `headings`、`root_chunk_ids` 与去重后的完整 `chunks`。每个 heading 含 `heading_key/title/heading_level/direct_chunk_ids/children`；同父 HEADING 与直属 CHUNK_REF 分别按各自 `sort_order` 排序，不声明两类节点间的混合顺序。文档越权或当前 pipeline 非 SUCCESS 时返回 403。

Wiki 错误码见 [error_codes.md §5.1](error_codes.md#51-wiki-端点错误映射)，实现与最终一致性游标语义见 [wiki_heading_tree.md](../internals/wiki_heading_tree.md)。

## 8. Apps API（接入应用服务端）

路由前缀：`/api/v1/apps`。实现：`src/api/routes/apps.py`，设计与隔离模型见 [docs/internals/app_identity.md](../internals/app_identity.md)。

仅供接入应用后端通过容器网络调用，例如 Link Resume 走 `tolink-app-net` 访问 `http://tolink-rag:8000`。公网 nginx 对本前缀返回 `404`。总开关 `APPS_API_ENABLED=false`（默认）时，所有路由返回 `404`。

### 鉴权

| Header | 说明 |
| --- | --- |
| `Authorization` | `Bearer <client_id>.<secret>`。凭证由 `scripts/ops/app_client.py create` 生成，只输出一次 |
| `X-App-User-Id` | 接入应用侧的用户 ID，格式 `[A-Za-z0-9_-]{1,64}`；BIGINT 用十进制字符串传入 |

- 凭证校验通过后，`X-App-User-Id` 映射为该应用命名空间内唯一的影子用户。首次调用时自动创建，之后幂等。
- 所有数据按影子用户隔离：同一应用的不同用户之间互不可见，与 toLink 用户之间也互不可见。
- 不接受 Web access token。

错误响应为 `{code, message, data}`，其中 `code` 等于 HTTP 状态码，`data.reason` 为以下之一：

| HTTP | `data.reason` | 场景 |
| --- | --- | --- |
| 401 | `APP_CREDENTIAL_INVALID` | 缺少凭证、格式错误、client 不存在或 secret 错误 |
| 403 | `APP_DISABLED` | 应用已停用 |
| 403 | `APP_USER_DISABLED` | 影子用户已被管理员禁用 |
| 400 | `APP_USER_ID_INVALID` | 缺少 `X-App-User-Id` 或格式不合法 |

业务错误沿用管理端的 `BusinessError` 约定。写入类接口受与 Web 端相同的开关约束：`B4_DATASET_WRITES_ENABLED`、`B5_FILE_WRITES_ENABLED`、`B5_DELETE_WRITES_ENABLED`，开关关闭时返回 `503`。

### 路由

| Method | Path | 说明 |
| --- | --- | --- |
| `PUT` | `/datasets/default` | 幂等获取或创建该用户的默认资料库（名称为"资料库"，绑定应用登记的 SYSTEM embedding 配置）；已被删除时重建。返回数据集 DTO；应用未登记 embedding 配置时返回 `409` |
| `POST` | `/files` | multipart 参数：`file`（必填）、`datasetId`（可选，默认使用默认资料库）、`externalRef`（可选，≤128，只在响应中回显，不落库）。上传后自动解析，立即返回文件 DTO（`uploadStatus=UPLOADING`），上传和解析都是异步的。同一数据集已有同名文件时自动改名为 `name (n).ext`（n 从 2 起），以响应中的 `originalFilename` 为准；同名记录上次上传失败时复用该记录，不改名。Web 端上传仍对重名返回 `400` |
| `GET` | `/files/{fileId}` | 文件 DTO，另附 `parseStatus`（`success`/`failed`/`created`/`null`）、`frontendStatus`（`parse_success`/`parse_failed`/`parsing`/`parse_waiting`）、`parseFailureReason` |
| `POST` | `/files/{fileId}/parse` | 重新提交解析 |
| `DELETE` | `/files/{fileId}` | 删除文件，级联清理 chunk、向量、BM25 和对象存储 |
| `POST` | `/recall` | 纯召回，返回的命中带正文，见下 |

建议的轮询方式：上传后轮询 `GET /files/{fileId}`，直到 `frontendStatus` 为 `parse_success` 或 `parse_failed`。

### POST /api/v1/apps/recall

请求体（未知字段返回 `400`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query` | string，1–2000 | 必填，不能为空白 |
| `datasetIds` | int[]，≤20 | 可选；省略时召回该用户全部有效数据集；包含他人或无效数据集时返回 `403` |
| `fileIds` | int[]，≤100 | 可选，限定在这些文件内召回；必须全部属于该用户且在召回数据集范围内，否则返回 `403`，不做静默过滤 |
| `topK` | int，1–50 | 可选，覆盖数据集配置里的融合结果条数 |

响应 `data`：

```json
{
  "hits": [
    {"chunkId": "…", "fileId": 3001, "datasetId": 901, "score": 0.83,
     "fileName": "resume.pdf", "content": "…chunk 正文…"}
  ],
  "failedSources": []
}
```

`fileId` 即上传返回的文件 `id`。正文按影子用户回读，已删除或不可见的命中会被丢弃。
