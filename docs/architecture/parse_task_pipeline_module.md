# Parse Task Pipeline Module

本文说明 `src/core/pipeline/parse_task/pipeline.py` 解析任务业务流水线的端到端职责、状态边界和失败语义。

## 1. 模块框架

`pipeline/` 顶层按概念分两个子包：

```text
src/core/pipeline/
├── parse_task/                  # 解析任务主编排
│   ├── pipeline.py              # ParseTaskPipeline 主类（编排骨架）
│   ├── constants.py             # 解析任务状态和用户提示文案
│   ├── error_codes.py           # ParseFailureCode + build_failure_reason
│   ├── models.py                # ParsePipelineResult / PipelineStatus
│   ├── log_repository.py        # ParseLogRepository: document_parsed_log 仓储与终态写入
│   ├── notifier.py              # ParseResultNotifier: parse_result MQ 通知与兜底
│   ├── source.py                # ParseSourceIO: 对象存储侧源文件下载 / Markdown 上传
│   ├── validator.py             # ParseTaskGuard: 前置校验、MQ 重投与中断状态收敛
│   ├── _utils.py                # 子包内部共享小工具（now / duration_ms / 等）
│   └── post_process/            # 文件级后处理子状态机（chunking → vectorizing → pretokenize → es_indexing）
│       ├── constants.py         # PIPELINE_STATUS_* / STAGE_STATUS_*
│       ├── models.py            # PostProcessStageResult / PostProcessResult
│       └── repository.py        # PostProcessPipelineRepository（document_post_process_pipeline 仓储）
```

`ParseTaskPipeline` 由 4 个协作者通过依赖注入组合而成：

| 协作者 | 职责 |
| --- | --- |
| `ParseLogRepository` | `document_parsed_log` 创建、按 task_id 查询、success/failed 终态写入 |
| `ParseSourceIO` | 源文件下载、Markdown 上传、MinerU URL 拼接、`should_skip_source_download` 判断 |
| `ParseResultNotifier` | parse_result MQ 通知；通知失败时按策略兜底 `RESULT_NOTIFY_FAILED` |
| `ParseTaskGuard` | 消息载荷一致性校验、重复 task_id 的终态补发、中断 pipeline 的失败收敛 |

`ChunkingEngine` 与 `VectorStorageFacade` 由各自模块的工厂入口装配，不再由 pipeline 自己组装：

| 工厂入口 | 位置 |
| --- | --- |
| `create_chunking_engine()` | `src/core/splitter/factory.py` |
| `create_system_embedding_client()` / `LazyEmbeddingClient` | `src/core/splitter/factory.py` |
| `compose_vector_storage_facade()` | `src/core/vector_storage/factory.py` |

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
Preprocessor / PreprocessorProtocol   # 预分词独立阶段，构建 FilePostIndexPlan；失败仅抛 PreprocessorError，不写 chunk
EsIndexingPipeline                    # 消费 FilePostIndexPlan 做 ES bulk 写入
ChunkRepository                       # 空 plan 兜底计数 count_es_not_success_by_doc_id（预分词失败不再标 chunk）
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
| 预分词（一等独立阶段） | `_run_pretokenize()` / `_get_preprocessor()` | `Preprocessor.build_file_post_index_plan()` 聚合 doc 下 chunk token 为内存 `FilePostIndexPlan`（单趟扇出，不持久化）。文件级 all-or-nothing：成功 `mark_pretokenize_success`；失败返回 `(None, reason)`，由 `_run` 统一 `mark_pretokenize_failed` + 通知 Java FAILED，**不写任何 chunk es_status** |
| ES 入库 | `_run_es_indexing()` | 仅消费内存 `FilePostIndexPlan` 调用 `EsIndexingPipeline.write_es_index()`，保持 chunk 级失败语义；`_ensure_index` 等基础设施故障按文件级处理（不标 chunk，`ensure_index:` 前缀）。失败由 `_run` 统一 `mark_es_failed` + 通知，**不计数、不设上限、不写 retry_exhausted** |
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
| `pretokenize_status` | `PENDING/SUCCESS/FAILED` |
| `es_indexing_status` | `PENDING/SUCCESS/FAILED` |

