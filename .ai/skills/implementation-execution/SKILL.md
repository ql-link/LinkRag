---
name: implementation-execution
description: 在需求和技术方案确认后执行代码实现，并在必要时产出 implementation_report.md。
when_to_use: "当需求和技术方案已确认并且给出需求和技术方案后、需要开始具体编码实现时激活。触发示例：'开始写代码吧'、'按方案实现这个功能'、'可以开始编码了'、'实现这个需求'"
---

# Implementation Execution

## 目的

按已确认方案落地代码，并在实现与方案有偏差时沉淀改造报告。

本 skill 主要负责：

- 根据已审核文档落地代码
- 控制实现不要偏离需求和技术方案
- 在需要时产出 `implementation_report.md`

## 输入前提

- `.specs/<feature-name>/brief.md` 已冻结
- `.specs/<feature-name>/acceptance.feature` 已冻结
- 若存在 `.specs/<feature-name>/technical_design.md`，则其也已审核通过

## 必读文件

1. `CLAUDE.md` / `AGENTS.md`（同一份，项目使用入口）
2. `.specs/<feature-name>/feature_info.md`（若存在）
3. `.specs/<feature-name>/brief.md`
4. `.specs/<feature-name>/acceptance.feature`
5. `.specs/<feature-name>/technical_design.md`（若存在）
6. 对应组件说明文档（若涉及，见 `docs/internals/`）
7. 涉及模块的真实代码

## 输出位置

代码改动直接落到仓库中。

若需要改造报告，输出位置固定为：

`.specs/<feature-name>/implementation_report.md`

> `.specs/` 整目录 git-ignored；合并 PR 前应把有长期价值的内容沉淀到 PR 描述 / `docs/internals/` / `tests/acceptance/features/`，详见 [.specs/README.md](../../../.specs/README.md)。

改造报告模板固定为：

`.ai/skills/implementation-execution/implementation_report.template.md`

## 输出要求

- 落地代码改动
- 当功能为 `L3`，或实现与技术方案存在显著偏差时，产出 `implementation_report.md`

## 什么时候必须写 `implementation_report.md`

以下任一情况成立时，必须写：

1. 当前期次功能等级为 `L3`
2. 实际实现明显偏离 `technical_design.md`
3. 改动跨多个模块、多个中间件或多个关键链路
4. 存在需要向后续测试、交付、审查特别说明的实现差异

以下情况通常可以不单独写：

- `L1` 小改动
- `L2` 且实现与技术方案基本一致
- 影响面小，且后续 `testing_delivery.md` 足以说明交付结果

## 写改造报告时必须读取

1. `.specs/<feature-name>/brief.md` + `acceptance.feature`
2. `.specs/<feature-name>/technical_design.md`（若存在）
3. 实际代码 diff
4. `.specs/<feature-name>/feature_info.md`

## 改造报告应包含什么

`implementation_report.md` 应重点记录：

- 实际改了哪些模块、文件、接口、配置、数据或中间件
- 代码最终落在哪些位置
- 与技术方案有哪些差异
- 为什么产生这些差异
- 有哪些遗留风险和后续事项

它不应该重复：

- 完整需求背景
- 完整技术方案
- 完整测试执行结果

写作时应优先按 `.ai/skills/implementation-execution/implementation_report.template.md` 的章节结构落文。

## 强制约束

- 不允许跳过已确认的需求边界私自扩展范围
- 若影响面扩大，应触发复杂度升级建议并等待用户确认
- 改造报告只记录实际落地内容与差异，不重复写需求与方案
- 编写代码时，关键逻辑必须补充注释，尤其是复杂判断、状态流转、组件衔接点和不直观的设计意图
- 注释应简洁、解释性强，不要写成机械式逐行说明
- 若方案与实现出现明显偏差，不能只改代码不留记录

## 实施步骤

### 步骤 1：按文档实现代码

- 以 `brief.md` + `acceptance.feature` 为边界
- 以 `technical_design.md` 为实现依据
- 先复用已有模块和组件，再考虑改 framework

### 步骤 2：在关键位置补注释

至少在以下位置补注释：

- 复杂业务判断
- 关键状态流转
- 跨组件调用链
- 不易直观看懂的设计意图

### 步骤 3：识别实现偏差

在编码过程中持续判断：

- 是否与技术文档一致
- 是否新增了未预期的模块改动
- 是否改变了原约定中的某些边界

### 步骤 4：需要时补 `implementation_report.md`

若触发“必须写改造报告”的条件，则立即整理：

- 改动清单
- 差异说明
- 风险与后续事项

## 完成后的停点

本 skill 完成后，不应直接宣称交付完成。

完成动作包括：

1. 代码实现完成
2. 必要时写好 `implementation_report.md`
3. 更新 `feature_info.md`
4. 进入 `test-and-delivery` 阶段
