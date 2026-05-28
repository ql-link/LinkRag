# 预分词独立阶段 实现报告

- **输入依据**：technical_design.md（v1.4，2026-05-18 冻结）/ brief.md / acceptance.feature（均含 R9 受控订正）
- **实现时间**：2026-05-18
- **目标分支**：feature/pretokenization
- **功能等级**：L3（跨模块编排 + schema 变更 + 状态机变更）

## 1. 实际改动清单（按 TD §13 顺序落地）

| 文件 | 动作 | 落地内容 |
| :--- | :--- | :--- |
| `src/core/pipeline/parse_task/post_process/constants.py` | 修改 | 新增 `POST_PROCESS_STAGE_PRETOKENIZE="PRETOKENIZE"` |
| `src/models/parse_task.py` | 修改 | `DocumentPostProcessPipeline` 新增 `pretokenize_status`/`pretokenize_duration_ms` 两列；retry 两列与 `idx_post_pipeline_retry` 索引保留不动 |
| `src/config.py` | 修改 | 删除 `ES_INDEXING_MAX_RETRY` |
| `migrations/versions/0002_20260518_pretokenize_stage.py` | 新增 | revision=0002 / down_revision=0001；upgrade 仅 add 2 列、downgrade 仅 drop 2 列 |
| `scripts/db/init.sql` | 修改 | `document_post_process_pipeline` 建表新增 2 列；failed_stage/recover_from_stage 注释加 PRETOKENIZE；retry 列注释改“用户侧重试” |
| `docs/reference/mysql_schema.md` | 修改 | 四段表头 + 2 行新字段 + retry/failed_stage 语义补注（idx 保留） |
| `src/core/pipeline/parse_task/post_process/repository.py` | 修改 | `create_for_log` 初始化 pretokenize_status；新增 `mark_pretokenize_success`/`mark_pretokenize_failed`；`_mark_failed` 增 PRETOKENIZE 分支；新增预留 `claim_failed_for_retry`；`mark_processing` 加不变量注释 |
| `src/core/preprocessor/service.py` | 修改 | 删 `_mark_pretokenize_failed`；`build_file_post_index_plan` except 仅 `raise PreprocessorError`；`__init__` 移除 `chunk_repository`；移除 `ChunkRepository`/`Sequence` 死导入 |
| `src/core/es_index_storage/pipeline.py` | 修改 | `_ensure_index` 失败改文件级（不标 chunk、`ensure_index:` 前缀、failed_item_ids=[]）；删 `_mark_all_failed` 及未用 `logger` 导入 |
| `src/core/pipeline/parse_task/pipeline.py` | 修改 | 新增 `_run_pretokenize`（返回 `tuple[plan, failure_reason]`）；`_run` 插入预分词阶段块，四阶段失败处理统一由 `_run` 内联写库+通知；`_run_es_indexing(plan, db)` 改为纯消费；删除 `_handle_pretokenize_failure`/`_handle_es_failure`/`_is_es_retry_exhausted`；`_get_preprocessor` 改 `Preprocessor()`；移除未用 `settings` 导入 |
| `src/core/pipeline/parse_task/validator.py` | 修改 | `_infer_recover_stage` 增 PRETOKENIZE（pretokenize_status 不被 mark_processing 清）；`_mark_incomplete_pipeline_failed` 增 PRETOKENIZE 分支；导入新常量 |
| `docs/architecture/parse_task_pipeline_module.md` | 修改 | 状态机/阶段表/失败语义/恢复入口/失败前缀同步（doc-sync error 级强制） |
| `docs/guides/configuration.md`、`docs/reference/elasticsearch_schema.md` | 修改 | 配置项移除说明、ensure_index 文件级失败说明（doc-sync warn 级） |
| 5 个测试文件 | 测试修改 | 见 §3 |

## 2. 与技术方案的差异

实现对 TD v1.4 有 1 处结构性偏离（已回写 TD 留痕）、1 处编码期修正、1 处架构统一、1 处死代码清理：

