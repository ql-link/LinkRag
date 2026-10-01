# 身份与用户模块（B1）

Python 在 `src/api/routes/identity_users.py` 提供登录、注册、退出、资料、头像和管理员用户路由；业务写入位于 `src/application/identity_users.py`，会话在 `identity_session.py`。接口字段和错误码见 [HTTP 契约](../api/http_contracts.md)。`sys_user` 与 `user_login_event` 沿用共享 MySQL 表，没有另建账号表或修改 baseline DDL。

当前 Dev/生产 Compose 启用 `B1_PYTHON_ISSUER_ENABLED=true` 和 `B1_JAVA_PROTECTED_ROUTES_RETIRED=true`，Python 使用只读挂载的 RS256 私钥签发 access JWT，并以公钥、当前数据库用户状态和角色验证受保护路由；管理 API 另校验管理受众。`java_access_auth` 及 `JAVA_ACCESS_JWT_*` 是为旧 JWT、表字段和密钥文件名保留的兼容命名，不表示运行时仍依赖 Java。Python 在 Redis 登记活动 `jti`，登出按剩余有效期保存撤销记录。

未启用上述两个 B1 开关的旧部署仍可只验证既有 access JWT；若配置 `B1_JAVA_AUTH_BASE_URL`，才会启用与遗留 Java 服务的会话桥接。该兼容模式不应作为新部署的前提条件。私钥、公钥或签发配置缺失时，Python 启动拒绝接管签发，避免产生无法验证的登录态。

用户资料写入提交后按兼容缓存键 `cache:user:profile:{id}` 与对应 fence key 失效，fence TTL 为 30 天。头像使用 F0 公开桶适配；数据库写失败清理新对象。若数据库已提交但缓存失效失败，保留仍被数据库引用的对象并显式报错、记录审计事件；这类失败需在联调环境验证 CDC 补偿或制定修复流程。权限直接读取数据库当前角色和状态，不信任 token 中可能过时的 `role`。注册时若会话登记失败，用户插入随数据库事务回滚，允许原请求安全重试。

注册兼容 Java 的校验顺序：用户名长度先按原始输入判定，随后去首尾空格作为唯一标识；默认昵称使用 `用户` 加 7 位大写字母或数字。真实 API 对照脚本位于 `scripts/acceptance/`；有状态冒烟脚本先检查本地验签服务可用，再创建开发库临时用户，结束时仅清理本轮用户与登录事件。

## 新用户购物演示数据集

`src/application/demo_dataset.py` 在本系统密码注册时初始化“购物演示数据集”，源素材为 `src/assets/demo_dataset/` 中的商品选购、下单配送、退换货售后三份 Markdown。开关和模型选择规则见[配置说明](../ops/configure.md#新用户购物演示数据集)。普通登录、接入应用影子用户和既有账号不自动补建；用户删除演示库后重新登录不会恢复它。

每次注册准备不同 RAW 原件，随后在注册事务内写入本人 dataset、dataset_parse_config、document_original_file、document_parse_file、默认模型指针和初始解析 outbox。用户、数据集和文件都用当前新用户 ID，沿用现有修改、删除、检索及引用权限。不会建立共享库、只读例外或复制模型密钥。

数据集精确绑定平台 EMBEDDING 和 SPARSE_EMBEDDING 配置，关闭表格、图片、标题增强及 rerank。新用户的 CHAT、EMBEDDING、SPARSE_EMBEDDING 默认指针也设为对应平台配置，现有模型加载和对话入口可以直接使用；之后调整默认模型不改变已建数据集向量模型。

注册成功代表三份原件和解析任务已经落库，不代表索引已完成。解析使用现有 `ParseTaskMessage` 的 `md` / `upload_auto` 载荷，task ID、文件指针与 outbox 同事务保存。既有 outbox 补发循环在下一轮投递任务（通常30秒内开始），Broker 暂不可用时保留待投递记录。文档需解析、索引成功后才能检索；失败可通过现有文件解析重试入口处理。

原件上传在写事务之前执行，初始化失败或请求取消时清理本次对象；会话登记及数据库提交失败仍回滚账号并撤销已签发会话。演示表写入异常返回503，避免被误判为邮箱冲突。对象存储的取消与补偿边界见[对象存储说明](object_storage.md#演示文档原件)。
