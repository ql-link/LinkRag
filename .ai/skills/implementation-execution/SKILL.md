---
name: implementation-execution
description: 「需求 → 交付」链的编码执行站。把已冻结的 brief.md / acceptance.feature（L3 还有 technical_design.md）落地为真实代码，并在 L3 或实现偏离方案时产出 implementation_report.md。核心纪律：编码中发现 spec 缺口必须先回写 spec 再继续，不允许静默改代码绕过、让 spec 与代码脱节。只要进入"按方案写代码 / 开始实现这个需求 / 可以编码了"的阶段就用本 skill。无冻结 spec（只有口头需求）→ 先转 brief-generator 收敛；代码写完 → 转 run-all-tests + code-review-and-quality，最终经 branch-pr-workflow 提 PR。
when_to_use: "当需求与技术方案已确认、要开始具体编码实现时激活。触发示例：'开始写代码吧'、'按方案实现这个功能'、'可以开始编码了'、'实现这个需求'、'把这个 feature 写出来'。前置：不存在冻结的 brief.md / acceptance.feature（用户只有口头需求、尚无 spec）时，不要直接编码，先转 brief-generator。边界：本 skill 只负责落地代码与改造报告，不跑全量测试（转 run-all-tests）、不做质量门禁（转 code-review-and-quality）、不建分支提 PR（转 branch-pr-workflow）。"
---

# Implementation Execution

## 1. 定位

本 skill 是「需求 → 交付」链的**编码执行站**：把上游已冻结的产物落地成仓库里的真实代码。

它主要回答"按既定边界与方案，怎么把代码写出来、写到哪、偏差怎么留痕"：

- 根据已审核的 `brief.md` / `acceptance.feature` / `technical_design.md` 落地代码
- 把实现约束在已确认的需求边界与技术方案内，不私自扩范围
- 在 L3 或实现与方案有偏差时，沉淀 `implementation_report.md`
- 编码中发现 spec 缺口时，**先回写 spec 再继续**（见第 8 节回流规则）

它**不负责**：

- 收敛需求、写 brief / acceptance / 技术方案（→ 对应上游 skill）
- 跑全量回归测试（→ `run-all-tests`）
- 质量门禁审查（→ `code-review-and-quality`）
- 建分支、提 PR、做收口门槛（→ `branch-pr-workflow`）

## 2. 触发边界

### 2.1 适合使用

- 已有冻结 spec，用户说"开始写代码 / 按方案实现 / 可以编码了 / 实现这个需求"
- L1 小改动经 `flow-router` 直转本 skill（无需 brief，直接编码）
- 续做一个进行中的 feature（尤其 L3 跨会话）

### 2.2 不适合使用

- 只有口头需求、无冻结 `brief.md` / `acceptance.feature` → 先转 `brief-generator` 收敛，不要凭聊天记忆直接编码
- 用户要的是跑测试 / 质量审查 / 提 PR → 分别转 `run-all-tests` / `code-review-and-quality` / `branch-pr-workflow`
- 用户只是要改本 skill 模板或工作规则本身

## 3. 输入前提与机器门禁

输入前提：

- `.specs/<feature-name>/brief.md` 已冻结
- `.specs/<feature-name>/acceptance.feature` 已冻结
- 若存在 `.specs/<feature-name>/technical_design.md`，则其也已审核通过

编码前先用脚本做机器门禁（L3 要求 TD 已冻结，L2 跳过 TD）：

```bash
python scripts/flow-guard.py check <feature-name> implementation
```

返回 `HARD STOP` 时按其 `Next:` 提示回上游冻结对应产物，不得在前置未满足时开始编码。这条门禁的意义是：让"能不能开始写代码"由可校验的状态决定，而不是靠记忆判断。

## 4. 跨会话恢复

接手一个进行中的 feature（尤其 L3 跨会话续做）时，先跑一条命令定位进度，不要逐个重读 `.specs` 产物：

```bash
python scripts/flow-guard.py status
```

它报出当前 active feature、所在 `phase`、唯一下一站和该读的单个输入文件。据此只读必要文件再继续。

## 5. 必读文件

1. `CLAUDE.md` / `AGENTS.md`（同一份，项目使用入口）
2. `.specs/<feature-name>/state.yaml`（机器拥有的阶段状态，取代旧 `feature_info.md`）
3. `.specs/<feature-name>/brief.md`
4. `.specs/<feature-name>/acceptance.feature`
5. `.specs/<feature-name>/technical_design.md`（若存在）
6. 对应组件说明文档（若涉及，见 `docs/internals/`）
7. 涉及模块的真实代码

