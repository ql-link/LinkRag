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
│   ├── notifier.py              # ParseResultNotifier: parse_result MQ 通知与兜底；ParseResultNotificationError 继承 RetriableError，由消费框架做有限退避重试 + 死信兜底（见 mq.md §4.1）
│   ├── source.py                # ParseSourceIO: 对象存储侧源文件流式下载到 Path / Markdown 上传
│   ├── temp_workspace.py        # PARSE_TEMP_DIR 启动清理、临时文件分配、safe_unlink 幂等
│   ├── validator.py             # ParseTaskGuard: 前置校验、MQ 重投与中断状态收敛
│   ├── _utils.py                # 子包内部共享小工具（now / duration_ms / 等）
│   └── post_process/            # 文件级后处理子状态机（cleaning → chunking → vectorizing → pretokenize → es_indexing → sparse_vectorizing）
│       ├── constants.py         # PIPELINE_STATUS_* / STAGE_STATUS_*
│       ├── models.py            # PostProcessStageResult / PostProcessResult
│       └── repository.py        # ParsePipelineRepository（document_parse_pipeline 仓储）
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
EsIndexingPipeline                    # 消费 FilePostIndexPlan 做 ES bulk 写入；delete_document_index 按 user+dataset+doc 文档级删除（全量重建）
ChunkRepository                       # 空 plan 兜底计数 count_es_not_success_by_doc_id（预分词失败不再标 chunk）
MQService
DocumentParsedLog / DocumentParsePipeline
```

## 2. 端到端流程

```text
parse_task message
  -> create document_parsed_log(created)
  -> validate document_parse_file context
  -> parse source file
  -> upload markdown
  -> mark document_parsed_log success
  -> create/mark document_parse_pipeline processing
  -> chunk markdown / ParseResult
  -> store chunk facts to MySQL
  -> reload persisted chunk truth rows
  -> dense index filtered chunks to Qdrant
  -> pretokenize chunks
  -> index chunks to Elasticsearch
  -> reload fresh chunk truth rows
  -> sparse vectorize filtered dense-success chunks
  -> mark document_parse_pipeline success
  -> send parse_result success
```

失败路径：

```text
any classified failure
  -> write document_parsed_log or document_parse_pipeline failure state
  -> send parse_result failed
  -> return ParsePipelineResult(status=FAILED)
