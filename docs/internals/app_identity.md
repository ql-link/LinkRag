# 接入应用身份层（App Identity）

让独立产品（首个是 Link Resume）以服务端到服务端的方式复用本服务的解析、分块、向量化与召回能力，同时与 toLink 用户及接入应用内部的不同用户严格隔离。

对外契约见 [http_contracts.md §8](../api/http_contracts.md#8-apps-api接入应用服务端)，表结构见 [mysql.md](../api/schemas/mysql.md)（`app_client`、`app_user_binding`、`sys_user.app_code`）。

## 隔离模型

隔离的真值只有 `user_id`。存储层（Qdrant、Manticore、MinIO、MySQL 业务表）本来就按 `user_id` 硬隔离，并且所有 ID 都由本服务生成（自增主键、uuid4），不会与外部系统冲突。因此接入应用不在存储层增加任何维度，只在身份层把外部用户映射成本系统的影子 `sys_user`：

```text
(app_code, external_user_id) ──app_user_binding──> sys_user.id (app_code=<应用>) ──> 全部下游按 user_id 隔离
```

由此得到下面几条保证：

- 同一应用内的两个外部用户分别映射到不同的 `user_id`，互相看不到对方的数据。
- 不同应用中相同的 `external_user_id` 映射到不同的 `user_id`，因为唯一键是 `(app_code, external_user_id)`。
- `external_user_id` 按 `utf8mb4_bin` 比较，区分大小写，所以 `aB` 和 `Ab` 是两个不同的用户。
- 影子用户名随机生成，Web 注册无法抢先占用，从而阻止某个外部用户首次访问。
- 影子用户和 toLink 用户是不同的 `sys_user` 行，数据天然互不可见。

## 边界规则

| 规则 | 实现位置 |
| --- | --- |
| `X-App-User-Id` 只在应用凭证校验通过后才采信，而且只能解析到本应用命名空间内的用户 | `src/api/app_auth.py` `require_app_principal` |
| 如果绑定指向了其他应用的用户（例如被人为篡改），请求直接失败（fail-closed） | `src/application/app_identity.py` `resolve_shadow_user` |
| `/apps/*` 不接受 Web access token | `require_app_principal` 只解析 `<client_id>.<secret>` |
| 影子用户不能密码登录，返回与"账号不存在"相同的错误，不记失败日志，也不执行 bcrypt | `IdentityUsers.login` |
| 影子用户拿不到可用的 Web 会话：即使签发环节出现漏洞，鉴权回查也会拒绝 | `SqlUserAuthorizationRepository.get_user`、`load_current_user_identity` |
| 管理端用户列表、看板和总览默认只统计 `tolink` 用户；`?appCode=` 可以查看影子用户 | `identity_users.search_users` / `list_users`、`admin_operations` |
| 影子用户的密码字段存哨兵值 `!app-shadow`，不是合法的 bcrypt 串 | `SHADOW_PASSWORD_SENTINEL` |
| 写入类接口复用 Web 端的 B4/B5 开关 | `src/api/routes/apps.py` |

## 影子用户的生命周期

- **创建**：外部用户第一次调用时，在同一个事务里插入 `sys_user` 和 `app_user_binding`。两个请求并发首建时，唯一键会拦下其中一个，失败的一方短暂重读，拿到获胜方写入的绑定。
- **默认资料库**：第一次调用 `PUT /datasets/default`（或上传时没有指定 `datasetId`）时，按应用登记的 SYSTEM embedding 配置创建，并写入 `app_user_binding.default_dataset_id`。如果这个数据集后来被删除，会自动重建。
- **重名上传**：`/apps/files` 以 `rename_on_conflict=True` 调用 `document_uploads.upload`，同名时改名为 `name (n).ext`，Web 端不开启。并发同名上传靠 `uk_dof_name_suffix_seq` 兜底，冲突方最多重试 5 次重新选名。Markdown 资源包不改名。
- **禁用**：管理员在后台禁用影子用户（`sys_user.status=0`）后，`/apps/*` 返回 403 `APP_USER_DISABLED`，已有数据保留。
- **应用停用**：执行 `scripts/ops/app_client.py disable` 后，该应用的所有请求都返回 403 `APP_DISABLED`，最多有 60 秒的缓存延迟。

## 凭证

- 格式为 `<client_id>.<secret>`。secret 用 `secrets.token_urlsafe(32)` 生成，库中只保存 bcrypt 哈希。
- 每个进程内有一个 LRU 缓存（key 为 `sha256(凭证)`，TTL 60 秒，容量 64），避免每个请求都做一次 bcrypt。这意味着轮换或停用后，旧凭证最多还能使用 60 秒。
- 只提供 CLI 运维入口，不开放 HTTP 管理接口，见 [configure.md](../ops/configure.md)。

## 已知限制

- 不做应用级配额和限流，目前由接入方自行控制速率。上传队列仍按进程共享（容量 32）。
- 用量（`llm_usage_log`）记在影子用户名下，管理端目前不能按 `app_code` 汇总用量。
- 不支持解析完成回调，调用方需要轮询 `GET /files/{id}`。
- `externalRef` 只在响应中回显，不落库。接入方应自己保存返回的 `fileId`。
