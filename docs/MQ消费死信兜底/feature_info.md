# MQ 消费 poison pill 死信与重试兜底 — Feature Info

- **来源**：GitHub issue #22 [P0] Kafka 消费 poison pill 无限重投，缺少 DLQ 与最大重试
- **当前阶段**：implementation 完成待审核（实施时间 2026-05-19 ～ 2026-05-20）
- **分支**：`feature/mq-dlq-poison-pill`（基于 dev）
- **产物清单**：
  - `brief.md` — 需求 brief（已冻结 2026-05-19）
  - `acceptance.feature` — 验收契约（已冻结 2026-05-19，17 Scenario）
  - `technical_design.md` — 技术方案（已冻结 2026-05-19，v1.0）
  - `implementation_report.md` — 实现报告（v1.0，2026-05-20）
- **实现概览**：
  - 生产代码：10 个文件（新增 `src/core/mq/retry.py`；改造 Kafka/RabbitMQ adapter / factory / topic_admin / exceptions / notifier / config / .env.example；main.py 不改）
  - 测试：6 个新增文件 + 1 个既有断言更新
  - 文档同步：3 个（mq_module.md / configuration.md / parse_task_pipeline_module.md）
  - 全量回归 367 passed（含 23 个 acceptance），doc-sync 全绿
- **遗留事项**（详见 implementation_report §6）：
  - 上线前与运维确认 RabbitMQ 既有 queue 是否需要重建（PRECONDITION_FAILED 风险）
  - 后续单开小 issue：DLT 端到端集成测试、DLT 消息回灌脚本
- **推荐阅读顺序**：`brief.md` → `acceptance.feature` → `technical_design.md` → `implementation_report.md`
- **下一步**：人工审核 implementation_report → 进入 code-review-and-quality → branch-pr-workflow（merge to dev）