1. **`pretokenize_failed` 持久列移除（结构性偏离，已回写 TD）**：TD v1.4（含 v1.2 决策）原定新增 3 列含持久标记列 `pretokenize_failed`，用于跨重投不丢失预分词失败定位。实现阶段确认 `mark_processing` 本就不重置任何阶段 `*_status` 列，`pretokenize_status` 自身已具备同等持久性，`_infer_recover_stage` 直接据 `pretokenize_status != SUCCESS` 即可保证恢复必回 PRETOKENIZE —— 该列冗余。故回归 brief 原定 2 列方案（`pretokenize_status` + `pretokenize_duration_ms`）。**该偏离已回写 TD：修订记录 v1.2 标「已废弃」、§12 R8 记录废弃理由、§6.3/§7.2/§10 正文已同步，acceptance.feature 无 `pretokenize_failed` 引用，三件套保持闭环一致。**
2. **`_run_pretokenize` 空 plan 判定**：TD §7.2.2 写作 `if plan.total_items == 0`，但 `FilePostIndexPlan` 模型无 `total_items` 属性（只有 `chunks_with_tokens`）。实现改为 `if len(plan.chunks_with_tokens) == 0`，语义等价、为 TD 笔误的必要订正。
3. **失败处理统一**：TD 原设计保留独立 `_handle_pretokenize_failure`/`_handle_es_failure` 方法，实现阶段为对齐 CHUNKING/VECTORIZING 的模式，将四阶段失败处理统一内联到 `_run`——`_run_pretokenize` 返回 `(None, failure_reason)` 失败信号，`_run` 统一写库+通知+return。两个 handler 方法已删除。
4. 顺带清理随改动失效的死导入（`ChunkRepository`/`Sequence`/`logger`/`settings`），符合项目“无死代码”约定，未超出 TD 范围。

除上述已回写 TD 的偏离外无其它偏离；brief/acceptance/TD 三件套与实现保持一致。

## 3. 测试改动与结果

- `tests/unit/core/preprocessor/test_service.py`：删 `chunk_repository` 注入；失败用例改为断言 `raises PreprocessorError` 且 `session.commit` 不被 await（零 DB 写、不标 chunk）。
- `tests/unit/core/es_index_storage/test_pipeline.py`：ensure_index 失败用例改为断言文件级（`failed_item_ids==[]`、`ensure_index:` 前缀、`mark_es_failed` 不被 await）。
- `tests/unit/core/pipeline/test_parse_task_pipeline_es.py`：重写为 `TestRunPretokenize`/`TestRunEsIndexing`/`TestHandleEsFailure`，覆盖文件级 all-or-nothing 不污染 chunk、空 plan ±pending、单趟扇出透传、失败不增 retry_count、前缀保留；删除 `TestIsEsRetryExhausted`。
- `tests/unit/core/pipeline/test_parse_task_pipeline.py` 与 `tests/integration/.../test_kafka_parse_task_pipeline_integration.py`：Fake 仓储补 `pretokenize_status` 字段与 `mark_pretokenize_success/failed` 方法。
- `tests/unit/core/pipeline/test_post_process_repository.py`：新增 pretokenize 状态写入、`claim_failed_for_retry` 预留行为断言。

**结果**：`tests/unit` 全量 **291 passed**；受影响 3 个 unit 目录 **59 passed**；Kafka 解析任务集成测试 **4 passed**；doc-sync `--staged` **0 error 0 warning（24 文件）**。

## 4. 遗留风险与后续事项

1. **Alembic 未运行时验证**：本环境 venv 未安装 `alembic` 且无在线 MySQL，`0002` 仅做语法编译校验（`py_compile` 通过）+ 按 `0001`/`script.py.mako` 同构编写。上线前需在有 DB 环境执行 `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` 验证（TD §10.3）。
2. **验收契约自动化形态**：仓库当前未引入 `pytest-bdd`/step definitions，`acceptance.feature` 作为冻结验收契约保留；本次通过 unit + Kafka 集成测试覆盖核心断言。
3. **R10 用户侧重试触发路径**：`claim_failed_for_retry` 已实现但**未接线**（`handle_duplicate` 未改、无新 MQ/接口契约）。在后续需求接线前 `retry_count` 维持初始 0、无写入方。
4. **venv 解释器路径陈旧**：`.venv/bin/pytest` shebang 指向旧项目路径失效，需用 `.venv/bin/python -m pytest`；属环境问题，非本次代码引入。
