# Error Codes

本文档记录当前项目错误码和异常约定。实现来源以 `src/core/pipeline/parse_task/error_codes.py` 及各模块异常类为准。

## 1. HTTP 错误约定

| 场景 | 表现 |
| --- | --- |
| Parser/MQ 路由未捕获异常 | HTTP `500`，`detail` 为异常文本 |
| LLM 配置不存在 | HTTP `404`，`detail` 为配置缺失原因 |
| LLM 普通异常 | `APIResponse(code=500, message=..., data=null)` |
| Internal LLM 普通异常 | `APIResponse(code=500, message=..., data=null)` |

## 2. ParseFailureCode

解析流水线失败原因统一由 `ParseFailureCode` 生成，格式：

```text
CODE: 中文业务原因；底层详情
```

最大长度默认 `512`，用于落库并发送给 Java。

| Code | 中文原因 | 典型触发场景 |
| --- | --- | --- |
| `INVALID_TASK_CONTEXT` | 解析任务上下文不一致，请联系管理员确认 | Java 表记录不存在，或 payload 与数据库记录的文件、用户、数据集不一致 |
| `DUPLICATE_TASK` | 解析任务已被处理，请勿重复提交 | 重复 task 命中既有终态记录 |
| `INTERRUPTED_TASK` | 解析任务中断，请重新解析 | 重复 task 命中非终态日志 |
| `SOURCE_FILE_NOT_FOUND` | 原始文件不存在或无法访问 | 对象存储下载源文件失败（对象 404 / 网络异常 / 权限） |
| `TEMP_DISK_FULL` | 服务器临时磁盘空间不足，请联系运维 | 流式下载阶段 worker 本机 `PARSE_TEMP_DIR` 所在盘写满，捕获 `OSError errno=ENOSPC` |
| `UNSUPPORTED_FILE_TYPE` | 当前文件类型暂不支持解析 | `ParserFactory` 不支持文件类型 |
| `PARSE_ENGINE_FAILED` | 文件解析失败，请检查文件内容 | 文件解析、Markdown 增强、分片失败（含增强环节读取 LLM 配置失败等可重试异常） |
| `PARSED_FILE_UPLOAD_FAILED` | 解析结果保存失败，请重新解析 | Markdown 上传对象存储失败 |
| `INTERNAL_UNKNOWN_ERROR` | 系统异常，请稍后重试 | 未归类内部异常 |
| `PARSING_FAILED` | 文件解析阶段失败，请检查文件内容或重新解析 | 文档清洗（解析+上传）阶段统一失败前缀，对应 `failed_stage=CLEANING`（brief 称 `PARSING`） |
| `SPARSE_VECTORIZING_FAILED` | 稀疏向量化失败，请稍后重试 | 稀疏向量阶段任一 chunk 失败、health-check 总数为 0、Qdrant 写入失败等 |
| `LLM_CONFIG_MISSING` | 未配置默认大模型，请先在系统中配置后重试 | 发起用户缺少必配能力的默认 LLM 配置：稠密向量化缺 EMBEDDING（仅「确实未配置」时归此码，配置读取失败仍按 `PARSE_ENGINE_FAILED`，LINK-91）。解析增强缺 CHAT/VISION 默认模型现归 `ENHANCEMENT_MODEL_MISSING` |
| `ENHANCEMENT_MODEL_MISSING` | 已开启表格/图片增强，但未配置对应的默认模型，请先配置默认模型后重试 | 数据集开启表格/图片增强，但发起用户未配对应能力（表格→CHAT，图片→VISION）的默认模型。数据集层不再选择增强模型，统一用用户默认模型，开启增强即要求已配；按约定不回退系统兜底模型，表格与图片对称失败（图片增强不再静默跳过） |
| `EMBEDDING_DIMENSION_UNSUPPORTED` | 所选向量模型维度不受支持，请改用系统支持的向量模型 | 稠密向量化阶段，用户 EMBEDDING 模型输出维度 ≠ `DENSE_VECTOR_DIMENSION`（方案 A 维度约束，LINK-91） |
| `RETRY_VALIDATION_FAILED` | 重试前置校验失败，请确认上次任务状态 | `ParseTaskGuard.validate_retry_context` 任一校验项不满足，或 `mark_superseded` CAS rowcount=0 |

后处理阶段还会生成以下文件级失败原因前缀，它们不是 `ParseFailureCode` 枚举成员，但会通过 `failure_reason` 发送给 Java：

