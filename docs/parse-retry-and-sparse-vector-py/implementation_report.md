# 实现改造报告：解析失败重试链路 + 稀疏向量阶段接入（Python 端）

- **文档状态：** 实现完成（2026-05-27）
- **业务输入：** [brief.md](./brief.md) v3 已冻结（2026-05-26）
- **验收输入：** [acceptance.feature](./acceptance.feature) v3 已冻结（2026-05-26，22 Scenario）
- **技术设计：** [technical_design.md](./technical_design.md) v1.0 已冻结（2026-05-26）
- **触发条件：** 改动跨 8+ 源码文件 + Alembic migration + 5 测试文件 + 4 文档，属于"跨多模块多中间件多关键链路"，按 SKILL.md 必须产出本报告。

---

## 1. 实际改动清单

### 1.1 ORM 模型 + Alembic Migration

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [src/models/parse_task.py](../../src/models/parse_task.py) | 修改 | `DocumentParsedLog` 加 `retry_of_task_id`（+ 索引 `idx_parsed_log_retry_of`）；`DocumentParsePipeline` 加 `sparse_vectorizing_status` / `sparse_vectorizing_duration_ms` / `superseded_by_task_id`（+ 索引 `idx_parse_pipeline_superseded`） |
| [migrations/versions/0009_20260527_add_retry_link_and_sparse_stage.py](../../migrations/versions/0009_20260527_add_retry_link_and_sparse_stage.py) | 新增 | 增量 DDL + 反向 drop；不动 `scripts/db/init.sql`（baseline 冻结） |

### 1.2 MQ 消息契约

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [src/core/mq/messages/parse_task.py](../../src/core/mq/messages/parse_task.py) | 修改 | `ParseTaskPayload` 加 `is_retry: bool=False` 与 `previous_task_id: Optional[str]=None`；`ParseTaskMessage.build()` 同步加形参；老消息缺省默认 `False` 完全向后兼容 |

### 1.3 阶段枚举 + 失败码

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [src/core/pipeline/parse_task/post_process/constants.py](../../src/core/pipeline/parse_task/post_process/constants.py) | 修改 | 新增 `STAGE_STATUS_PROCESSING`、`POST_PROCESS_STAGE_SPARSE_VECTORIZING`、`POST_PROCESS_STAGE_RETRY_VALIDATION`；导出 6 阶段顺序元组 `POST_PROCESS_STAGE_ORDER` 给仓储/编排复用 |
| [src/core/pipeline/parse_task/error_codes.py](../../src/core/pipeline/parse_task/error_codes.py) | 修改 | `ParseFailureCode` 新增 `PARSING_FAILED` / `SPARSE_VECTORIZING_FAILED` / `RETRY_VALIDATION_FAILED` 与对应中文文案 |

### 1.4 Repository 扩展

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [src/core/pipeline/parse_task/post_process/repository.py](../../src/core/pipeline/parse_task/post_process/repository.py) | 修改 | 抽 `_mark_started` 通用方法 → 6 个对称 `mark_<stage>_started`；新增 `mark_sparse_vectorizing_success/_failed`、`mark_superseded`（CAS UPDATE + rowcount 仲裁）、`create_with_inherited_state`（6 阶段继承 SUCCESS）、`create_failed_for_retry_validation`；**关键变更**：`mark_es_success` 不再翻 `pipeline_status=SUCCESS`，下沉到 `mark_sparse_vectorizing_success` |
| [src/core/pipeline/parse_task/log_repository.py](../../src/core/pipeline/parse_task/log_repository.py) | 修改 | 新增 `create_for_retry` / `create_failed_for_retry_validation`；不主动 commit，事务由调用方收敛 |

### 1.5 Validator（重试前置校验）

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [src/core/pipeline/parse_task/validator.py](../../src/core/pipeline/parse_task/validator.py) | 修改 | 新增 `RetryValidationError` 异常类；`ParseTaskGuard.validate_retry_context` 实现 8 项校验（含 CAS 第 1 层 SELECT 快速失败 + 9 个错误后缀，对应 acceptance Outline 9 行）；`_infer_recover_stage` 序列扩到 sparse |

