# 稀疏向量 Feature Info

## 当前阶段

test-and-delivery 待确认

## 产物清单

| 产物 | 状态 | 说明 |
| :--- | :--- | :--- |
| brief.md | 已冻结 | 基于 `docs/稀疏向量/sparse_vector_PRD.md` 收敛为 Spec-as-Test brief；字段修复已同步读时过滤字段名 |
| acceptance.feature | 已冻结 | 已生成 16 个 Scenario/Scenario Outline，覆盖主流程、异常处理、幂等与重试、CPU fp32、本地模型、边界条件与非目标 |
| technical_design.md | 已冻结 | 已基于已冻结的 acceptance.feature 修订技术设计，明确 CPU fp32 / CUDA fp16 路线 |
| implementation_report.md | 待确认 | 已记录实现落点、方案差异、一致性处理、测试与遗留事项 |

## 输入来源

- `docs/稀疏向量/brief.md`
- `docs/稀疏向量/acceptance.feature`
- `docs/development/spec_as_test_handbook.md`
- `.ai/skills/technical-design/SKILL.md`
- `.ai/skills/technical-design/technical_design.template.md`
- `.ai/skills/implementation-execution/SKILL.md`

## 推荐阅读顺序

1. `brief.md`
2. `acceptance.feature`
3. `technical_design.md`
4. `implementation_report.md`
