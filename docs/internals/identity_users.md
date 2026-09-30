# 身份与用户模块（B1）

Python 在 `src/api/routes/identity_users.py` 提供登录、注册、退出、资料、头像和管理员用户路由；业务写入位于 `src/application/identity_users.py`，会话在 `identity_session.py`。接口字段和错误码见 [HTTP 契约](../api/http_contracts.md)。`sys_user` 与 `user_login_event` 沿用共享 MySQL 表，没有另建账号表或修改 baseline DDL。

当前 Dev/生产 Compose 启用 `B1_PYTHON_ISSUER_ENABLED=true` 和 `B1_JAVA_PROTECTED_ROUTES_RETIRED=true`，Python 使用只读挂载的 RS256 私钥签发 access JWT，并以公钥、当前数据库用户状态和角色验证受保护路由；管理 API 另校验管理受众。`java_access_auth` 及 `JAVA_ACCESS_JWT_*` 是为旧 JWT、表字段和密钥文件名保留的兼容命名，不表示运行时仍依赖 Java。Python 在 Redis 登记活动 `jti`，登出按剩余有效期保存撤销记录。

未启用上述两个 B1 开关的旧部署仍可只验证既有 access JWT；若配置 `B1_JAVA_AUTH_BASE_URL`，才会启用与遗留 Java 服务的会话桥接。该兼容模式不应作为新部署的前提条件。私钥、公钥或签发配置缺失时，Python 启动拒绝接管签发，避免产生无法验证的登录态。

用户资料写入提交后按兼容缓存键 `cache:user:profile:{id}` 与对应 fence key 失效，fence TTL 为 30 天。头像使用 F0 公开桶适配；数据库写失败清理新对象。若数据库已提交但缓存失效失败，保留仍被数据库引用的对象并显式报错、记录审计事件；这类失败需在联调环境验证 CDC 补偿或制定修复流程。权限直接读取数据库当前角色和状态，不信任 token 中可能过时的 `role`。注册时若会话登记失败，用户插入随数据库事务回滚，允许原请求安全重试。

注册兼容 Java 的校验顺序：用户名长度先按原始输入判定，随后去首尾空格作为唯一标识；默认昵称使用 `用户` 加 7 位大写字母或数字。真实 API 对照脚本位于 `scripts/acceptance/`；有状态冒烟脚本先检查本地验签服务可用，再创建开发库临时用户，结束时仅清理本轮用户与登录事件。
