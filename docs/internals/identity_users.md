# 身份与用户模块（B1）

Python 在 `src/api/routes/identity_users.py` 提供 Java 兼容的登录、注册、退出、资料、头像和管理员用户路由；业务写入位于 `src/application/identity_users.py`，会话在 `identity_session.py`。接口字段和错误码见 [HTTP 契约](../api/http_contracts.md)。`sys_user` 与 `user_login_event` 沿用共享 MySQL 表，没有另建账号表或修改 baseline DDL。

受保护路由与现有 RAG/Wiki 共用 `java_access_auth` 的 RS256 验签和公钥配置，管理 API 另校验管理受众；会话有效性、当前数据库状态和角色均需通过。Java 签发的旧 JWT 仍登记在 Sa-Token；Python 的会话适配暂通过 Java 现有 `GET /api/v1/user/profile` 核验，退出时调用 Java 现有 `POST /api/v1/auth/logout`。配置 Java 桥接后，RAG/Wiki 也检查同一会话状态；Java 不可用时拒绝请求。Python 本地签发的 token 在 Redis 登记活动 `jti`，登出按剩余有效期保存撤销记录。

默认关闭 Python 登录签发；只有 Java 受保护业务路由确已退场并显式配置两个开关、私钥、公钥后才能启用。Java 仍需 Sa-Token 的阶段必须继续由 Java 唯一签发，否则 Python 新 token 无法访问 Java。由于旧 Java 路由未统一校验用户禁用状态，Python 的管理员状态变更接口在该阶段拒绝写入；若要提前切流，必须先在 Java 端补齐禁用后的会话撤销或逐请求状态校验。B1 的其余资料/角色接口可单独验收，不以登录签发及状态接口尚未切流阻塞后续模块开发。

用户资料写入提交后按 Java 共用的 `cache:user:profile:{id}` 与对应 fence key 失效，fence TTL 与 Java 默认的 30 天一致。头像使用 F0 公开桶适配；数据库写失败清理新对象。若数据库已提交但缓存失效失败，保留仍被数据库引用的对象并显式报错、记录审计事件；这类失败需在联调环境验证 CDC 补偿或制定修复流程。权限直接读取数据库当前角色和状态，不信任 token 中可能过时的 `role`。注册时若会话登记失败，用户插入随数据库事务回滚，允许原请求安全重试。

注册兼容 Java 的校验顺序：用户名长度先按原始输入判定，随后去首尾空格作为唯一标识；默认昵称使用 `用户` 加 7 位大写字母或数字。真实 API 对照脚本位于 `scripts/acceptance/`；有状态冒烟脚本先检查本地验签服务可用，再创建开发库临时用户，结束时仅清理本轮用户与登录事件。