| Prefix | 含义 | 典型触发场景 |
| --- | --- | --- |
| `VECTORIZING_FAILED` | 向量化失败 | Chunk embedding、MySQL 真值写入或 Qdrant 写入存在失败 Chunk |
| `ES_INDEXING_FAILED` | ES 入库失败 | Elasticsearch index 创建或 Chunk 文档写入失败 |

## 3. 解析终态读取（parse_result MQ 已下线，LINK-166）

> **parse_result 终态回传 MQ 已下线（LINK-166）**：Python 端解析完成后**只写 DB 终态**，不再向 Java 发送 `ParseResultMessage`；生产侧 `ParseResultNotifier`、`messages/parse_result.py` 与 `PARSE_RESULT_TOPIC` 配置项均已删除。

解析终态的权威单源是 MySQL `document_parse_pipeline.pipeline_status`（`SUCCESS` / `FAILED`，附 `failed_stage` / `recover_from_stage` / `failure_reason` / 各阶段耗时）。

- `failure_reason` 由 `build_failure_reason` 构造（见 §2），格式 `CODE: 中文原因；底层详情`；成功时为 `null`。
- `pipeline_status=SUCCESS` 表示 Markdown、分片、向量化、ES 入库、稀疏向量全部完成；任一阶段失败即 `FAILED`。
- 前端改由轮询 Java `parse-results` 接口读 DB 获取终态（LINK-98）；Java 端停止消费见 LINK-165。详见 [http_contracts.md](http_contracts.md) / [mq_contracts.md](mq_contracts.md) 的「解析终态读取」。

## 4. Module Exceptions

### Parser

| Exception | 含义 |
| --- | --- |
| `ParseBaseException` | 解析模块基础异常 |
| `UnsupportedFormatError` | 不支持的文件格式 |
| `ParseTimeoutError` | 解析超时 |
| `ValueError("文件流不可为空")` | 空文件流 |

### MQ

| Exception | 含义 |
| --- | --- |
| `MQException` | MQ 基础异常 |
| `MQConnectionError` | Broker 不可达、认证失败、客户端初始化失败 |
| `MQSendError` | 消息发送失败 |
| `MQConsumeError` | 消费失败或回调异常 |
| `MQConfigError` | vendor 或必要参数配置错误 |
| `MQSerializationError` | 消息序列化或反序列化失败 |

### LLM

| Exception | 含义 |
| --- | --- |
| `LLMException` | LLM 基础异常 |
| `AuthenticationError` | API key 无效或认证失败 |
| `RateLimitError` | Provider 限流 |
| `ProviderConnectionError` | Provider 连接失败 |
| `InvalidResponseError` | Provider 响应结构异常 |
| `ConfigurationException` | 配置类异常 |
| `ConfigNotFoundError` | 用户或系统配置不存在 |
| `InvalidConfigError` | 配置非法 |
| `CircuitBreakerOpenError` | 熔断器打开 |
| `AllProvidersFailedError` | 所有 provider 均失败 |
| `TokenLimitExceededError` | Token 超限 |

### Vector Storage

| Exception | 含义 |
| --- | --- |
| `VectorStorageError` | 向量存储基础异常 |
| `VectorStorageConfigurationError` | 向量存储配置错误 |
| `QdrantVectorStorageError` | Qdrant 索引存储基础异常 |
| `QdrantVectorStorageConfigurationError` | Qdrant 依赖或配置错误 |
| `QdrantStoreError` | Qdrant collection 或 point 操作失败 |

### Recall（内部召回 pipeline）

| Exception | 含义 |
| --- | --- |
| `RecallValidationError` | 召回入参非法（query 空白 / user_id 非正 / top_k 非正）|
| `RecallError` | 严格模式任一路失败，或宽松模式全路失败 |
| `RecallFatalError` | `RecallError` 子类；前置必备条件缺失（当前唯一来源：发起用户无默认 EMBEDDING 配置）时**绕过宽松降级**强制整请求失败，映射为 `RECALL_EMBEDDING_CONFIG_MISSING` |

## 5. Recall 错误码（对外 RAG 流 / 纯召回 JSON）

