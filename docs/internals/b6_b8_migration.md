# B6–B8 对话、用量和管理运维迁移

本工作树已经把 B6–B8 的 Python 实现接到现有管理鉴权、数据库、Redis 和 RAG 运行时。这里的“已实现”只指代码与本地验证；Java 路由退场、Dev 迁移与前端切流仍需单独验收。

## B6 对话

`/api/v1/chat/conversations` 提供建会话、分页列表、消息分页、标题/置顶更新和删除；`/api/v1/knowledge/chunks/batch` 读取当前用户的有效 Chunk。入口复用 `require_login` 与共享表，不另建认证。RAG 流建流前校验会话所有权和数据集范围；轮次 `GENERATING` 与终态由 `recall_stream_runtime` 直接调用 `chat_service.persist_chat_turn` 在独立事务中写 `chat_message`，以全局唯一 `turn_id` 防重复、以会话行锁防乱序、终态不回退。首轮标题只覆盖默认标题，不覆盖用户手改标题。

## B7 用量

全部模型调用仍走原有 `report_usage_nowait` 埋点入口，后台任务改为本地写 `llm_usage_log`。查询端 `/api/v1/llm/usage/{summary,daily,logs,by-model,trend}` 使用登录用户 ID。前 3 个默认只查 `chat` 阶段；后 2 个按全链路统计。`summary` 的平均延迟只取成功调用，趋势对比相邻等长日区间，上一周期为零时增长率为 `null`。用量旁路的旧失败不阻断主链路语义仍保留，因此进程终止或数据库故障可能丢失用量，不能视为强账务系统。

## B8 管理与运维

`/api/v1/admin/users/dashboard`、`/api/v1/admin/document-file-config` 和 `/api/v1/admin/logs*` 均使用 B1 的数据库角色鉴权，只允许 `ADMIN`。看板按上海业务日期统计 7/30/90 日新增与登录活跃，跨日活跃人数按周期内 distinct 用户数计算。上传配置继续使用现有 `document_runtime_config` 和 Redis 键；PUT 默认由 `B8_DOCUMENT_CONFIG_WRITES_ENABLED=false` 阻止，切流后启用时再检查 Java 的默认配置指纹，不同实例默认值不一致返回 503，Redis 写入成功才更新本进程有效快照。Redis 故障保留旧快照。Loki 由服务端代理，只接受受限的服务名、日志级别、追踪 ID 和经过转义的关键词；地址由 `LOKI_BASE_URL` 配置，前端不传后端地址。

## MQ 收敛与切流

`chat_turn` 和 `usage_report` 原本只在 Python→Java 落库时提供跨服务传递，迁入后生产链路改为进程内调用和本地数据库事务；Kafka 启动不再自动创建这两个 Topic。旧消息类保留为历史载荷兼容资料，运行时不再生产。`parse_task` 继续异步执行文档解析，`document_delete` 继续异步清理解析衍生产物，两者及其 DLT 继续保留。Broker 上旧 Topic 和 Java 消费者需要在切流/排空后由运维退场，应用不会自动删 Topic。

切流前必须确认 Java 的会话、用量、上传配置和日志路由不再承接同一流量，并以同一数据库/Redis 的真实请求对照响应；B3–B5 的写入门禁与 0040/0041 迁移仍按各模块进度处理。特别是 Java 上传默认后缀与当前 Python 解析支持集合并不完全相同，管理员配置写入前须先确定单一控制端和最终格式白名单。Java 配置写入端彻底退场后，如 Redis 的 `runtime:document-file:default-fingerprint` 仍记录 Java 默认值，需在受控切流中将该指纹更新为 Python 默认值，或清除该指纹让 Python 首次写入时重新建立；操作前要确认所有实例默认值一致。生产系统不能把本地测试视为切流验收。
