# 解析 Pipeline 架构

本文只说明 **解析任务 Pipeline**：`src/core/pipeline/parse_task/` 如何承接 Java 通过 MQ 投递的 `parse_task` 消息，并把一次文档入库任务收敛为 `document_parse_pipeline` 的终态。

召回链路是另一条独立 Pipeline，见 [recall_pipeline.md](recall_pipeline.md)。

与本文互补：
- 解析任务端到端流程、状态语义、失败码 → [parse_task_pipeline.md](parse_task_pipeline.md)
- 分块策略 → [chunking.md](chunking.md)
- 向量化存储 → [vectorization.md](vectorization.md)
- MQ 集成 → [mq.md](mq.md)

---

## 1. 设计目标

解析 Pipeline 负责把"一次解析任务"的副作用收敛到单一编排入口 `ParseTaskPipeline`，包括日志、对象存储、分块、dense 向量化、预分词、ES 入库、sparse 向量化、状态落库与终态通知。

设计上遵循三条规则：

1. **解析主编排保持薄**：`ParseTaskPipeline` 只做消息分流、幂等屏障、上下文校验、重试 CAS 与兜底异常收敛。
2. **阶段执行类化**：六阶段执行委托给 `stages/` 子包的 `StagePipeline`；首次执行与用户侧重试共用同一条阶段链路。
3. **副作用边界清晰**：阶段状态写入和通知由 `Stage` 模板统一处理；解析、分片、向量化、预分词、ES、sparse 等底层操作集中在 `StageServices`，不直接写阶段状态、不发通知。

---

## 2. 包结构

```text
src/core/pipeline/
├── __init__.py                  # 对外门面：ParseTaskPipeline / RecallPipeline 等
├── parse_task/                  # 解析任务 Pipeline
│   ├── pipeline.py              # ParseTaskPipeline：首次/重试分流 + StagePipeline 调度
│   ├── constants.py             # 解析任务状态和用户提示文案
│   ├── error_codes.py           # ParseFailureCode + build_failure_reason
│   ├── models.py                # ParsePipelineResult / PipelineStatus
│   ├── log_repository.py        # document_parsed_log 仓储
│   ├── notifier.py              # parse_result MQ 通知与兜底
│   ├── source.py                # 对象存储下载、Markdown 上传、MinerU URL 构造
│   ├── temp_workspace.py        # PARSE_TEMP_DIR 清理、临时文件分配、safe_unlink
│   ├── validator.py             # 前置校验、MQ 重投、中断状态收敛、重试校验
│   ├── _utils.py                # 子包内部共享工具
│   ├── stages/                  # 六阶段类化编排
│   │   ├── base.py              # Stage 抽象基类 + StagePipeline 编排器
│   │   ├── context.py           # StageContext / StageOutcome
│   │   ├── services.py          # StageServices + PreprocessorProtocol
│   │   ├── cleaning.py          # 下载 -> 解析 -> 上传 Markdown
│   │   ├── chunking.py          # 分片 / 重试反查完整 chunk truth set
│   │   ├── vectorizing.py       # dense 向量化
│   │   ├── pretokenize.py       # 文件级预分词 plan
│   │   ├── es_indexing.py       # ES 文档级全量重建
│   │   └── sparse_vectorizing.py# sparse 向量化，最终翻转 pipeline_status=SUCCESS
│   └── post_process/            # document_parse_pipeline 状态机仓储
│       ├── constants.py         # PIPELINE_STATUS_* / STAGE_STATUS_* / POST_PROCESS_STAGE_*
│       ├── models.py            # PostProcessStageResult / PostProcessResult
│       └── repository.py        # ParsePipelineRepository
└── recall/                      # 召回 Pipeline，见 recall_pipeline.md
```

`post_process/` 嵌在 `parse_task/` 下，是因为 `document_parse_pipeline` 行由解析任务创建和驱动，生命周期与 `document_parsed_log` 1:1 绑定。它不是独立顶层 Pipeline，而是解析 Pipeline 的内部状态机仓储。

---

## 3. 编排结构

```text
ParseTaskConsumer
  -> ParseTaskMessage.parse_msg()
  -> ParseTaskPipeline.execute(payload)
       -> _run(payload, db)
            ├── is_retry=True
            │     -> validate_retry_context
            │     -> mark_superseded(old_pipeline, new_task_id)
            │     -> create_for_retry + create_with_inherited_state
            │     -> StagePipeline.run(ctx)
            └── is_retry=False
                  -> log_repository.create(payload)
                  -> guard.handle_duplicate / guard.validate
                  -> StagePipeline.run(ctx)
```