阶段顺序：`CHUNKING → VECTORIZING(dense/Qdrant) → PRETOKENIZE → ES_INDEXING`。发送给 Java 的 parse_result `success` 是整体成功语义：Markdown、分片、向量化、预分词与 ES 入库均成功。任一阶段失败都会发送 `failed`。

### 失败即终态与恢复入口（无 ES 内部自动重试）

任一阶段失败即终态：只把结果写入 `document_post_process_pipeline`（阶段状态 FAILED、`failed_stage`、`recover_from_stage`、`failure_reason`、`finished_at`、耗时）并通知 Java `failed`。系统**不计数、不设上限、不写 retry_exhausted、不自动重试**。

- **预分词失败**（`_run_pretokenize` 捕获 `PreprocessorError`，或空 plan 但仍有未完成 chunk）：`mark_pretokenize_failed` 落 `pretokenize_status=FAILED` + `recover_from_stage=PRETOKENIZE`；**绝不写任何 chunk es_status**（文件级 all-or-nothing）。
- **ES 基础设施故障**（`_ensure_index` 等）：文件级，不标 chunk，`failure_reason` 以 `ensure_index:` 前缀。
- **ES chunk 级写失败**：逐 chunk 标 `es_status=FAILED`，文件级 `es_indexing_status=FAILED`，前缀 `ES_INDEXING_FAILED:`。
- **恢复入口** `_infer_recover_stage()` 取首个非 SUCCESS 阶段（chunking→vectorizing→pretokenize→es）。`pretokenize_status` 不被 `mark_processing` 清，恢复推断据此回 `PRETOKENIZE`。
- **用户侧重试**：`document_post_process_pipeline.retry_count`/`last_retry_at` 保留，语义为用户前端触发重试的计数；仅由预留方法 `claim_failed_for_retry`（对照 `ChunkRepository.claim_failed_for_reindex`）在认领重试时 +1，模块/失败处理器/`mark_processing` 一律不写。**本期仅提供该方法、不接线任何触发路径**。

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

后处理阶段还会构造文件级失败原因，并以来源前缀区分（纯内部排障，Java 仅展示不解析）：

- `VECTORIZING_FAILED`
- `pretokenize:`（预分词失败 / 空 plan 但仍有未完成 chunk）
- `ensure_index:`（ES 确保索引存在等基础设施故障）
- `ES_INDEXING_FAILED:`（ES bulk chunk 级写失败）

失败原因统一写入 `failure_reason`，最大长度按数据库字段控制为 512。

## 7. 修改原则

- 不要在 MQ consumer 中直接拼接业务流程，业务编排应留在 `ParseTaskPipeline`。
- 解析成功通知必须晚于 Markdown、分片、向量化、预分词和 ES 入库全部完成。
- 新增阶段时应同步更新 `document_post_process_pipeline` 表结构、`docs/reference/mysql_schema.md` 和 `docs/reference/error_codes.md`。
- 重投场景必须保持幂等，不应重复解析同一 `task_id`。

## 8. 测试建议

```bash
.venv/bin/pytest tests/unit/core/pipeline/test_parse_task_pipeline.py -q
.venv/bin/pytest tests/unit/core/pipeline/test_parse_task_pipeline_es.py -q
.venv/bin/pytest tests/unit/core/pipeline/test_post_process_repository.py -q
.venv/bin/pytest tests/integration/core/mq/test_kafka_parse_task_pipeline_integration.py -q
```

建议覆盖：

- 新任务正常全链路。
- 重复 task 的补发、跳过和中断收敛。
- 解析、上传、分片、向量化、ES 和通知失败。
- MinerU 后端跳过源文件下载并注入 `source_file_url`。
- 预分词失败为文件级 all-or-nothing：落 `pretokenize_status=FAILED`，不写任何 chunk es_status。
- ES 基础设施故障（`ensure_index`）文件级不标 chunk；ES chunk 级失败逐 chunk 标记。
- 失败即终态：ES 失败不递增 retry_count、无 retry_exhausted；`mark_processing` 不清各阶段 `*_status`/`retry_count`。所有阶段失败均由 `_run` 统一写库+通知。
- 恢复入口推断按首个非 SUCCESS 阶段，`pretokenize_status` 与其他阶段状态列一样跨重投持久。
