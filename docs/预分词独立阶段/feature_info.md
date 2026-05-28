# 预分词独立阶段 — Feature Info

- **当前阶段**：test-and-delivery 完成 → 待交付收口
- **technical_design 冻结时间**：2026-05-18
- **实现完成时间**：2026-05-18
- **创建时间**：2026-05-18
- **brief 冻结时间**：2026-05-18（2026-05-18 TD 阶段受控订正：保留 retry 两列，仅删 ES 内部自动重试）
- **acceptance 冻结时间**：2026-05-18（2026-05-18 受控订正：2 处 retry 断言 + 1 Scenario 更名）

## 产物清单

| 产物 | 路径 | 状态 |
| :--- | :--- | :--- |
| 需求 Brief | `docs/预分词独立阶段/brief.md` | 已冻结（v1 + R9 受控订正） |
| 验收契约 | `docs/预分词独立阶段/acceptance.feature` | 已冻结（16 Scenario，含 4 Outline；R9 受控订正） |
| 技术方案 | `docs/预分词独立阶段/technical_design.md` | 已冻结（v1.4，R1–R10 全部处置/拍板） |
| 实现报告 | `docs/预分词独立阶段/implementation_report.md` | 已产出（L3，含差异与遗留） |

## acceptance.feature 概览

- Scenario 总数：16（含 4 个 Scenario Outline）
- 覆盖分类：
  - 主流程：全链路成功通知、单趟扇出只分词一次且不持久化
  - 预分词 all-or-nothing：任一 chunk 失败文件级终态不污染 chunk、各类失败触发条件 Outline
  - dense 耦合：仅 dense 成功 chunk 进入、空计划但仍有 pending 不误判成功
  - ES chunk 级语义：部分失败不中止整批、基础设施故障文件级不标 chunk、全部成功收敛
  - 失败即终态：无 ES 内部重试计数/上限/exhausted Outline、多次失败不被次数拦截（retry 两列保留作用户侧重试，仅预留 claim_failed_for_retry 不接线）
  - 外部重投幂等续跑：ES 部分失败只补子集、预分词失败整篇重入、recover_from_stage 推断 Outline、全成功重投空操作
  - 失败来源前缀映射 Outline（纯内部排障）

## 推荐阅读顺序

1. `brief.md`（已冻结，含 R9 受控订正）— 需求理解与决策
2. `acceptance.feature`（已冻结，含 R9 受控订正）— 可执行验收契约
3. `technical_design.md`（v1.4 已冻结）— 方法级实现方案

## 下一步

代码实现与 test-and-delivery 已完成：unit 全量 291 passed、Kafka 解析任务集成测试 4 passed、doc-sync 0 error 0 warning。交付前仅剩环境侧 Alembic DB 升降级验证，以及后续需求中的 R10 用户侧重试接线。