### 1.6 SparseIndexingPipeline（新建）

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [src/core/sparse_vector/indexing.py](../../src/core/sparse_vector/indexing.py) | 新增 | 文件级 all-or-nothing 编排：健康性校验（总数 0 抛 FAILED / 全 INDEXED 短路）→ 反查 `sparse_vector_status IN (PENDING, FAILED)` + `dense_vector_status=INDEXED` → 分批 encode → Qdrant upsert → mark INDEXED；异常类 `SparseIndexingError` 由编排层捕获翻 FAILED |
| [src/core/sparse_vector/pipeline.py](../../src/core/sparse_vector/pipeline.py) | 修改 | 给 `SparseVectorService` 加 `vectorize_texts(texts: list[str]) -> list[SparseVector]` 批量方法，避免重复使用底层 encoder 的私有接口 |
| [src/core/sparse_vector/__init__.py](../../src/core/sparse_vector/__init__.py) | 修改 | 不在 `__init__` 顶层导入 `SparseIndexingPipeline`（与 `qdrant_vector_storage` 循环导入），使用方直接 `from src.core.sparse_vector.indexing import ...` |
| [src/core/chunk_fact_storage/repository.py](../../src/core/chunk_fact_storage/repository.py) | 修改 | 新增 `count_by_doc_id`，服务于 sparse 健康性校验 |

### 1.7 Pipeline 编排重构

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [src/core/pipeline/parse_task/pipeline.py](../../src/core/pipeline/parse_task/pipeline.py) | 修改 | `_run` 顶部按 `is_retry` 分流到 `_handle_retry_branch` / `_handle_retry_validation_failure` / `_run_retry_stages`；首次路径在每个 post-clean 阶段前补 `mark_<stage>_started`，并在 ES 成功后新增 sparse 阶段（`_run_sparse_vectorizing`）；新增 `_load_chunks_from_db` 反查 + `_run_retry_vectorizing` + `_fail_unexpected_retry_state` 兜底；`__init__` 加 `sparse_indexing_pipeline` 注入参数（测试友好） |

### 1.8 测试

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [tests/unit/core/pipeline/test_post_process_repository.py](../../tests/unit/core/pipeline/test_post_process_repository.py) | 修改 | 修正 `mark_stage_success` 不再期望 ES 翻 SUCCESS；新增 `test_mark_es_success_does_not_flip_pipeline_status` / sparse 成功失败 / `mark_*_started` 幂等 / `mark_superseded` CAS 两态 / `create_with_inherited_state` / `create_failed_for_retry_validation` 等 9 个新用例 |
| [tests/unit/core/pipeline/test_parse_task_pipeline.py](../../tests/unit/core/pipeline/test_parse_task_pipeline.py) | 修改 | `FakePostProcessRepository` 补 6 个 `mark_<stage>_started`、sparse 系列方法、修正 `mark_es_success` 不再翻 SUCCESS；新增 `FakeSparseIndexingPipeline` 测试替身；3 个走 SUCCESS 路径的现有用例改为注入 sparse fake |
| [tests/unit/core/pipeline/test_validator_retry.py](../../tests/unit/core/pipeline/test_validator_retry.py) | 新增 | `validate_retry_context` 9 路径全覆盖（含 CAS 第 1 层快速失败） |
| [tests/unit/core/pipeline/test_sparse_indexing_pipeline.py](../../tests/unit/core/pipeline/test_sparse_indexing_pipeline.py) | 新增 | sparse 健康性 Outline、成功、失败、重试只补做 PENDING/FAILED |
| [tests/unit/core/pipeline/test_parse_task_pipeline_retry.py](../../tests/unit/core/pipeline/test_parse_task_pipeline_retry.py) | 新增 | 端到端重试 happy path / CAS 第 2 层 rowcount=0 / 校验失败双表落 FAILED / 老消息缺省 is_retry |

