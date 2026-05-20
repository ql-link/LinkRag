# 解析任务OOM风险治理

- **当前阶段**：implementation 完成，待 test-and-delivery（2026-05-19）
- **产物清单**：
  - `brief.md` — 已冻结
  - `acceptance.feature` — 已冻结（pytest-bdd 18 Scenario 全绿）
  - `technical_design.md` — 已冻结（v1.0）
  - `implementation_report.md` — v1.0（L3 改造完成）
- **测试结果**：
  - `pytest tests/unit tests/acceptance -q` → 317 passed / 0 failed
  - `pytest tests/acceptance -v` → 18 passed（acceptance.feature 全量 Scenario）
- **推荐阅读顺序**：
  1. `brief.md` — 第 1 章摘要 → 第 2 章流程 → 第 3 章模块 → 第 5 章待确认问题
- **相关代码入口**：
  - `src/core/pipeline/parse_task/source.py:22-35`
  - `src/core/pipeline/parse_task/pipeline.py:149-160`
  - `src/services/storage/{base,minio_storage,oss_storage}.py`
  - `src/core/parser/base.py`
  - `src/services/parse_task_service.py`
  - `src/core/mq/consumers/parse_task_consumer.py`
