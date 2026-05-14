# Parse Task Pipeline Module

本文说明 `src/core/pipeline/parse_task_pipeline.py` 解析任务业务流水线的端到端职责、状态边界和失败语义。

## 1. 模块框架

```text
src/core/pipeline/
├── parse_task_pipeline.py       # 解析任务主编排
├── constants.py                 # 解析任务状态和用户提示文案
├── error_codes.py               # ParseFailureCode
├── models.py                    # ParsePipelineResult / 后处理结果模型
├── post_process_constants.py    # 文件级后处理状态常量
└── post_process_repository.py   # document_post_process_pipeline 仓储
```

上游入口：

```text
ParseTaskConsumer
  -> ParseTaskMessage.parse_msg()
  -> ParseTaskPipeline.execute()
```

下游依赖：

```text
StorageFactory / BaseObjectStorage
ParseTaskService
ChunkingEngine
VectorStorageFacade
EsIndexingPipeline
MQService
DocumentParsedLog / DocumentPostProcessPipeline
```

## 2. 端到端流程

```text
parse_task message
  -> create document_parsed_log(created)
  -> validate document_parse_file context
  -> parse source file
  -> upload markdown
  -> mark document_parsed_log success
  -> create/mark document_post_process_pipeline processing
  -> chunk markdown / ParseResult
  -> store chunks to MySQL + Qdrant
  -> index chunks to Elasticsearch
  -> mark document_post_process_pipeline success
  -> send parse_result success
```

失败路径：

```text
any classified failure
  -> write document_parsed_log or document_post_process_pipeline failure state
  -> send parse_result failed
  -> return ParsePipelineResult(status=FAILED)
```

## 3. 核心职责

| 阶段 | 主要方法 | 说明 |
| --- | --- | --- |
| 幂等屏障 | `_create_log_record()` | 先插入 `document_parsed_log`，依赖 task_id 唯一索引阻止重复解析 |
| 重投处理 | `_handle_duplicate_task()` | 对已有终态补发通知；对中断后处理收敛为可恢复失败 |
| 上下文校验 | `_validate_parse_task()` | 校验 MQ payload 与 Java 侧 `document_parse_file` 记录一致 |
| 源文件处理 | `_should_skip_source_download()` / `_download_file()` | MinerU URL API 可跳过本服务下载；其他后端下载源文件 bytes |
| 文件解析 | `_parse_file()` | 调用 `ParseTaskService.aprocess()`，PDF 后端参数来自 payload |
| Markdown 上传 | `_upload_markdown()` | 上传 Markdown 到 payload 指定 bucket/key |
| 分片 | `_run_chunking()` / `_chunk_markdown()` | 优先消费上游 `ParseResult`，否则重新解析 Markdown |
| 向量化 | `_store_chunk_vectors()` | 通过 `VectorStorageFacade` 写 MySQL 真值和 Qdrant |
| ES 入库 | `_get_es_indexing_pipeline()` | 通过 `EsIndexingPipeline` 写 Elasticsearch |
| 结果通知 | `_send_parse_result()` | 向 `tolink.rag.parse_result` 发送整体终态 |

## 4. 状态语义

`document_parsed_log.task_status` 只表示 Markdown 解析和上传事实：

| 状态 | 含义 |
| --- | --- |
| `created` | 日志已创建，任务进入执行 |
| `success` | Markdown 解析产物已上传 |
| `failed` | 解析、上传或前置校验失败 |

`document_post_process_pipeline` 表示文件级后处理状态：

| 阶段字段 | 状态 |
| --- | --- |
| `pipeline_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `chunking_status` | `PENDING/SUCCESS/FAILED` |
| `vectorizing_status` | `PENDING/SUCCESS/FAILED` |
| `es_indexing_status` | `PENDING/SUCCESS/FAILED` |

发送给 Java 的 parse_result `success` 是整体成功语义：Markdown、分片、向量化和 ES 入库均成功。任一阶段失败都会发送 `failed`。

## 5. MinerU URL 直拉

当 payload 满足：

```text
file_type == "pdf"
pdf_parser_backend == "mineru"
```

流水线会：

1. 跳过本服务下载源 PDF。
2. 使用 `storage.build_object_url(source_bucket, source_object_key)` 构造 `source_file_url`。
3. 将 URL 传给 `PdfParser` 和 `MinerUBackend`。

生产环境必须保证该 URL 能被 MinerU 官方云端访问，否则 MinerU 任务创建或轮询会失败。

## 6. 失败码

解析和上传阶段使用 `ParseFailureCode`：

- `INVALID_TASK_CONTEXT`
- `DUPLICATE_TASK`
- `INTERRUPTED_TASK`
- `SOURCE_FILE_NOT_FOUND`
- `UNSUPPORTED_FILE_TYPE`
- `PARSE_ENGINE_FAILED`
- `PARSED_FILE_UPLOAD_FAILED`
- `RESULT_NOTIFY_FAILED`
- `INTERNAL_UNKNOWN_ERROR`

后处理阶段还会构造文件级失败原因：

- `VECTORIZING_FAILED`
- `ES_INDEXING_FAILED`

失败原因统一写入 `failure_reason`，最大长度按数据库字段控制为 512。

## 7. 修改原则

- 不要在 MQ consumer 中直接拼接业务流程，业务编排应留在 `ParseTaskPipeline`。
- 解析成功通知必须晚于 Markdown、分片、向量化和 ES 入库全部完成。
- 新增阶段时应同步更新 `document_post_process_pipeline`、`docs/reference/data_models.md` 和 `docs/reference/error_codes.md`。
- 重投场景必须保持幂等，不应重复解析同一 `task_id`。

## 8. 测试建议

```bash
.venv/bin/pytest tests/unit/core/pipeline/test_parse_task_pipeline.py -q
.venv/bin/pytest tests/unit/core/pipeline/test_post_process_repository.py -q
.venv/bin/pytest tests/integration/core/mq/test_kafka_parse_task_pipeline_integration.py -q
```

建议覆盖：

- 新任务正常全链路。
- 重复 task 的补发、跳过和中断收敛。
- 解析、上传、分片、向量化、ES 和通知失败。
- MinerU 后端跳过源文件下载并注入 `source_file_url`。