## 6. 输出位置

代码改动直接落到仓库中。

若需要改造报告，输出位置固定为：

```
.specs/<feature-name>/implementation_report.md
```

> `.specs/` 整目录 git-ignored；合并 PR 前应把有长期价值的内容沉淀到 PR 描述 / `docs/internals/` / `tests/acceptance/features/`，详见 [.specs/README.md](../../../.specs/README.md)。

改造报告结构遵循模板：`.ai/skills/implementation-execution/implementation_report.template.md`。

## 7. 何时必须写 implementation_report.md

以下任一情况成立时，必须写——否则偏差无处留痕：

1. 当前功能等级为 `L3`
2. 实际实现明显偏离 `technical_design.md`
3. 改动跨多个模块、多个中间件或多个关键链路
4. 存在需要向后续测试、交付、审查特别说明的实现差异
5. **编码阶段发生了任何 spec 回写**（回写了 `brief.md` 或 `acceptance.feature`，见第 8 节）

以下情况通常可不单独写：

- `L1` 小改动
- `L2` 且实现与技术方案基本一致
- 影响面小，且后续测试与 PR 描述足以说明交付结果

改造报告应重点记录：实际改了哪些模块/文件/接口/配置/数据/中间件、代码最终落在哪、与技术方案的差异及原因、遗留风险与后续事项。它**不应**重复完整需求背景、完整技术方案、完整测试执行结果。写报告时必须读取 `brief.md` + `acceptance.feature`、`technical_design.md`（若存在）、实际代码 diff、`state.yaml`。

## 8. 回流规则（spec 缺口不允许静默绕过）

编码阶段若发现 `brief.md` / `acceptance.feature` 与实际需求存在缺口（漏了场景、边界写错、约定与现实不符），**不允许直接改代码绕过、让 spec 与代码脱节**。这条规则给原本单向的链补上返回边——缺口 → 回写 spec → 留痕 → 收口提升，而不是悄悄改代码。必须：

1. **先回写 spec**：涉及业务规则 / 验收断言的，回写 `acceptance.feature`；涉及范围 / 流程 / 模块判断的，回写 `brief.md` 对应章节。回写后再继续编码。
2. **留痕**：在 `implementation_report.md` 的「Spec 偏差记录」章节记一条（原 spec 怎么写、实际怎么改、回写到哪）。任何一次 spec 回写都使本次实现落入第 7 节"必须写改造报告"。
3. **收口对齐**：回写过的 `acceptance.feature` 在 `branch-pr-workflow` 收口时用 `python scripts/promote_acceptance.py <feature>` 提升到 `tests/acceptance/features/`（搬运 + 校验 0 undefined step），保证追溯链不断。

## 9. 强制约束

- 不允许跳过已确认的需求边界私自扩展范围；若影响面扩大，触发复杂度升级建议并等待用户确认。
- 改造报告只记录实际落地内容与差异，不重复写需求与方案。
- 关键逻辑必须补注释，尤其是复杂判断、状态流转、组件衔接点和不直观的设计意图；注释简洁、解释性强，不写机械式逐行说明。
- 方案与实现出现明显偏差时，不能只改代码不留记录。

## 10. 实施步骤

### 步骤 1：按文档实现代码

- 以 `brief.md` + `acceptance.feature` 为边界
- 以 `technical_design.md` 为实现依据（L3）
- 先复用已有模块和组件，再考虑改 framework

### 步骤 2：在关键位置补注释

至少在复杂业务判断、关键状态流转、跨组件调用链、不易直观看懂的设计意图处补注释。

### 步骤 3：识别实现偏差

编码中持续判断：是否与技术文档一致、是否新增了未预期的模块改动、是否改变了原约定的某些边界。命中第 8 节缺口时按回流规则处理。

### 步骤 4：需要时补 implementation_report.md

若触发第 7 节条件，立即整理改动清单、差异说明、风险与后续事项。

## 11. 完成后的停点与衔接

本 skill 完成后，不应直接宣称交付完成。完成动作包括：

1. 代码实现完成
2. 必要时写好 `implementation_report.md`
3. 回写 `state.yaml`：写过改造报告则把 `artifacts.implementation.report_written` 置为 `true`；测试全绿后由收口段置 `verified: true`、`phase: done`
4. 进入测试与收口段：先 `run-all-tests` 跑全量回归，再 `code-review-and-quality` 过质量门禁，最终经 `branch-pr-workflow` 提 PR