```

## 3. 核心职责

| 阶段 | 主要方法 | 说明 |
| --- | --- | --- |
| 幂等屏障 | `_create_log_record()` | 先插入 `document_parsed_log`，依赖 task_id 唯一索引阻止重复解析 |
| 重投处理 | `_handle_duplicate_task()` | 对已有终态补发通知；对中断后处理收敛为可恢复失败 |
| 上下文校验 | `_validate_parse_task()` | 校验 MQ payload 与 Java 侧 `document_parse_file` 记录一致 |
| 源文件处理 | `ParseSourceIO.should_skip_source_download()` / `ParseSourceIO.download_to_path()` + `temp_workspace.create_temp_file()` + `temp_workspace.safe_unlink()` | MinerU URL API 跳过本地下载（`source_path=None`）；其他后端流式下载到 `PARSE_TEMP_DIR/parse-{task_id}-{rand}.tmp`，拿到 markdown 后立即 `safe_unlink` 早删，外层 `finally` 二次兜底。下载阶段 `OSError errno=ENOSPC` 归类 `TEMP_DISK_FULL`，其他下载异常归类 `SOURCE_FILE_NOT_FOUND` |
| 文件解析 | `_run_cleaning_stage()` / `_parse_file()` | `recover_from_stage=CLEANING` 的 retry 入口，按首次解析一致的顺序下载源文件、调用 `ParseTaskService.aprocess()`、上传 Markdown，并在上传成功后写入 `document_parsed_log.parsed_*` |
| Markdown 上传 | `ParseSourceIO.upload_markdown()` | 上传 Markdown 到 payload 指定 bucket/key；cleaning retry 不预写旧 markdown 坐标，成功后由 `mark_parsed()` 写入真实坐标 |
| 分片 | `_run_chunking()` / `_chunk_markdown()` / `_persist_chunk_facts()` | 优先消费上游 `ParseResult`，否则重新解析 Markdown；分片成功后在 chunking 阶段单事务批量写入 `kb_document_chunk` 真值记录，并在 commit 后按 `doc_id` 反查 ORM 行，返回 `list[ChunkRecordDB]` 作为下游唯一 chunk 形态 |
| 向量化 | `_store_chunk_vectors()` | 接收 `list[ChunkRecordDB]`，现场过滤 `dense_chunks = [c for c in chunks if c.dense_vector_status != SUCCESS]`，再通过 `VectorStorageFacade.index_chunks(user_id, set_id, doc_id, chunks=...)` 写 Qdrant；dense 模块不再自查 SQL、不接收 `include_failed`，由多值 CAS `(PENDING, FAILED)` 兜底首次 / 重试共用入口 |
| 预分词（一等独立阶段） | `_run_pretokenize()` / `_get_preprocessor()` | `Preprocessor.build_file_post_index_plan()` 聚合 doc 下 chunk token 为内存 `FilePostIndexPlan`（单趟扇出，不持久化）。**plan 覆盖该文档全部有效 chunk（不按 `es_status` 过滤，Issue #57）**，已 SUCCESS 的 chunk 也重新 tokenize 进入 plan，供 ES 文档级全量重建消费。文件级 all-or-nothing：成功 `mark_pretokenize_success`；失败返回 `(None, reason)`，由 `_run` 统一 `mark_pretokenize_failed` + 通知 Java FAILED，**不写任何 chunk es_status** |
| ES 入库（文档级全量重建，Issue #57） | `_run_es_indexing()` | **前置删除 → 全量写入 → 失败清理**：先 `EsIndexingPipeline.delete_document_index(user+dataset+doc)` 删干净该文档已有 ES 索引（首次执行命中 0 的幂等空操作，重试时清理旧残留与陈旧 chunk），再消费内存 `FilePostIndexPlan` 调 `write_es_index()` 全量写（相同 `_id` 覆盖）。前置删除失败（ES 不可达）直接判 ES 失败、不写入（`es_delete:` 前缀）；写入未全部成功时再次 delete 清理本趟半成品（best-effort）。**不再按 `es_status` 只补失败 chunk**。`_ensure_index` 等基础设施故障按文件级处理（不标 chunk，`ensure_index:` 前缀）。失败由 `_run` 统一 `mark_es_failed` + 通知，**不计数、不设上限、不写 retry_exhausted** |
| 稀疏向量化 | `_run_sparse_vectorizing()` | dense 阶段完成后重新按 `doc_id` load 一次 `list[ChunkRecordDB]`，避免读取陈旧 `dense_vector_status`；现场过滤 `dense_vector_status=SUCCESS AND sparse_vector_status!=SUCCESS` 后调用 `SparseIndexingPipeline.run(chunks=..., task_id=..., db=...)`。`bucket_id` 取自 chunk 行，不再由调用方传入 |
| 结果通知 | `_send_parse_result()` | 向 `tolink.rag.parse_result` 发送整体终态 |

## 4. 状态语义

整体任务状态的**权威单源**是 `document_parse_pipeline.pipeline_status`，覆盖 **文档清洗 → 分片 → 向量化 → 预分词 → ES 入库 → 稀疏向量化** 六段状态机。`document_parsed_log` 退化为"文件解析产物快照表"，只承载解析产物（Markdown 文件位置、解析起止时间）与触发上下文；重试链路由 `retry_of_task_id` 串接（migration 0009）。

> **术语对照表**（brief / acceptance ↔ 代码 / schema）：
>
> | brief / acceptance | 代码 / schema | 备注 |
> | --- | --- | --- |
> | `parsing_status` / `parsing_duration_ms` | `cleaning_status` / `cleaning_duration_ms` | migration 0007 落地时选择 cleaning 词根；统一重命名由 issue [#48](https://github.com/ql-link/LinkRag/issues/48) 跟踪 |
> | `STAGE_PARSING` | `POST_PROCESS_STAGE_CLEANING` | 同上 |
> | `mark_parsing_*` | `mark_cleaning_*` | 同上 |

| 字段 | 状态 |
| --- | --- |
| `pipeline_status` | `PENDING/PROCESSING/SUCCESS/FAILED`（整体任务状态，Java 侧判定"上次任务是否整体成功"的唯一字段） |
| `cleaning_status` | `PENDING/PROCESSING/SUCCESS/FAILED`（文档清洗=解析+上传阶段；brief 称 `parsing_status`） |
| `chunking_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `vectorizing_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `pretokenize_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `es_indexing_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `sparse_vectorizing_status` | `PENDING/PROCESSING/SUCCESS/FAILED`（migration 0009 新增） |
| `superseded_by_task_id` | `VARCHAR(36) NULL`（重试 CAS 第 2 层目标列；migration 0009 新增） |

阶段顺序：`CLEANING(PARSING) → CHUNKING → VECTORIZING(dense/Qdrant) → PRETOKENIZE → ES_INDEXING → SPARSE_VECTORIZING`。发送给 Java 的 parse_result `task_status=success` 是整体成功语义：6 阶段全部成功才算整体成功；任一阶段失败都会发送 `task_status=failed`。

**`pipeline_status` 三态翻转**（整体唯一权威）：
- **`PENDING → PROCESSING`**：首个 `mark_<stage>_started` 触发（幂等，已 PROCESSING 不重复翻转）。
- **`* → SUCCESS`**：6 阶段全部 SUCCESS 后由 `mark_sparse_vectorizing_success` **唯一**翻转；`mark_es_success` 不再触碰 `pipeline_status`（本期重要变更，与 sparse 阶段对称）。
- **`* → FAILED`**：任一阶段 `mark_<stage>_failed` 触发，同时写 `failed_stage` / `recover_from_stage` / `failure_reason` / `finished_at`。

**Java 侧消费规则**：
- 整体任务是否成功 → 读 `document_parse_pipeline.pipeline_status == SUCCESS`
- Markdown 是否已上传 → 读 `document_parsed_log.parsed_object_key IS NOT NULL`
- 失败原因 → 读 `document_parse_pipeline.failure_reason`

### 失败即终态与恢复入口（无内部自动重试）

任一阶段失败即终态：只把结果写入 `document_parse_pipeline`（阶段状态 FAILED、`failed_stage`、`recover_from_stage`、`failure_reason`、`finished_at`、耗时）并通知 Java `failed`。系统**不计数、不设上限、不写 retry_exhausted、不自动重试**。

- **文档清洗失败**：`mark_cleaning_failed` 落 `cleaning_status=FAILED` + `failed_stage=CLEANING` + `recover_from_stage=CLEANING`。`failure_reason` 含前缀 `INVALID_TASK_CONTEXT:` / `SOURCE_FILE_NOT_FOUND:` / `PARSE_ENGINE_FAILED:` / `PARSED_FILE_UPLOAD_FAILED:` / `INTERRUPTED_TASK:` / `INTERNAL_UNKNOWN_ERROR:` / `PARSING_FAILED:` 等。
- **预分词失败**（`_run_pretokenize` 捕获 `PreprocessorError`，或空 plan 但仍有未完成 chunk）：`mark_pretokenize_failed` 落 `pretokenize_status=FAILED` + `recover_from_stage=PRETOKENIZE`；**绝不写任何 chunk es_status**（文件级 all-or-nothing）。
- **chunking 写入失败**：`_persist_chunk_facts` 回滚整批 chunk 真值，`mark_chunking_failed` 落 `chunking_status=FAILED`，不进入 vectorizing。
- **vectorizing 失败**：当前失败 chunk 的 dense 状态标 `FAILED`，已成功 chunk 保持 `SUCCESS`，未处理 chunk 保持 `PENDING`；文件级 `vectorizing_status=FAILED` 并通知 Java。稀疏向量不在 vectorizing 阶段执行。用户侧人工重试进入 VECTORIZING 时会补做 dense `PENDING` 与 `FAILED` chunk，已 `SUCCESS` 的 chunk 不重复向量化。
- **ES 前置删除失败**（`delete_document_index` 抛异常，如 ES 不可达）：直接判 ES 阶段失败、不进入写入，`failure_reason` 以 `es_delete:` 前缀。
- **ES 基础设施故障**（`_ensure_index` 等）：文件级，不标 chunk，`failure_reason` 以 `ensure_index:` 前缀。
- **ES chunk 级写失败**：逐 chunk 标 `es_status=FAILED`，文件级 `es_indexing_status=FAILED`，前缀 `ES_INDEXING_FAILED:`；失败后触发文档级删除清理半成品（best-effort），避免 ES 残留部分写入。
- **稀疏向量阶段失败**（`SparseIndexingPipeline.run` 抛 `SparseIndexingError`）：触发失败的 chunk 标 `sparse_vector_status=FAILED` 留审计痕迹；文件级 `mark_sparse_vectorizing_failed` 落 `sparse_vectorizing_status=FAILED` + `failed_stage=SPARSE_VECTORIZING`，前缀 `SPARSE_VECTORIZING_FAILED:`。
- **恢复入口** `_infer_recover_stage()` 取首个非 SUCCESS 阶段（cleaning→chunking→vectorizing→pretokenize→es→sparse_vectorizing）。所有 `*_status` 跨重投持久，不被 `mark_<stage>_started` 清空（只清 `failed_stage` / `failure_reason` 等失败痕迹）。
- **用户侧重试**：重试由 Java 端负责，重试链通过 `document_parsed_log.retry_of_task_id` 与 `document_parse_pipeline.superseded_by_task_id` 双向追溯（migration 0009）。Python 侧已不再维护 `retry_count` / `last_retry_at`（migration 0007 下线）。

### 重试分支（`is_retry=true`）

收到 `payload.is_retry=true` 时，`ParseTaskPipeline._run` 顶部进入重试分支：

1. `ParseTaskGuard.validate_retry_context(payload, db)`：严格校验（含 CAS 第 1 层快速失败 `superseded_by_task_id IS NULL`），失败抛 `RetryValidationError`。若旧 pipeline 的 `recover_from_stage=CLEANING`，不要求旧 log 已有 `parsed_object_key`；若恢复点晚于 CLEANING，则要求旧 markdown 坐标存在。
2. `ParsePipelineRepository.mark_superseded(old_pipeline, new_task_id)`：CAS 第 2 层真原子，`UPDATE ... WHERE superseded_by_task_id IS NULL` 依赖 rowcount 仲裁；rowcount=0 抛 `RetryValidationError("RETRY_VALIDATION_FAILED:concurrent_supersede")`。
3. `ParseLogRepository.create_for_retry(...)` + `ParsePipelineRepository.create_with_inherited_state(old_pipeline, new_log)`：建新 log + 新 pipeline，复制 6 阶段 SUCCESS 状态与 duration，重置非 SUCCESS 阶段。若从 CLEANING 恢复，新 log 初始不写 `parsed_*` 字段，等待重新上传 markdown 成功后写真实值。
4. 进入 6 阶段循环，跳过继承到的 SUCCESS 阶段、从首个非 SUCCESS 阶段恢复执行；若恢复点是 CLEANING，则复用 `_run_cleaning_stage()` 重新下载源文件、解析、上传 markdown，成功后继续 chunking。chunking 被跳过时由 `_load_all_chunks_from_db(payload, db)` 反查当前文档**完整** chunk 真值表（仅按 `doc_id` 过滤、排除删除态保护集合，按 `chunk_index` 排序），返回 `list[ChunkRecordDB]` 喂给下游，语义等价于首次执行的 `_run_chunking()` 返回值。dense 阶段由 pipeline 现场过滤 `dense_vector_status != SUCCESS` 后调用 `index_chunks`；sparse 阶段在 dense 完成后重新 load 一次最新 ORM 行，再过滤 `dense_vector_status=SUCCESS AND sparse_vector_status!=SUCCESS` 后调用 `SparseIndexingPipeline.run`；**ES 阶段为文档级全量重建（Issue #57）——不按 `es_status` 补做子集，而是先删该文档全部 ES 索引再基于完整 chunk 集全量重写**（首次执行与重试同一编排）。

校验或 CAS 失败时走 `_handle_retry_validation_failure`：双表落 FAILED 终态（`pipeline_status=FAILED` + `failed_stage=RETRY_VALIDATION` + 前缀 `RETRY_VALIDATION_FAILED:`），不更新任何旧表行，通知 Java FAILED。

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
- `es_delete:`（ES 文档级全量重建前置删除失败，如 ES 不可达）
- `ensure_index:`（ES 确保索引存在等基础设施故障）
- `ES_INDEXING_FAILED:`（ES bulk chunk 级写失败）
- `SPARSE_VECTORIZING_FAILED:`（稀疏向量阶段失败；包括 dense 前置条件不满足、稀疏编码、Qdrant 写入或状态回写失败）

失败原因统一写入 `failure_reason`，最大长度按数据库字段控制为 512。

## 7. 修改原则

- 不要在 MQ consumer 中直接拼接业务流程，业务编排应留在 `ParseTaskPipeline`。
- 解析成功通知必须晚于 Markdown、分片、向量化、预分词和 ES 入库全部完成。
- 新增阶段时应同步更新 `document_parse_pipeline` 表结构、`docs/api/schemas/mysql.md` 和 `docs/api/error_codes.md`。
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
- chunking 成功后已批量落库 chunk 真值；SQL 批量落库失败时回滚且不进入向量化。
- chunking 成功后返回 `list[ChunkRecordDB]`；retry `_load_all_chunks_from_db` 同样返回 ORM 行，不再 wrap 成 splitter `Chunk`。
- vectorizing 现场过滤 `dense_vector_status != SUCCESS` 后只调用 `index_chunks(chunks=...)`，不再创建 chunk 真值，也不再调用旧 `index_document_chunks` / 传 `include_failed`。
- sparse vectorizing 在调用前重新 load chunks，并只把 `dense_vector_status=SUCCESS` 且 `sparse_vector_status!=SUCCESS` 的 ORM 行传给 `SparseIndexingPipeline.run(chunks=..., task_id=..., db=...)`。
- MinerU 后端跳过源文件下载并注入 `source_file_url`；旁路下 `source_path` 在整条链路中保持 `None`，不创建临时文件、不需要清理。
- 预分词失败为文件级 all-or-nothing：落 `pretokenize_status=FAILED`，不写任何 chunk es_status。
- ES 基础设施故障（`ensure_index`）文件级不标 chunk；ES chunk 级失败逐 chunk 标记。
- ES 入库为文档级全量重建（Issue #57）：前置删除 + 全量写入 + 失败清理，首次/重试同一编排；不按 `es_status` 补做子集。
- 失败即终态：ES 失败无 retry_exhausted；`mark_parsing_started` / `mark_post_processing` 不清各阶段 `*_status`。所有阶段失败均由 `_run` 统一写库+通知。
- 恢复入口推断按首个非 SUCCESS 阶段，`pretokenize_status` 与其他阶段状态列一样跨重投持久。