`StagePipeline` 是唯一的六阶段执行链：

```text
CleaningStage
  -> ChunkingStage
  -> VectorizingStage
  -> PretokenizeStage
  -> EsIndexingStage
  -> SparseVectorizingStage
```

`ParseTaskPipeline._build_stage_pipeline()` 每次执行时从当前协作者重新装配 `StagePipeline`，便于单测在构造后替换 fake repository、notifier 或 services。

---

## 4. 职责切分

| 层 | 角色 | 职责 |
| --- | --- | --- |
| `ParseTaskPipeline` | 薄编排 | 首次/重试分流、幂等屏障、上下文校验、重试 CAS、未归类异常兜底 |
| `StagePipeline` | 阶段循环 | 按固定顺序执行六阶段，遇到 finalized 结果立即返回 |
| `Stage` 子类 | 单阶段模板 | `mark_started -> run -> mark_success`；失败时 `mark_failed + notify failed`；继承 SUCCESS 时走 `on_skip` |
| `StageServices` | 底层操作集合 | 解析、分片、dense 向量化、预分词、ES 写入、sparse 向量化、chunk 反查 |
| `ParsePipelineRepository` | 状态仓储 | 写 `document_parse_pipeline` 整体状态、阶段状态、耗时、失败原因和恢复入口 |

核心协作者：

| 协作者 | 输入依赖 | 主要职责 | 副作用 |
| --- | --- | --- | --- |
| `ParseLogRepository` | `ParsePipelineRepository` | `document_parsed_log` 创建、查询、解析产物快照写入；首次创建时同步生成 `document_parse_pipeline` 行 | MySQL |
| `ParseSourceIO` | `BaseObjectStorage` | 源文件下载、Markdown 上传、MinerU URL 构造、判断是否跳过下载 | OSS |
| `ParseResultNotifier` | `MQService`, `ParseLogRepository`, `ParsePipelineRepository` | 发送 `parse_result` 终态消息；通知失败时兜底落库 | MQ + MySQL |
| `ParseTaskGuard` | `ParseLogRepository`, `ParsePipelineRepository`, `ParseResultNotifier` | MQ 消息一致性校验、重复 task_id 终态补发、非终态 pipeline 中断收敛、重试上下文校验 | 通过依赖产生副作用 |

---

## 5. 六阶段状态机

`document_parse_pipeline.pipeline_status` 是整体任务状态的权威单源。阶段顺序由 `POST_PROCESS_STAGE_ORDER` 固定：

```text
CLEANING
  -> CHUNKING
  -> VECTORIZING
  -> PRETOKENIZE
  -> ES_INDEXING
  -> SPARSE_VECTORIZING
```

| 阶段 | 主要动作 | 成功入口 | 失败入口 |
| --- | --- | --- | --- |
| `CLEANING` | 下载源文件或构造 MinerU URL，解析文件，上传 Markdown，写解析产物快照 | `mark_cleaning_success` | `mark_cleaning_failed` |
| `CHUNKING` | 基于 Markdown / `ParseResult` 分片，批量写入 `kb_document_chunk` truth set | `mark_chunking_success` | `mark_chunking_failed` |
| `VECTORIZING` | 消费已落库 chunk 写 dense 向量；重试时补做 `PENDING` + `FAILED` chunk | `mark_vectorizing_success` | `mark_vectorizing_failed` |
| `PRETOKENIZE` | 构建文件级内存 `FilePostIndexPlan`，不持久化、不写 chunk 状态 | `mark_pretokenize_success` | `mark_pretokenize_failed` |
| `ES_INDEXING` | 文档级前置删除、全量写入 ES、失败时 best-effort 清理半成品 | `mark_es_success` | `mark_es_failed` |
| `SPARSE_VECTORIZING` | 对 dense-success chunk 做 sparse 向量化，是整体成功的最后一段 | `mark_sparse_vectorizing_success` | `mark_sparse_vectorizing_failed` |

整体状态翻转：

- `PENDING -> PROCESSING`：首个 `mark_<stage>_started` 触发。
- `* -> SUCCESS`：仅 `mark_sparse_vectorizing_success` 翻转；`mark_es_success` 不代表整体成功。
- `* -> FAILED`：任一阶段 `mark_<stage>_failed` 触发，同时写 `failed_stage`、`recover_from_stage`、`failure_reason`、`finished_at`。

---

## 6. 重试与恢复

用户侧重试通过 MQ payload 的 `is_retry=true` 进入解析 Pipeline 的重试分支。Python 侧不自动重试、不计数、不设上限。

重试准备阶段：