### 1.9 文档同步

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| [docs/reference/mysql_schema.md](../reference/mysql_schema.md) | 修改 | 加 `retry_of_task_id` / `sparse_vectorizing_*` / `superseded_by_task_id` 字段与索引；加术语映射（parsing↔cleaning）；明确 `pipeline_status=SUCCESS` 翻转点已下沉到 sparse；明确两层 CAS 语义 |
| [docs/reference/error_codes.md](../reference/error_codes.md) | 修改 | 加 `PARSING_FAILED` / `SPARSE_VECTORIZING_FAILED` / `RETRY_VALIDATION_FAILED` 三个新失败码 |
| [docs/architecture/parse_task_pipeline_module.md](../architecture/parse_task_pipeline_module.md) | 修改 | 更新为 6 阶段状态机；加术语对照表；加 §4 重试分支小节；加 `pipeline_status` 三态翻转的唯一权威说明 |
| [docs/guides/mq_integration.md](../guides/mq_integration.md) | 修改 | `ParseTaskPayload` 加 `is_retry` / `previous_task_id` 字段说明；加重试请求示例；加重试链路约束 |
| [docs/architecture/mq_module.md](../architecture/mq_module.md) | 修改 | `ParseTaskMessage` / `ParseResultMessage` 说明同步重试链路语义 |

---

## 2. 与技术方案的差异

### 2.1 重试场景下 cleaning_status != SUCCESS 或 chunking_status != SUCCESS 走"状态不一致"FAILED

**TD §7.2.5** 假定重试场景的 `cleaning_status` / `chunking_status` 都是 SUCCESS（被跳过）。
**实际实现**：在 `_run_retry_stages` 中加了一道防御 — 若进入重试时 cleaning 或 chunking 不是 SUCCESS，直接通过 `_fail_unexpected_retry_state` 走 mark_*_failed + 通知 FAILED 路径（失败原因 `RETRY_VALIDATION_FAILED:cleaning_not_success_in_retry` / `:chunking_not_success_in_retry`）。

**原因**：避免在重试场景重新触发解析+上传 / markdown 反向下载等高代价路径；让"状态不一致"以可观察的 FAILED 终态暴露给 Java / 运维。本期 brief 没有要求"重试再做一次解析+上传"。这个分支虽未在 acceptance 显式列出，但语义保守、不破坏现有 happy path。

### 2.2 `_load_chunks_from_db` 反查谓词

**TD §7.2.5** 写：`vector_status IN (PENDING, FAILED)`。
**实际实现**：使用 ORM 字段名 `dense_vector_status IN (PENDING, FAILED)`（chunk_fact_storage 模块 migration 0005 把字段更名为 `dense_vector_status`；`vector_status` 已不存在）。这是命名映射，不是行为差异。

### 2.3 `ParseTaskPipeline.__init__` 新增 `sparse_indexing_pipeline` 注入参数

TD 未显式声明，但为支持单测 mock（避免在测试中真实初始化 BGE-M3 + Qdrant 客户端），构造函数加了可选参数 `sparse_indexing_pipeline`，默认懒构造真实实现。这是测试友好性改动，向后兼容、不影响生产路径。

### 2.4 sparse_vector 包顶层不再导出 `SparseIndexingPipeline`

发现 `qdrant_vector_storage.models` 依赖 `sparse_vector.models`，而 `SparseIndexingPipeline` 又依赖 `qdrant_vector_storage`，构成循环导入。改为：`sparse_vector/__init__.py` 不导出该类，使用方直接 `from src.core.sparse_vector.indexing import SparseIndexingPipeline`。注释已写明原因。

### 2.5 TD §7.2.4 中"统一 `_execute_stage_if_pending` 抽象"未抽出独立函数

TD 设计了一个统一的 `_execute_stage_if_pending(payload, pipeline, stage_key, runner, db, ctx)` 抽象。
**实际实现**：首次解析路径保留了原有"显式 try/except 每阶段"的结构，只在每个阶段前添加 `mark_<stage>_started`；重试路径 (`_run_retry_stages`) 用条件分支按 6 阶段执行。

**原因**：原首次解析路径里有大量阶段特定的逻辑（PDF backend kwargs、source download 早删、parse_result 元数据落库等），强行抽到统一 runner 抽象会牺牲可读性。所有 22 Scenario 仍通过；后续如需进一步抽象，可由 issue #48（命名重构）一并处理。

### 2.6 重试场景下 pretokenize 跳过但 ES 失败 → 重新 build plan

