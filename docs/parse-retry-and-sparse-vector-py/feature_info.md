# 需求信息：解析失败重试链路 + 稀疏向量阶段接入（Python 端）

- **当前阶段**：implementation-execution 已完成（2026-05-27），代码已落地、单测 83 通过、文档已同步、改造报告已沉淀；待进入 test-and-delivery（端到端集成测试 + Java 端联动验收）
- **brief 版本历史**：
  - v1：2026-05-21（首版冻结）
  - v2：2026-05-26（task_status 上调为整体终态、failed_stage 枚举扩充、解析失败 pipeline 同步、CAS 两层）
  - v3：2026-05-26（状态权威单源化：删除 log.task_status / log.failure_reason；删除 pipeline.chunk_count / retry_count / last_retry_at；新增 pipeline.parsing_status / parsing_duration_ms；pipeline 表升格为"文件解析流程状态表"）— **已冻结**
- **产物清单**：
  - `brief.md` — v3 已冻结（2026-05-26）
  - `technical_design.md` — v1.0 已冻结（2026-05-26）
  - `implementation_report.md` — 2026-05-27 已沉淀（含改动清单、与 TD 差异、风险与遗留事项）
  - `acceptance.feature` — v3 已冻结（2026-05-26），22 Scenario：
    - 状态权威单源化不变量 ×4（PENDING / PROCESSING 翻转 / 不重复翻转 / 全 SUCCESS 翻转）
    - 主流程首次解析 ×3（happy path / 老消息向后兼容 / 解析失败仅 pipeline 落 FAILED）
    - 主流程重试解析 ×3（跳过已成功阶段 / duration 继承 / 跳过 chunking 反查 chunks）
    - 重试前置校验失败 Scenario Outline ×1（9 个校验项 Examples）
    - 并发重试 CAS 第 2 层 ×1
    - Dense 向量化失败/重试 ×2
    - 稀疏向量阶段 ×4（成功 / 失败 / 重试补做 / 健康性校验 Outline）
    - 跳阶段数据完整性 ×1
    - 通知契约 ×1
    - Schema 变更 ×1
- **v3 主要修订**：
  1. 删除 `document_parsed_log.task_status`：整体任务状态唯一权威收敛到 `pipeline_status`
  2. 删除 `document_parsed_log.failure_reason`：失败原因唯一权威收敛到 `pipeline.failure_reason`
  3. 新增 `document_post_process_pipeline.parsing_status` 与 `parsing_duration_ms`：覆盖解析+上传阶段的状态机
  4. 删除 `document_post_process_pipeline.chunk_count`：chunk 真值表为 source of truth
  5. 保留 `recover_from_stage` 与 `total_duration_ms`（作为缓存/便利字段，不强制推导）
  6. `document_post_process_pipeline` 表注释由"文件级解析后处理流程状态表"改为"**文件解析流程状态表**"（覆盖 6 阶段）
  7. log 表退化为"解析产物快照表"
  8. `ParseLogRepository.mark_success` / `mark_failed` 整体废弃，状态翻转下沉到 `PostProcessPipelineRepository`
  9. 新增 `mark_parsing_success` / `mark_parsing_failed` 编排首次解析阶段
- **配套独立 issue**：
  - [#46 解析状态权威单源化与表结构清理](https://github.com/ql-link/LinkRag/issues/46) — schema 字段增删 + Alembic migration + Java/Python 联动改造；该 issue 必须先于本 brief 实现合入
- **联动影响（出本仓库范围）**：
  - Java 端 brief `docs/parse-retry-and-sparse-vector-java/brief.md` 第 2.2 节首次/重试判定需重写：
    - "整体已成功" → 读 `pipeline_status == SUCCESS`
    - "markdown 已上传" → 读 `log.parsed_object_key IS NOT NULL`
    - "失败原因" → 读 `pipeline.failure_reason`
    - 不再读 `log.task_status` 与 `log.failure_reason`
  - Java DAO 移除对 `log.task_status` / `log.failure_reason` 的字段映射
- **推荐阅读顺序**：
  1. `brief.md`（本目录，v3）
  2. [docs/architecture/parse_task_pipeline_module.md](../architecture/parse_task_pipeline_module.md)（现有架构）
  3. [src/core/pipeline/parse_task/pipeline.py](../../src/core/pipeline/parse_task/pipeline.py)（主编排）
- **关联资料**：
  - Java 端 brief：`docs/parse-retry-and-sparse-vector-java/brief.md`（已冻结 2026-05-21，因 v3 语义变更需再次同步修订）
  - 关联 issue：
    - [#46 解析状态权威单源化与表结构清理](https://github.com/ql-link/LinkRag/issues/46)（配套 issue，必须先合入）
    - #38 chunking 落库与 dense 向量化时机改造（并行分支推进）
    - #41 kb_document_chunk 与 document_post_process_pipeline 职责拆分
    - #42 删除 claim_failed_for_retry 预留方法
- **下一步**：
  1. ~~你开"解析状态权威单源化与表结构清理"独立 issue~~ ✅ 已开 [#46](https://github.com/ql-link/LinkRag/issues/46)
  2. ~~审阅 v3 brief 并确认冻结~~ ✅ 已冻结（2026-05-26）
  3. ~~进入 `acceptance-generator` 基于 v3 整体重写 `acceptance.feature`~~ ✅ v3 已冻结（2026-05-26）
  5. ~~进入 `technical-design` 基于冻结 brief + acceptance 生成技术方案~~ ✅ v1.0 已冻结（2026-05-26）
  6. ~~进入 `implementation-execution` 按 TD §13 实施顺序落地~~ ✅ 2026-05-27 完成（83 单测通过、5 文档同步、改造报告已沉淀）
  4. 同步通知 Java 团队按 v3 联动影响修订 Java 端 brief（issue #46 已在 Body 中说明 Java 联动改造，可作为通知锚点）
