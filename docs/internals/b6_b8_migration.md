# B6–B8 对话、用量和管理运维迁移

本页主体是 Java→Python 迁移期间的验证记录。自 2026-09-30 起，`dev` 的 Compose 与 Nginx 已将 Java 管理端下线、把 `/api/` 统一转发给 Python，B1–B10 相关开关在 Dev/生产 Compose 中默认开启；当前部署事实以 [部署指南](../ops/deploy.md) 为准。下文保留当时的 Java 对照和切流风险，作为历史验收证据，不应解读为现行路由状态。

## B6 对话

`/api/v1/chat/conversations` 提供建会话、分页列表、消息分页、标题/置顶更新和删除；`/api/v1/knowledge/chunks/batch` 读取当前用户的有效 Chunk。入口复用 `require_login` 与共享表，不另建认证。RAG 流建流前校验会话所有权和数据集范围；轮次 `GENERATING` 与终态由 `recall_stream_runtime` 直接调用 `chat_service.persist_chat_turn` 在独立事务中写 `chat_message`，以全局唯一 `turn_id` 防重复、以会话行锁防乱序、终态不回退。首轮标题只覆盖默认标题，不覆盖用户手改标题。

## B7 用量

全部模型调用仍走原有 `report_usage_nowait` 埋点入口，后台任务改为本地写 `llm_usage_log`。查询端 `/api/v1/llm/usage/{summary,daily,logs,by-model,trend}` 使用登录用户 ID。前 3 个默认只查 `chat` 阶段；后 2 个按全链路统计。`summary` 的平均延迟只取成功调用，趋势对比相邻等长日区间，上一周期为零时增长率为 `null`。用量旁路的旧失败不阻断主链路语义仍保留，因此进程终止或数据库故障可能丢失用量，不能视为强账务系统。

## B8 管理与运维

`/api/v1/admin/users/dashboard`、`/api/v1/admin/document-file-config` 和 `/api/v1/admin/logs*` 均使用 B1 的数据库角色鉴权，只允许 `ADMIN`。看板按上海业务日期统计 7/30/90 日新增与登录活跃，跨日活跃人数按周期内 distinct 用户数计算。上传配置继续使用现有 `document_runtime_config` 和 Redis 键；PUT 默认由 `B8_DOCUMENT_CONFIG_WRITES_ENABLED=false` 阻止，切流后启用时再检查 Java 的默认配置指纹，不同实例默认值不一致返回 503，Redis 写入成功才更新本进程有效快照。Redis 故障保留旧快照。Loki 由服务端代理，只接受受限的服务名、日志级别、追踪 ID 和经过转义的关键词；地址由 `LOKI_BASE_URL` 配置，前端不传后端地址。

## MQ 收敛与切流

`chat_turn` 和 `usage_report` 原本只在 Python→Java 落库时提供跨服务传递，迁入后生产链路改为进程内调用和本地数据库事务；Kafka 启动不再自动创建这两个 Topic。旧消息类保留为历史载荷兼容资料，运行时不再生产。`parse_task` 继续异步执行文档解析，`document_delete` 继续异步清理解析衍生产物，两者及其 DLT 继续保留。Broker 上旧 Topic 和 Java 消费者需要在切流/排空后由运维退场，应用不会自动删 Topic。

切流前必须确认 Java 的会话、用量、上传配置和日志路由不再承接同一流量，并以同一数据库/Redis 的真实请求对照响应；B3–B5 的写入门禁与 0040/0041 迁移仍按各模块进度处理。管理员配置写入前须确定单一控制端，并逐环境核对 Java 与 Python 的最终格式白名单；本轮仅确认 Dev 指纹一致。Java 配置写入端彻底退场后，如 Redis 的 `runtime:document-file:default-fingerprint` 仍记录不同的 Java 默认值，需在受控切流中将该指纹更新为 Python 默认值，或清除该指纹让 Python 首次写入时重新建立；操作前要确认所有实例默认值一致。生产系统不能把本地测试视为切流验收。

## 2026-09-29 审查与 Dev API 验证

本轮审查修复了三个可观察的契约问题：Chunk 批量详情有命中时，轻量文件表定义缺少 `original_filename` 导致 500；B7 同一秒用量日志多加了 ID 降序，与 Java 页内顺序不同；B8 日志代理的脱敏、Loguru 时间与 `ACCESS/AUDIT` 级别、异常堆栈字段，以及上传配置后缀顺序与 Java 不一致。对应测试覆盖了命中、跨用户和已移除 Chunk，非空用量以及正常、畸形 Loki 载荷。

在本地 FastAPI 真实路由连接 Dev MySQL/Redis 的条件下，52 个 `curl` 场景全部通过，覆盖 B6 会话创建、列表、标题与置顶更新、消息分页、删除、Chunk 批量详情、参数校验、身份与所有权；B7 五类查询、阶段过滤、成功/失败、跨日趋势、分页和隔离；B8 7/30/90 日看板、配置读取与默认写入门禁、日志筛选/脱敏/分页、权限和异常。Loki 成功路径使用本地协议模拟服务，停止该服务后另测得 labels 回退 200、日志查询 502。Dev Java 与 Python 在同一临时账号、同一非空 B6/B7 数据下，八个接口的 HTTP 与 JSON 响应逐项一致；B8 看板和配置读取的两个只读接口也一致。B8 配置 PUT 在独立 Redis 测试键下覆盖合法写入回读、非法大小/后缀及普通用户拒绝，测试键随后清除。B6 SSE 握手覆盖缺少 `turn_id`、越权数据集和缺少模型绑定；另用确定性的空检索与模型替身，通过 `curl` 验证空命中写 `COMPLETED`、同 `turn_id` 重放不增行及模型解析失败写 `FAILED`，消息均从 Dev MySQL 回读。

