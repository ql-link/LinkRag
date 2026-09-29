# Java 管理端迁移基座（F0）

F0 为后续业务迁移提供可复用边界；B1 用户管理路由已在 Python 注册，但尚未切换前端流量。
现有解析流程保持原协议；RAG、Recall、Wiki 已使用 Java RS256 access JWT。配置 B1 Java 会话桥接后，这些路由还会检查旧 Sa-Token 会话是否有效。

## HTTP 与身份

新业务路由使用 `ManagementRouter`，正常返回 `success(data)`，业务错误抛
`BusinessError(code, message, http_status)`。它把参数验证转换为 HTTP 400 和
`{code: 400, message: "请求参数不合法", data: null}`，只作用于使用该 Router 的路由。
Java `Result<T>` 的成功包为整数 `code=200`、`message="success"`、`data`。

受保护路由通过 `Depends(require_login)` 或 `Depends(require_role("ADMIN"))` 获得
`CurrentUser`。管理接口只读取 `satoken` 请求头；RAG 等接口使用 Bearer 请求头。
`AccessTokenVerifier` 固定 RS256，验证 `iss`、`aud`、`sub`、`token_use=access`、
`iat`、`exp`、`jti`。`ManagementAuthenticator` 还要求可信的 `SessionStateProvider`
确认会话仍有效，并经 `UserAuthorizationRepository` 读取 `sys_user` 的当前状态和角色；
`build_access_token_verifier()` 复用 RAG 的 `JAVA_ACCESS_JWT_*` 公钥和签发者配置，仅校验管理接口自己的 audience，缺少配置即报错。
JWT 中的旧角色不参与授权。会话源或用户状态不可用时返回 503，撤销后返回 401，
禁用用户返回 403。B1 已通过 Java 现有受保护资料接口实现过渡期会话核验，并为 Python 签发令牌提供 Redis 活动/撤销状态；目标环境尚需真实联调。不能只凭 JWT 签名启用管理接口。

资源归属应在业务 Repository 中使用 `WHERE owner_id = :current_user_id` 的查询或条件更新。
`require_owner` 可用于已经从可信数据库读取 owner 的用例，ADMIN 不隐式跨越资源归属。
HTTP body 与 MQ 消息的 `user_id` 均不可作为授权依据；消费者需要回查持久记录。
内部服务接口继续使用各自的服务身份，不能复用用户 `satoken`。

## 事务、中间件和审计

写用例可使用 `write_transaction()`，在上下文退出成功提交之后再失效 Redis 缓存或发送 MQ。
普通 `get_db()` / `get_db_context()` 遇到业务异常与取消同样回滚。
跨存储不可丢的操作仍需在业务模块设计 outbox、持久任务或可重扫账本，单纯提交后回调不能保证送达。

MQ 继续使用 `MQService`、`MQFactory` 与已有的四类消息模型；解析/删除消费者仍由
`src/main.py` 启动。Redis 继续使用现有 fenced cache 的 data/fence/lock 和失效方法。
新增业务写路径需逐项列明其缓存 key 和消息所有者；F0 不改变队列、key、TTL 和消息线格式。
审计使用 `audit_event(action, outcome, actor_id, target_id)`，只记录固定结构字段，
不得记录令牌、密钥、请求体、提示词和 MQ 正文；HTTP/MQ trace 继续使用现有 tracing 模块。

## 后续启用门槛

核实目标环境 Java/Web 版本、网关路径、Java token 样本、Sa-Token 撤销行为、
公钥和受众配置，再完成带真实 Java token 的联调。联调通过前管理业务路由不得接入真实用户流量。
Python 自身登录、签发和注销代码由 B1 提供，但签发在 Java 受保护路由退场前默认关闭；详见 [身份与用户模块](identity_users.md)。