1. `ParseTaskGuard.validate_retry_context(payload, db)` 校验旧任务存在、旧 pipeline 为 `FAILED`、`recover_from_stage` 可用、未被其他重试接班。
2. `ParsePipelineRepository.mark_superseded(old_pipeline, new_task_id)` 使用 `UPDATE ... WHERE superseded_by_task_id IS NULL` 做 CAS 仲裁。
3. `ParseLogRepository.create_for_retry(...)` 与 `ParsePipelineRepository.create_with_inherited_state(...)` 创建新 log 与新 pipeline，继承旧 pipeline 已成功阶段。
4. 进入同一条 `StagePipeline.run(ctx)`；继承 `SUCCESS` 的阶段跳过，从首个非 SUCCESS 阶段恢复。

关键恢复语义：

- 从 `CLEANING` 恢复时重新下载、解析并上传 Markdown。
- `CHUNKING` 被跳过时，`ChunkingStage.on_skip` 会从 MySQL 反查当前文档完整 chunk truth set，语义等价于首次分片输出。
- dense / sparse 按各自 SQL 状态决定补做范围。
- ES 阶段始终按文档级全量重建，不按 `es_status` 补做子集。

---

## 7. 工厂层与基础设施装配

解析 Pipeline 不持有"怎么按 settings 造具体基础设施"的装配细节。相关逻辑归属各自模块：

| 工厂入口 | 位置 | 用途 |
| --- | --- | --- |
| `create_chunking_engine()` | `src/core/splitter/factory.py` | 按 `CHUNKING_*` 配置组装 `ChunkingEngine` |
| `create_system_embedding_client()` / `LazyEmbeddingClient` | `src/core/splitter/factory.py` | 按 `SYSTEM_LLM_*` 配置构造或延迟构造 embedding 客户端 |
| `compose_vector_storage_facade()` | `src/core/storage/vector/factory.py` | 装配 `VectorStorageFacade` |
| `StorageFactory.get_storage()` | `src/services/storage/factory.py` | 按配置返回对象存储实现 |

---

## 8. 扩展指南

### 8.1 新增解析后处理阶段

1. 在 `post_process/constants.py` 增加阶段常量、状态字段映射，并调整 `POST_PROCESS_STAGE_ORDER`。
2. 给 `document_parse_pipeline` 增加 `xxx_status` / `xxx_duration_ms` 字段，写 Alembic migration。
3. 在 `ParsePipelineRepository` 增加 `mark_xxx_started` / `mark_xxx_success` / `mark_xxx_failed`。
4. 在 `stages/` 下增加新的 `Stage` 子类，并接入 `build_stage_pipeline()`。
5. 若阶段需要底层能力，先放进 `StageServices`，保持 Stage 只写状态模板和阶段特例。
6. 同步 [parse_task_pipeline.md](parse_task_pipeline.md)、[../api/schemas/mysql.md](../api/schemas/mysql.md)，必要时同步对外契约文档。

### 8.2 替换某个协作者实现

构造 `ParseTaskPipeline` 时传入替身即可。测试里也可以替换 `_notifier`、`_services` 等协作者后再调用 `_build_stage_pipeline()`，因为每次执行都会重新装配阶段链。

### 8.3 接入新的对象存储后端

只动 `src/services/storage/`：实现 `BaseObjectStorage`，让 `StorageFactory` 按配置返回新实例。`ParseSourceIO` 不需要感知具体后端。

---

## 9. 测试约定

| 测试目标 | 推荐入口 |
| --- | --- |
| 解析 Pipeline 编排骨架 | `tests/unit/core/pipeline/test_parse_task_pipeline.py` |
| 解析 Pipeline ES 阶段语义 | `tests/unit/core/pipeline/test_parse_task_pipeline_es.py` |
| `document_parse_pipeline` 仓储 | `tests/unit/core/pipeline/test_post_process_repository.py` |
| MQ 端到端集成 | `tests/integration/core/mq/test_kafka_parse_task_pipeline_integration.py` |

测试时优先替换协作者或 `StageServices` 方法，不要在 MQ consumer 中拼接业务流程，也不要通过 patch 大量私有方法绕过阶段模板。

---

## 10. 修改原则

- 解析成功通知必须晚于 Markdown、分片、dense 向量化、预分词、ES 入库和 sparse 向量化全部完成。
- 新增外部系统调用时，先判断归属 `StageServices`、独立协作者还是下游模块工厂，不直接塞进 `ParseTaskPipeline._run`。
- `document_parse_pipeline.pipeline_status` 是整体成功/失败的权威单源。
- `migrations/db.sql` 是 0001 baseline 冻结快照；schema 演进只通过 ORM + Alembic migration。
