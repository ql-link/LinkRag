# Error Codes

本文档记录当前项目错误码和异常约定。实现来源以 `src/core/pipeline/error_codes.py` 及各模块异常类为准。

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
| `SOURCE_FILE_NOT_FOUND` | 原始文件不存在或无法访问 | 对象存储下载源文件失败 |
| `UNSUPPORTED_FILE_TYPE` | 当前文件类型暂不支持解析 | `ParserFactory` 不支持文件类型 |
| `PARSE_ENGINE_FAILED` | 文件解析失败，请检查文件内容 | 文件解析、Markdown 增强、分片失败 |
| `PARSED_FILE_UPLOAD_FAILED` | 解析结果保存失败，请重新解析 | Markdown 上传对象存储失败 |
| `RESULT_NOTIFY_FAILED` | 解析结果通知失败，请重新解析 | parse_result 终态通知 MQ 发送失败 |
| `INTERNAL_UNKNOWN_ERROR` | 系统异常，请稍后重试 | 未归类内部异常 |

## 3. Parse Result 失败通知

发送给 Java 的 parse result payload 字段：

```json
{
  "task_id": "...",
  "original_file_id": 10001,
  "document_parse_task_id": 10002,
  "dataset_id": 10003,
  "user_id": 10002,
  "task_status": "failed",
  "failure_reason": "PARSE_ENGINE_FAILED: 文件解析失败，请检查文件内容；...",
  "parse_finished_at": "2026-04-28T10:00:08"
}
```

约定：

- 成功时 `failure_reason` 为 `null`。
- 失败时异常详情放入 `failure_reason`。
- 不添加用户通知字段。
- 不添加 `mq_type`、`mq_name`、`payload` 信封。

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

## 5. Chunk Status Values

| Status | 含义 |
| --- | --- |
| `PENDING` | Chunk 真值已入库，等待索引 |
| `INDEXING` | 正在写入向量索引 |
| `INDEXED` | 向量索引完成 |
| `FAILED` | 向量化或索引失败 |
| `DELETING` | 正在删除 |
| `DELETED` | 已删除 |
| `DELETE_FAILED` | 删除失败，等待补偿 |

辅助状态：

- `vector_status`: `PENDING/SUCCESS/FAILED`
- `es_status`: `PENDING/SUCCESS/FAILED`
