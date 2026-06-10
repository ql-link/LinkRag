# Parse Task Pipeline Module

本文说明 `src/core/pipeline/parse_task/pipeline.py` 解析任务业务流水线的端到端职责、状态边界和失败语义。

## 1. 模块框架

`pipeline/` 顶层按概念分两个子包：

```text
src/core/pipeline/
├── parse_task/                  # 解析任务主编排
│   ├── pipeline.py              # ParseTaskPipeline 主类（薄编排）：消息分流/幂等/校验/重试 CAS，6 阶段执行委托 stages/
│   ├── constants.py             # 解析任务状态和用户提示文案
│   ├── error_codes.py           # ParseFailureCode + build_failure_reason
│   ├── models.py                # ParsePipelineResult / PipelineStatus
│   ├── log_repository.py        # ParseLogRepository: document_parsed_log 仓储与终态写入
│   ├── notifier.py              # ParseResultNotifier: parse_result MQ 通知与兜底；ParseResultNotificationError 继承 RetriableError，由消费框架做有限退避重试 + 死信兜底（见 mq.md §4.1）
│   ├── source.py                # ParseSourceIO: 对象存储侧源文件流式下载到 Path / Markdown 上传
│   ├── temp_workspace.py        # PARSE_TEMP_DIR 启动清理、临时文件分配、safe_unlink 幂等
│   ├── validator.py             # ParseTaskGuard: 前置校验、MQ 重投与中断状态收敛
│   ├── _utils.py                # 子包内部共享小工具（now / duration_ms / 等）
│   ├── stages/                  # 6 阶段类化编排（LINK-37）：唯一的 mark/run/notify 模板
│   │   ├── base.py              # Stage 抽象基类（execute 模板）+ StagePipeline 编排器
│   │   ├── context.py           # StageContext（跨阶段产物）/ StageOutcome（单阶段结果）
│   │   ├── services.py          # StageServices：解析/分片/向量化/预分词/ES/稀疏等底层操作 + PreprocessorProtocol
│   │   ├── cleaning.py          # CleaningStage（下载→解析→上传 markdown）
│   │   ├── chunking.py          # ChunkingStage（分片 / 重试反查完整 chunk 集合）
│   │   ├── vectorizing.py       # VectorizingStage（dense）
│   │   ├── pretokenize.py       # PretokenizeStage（内存 plan，文件级 all-or-nothing）
│   │   ├── es_indexing.py       # EsIndexingStage（plan 缺失先重建；文档级全量重建）
│   │   └── sparse_vectorizing.py# SparseVectorizingStage（最后一段，唯一翻转 pipeline_status=SUCCESS）
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
  -> reload persisted chunk truth rows (list[ChunkRecordDB])
  -> dense index filtered chunks to Qdrant (filter dense_vector_status != SUCCESS)
  -> pretokenize chunks
  -> index chunks to Elasticsearch
  -> reload fresh chunk truth rows
  -> sparse vectorize filtered chunks (filter dense=SUCCESS AND sparse != SUCCESS)
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

消费者层兜底：`ParseTaskConsumer.handle_parse_task` 在 `execute()` 之外再包一层 catch-all。`execute` 逃逸的未预期异常（pipeline 内部归类兜底之外，如 DB/会话故障）会触发 `ParseTaskPipeline.notify_unexpected_failure(payload, exc)`——按 `task_id` 反查已建 log 行、尽力回发 `task_status=failed`（`INTERNAL_UNKNOWN_ERROR`），避免 Java 端文件永久卡「解析中」，随后仍 `raise` 保留死信记账；log 行尚不存在时放弃通知交由 Java stuck scanner 兜底（见 [mq.md §消费者层异常兜底](mq.md)）。

## 3. 核心职责

### 编排架构（Stage 类化，LINK-37）

`ParseTaskPipeline` 退化为**薄编排**：只做消息分流、幂等屏障、上下文校验、重试 CAS 与继承式新建；6 阶段执行委托给 `stages/` 子包的 `StagePipeline`。首次执行与重试共用**同一条** StagePipeline，差异只在「建行 / 校验」准备阶段。

```text
ParseTaskPipeline._run
 ├── is_retry=True  → _handle_retry_branch（校验 + CAS supersede + 继承式新建）
 │                     → _build_stage_pipeline().run(ctx, is_retry=True)
 └── is_retry=False → create log + 幂等/上下文校验
                       → _build_stage_pipeline().run(ctx)  （外层保留一层兜底 except）