`_run_retry_stages` 中：若继承时 `pretokenize_status=SUCCESS` 但 `es_indexing_status=PENDING/FAILED`，进入 ES 阶段需要 `plan`，但 plan 是 pretokenize 产出的内存对象（无持久化）。**实际实现**：此场景下重新调 `_run_pretokenize` 重建 plan（不修改 pretokenize_status 因为已 SUCCESS）。TD §7.2.4 提到这条边界但未细化方案；本实现选择最简化路径（重做 pretokenize），后续若 pretokenize 成为性能瓶颈再考虑持久化 plan。

---

## 3. 风险与遗留事项

### 3.1 命名重构待办（issue [#48](https://github.com/ql-link/LinkRag/issues/48)）

代码侧仍是 `cleaning_*`，brief / acceptance 用 `parsing_*`；本期通过 TD §2.3 术语映射表 + 文档对照表桥接。**主 PR 合入后**启动 issue #48 做全量重命名（schema 列名也会改）。

### 3.2 Java 端联动

Java 端 brief `docs/parse-retry-and-sparse-vector-java/brief.md` 需按 v3 语义更新（issue [#46](https://github.com/ql-link/LinkRag/issues/46) Body 已说明）。Java 团队需要：
- 读 `pipeline_status` / `parsed_object_key` / `pipeline.failure_reason` 替代 `log.task_status` / `log.failure_reason`
- 投递 `is_retry=true` 消息时回填上轮 `md_bucket` / `md_object_key`
- 部署顺序：先 migration 0009 → Python 部署 → Java 开始投重试

### 3.3 SparseIndexingPipeline 在 worker 启动期的延迟构造

`SparseIndexingPipeline.__init__` 不构造 `SparseVectorService` 与 `QdrantIndexStore`，第一次 `run()` 时才触发 BGE-M3 模型加载。生产环境第一条解析消息会承担模型预热成本（数秒~数十秒，视设备）。如需 worker 起手就预热，可在启动钩子里调 `SparseIndexingPipeline()._get_sparse_vector_service()`。

### 3.4 预存在的测试失败 (`aio_pika` 模块缺失)

`tests/unit/core/mq/test_rabbitmq_receiver.py` 的 4 个用例因测试环境缺少 `aio_pika` 失败，与本期无关（同样的 4 个在上一个 commit `8a674b3` 也失败），不影响本次实现。

### 3.5 集成测试 (`tests/integration/core/mq/test_kafka_parse_task_pipeline_integration.py`) 未在本期扩展端到端重试链

TD §10.1 / §13 step 9 列了"端到端集成测试"。本期实现优先覆盖单元测试 22 Scenario；端到端集成测试更适合 Java 端联动完成后一起跑通。建议在 Java 端 brief 修订并合入后单独开 PR 补集成测试。

---

## 4. 验证结果

- **单元测试**：`pytest tests/unit/core/pipeline tests/unit/core/sparse_vector -q` → **83 passed**
- **全量 unit 套件**：`pytest tests/unit -q` → **383 passed**, 4 pre-existing failures（与本期无关，aio_pika 模块缺失）
- **doc-sync 检查**：`scripts/check_docs_sync.py --working` → **OK: 23 changed file(s), no doc-sync issues**
- **导入冒烟**：`python -c "import src.core.pipeline.parse_task.pipeline; import src.core.sparse_vector.indexing; ..."` → OK
- **22 Scenario 覆盖**：与 TD §10.2 一致；新增 4 个测试文件 + 修订现有 fake repo，所有 Scenario 通过对应单测验证

---

## 5. 后续动作（按优先级）

1. **Java 端联动修订**：通知 Java 团队按 v3 brief 修订 Java 端 brief（`docs/parse-retry-and-sparse-vector-java/brief.md`）。
2. **集成测试扩展**：Java 端联动完成后补端到端重试链路集成测试。
3. **issue #48 推进**：主 PR 合入后启动 `cleaning_*` → `parsing_*` 命名重构。
4. **生产灰度**：建议先在 1-2 个低流量数据集上启用重试链路 + sparse 阶段，观察 BGE-M3 模型加载成本与 Qdrant sparse 写入吞吐。
