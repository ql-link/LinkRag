> ⚠️ **本方向已废弃（2026-05）**
>
> 本目录文档对应的 ES 入库后台自动重试方案与项目流水线"用户驱动 + 断点续跑"契约不一致，已被 leader 否决（见 issue #25 review）。实际实现改为用户手动重试路径，详见 [docs/ES入库手动重试/brief.md](../ES入库手动重试/brief.md)。
>
> 本文件仅保留作历史决策记录，不再维护，亦不反映线上代码现状。

---

# ES入库重试机制 Implementation Report

## 1. 实际改动范围

本次按已冻结 `technical_design.md` 落地 ES 入库失败补偿重试机制，代码改动覆盖：

- `src/core/pipeline/parse_task/post_process/repository.py`
  - 新增 ES 重试候选查询、条件认领、按 id 查询。
- `src/core/pipeline/parse_task/es_retry_service.py`
  - 新增单轮 / 单条 ES 补偿重试服务。
  - 从已落库的后处理记录、解析日志、文件解析表恢复 ES 重试上下文。
  - 成功时收敛后处理状态并补发 success。
  - 失败未耗尽时仅落库，耗尽时追加 `retry_exhausted=true` 并补发 failed。
- `src/core/pipeline/parse_task/es_retry_scheduler.py`
  - 新增后台调度器，支持启停和异常隔离。
- `src/core/pipeline/parse_task/notifier.py`
  - 新增字段级 parse_result 发送方法，避免 ES 重试链路伪造完整 `ParseTaskPayload`。
- `src/core/pipeline/parse_task/pipeline.py`
  - 抽出按 doc/task 执行 ES 入库的内部入口。
  - 暴露 ES 失败原因构建与重试耗尽判断供重试服务复用。
- `src/config.py` / `.env.example`
  - 新增 ES 重试开关、扫描间隔、批量配置。
- `src/main.py`
  - FastAPI lifespan 中启动和停止 ES 重试调度器。

测试改动覆盖：

- `tests/unit/core/pipeline/test_post_process_repository.py`
- `tests/unit/core/pipeline/test_es_index_retry_service.py`
- `tests/unit/core/pipeline/test_es_index_retry_scheduler.py`
- `tests/unit/test_main_lifespan_es_retry.py`

文档同步覆盖：

- `docs/architecture/parse_task_pipeline_module.md`
- `docs/architecture/project_structure.md`
- `docs/guides/configuration.md`
- `docs/ES入库重试机制/*`

## 2. 与技术方案的差异

整体实现与技术方案一致。实现阶段有两处细化：

- `EsIndexRetryService.run_once()` 先查询候选 id，再逐条调用 `retry_one()` 独立认领和执行。这样每条记录使用独立事务上下文，避免一条失败影响整批。
- `retry_one()` 自身也执行认领动作，而不是要求调用方预先认领。这样便于测试、后续管理命令和后台调度复用同一个入口。

这两处不改变业务语义，仍满足“数据库层条件认领、同一记录只执行一次”的约束。

## 3. 状态与通知语义

- 候选条件：`pipeline_status=FAILED`、`recover_from_stage=ES_INDEXING`、`es_indexing_status=FAILED`、`retry_count < ES_INDEXING_MAX_RETRY`。
- 认领时：`pipeline_status` 置为 `PROCESSING`，写 `last_retry_at`，不增加 `retry_count`。
- 重试成功：`pipeline_status=SUCCESS`、`es_indexing_status=SUCCESS`，补发 `parse_result success`。
- 重试失败未耗尽：`retry_count + 1`，保持 `FAILED/ES_INDEXING`，不补发 failed。
- 重试失败耗尽：失败原因追加 `retry_exhausted=true`，补发 `parse_result failed`。

## 4. 验证结果

已执行：

```bash
.venv/bin/python -m pytest tests/unit/core/pipeline/test_post_process_repository.py tests/unit/core/pipeline/test_parse_task_pipeline_es.py tests/unit/core/pipeline/test_es_index_retry_service.py tests/unit/core/pipeline/test_es_index_retry_scheduler.py tests/unit/test_main_lifespan_es_retry.py tests/unit/core/es_index_storage/test_pipeline.py -q
.venv/bin/python -m pytest tests/unit/core/pipeline -q
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python scripts/check_docs_sync.py --working
```

结果：

- 相关测试：31 passed
- pipeline 单测：42 passed
- unit 全量：342 passed
- doc-sync：OK，10 changed file(s)，no doc-sync issues

## 5. 遗留风险

- 当前分支仍存在 `ParseTaskPipeline._get_preprocessor()` 动态导入 `src.core.preprocessor.service.Preprocessor` 的问题；本次未改变该依赖，只补齐 ES 失败后的补偿调度。如果目标基线缺少该模块，真实 ES 入库会在预分词阶段失败并进入本次补偿失败路径。
- 通知 success 失败时，本次按验收要求保留 ES 成功和后处理成功，不回滚索引结果。后续如需补偿通知，可单独做 parse_result 通知补偿机制。