StagePipeline.run（唯一的 6 阶段编排）
 CleaningStage → ChunkingStage → VectorizingStage
   → PretokenizeStage → EsIndexingStage → SparseVectorizingStage
```

三层职责切分：

| 层 | 角色 | 职责 |
| --- | --- | --- |
| `ParseTaskPipeline` | 薄编排 | 分流 / 幂等 / 校验 / 重试 CAS / 兜底 except；`_build_stage_pipeline()` 每次执行从当前协作者装配 StagePipeline（便于测试替换协作者即时生效） |
| `Stage` 基类 | **唯一**的执行模板 | `execute`：已继承 `SUCCESS` → `on_skip`；否则 `mark_started → run → 成功 mark_success / 失败 mark_failed + 通知 Java FAILED`。新增/调整阶段只写一个子类，不再双链路改动 |
| `StageServices` | 底层操作集合 | 解析 / 分片 / dense 向量化 / 预分词 / ES 写入 / 稀疏向量化 / chunk 反查等；**不写阶段状态、不发通知**（副作用边界清晰） |

`StageContext` 在阶段间传递可变产物（`parse_result` / `chunks` / `plan` / `vector_result`）并收敛最终 `ParsePipelineResult`；`StageOutcome` 是单阶段成败结果（`finalized=True` 表示该阶段已自行 mark+notify，模板不重复处理）。

各阶段的特例（均封装在对应 Stage 子类内，对编排循环透明）：

- **CleaningStage**：`cleaning_status != SUCCESS` 才执行（首次恒执行）；下载/解析/上传失败按错误码归类（`TEMP_DISK_FULL` / `SOURCE_FILE_NOT_FOUND` / `PARSE_ENGINE_FAILED` / `PARSED_FILE_UPLOAD_FAILED`）。**数据集级配置注入（LINK-148）**：解析前按 `(user_id, dataset_id)` 经 `DatasetConfigService.get_config` 读数据集配置（无行/DB 故障降级系统默认，只读不写库），把 PDF 后端（`payload 显式 > 数据集 pdf_config > settings.PDF_PARSER_BACKEND` 三层）与 Markdown 增强配置注入 `parse_file`。Markdown 增强模型名取自数据集 `enhancement_config.table_model` / `vision_model`：增强开启但模型名未配 → `ENHANCEMENT_MODEL_MISSING`（**不再回退系统/用户默认模型**，表格与图片对称失败）；模型名已配但发起用户缺该能力（CHAT/VISION）默认 provider 配置 → `LLM_CONFIG_MISSING`；数据集 JSON 字段类型非法 → 归 `PARSE_ENGINE_FAILED`（reason 含字段名）。成功在 `mark_success` 写 `mark_parsed + mark_cleaning_success + mark_post_cleaning`。临时文件早删 + `finally` 兜底封装在 `run` 内。
  - **`md` / `markdown` 透传**：cleaning 的职责是把多源文件「解析为 md」，而 md 源文件本身即目标格式——经 `payload.is_markdown_passthrough` 判定后 `_read_markdown_passthrough` 直接读取已下载的源文件文本作为 markdown 产物（`parse_result=None`，下游 chunking 走纯 markdown 分片路径），**跳过解析引擎**；且 md 在上传阶段已存入对象存储，cleaning **不再重复写 `md_bucket`**。透传仍走完整成功收口（`mark_parsed + mark_cleaning_success + mark_post_cleaning`），`cleaning_status=SUCCESS`，状态语义与正常清洗一致。
  - **markdown 产物坐标解析**：markdown 真实所在位置由 `ParseTaskPayload.markdown_bucket` / `markdown_object_key` 统一解析——**md/markdown 取上传位置 `source_*`，其余格式取 cleaning 写出的 `md_*`**。`mark_parsed`（写 `parsed_bucket_name`/`parsed_object_key`）、`StageServices.load_markdown`（重试从 CHUNKING 恢复读回旧 markdown）、重试 `create_for_retry` 的预写坐标三处一致取用，确保「清洗完成、分片失败」重试时 md 按上传位置读回，不会误用 `md_bucket`。
- **ChunkingStage**：`chunking_status == SUCCESS` → `on_skip` 调 `StageServices.load_all_chunks_from_db` 反查完整 chunk truth set；反查为空按历史语义落 `vectorizing_failed` + 通知（`finalized`）。否则进入 `run`：有本轮 cleaning 产物用其分片；无 cleaning 产物但旧 markdown 坐标可用（**重试从 CHUNKING 恢复**，LINK-32）则经 `StageServices.load_markdown` 读回旧 markdown 重新分片；二者皆无（无产物也无 markdown 坐标）才视为状态不一致落 `chunking_failed`（`failure_reason` 含 `chunking_not_success_in_retry`）。
- **VectorizingStage / PretokenizeStage / SparseVectorizingStage**：`*_status != SUCCESS` 才执行。SparseVectorizingStage 是 `pipeline_status=SUCCESS` 的**唯一**翻转点——即便继承 SUCCESS 被跳过，也在 `on_skip` 翻转整体终态。
- **EsIndexingStage**：依赖 pretokenize 的内存态 `FilePostIndexPlan`，`ctx.plan` 缺失（pretokenize 继承 SUCCESS 被跳过）时先重做 pretokenize 重建再消费（见 §4 重试恢复起点）。

| 阶段 | StageServices 主要方法 | 说明 |
| --- | --- | --- |
| 幂等屏障 | `ParseLogRepository.create()` | 先插入 `document_parsed_log`，依赖 task_id 唯一索引阻止重复解析 |
| 重投处理 | `ParseTaskGuard.handle_duplicate()` | 对已有终态补发通知；对中断后处理收敛为可恢复失败 |
| 上下文校验 | `ParseTaskGuard.validate()` | 校验 MQ payload 与 Java 侧 `document_parse_file` 记录一致 |
| 源文件处理 | `ParseSourceIO.should_skip_source_download()` / `.download_to_path()` + `temp_workspace.*` | MinerU URL API 跳过本地下载（`source_path=None`）；其他后端流式下载到 `PARSE_TEMP_DIR/parse-{task_id}-{rand}.tmp`，拿到 markdown 后立即 `safe_unlink` 早删，`finally` 二次兜底 |
| 文件解析 | `StageServices.parse_file()` | 调 `ParseTaskService.aprocess()` 生成 Markdown；首次与 `recover_from_stage=CLEANING` 重试同序 |
| 分片 | `StageServices.run_chunking()` / `._chunk_markdown()` / `.load_markdown()` / `._reload_chunks_from_db()` | 优先消费上游 `ParseResult`，否则重新解析 Markdown；分片成功后单事务批量写入 `kb_document_chunk` 真值记录，**commit 后立即按 `doc_id` 反查 ORM 行（`_reload_chunks_from_db`）作为返回值 `list[ChunkRecordDB]`**——使首次链路与 retry 链路（`load_all_chunks_from_db`）的 chunks 形态完全一致，下游 dense / sparse 用同一套字段契约消费。`_reload_chunks_from_db` 的 SELECT 带 **`execution_options(populate_existing=True)`**：session 配置为 `expire_on_commit=False`，而 dense 阶段在**独立 session** 推进 `dense_vector_status=SUCCESS`，若不强制刷新，身份映射里 chunking 阶段加载的同主键 ORM 实例会保留旧值（`PENDING`），导致 sparse 入口按 `dense=SUCCESS` 过滤恒为空、稀疏索引永不写入。`populate_existing` 用查询结果覆盖已加载实例属性，确保读到最新真值。**重试时**（`payload.is_retry`）`_persist_chunk_facts` 先 `ChunkRepository.delete_by_doc_id(doc_id)` 清本文档残留再全量写入，同事务原子重建 chunk truth set（`chunk_id` 由内容派生且全局唯一，不清残留会撞唯一键）。`load_markdown` 经 `download_to_path` 流式读回旧 markdown（守 OOM 约束），供「重试从 CHUNKING 恢复」重新分片。**数据集级分块配置（LINK-148）**：ChunkingStage 按 `(user_id, dataset_id)` 读 `dataset_parse_config.chunking_config` 注入 `run_chunking`/`create_chunking_engine`，未配置数据集取系统 `CHUNKING_*` 默认（L1 fallback），JSON 字段非法归 `PARSE_ENGINE_FAILED` |
| 向量化（dense） | `StageServices.store_chunk_vectors()` | 接收 `list[ChunkRecordDB]`，**现场过滤 `dense_vector_status != SUCCESS`** 后通过 `VectorStorageFacade.index_chunks(chunks=...)` 写 Qdrant；dense 模块不再自查 SQL、不感知首次/retry（`index_document_chunks(include_failed=...)` 已删除）。多值 CAS（`mark_indexing(allowed_statuses=(PENDING, FAILED))`）在 SQL 层兜底：若现场过滤口径错误把已 SUCCESS chunk 混入，UPDATE rowcount 不达预期进失败路径，不会把 SUCCESS chunk 拉回 INDEXING。全部已 SUCCESS 时短路幂等成功。**embedder 按发起用户解析（LINK-91）**：`index_chunks` 用 `user_id` 经 `aresolve_user_chunk_embedding_pipeline` 走「查配置→解密 api_key→`ModelFactory.create_client`」按用户默认 EMBEDDING 配置构造稠密 embedder，复用 `ModelFactory`/`ConfigReaderService` 缓存。**EMBEDDING 必配、解析写入链路不保留系统兜底**：用户无默认 EMBEDDING 配置抛 `DenseEmbeddingConfigMissingError`，在 embed 前直接上抛（不触碰 chunk 状态），由 VectorizingStage 归类 `LLM_CONFIG_MISSING`。**维度方案 A**：写入前校验用户模型输出维度须等于 `settings.DENSE_VECTOR_DIMENSION`（per-bucket 共享 collection、维度固定），不符抛 `DenseEmbeddingDimensionError` → `EMBEDDING_DIMENSION_UNSUPPORTED`。召回路径仍用系统模型（另立 issue），稀疏向量不受影响 |
| 预分词 | `StageServices.build_pretokenize_plan()` | 聚合 doc 下 chunk token 为内存 `FilePostIndexPlan`（不持久化、不写状态）。**plan 覆盖该文档全部有效 chunk（不按 `es_status` 过滤，Issue #57）**。文件级 all-or-nothing：成功置 `ctx.plan`，失败返回 `(None, reason)`，由 PretokenizeStage 统一 mark + 通知，**不写任何 chunk es_status** |
| ES 入库 | `StageServices.run_es_indexing()` | **前置删除 → 全量写入 → 失败清理**（Issue #57）；前置删除失败 `es_delete:` 前缀；写入未全部成功再 delete 清理半成品（best-effort）。失败由 EsIndexingStage 统一 mark + 通知，**不计数、不设上限** |
| 稀疏向量化 | `StageServices.run_sparse_vectorizing()` → `SparseIndexingPipeline.run(chunks=...)` | dense 完成后**重新 load** chunks（`_reload_chunks_from_db`，读刷新后的 `dense_vector_status`），**现场过滤 `dense=SUCCESS AND sparse != SUCCESS`** 后透传；sparse 模块不再自查 SQL（`count_by_doc_id` 健康校验 / `list_sparse_candidates_by_doc_id` 反查不再调用），`bucket_id` 从 `chunks[0].bucket_id` 取（不再误传 `payload.dataset_id`，关闭 #95）。入口前置断言 `dense=SUCCESS`（fail-fast），多值 CAS `allowed_statuses=(PENDING, FAILED)` 切 INDEXING；空集短路幂等成功 |
| 重试抢占 | `ParsePipelineRepository.mark_superseded()` | CAS 第 2 层只执行 `UPDATE ... WHERE superseded_by_task_id IS NULL` 并返回 rowcount，不主动 commit；调用方必须与新 retry log / pipeline 建行放在同一事务内提交 |
| 结果通知 | `ParseResultNotifier.send_or_raise()` | 由 Stage / StagePipeline 统一调用，向 `tolink.rag.parse_result` 发送整体终态 |

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
- **预分词失败**（`StageServices.build_pretokenize_plan` 捕获 `PreprocessorError`，或空 plan 但仍有未完成 chunk）：`PretokenizeStage` 落 `mark_pretokenize_failed`（`pretokenize_status=FAILED` + `recover_from_stage=PRETOKENIZE`）；**绝不写任何 chunk es_status**（文件级 all-or-nothing）。
- **chunking 写入失败**：`_persist_chunk_facts` 回滚整批 chunk 真值，`mark_chunking_failed` 落 `chunking_status=FAILED` + `recover_from_stage=CHUNKING`，不进入 vectorizing。该终态可由「重试从 CHUNKING 恢复」链路（读回旧 markdown 重新分片，见 §重试分支）链式恢复，无需重新上传源文件。
- **vectorizing 失败**：当前失败 chunk 的 dense 状态标 `FAILED`，已成功 chunk 保持 `SUCCESS`，未处理 chunk 保持 `PENDING`；文件级 `vectorizing_status=FAILED` 并通知 Java。稀疏向量不在 vectorizing 阶段执行。用户侧人工重试进入 VECTORIZING 时由 `store_chunk_vectors` 现场过滤出 dense `PENDING` 与 `FAILED` chunk 透传给 `index_chunks`，已 `SUCCESS` 的 chunk 被过滤掉不重复向量化（多值 CAS `allowed_statuses=(PENDING, FAILED)` 在 SQL 层兜底）。
- **vectorizing 配置/维度失败（LINK-91）**：发起用户无默认 EMBEDDING 配置时 `index_chunks` 在 embed 前抛 `DenseEmbeddingConfigMissingError`（不触碰任何 chunk 状态），`store_chunk_vectors` 透传、VectorizingStage 归类 `LLM_CONFIG_MISSING` 通知 Java；用户模型输出维度与 `DENSE_VECTOR_DIMENSION` 不一致时当前批标 `FAILED` 后抛 `DenseEmbeddingDimensionError`，归类 `EMBEDDING_DIMENSION_UNSUPPORTED`。两者区别于普通 `VECTORIZING_FAILED`，使 Java 能提示用户去配置 / 换模型。
- **ES 前置删除失败**（`delete_document_index` 抛异常，如 ES 不可达）：直接判 ES 阶段失败、不进入写入，`failure_reason` 以 `es_delete:` 前缀。
- **ES 基础设施故障**（`_ensure_index` 等）：文件级，不标 chunk，`failure_reason` 以 `ensure_index:` 前缀。
- **ES chunk 级写失败**：逐 chunk 标 `es_status=FAILED`，文件级 `es_indexing_status=FAILED`，前缀 `ES_INDEXING_FAILED:`；失败后触发文档级删除清理半成品（best-effort），避免 ES 残留部分写入。
- **稀疏向量阶段失败**（`SparseIndexingPipeline.run` 抛 `SparseIndexingError`）：触发失败的 chunk 标 `sparse_vector_status=FAILED` 留审计痕迹；文件级 `mark_sparse_vectorizing_failed` 落 `sparse_vectorizing_status=FAILED` + `failed_stage=SPARSE_VECTORIZING`，前缀 `SPARSE_VECTORIZING_FAILED:`。
- **恢复入口** `_infer_recover_stage()` 取首个非 SUCCESS 阶段（cleaning→chunking→vectorizing→pretokenize→es→sparse_vectorizing）。所有 `*_status` 跨重投持久，不被 `mark_<stage>_started` 清空（只清 `failed_stage` / `failure_reason` 等失败痕迹）。
- **用户侧重试**：重试由 Java 端负责，重试链通过 `document_parsed_log.retry_of_task_id` 与 `document_parse_pipeline.superseded_by_task_id` 双向追溯（migration 0009）。Python 侧已不再维护 `retry_count` / `last_retry_at`（migration 0007 下线）。

### 重试分支（`is_retry=true`）

收到 `payload.is_retry=true` 时，`ParseTaskPipeline._run` 顶部进入重试分支：

1. `ParseTaskGuard.validate_retry_context(payload, db)`：严格校验（含 CAS 第 1 层快速失败 `superseded_by_task_id IS NULL`），失败抛 `RetryValidationError`。若旧 pipeline 的 `recover_from_stage=CLEANING`，不要求旧 log 已有 `parsed_object_key`；若恢复点晚于 CLEANING，则要求旧 markdown 坐标存在。
2. `ParsePipelineRepository.mark_superseded(old_pipeline, new_task_id)`：CAS 第 2 层真原子，`UPDATE ... WHERE superseded_by_task_id IS NULL` 依赖 rowcount 仲裁；rowcount=0 抛 `RetryValidationError("RETRY_VALIDATION_FAILED:concurrent_supersede")`。该方法不主动 commit，只把抢占写入当前事务。
3. `ParseLogRepository.create_for_retry(...)` + `ParsePipelineRepository.create_with_inherited_state(old_pipeline, new_log)`：建新 log + 新 pipeline，复制 6 阶段 SUCCESS 状态与 duration，重置非 SUCCESS 阶段。`mark_superseded`、新 log、新 pipeline 三步在同一事务内统一 commit；若新 log 或新 pipeline 创建抛异常，编排层 rollback 整个事务，旧 pipeline 不应残留 `superseded_by_task_id`。若从 CLEANING 恢复，新 log 初始不写 `parsed_*` 字段，等待重新上传 markdown 成功后写真实值。
4. 进入 `StagePipeline.run()`（与首次执行**共用同一编排**），跳过继承到的 SUCCESS 阶段、从首个非 SUCCESS 阶段恢复执行；若恢复点是 CLEANING，则 `CleaningStage` 重新下载源文件、解析、上传 markdown，成功后继续 chunking。**若恢复点是 CHUNKING**（旧 chunking 失败但 markdown 已上传，LINK-32）：cleaning 继承 SUCCESS 被跳过、不重跑解析上传，由 `ChunkingStage.run` 经 `StageServices.load_markdown` 读回旧 markdown 重新分片，`_persist_chunk_facts` 内先 `delete_by_doc_id(doc_id)` 清残留再全量写入、原子重建 chunk truth set，随后继续 dense→pretokenize→es→sparse。chunking 被跳过（继承 SUCCESS）时则由 `ChunkingStage.on_skip` 经 `StageServices.load_all_chunks_from_db(doc_id)` 反查当前文档**完整有效** chunk 真值表（按 `doc_id` + `lifecycle_status=ACTIVE` 过滤，按 `chunk_index` 排序）返回 `list[ChunkRecordDB]` 喂给下游（不再 `chunk_from_record` 包成 splitter `Chunk`），语义等价于首次执行的 chunking 输出。下游 dense / sparse 入口由 `StageServices` 在**编排层现场过滤**决定补做范围：dense 过滤 `dense_vector_status != SUCCESS`，sparse 在 dense 完成后**重新 load 一次**（`_reload_chunks_from_db`，读到刷新后的 `dense_vector_status`）再过滤 `dense=SUCCESS AND sparse != SUCCESS`，把过滤后的 chunks 透传给各自模块（dense/sparse 模块不再自查 SQL）；多值 CAS 在 SQL 层兜底过滤口径错误。**ES 阶段为文档级全量重建（Issue #57）——不按 `es_status` 补做子集，而是先删该文档全部 ES 索引再基于完整 chunk 集全量重写**（首次执行与重试同一编排）。

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
- `LLM_CONFIG_MISSING`（发起用户缺少必配能力的默认 LLM 配置：解析增强缺 CHAT/VISION provider 配置（仅「确实未配置」时归此码，读取失败仍走 `PARSE_ENGINE_FAILED`），或稠密向量化缺 EMBEDDING，LINK-91）
- `ENHANCEMENT_MODEL_MISSING`（LINK-148：数据集开启表格/图片增强但 `enhancement_config.table_model` / `vision_model` 未配；按约定不回退系统/用户默认模型，直接失败。表格与图片对称——图片增强模型缺失不再静默跳过）
- `EMBEDDING_DIMENSION_UNSUPPORTED`（稠密向量化：用户模型维度 ≠ `DENSE_VECTOR_DIMENSION`，LINK-91）

后处理阶段还会构造文件级失败原因，并以来源前缀区分（纯内部排障，Java 仅展示不解析）：

- `VECTORIZING_FAILED`
- `pretokenize:`（预分词失败 / 空 plan 但仍有未完成 chunk）
- `es_delete:`（ES 文档级全量重建前置删除失败，如 ES 不可达）
- `ensure_index:`（ES 确保索引存在等基础设施故障）
- `ES_INDEXING_FAILED:`（ES bulk chunk 级写失败）

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
- vectorizing 只调用 `index_chunks(chunks=...)`（接收 pipeline 现场过滤好的 `list[ChunkRecordDB]`），不再创建 chunk 真值、不再自查 SQL。
- MinerU 后端跳过源文件下载并注入 `source_file_url`；旁路下 `source_path` 在整条链路中保持 `None`，不创建临时文件、不需要清理。
- 预分词失败为文件级 all-or-nothing：落 `pretokenize_status=FAILED`，不写任何 chunk es_status。
- ES 基础设施故障（`ensure_index`）文件级不标 chunk；ES chunk 级失败逐 chunk 标记。
- ES 入库为文档级全量重建（Issue #57）：前置删除 + 全量写入 + 失败清理，首次/重试同一编排；不按 `es_status` 补做子集。
- 失败即终态：ES 失败无 retry_exhausted；各阶段的 `mark_<stage>_started`（如 `mark_cleaning_started`）只清 `failed_stage` / `failure_reason` 等失败痕迹，不清各阶段 `*_status`。所有阶段失败均由对应 `Stage`（经 `Stage.execute` 模板）统一写库+通知（首次/重试同一 `StagePipeline`）。
- 恢复入口推断按首个非 SUCCESS 阶段，`pretokenize_status` 与其他阶段状态列一样跨重投持久。
