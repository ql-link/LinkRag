---
name: code-review-and-quality
description: 在进入最终提交/合并前执行五维代码审查并输出分级结论。用于功能实现完成后、测试交付完成后、以及任何准备发布前的质量门禁。
when_to_use: "当代码实现完成、测试交付后、准备提交代码或合并分支前需要进行质量审查时激活。触发示例：'代码写完了帮我 review'、'提交前检查一下'、'看看有没有问题'、'准备合并了'"
---

# Code Review And Quality

## 1. 目的

本 skill 用于在“测试与交付”之后、最终提交或合并之前执行质量门禁审查。

审查固定覆盖五个维度：

1. Correctness（正确性）
2. Readability（可读性与简洁性）
3. Architecture（架构一致性）
4. Security（安全）
5. Performance（性能）

## 2. 使用前提

仅在以下场景使用：

- 当前需求已完成实现与测试交付
- 准备进入“最终审核与提交/合并/发布”
- 需要对 AI 或人工产出的改动进行统一质量审查

## 3. 必读输入

1. `CLAUDE.md` / `AGENTS.md`
2. `.specs/<feature-name>/feature_info.md`（若存在）
3. `.specs/<feature-name>/brief.md`
4. `.specs/<feature-name>/acceptance.feature`
5. `.specs/<feature-name>/technical_design.md`（若存在）
6. `.specs/<feature-name>/implementation_report.md`（若存在）
7. 实际代码变更（`git diff` / 关键文件）

## 4. 审查流程

### 步骤 1：先看目标与测试证据

- 核对改动是否覆盖 `brief.md` + `acceptance.feature` 的核心目标
- 检查 `tests/acceptance/` 下对应 feature 的测试是否齐全且通过
- 若缺关键测试证据，直接记为 Required 问题

### 步骤 2：五维审查

按以下顺序检查每个变更点：

1. Correctness：功能是否符合需求，异常路径是否可用
2. Readability：命名、控制流、注释是否清晰，是否存在不必要复杂度
3. Architecture：是否遵循现有分层与模块边界，是否引入不必要耦合
4. Security：输入校验、权限校验、敏感信息处理是否合规
5. Performance：是否存在明显 N+1、无界查询、热点路径低效实现

### 步骤 3：问题分级

- `Critical`：阻塞合并（安全漏洞、数据风险、核心功能错误）
- `Required`：必须修复后再合并（需求偏差、关键测试缺失、明显架构问题）
- `Suggestion`：可优化项（不阻塞当前交付）

## 5. 输出要求

审查结果必须包含：

1. 审查范围（哪些文档、哪些代码）
2. 分级问题清单（含文件路径与简要修复建议）
3. 审查结论：`APPROVE` 或 `REQUEST_CHANGES`
4. 下一步建议（修复后复审，或进入提交/合并）

## 6. 阶段切换 Gate

审查结束时必须输出状态块（与 `AGENTS.md` 双重审核协议一致）：

```text
PHASE: 最终审核与提交/合并/发布
AI_REVIEW: PASS | FAIL
HUMAN_REVIEW: APPROVED | PENDING
NEXT_PHASE: 提交/合并/发布 | BLOCKED
BLOCK_REASON: <阻塞原因；无则写 NONE>
```

判定规则：

- 存在 `Critical` 或 `Required` 未关闭：`AI_REVIEW=FAIL`
- 无阻塞问题且审查结论为 `APPROVE`：`AI_REVIEW=PASS`
- 仅当 `AI_REVIEW=PASS` 且 `HUMAN_REVIEW=APPROVED` 才允许进入提交/合并/发布