对外两个端点（见 [http_contracts.md §6](http_contracts.md#6-rag--recall-api对外)）：RAG 问答流
`POST /api/v1/rag/stream`（SSE）与纯召回 `POST /api/v1/recall`（JSON）。两端点**握手前错误码相同**；
**执行期错误的载体不同**——RAG 流走 SSE `error` 帧，纯召回走 HTTP 状态码。

> 历史背景：早期 `POST /api/v1/recall/stream` 以 `recall` 之名承载完整 RAG 问答，LINK-131 拆分后
> 删除；更早 Java 网关链路（内部端点 `/api/v1/internal/recall/stream`）的
> `RECALL_INTERNAL_UNAUTHORIZED` / `RECALL_USER_MISMATCH` 等错误码随该链路废弃清理（LINK-122）后不再使用。

**握手前**（会话鉴权 / 参数 / scope / 限流失败）→ 非 2xx 的 `{code, message, data}` JSON，两端点一致：

| 场景 | HTTP | code |
| --- | --- | --- |
| 缺失 / 验签 / iss / aud / scope / exp 失败、用非 session 密钥签发的 token | `401` | `RECALL_SESSION_UNAUTHORIZED` |
| `dataset_ids` 超出 token 授权范围 | `403` | `RECALL_SCOPE_FORBIDDEN` |
| JSON 非法 / 缺字段 / 类型错 / 出现未知字段（含 `user_id`；纯召回端点的 `config_id` 亦属未知字段；RAG 流缺 `config_id`） | `422` | `RECALL_INVALID_REQUEST` |
| `query` 为空或纯空白 | `400` | `RECALL_INVALID_REQUEST` |
| 单用户并发流数超过 `RECALL_SESSION_MAX_CONCURRENT`（**仅 RAG 流**；纯召回不限流） | `429` | `RECALL_RATE_LIMITED` |

**RAG 流握手后**（pipeline 执行期 / 召回前置 / 生成阶段）→ SSE `error` 事件，发送后关闭流：

| 场景 | 事件 | code |
| --- | --- | --- |
| 所选模型 `config_id` 不属本用户 / 非 CHAT 能力 / 已停用 / 不存在（召回前置校验，不进入召回） | `error` | `RECALL_MODEL_CONFIG_MISSING` |
| 发起用户无默认 EMBEDDING 配置（dense 路无法编码 query） | `error` | `RECALL_EMBEDDING_CONFIG_MISSING` |
| 全部召回路失败 / 严格模式失败 | `error` | `RECALL_ALL_SOURCES_FAILED` |
| 召回执行超过 `RECALL_STREAM_TIMEOUT_MS` | `error` | `RECALL_TIMEOUT` |
| 生成阶段 LLM 调用失败（超时 / 报错 / 限流），整请求失败 | `error` | `RECALL_GENERATION_FAILED` |
| 未预期内部异常 | `error` | `RECALL_INTERNAL_ERROR` |

**纯召回执行期**（`POST /api/v1/recall`，无生成）→ HTTP 状态码 + `{code, message, data}` JSON：

| 场景 | HTTP | code |
| --- | --- | --- |
| 发起用户无默认 EMBEDDING 配置 | `422` | `RECALL_EMBEDDING_CONFIG_MISSING` |
| 全部召回路失败 / 严格模式失败 | `500` | `RECALL_ALL_SOURCES_FAILED` |
| 召回执行超过 `RECALL_STREAM_TIMEOUT_MS` | `504` | `RECALL_TIMEOUT` |
| 未预期内部异常 | `500` | `RECALL_INTERNAL_ERROR` |

宽松模式下单路失败但仍有成功路时**不是错误**：正常生成并返回 `answer_done`（0 命中 / 全部片段
缺正文时为 `recall_done`），失败路计入 `failed_sources`。客户端断连不作为业务错误，Python
停止发送事件并取消召回任务。token **短期可复用**：有效期内重复建连均放行，无重放类错误码。

例外：dense 召回 query 编码按发起用户的 EMBEDDING 配置解析（与写入侧同源）。用户无默认
EMBEDDING 配置属**必备前置缺失**，走硬失败（`RECALL_EMBEDDING_CONFIG_MISSING`）而非宽松降级——
即便其余路可用也不返回部分结果，避免"读侧系统模型 / 写侧用户模型"向量空间不一致的误召回。

## 6. Chunk Status Values

| Status | 含义 |
| --- | --- |
| `PENDING` | Chunk 真值已入库，等待索引 |
| `INDEXING` | 正在写入向量索引 |
| `INDEXED` | 向量索引完成 |
| `FAILED` | 向量化或索引失败 |

辅助状态：

- `dense_vector_status`: `PENDING/SUCCESS/FAILED`
- `sparse_vector_status`: `PENDING/SUCCESS/FAILED`
- `es_status`: `PENDING/SUCCESS/FAILED`
- `lifecycle_status`: `ACTIVE/REMOVED`