| 测试组 | 可断言场景 |
| --- | --- |
| B6 会话 | 未登录/坏 JWT 拒绝；本人建会话、默认标题、列表分页、改标题与置顶、消息分页、删除；空更新/空标题/非法页码拒绝；跨用户数据集、消息、更新、删除均拒绝。 |
| B6 引用 | ACTIVE 且归本人的 Chunk 带文件名返回；重复 ID 去重；已移除和他人的 Chunk 不返回；空数组和超过上限拒绝。 |
| B6 流 | 缺 `turn_id` 返回 422、越权数据集返回 403、未绑定模型返回 409；隔离外部依赖后验证空命中终态、同轮重放及失败终态落库。 |
| B7 查询 | `summary` 成功率与仅成功调用的平均延迟；`daily` 跨日；`logs` 分页；`by-model` 聚合；`trend` 等长前期；默认 `chat`、`all`、空阶段和跨用户隔离。 |
| B7 异常 | 反向/错误/缺少日期、页码 0、超上限页大小、未登录均拒绝；同秒日志顺序与 Java 非空样本对照。 |
| B8 管理 | 普通用户及未登录拒绝；7/30/90 日趋势长度与非法天数；配置 GET、默认 PUT 门禁；隔离 Redis 键下校验合法 PUT 回读、非法大小与后缀、普通用户 PUT 拒绝。 |
| B8 日志 | labels 与查询成功、分页、敏感字段遮盖；LogQL 注入、无效级别和时间拒绝；Loki 断开时 labels 回退、查询返回 502；畸形响应不造成 500。 |

上述 52 个场景当时尚未覆盖真实模型生成与断连续跑、真实 Loki 查询和 Java/Python 流量切换。完整文档解析 MQ 保留，本地 API 验证未启动 Dev MQ 消费者，避免抢占解析任务。运行环境最初缺少 `infinity-sdk`，导致 RAG 握手前返回 500；本轮仅从本机缓存补入隔离的临时测试环境后复测，项目依赖文件没有改变。

## 2026-09-29 真实依赖补充验收

本地 FastAPI 连接 Dev MySQL/Redis，使用现有已配置的 SiliconFlow CHAT 模型与临时合成数据集。为了避免把现有用户文档送到外部模型，测试夹具只把该数据集中的一条合成 Chunk 作为召回命中；模型解析、流式生成、对话落库与用量记录均走真实实现。完整请求返回 HTTP 200，SSE 包含 `stream_started`、多个 `answer_delta`、`answer_done`，Dev `chat_message` 为 `COMPLETED` 且答案非空。第二轮 `curl --max-time 1.5` 在只收到 `stream_started` 后以退出码 28 断开，随后数据库中的同轮消息仍变成 `COMPLETED` 且答案非空。真实三路召回对空测试数据集的请求返回 `RECALL_ALL_SOURCES_FAILED`；本机日志显示 BM25 缺少 NLTK `punkt_tab`，因此本次不把真实召回链路标记为通过。三个测试消息、三条用量记录、临时数据集/Chunk/会话与测试登录态已经清理。

Dev Loki 的 `/ready` 返回 200。首次查询发现 `service` 标签只有 `linkresume`，但历史 `tolink-service` 日志实际存于 Promtail 的 `service_name` 标签，直接用 `{service_name="tolink-service"}` 可查到 5 条；`tolink-rag` 在两类标签下均未出现。本轮把 Python 查询与标签列表改为兼容 `service`/`service_name`，并把 Dev Promtail 的新写入标签统一为 `service`。修复后的本地 Python 管理路由真实请求中，`GET /api/v1/admin/logs/labels` 返回 `linkresume` 和 `tolink-service`，`GET /api/v1/admin/logs?service=tolink-service&page_size=5` 返回 5 条 Java 历史日志，均为 HTTP 200。Promtail 配置改动尚未部署；需在 Dev 部署后确认新日志使用 `service`，并查明 Python 日志未入 Loki 的原因。

Dev Redis 中 Java 的默认配置指纹与当前 Python 默认值一致，且上传配置键在测试前不存在。本地临时启用 Python B8 PUT，以与默认值完全相同的 20 MiB、六种后缀写入真实共享键；PUT 返回 200，另一 Python 进程 GET 返回相同快照，指纹未改变。测试结束时通过值比较原子删除本次写入，上传配置键恢复为不存在。该测试证明 Python 共享键读写和本次 Dev 默认指纹门禁通过；未通过 Java 运行时接口验证其快照反序列化。

**共享配置流量尚未切换。** 当前 `deploy/dev-server/nginx.conf` 的 `/api/` 仍转给 Java，仅 `/api/v1/rag/stream` 转给 Python；部署的 Python 写入开关默认关闭，Java 配置写入口仍在。正式切流需先部署本工作树对应的 Python 版本并配置真实 Java JWT 公钥和 Loki 内网地址，再使 Java 的配置 PUT 退场、启用单一 Python 写入者、把配置 GET/PUT 路由转给 Python，最后用真实管理员令牌对比 Java/Python 读回并核对 Redis 快照。其他环境的默认白名单仍须逐环境核对；本轮仅验证 Dev 指纹一致。切流失败时先关闭 Python PUT 并恢复路由，Redis 快照只能在确认没有后续管理员写入后按备份值恢复。

后续已将 NLTK 数据下载脚本改为经现有 `httpx` 证书包下载，修复本机 `urllib` 官方源证书链报错。项目内的 `punkt`、`punkt_tab`、`stopwords`、`wordnet`、`omw-1.4` 已实际下载，运行时 `nltk.word_tokenize` 成功。此前失败的三路真实召回请求尚未重跑，不能据此宣称完整检索通过。
