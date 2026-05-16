# 基于 Spec-as-Test 的 AI 协作开发工作流

> 适用对象：没有专职产品经理、开发者兼任产品角色、主要使用 LLM 辅助代码生成的工程团队。
>
> 本文档是新版需求-验收-技术设计三段式工作流的设计说明与使用指南。

---

## 一、为什么要重构工作流

### 1.1 现状的三个本质问题

**问题 1：三份文档信息重叠严重，维护成本随时间发散。**

| 主题 | 旧版预分析 | 旧版 PRD | TD |
|---|:---:|:---:|:---:|
| 主流程 + Mermaid | ✓ | ✓ | ✓ |
| 状态变化 | ✓ | ✓ | ✓ |
| 业务对象 | 隐含 | ✓ | ✓ |
| 系统协作 / 中间件 | ✓ | ✓ | ✓ |
| 风险 | ✓ | ✓ | ✓ |

业务一变，三处都要改；漏改一处，文档间就漂移。

**问题 2：PRD 的边界尴尬。**

PRD 既不是纯业务文档（已写中间件名、数据可见性、"给 TD 的输入清单"），也不是技术文档（不让写 API 路径、表名）。位置在"业务"和"技术"之间，两边都跨界一点。

**问题 3：自然语言允许模糊，LLM 会脑补，代码偏离预期。**

这是最严重的问题。PRD 里可以写："用户上传 PDF 后，系统应正确处理重复上传场景"——读起来通顺，但留下大量未定义空间。LLM 拿到这条需求会自行决定，开发者审核时不一定能发现遗漏。**代码不符合预期，根因往往在这里。**

---

## 二、新工作流：brief + acceptance.feature + TD

### 2.1 一图概览

```
┌─────────────────────────────────────────────────────────────┐
│  原始需求                                                    │
│      ▼                                                       │
│  ┌──────────────┐                                            │
│  │  brief.md    │  ← 给开发者审阅迭代                          │
│  └──────┬───────┘    "为什么做 + 上下文 + 模块实现思路"        │
│         ▼                                                    │
│  ┌────────────────────┐                                      │
│  │ acceptance.feature │ ← Gherkin 验收契约                    │
│  └──────┬─────────────┘   "什么是做对了"                       │
│         ▼                                                    │
│  ┌────────────────────┐                                      │
│  │ technical_design.md│ ← LLM 基于 brief + .feature + 代码生成 │
│  └──────┬─────────────┘   "在哪里做 + 怎么做"                  │
│         ▼                                                    │
│  ┌────────────────────┐                                      │
│  │  Code + Tests      │ ← pytest-bdd 直接消费 .feature         │
│  └────────────────────┘   测试通过 ≡ 满足验收                  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 三个产物的职责切割

| 产物 | 唯一职责 | 形态 | 受众 |
|---|---|---|---|
| **brief.md** | 回答**为什么做** + 涉及哪些模块、各模块实现思路 | Markdown | 开发者审阅迭代 |
| **acceptance.feature** | 回答**什么是做对了** | Gherkin | 开发者审核 + LLM 实现 + pytest-bdd 执行 |
| **technical_design.md** | 回答**在哪里做、怎么做** | Markdown | LLM 实现 + 开发者审核 |

**关键设计原则**：三者职责零重叠。brief 不写验收规则，.feature 不写背景动机，TD 不复述业务。

---

## 三、三个产物的详细说明

### 3.1 brief.md

**定位**：让任何团队成员读完后能在脑子里"跑通"这次需求——知道做什么、为什么、涉及哪些模块、各模块如何实现。

**篇幅原则**：不设硬性上限。简单需求 1 页够，复杂需求 5-8 页合理。**篇幅由内容必要性决定，不由模板预算决定**。

**模板（5 章固定）**：

```markdown
# [需求名] Brief

## 1. 需求摘要
- 做什么 / 为什么做 / 本次不做

## 2. 业务流程
### 2.1 主流程图（Mermaid）
### 2.2 流程详解（含异常分支）

## 3. 核心模块与实现思路
每个模块独立一段：
- 位置（在项目哪个目录/层）
- 职责
- 实现思路（复用什么、新增什么、与上下游如何串联）
- 关键决策（选型/取舍及理由）
**写到"另一个开发者能在脑子里跑通模块工作方式"为止，不到代码层**

## 4. 风险与不确定性
表格，每条落到具体场景

## 5. 待确认问题（仅迭代期，收敛后删除）
```

**核心特性：可迭代**。Agent 首次生成后，开发者审阅、提出疑问，Agent 把修订**写回原章节**（不是追加在末尾），反复直到开发者明确说"冻结"。

详见 [.ai/skills/pre-prd-requirement-analysis/SKILL.md](../../.ai/skills/pre-prd-requirement-analysis/SKILL.md)。

### 3.2 acceptance.feature

**定位**：用 Gherkin 把所有业务规则写成可机器验证的断言。

**关键特性**：

1. **强制不模糊**：`Then` 必须可断言。写不出 `Then` → 业务没想清楚，回到 brief。
2. **强制对齐颗粒度**：每个 Scenario 一个独立规则；重复参数化用 `Scenario Outline + Examples`。
3. **强制覆盖边界**：主流程 / 异常 / 幂等 / 边界条件每类至少一条。
4. **强制可执行**：pytest-bdd 直接消费 `.feature`，每条 Scenario 编译为一个测试用例。

**示例**：

```gherkin
Scenario: 重复上传同一文件返回已有任务
  Given 已存在 task=T1 hash=abc123 status=PARSED
  When alice 再次提交 PDF hash=abc123
  Then 接口返回 task_id=T1
  And 不创建新任务
  And 不发送 MQ 消息
```

**约束**：

- 单 feature 文件目标 10-25 个 Scenario；超过 30 个考虑拆分或合并 Outline。
- 非功能性需求（性能、监控）不进 .feature。
- UI/UX 视觉细节不属于 Gherkin。

详见 [.ai/skills/prd-generator/SKILL.md](../../.ai/skills/prd-generator/SKILL.md) 和 [.ai/skills/prd-generator/acceptance.template.feature](../../.ai/skills/prd-generator/acceptance.template.feature)。

### 3.3 technical_design.md

**与旧版差异**：

- 输入源从 `pre_requirement_analysis.md + requirement.md` 改为 `brief.md + acceptance.feature + 代码扫描`。
- 删除"输入依据映射"中对旧 PRD 的引用，改为映射 brief + .feature。
- **新增**：方法级变更总表中每个方法必须关联到至少一条 Scenario（业务规则 → 验收 → 方法 → 测试的追溯链）。
- **新增**：测试方案章节有 "Scenario 覆盖自检"——逐条 .feature Scenario 检查是否都有方法承接 + 测试承接。
- 主动吸收原 PRD 中砍掉的技术内容（数据可见性、系统协作、中间件边界）。

详见 [.ai/skills/technical-design/SKILL.md](../../.ai/skills/technical-design/SKILL.md)。

---

## 四、完整开发生命周期

### Day 1：写 brief.md

开发者收到需求，用 brief generator 生成初稿（~30 分钟）。提交 PR 请同事 review。

**Review 目标**：方向对不对、模块切割合不合理、风险列全没。5-10 分钟决断。

如果有疑问 → 和 Agent 对话迭代修订 → 反复直到冻结。

### Day 1-2：写 acceptance.feature

brief 冻结后，用 acceptance generator 生成 Gherkin。

**核心价值**：写到第 N 个 Scenario 时，会发现自己根本没想清楚某条规则——此时**回头改 brief**，不要硬写。这种"卡住"正是它的价值。

最终产出覆盖主流程 / 异常 / 边界 / 幂等的 10-25 个 Scenario。同事 review 10 分钟即可决断。

### Day 2-3：LLM 生成 TD

输入 brief + .feature + 代码扫描，TD 生成器输出技术方案。开发者审核技术选型、模块边界、复用充分性。

### Day 3-7：实现

LLM + 开发者协作实现。pytest-bdd 把 .feature 编译成测试用例骨架。

**所有 Scenario 绿 ≡ 代码满足验收**。

### Day 7：合并

合并 PR 检查清单：

- [ ] brief.md / acceptance.feature / technical_design.md / 实现代码 同步提交
- [ ] 所有 Scenario 都有对应 step 实现
- [ ] pytest 全绿
- [ ] 代码 review 通过

---

## 五、与旧方案的对比

| 维度 | 旧方案 | 新方案 |
|---|---|---|
| 文档数量 | 3 (pre_analysis + PRD + TD) | 3 (brief + .feature + TD) |
| 总篇幅 | ~30 页 markdown | ~10 页 markdown + Gherkin |
| 信息重叠 | 高 | 零 |
| 业务约束载体 | 自然语言（允许模糊） | Gherkin 断言（强制精确） |
| 业务审核单位 | 14 章 markdown | 20 条 Scenario |
| 业务审核耗时 | 30-60 分钟 | 10-15 分钟 |
| LLM 脑补空间 | 大 | 极小 |
| "代码不符合预期"发现时机 | 上线后 / code review | 写 .feature 时 / 测试运行时 |
| 业务变更同步成本 | 改 3 份 markdown | 改 .feature，测试自动指出影响 |
| 是否强制写代码前定义业务 | ❌ | ✅ |
| 是否强制覆盖边界场景 | ❌ | ✅（Outline） |
| 文档-代码一致性保障 | 人工 | 测试 |

---

## 六、设计原则

**原则 1：每个产物职责单一。**

brief 只回答 why。.feature 只回答 what-is-correct。TD 只回答 where-and-how。任何一个产物想"顺便覆盖"另一个的职责时，应立刻警觉。

**原则 2：人审视野不超过一屏。**

每个 Scenario 一屏。TD 按模块拆段，单段不超过一屏。审核单位足够小，才能做到"快速、准确、可拒绝"。

**原则 3：机器能验证的，绝不交给人。**

业务约束 → 测试。代码-文档一致性 → CI。"应该处理 X" → 写不出 Scenario 就说明业务没想清楚。

---

## 七、适用边界

### 7.1 强适用

- 后端服务、API、异步任务、状态机、数据处理
- 业务规则多、边界条件多、需要严格幂等/一致性
- 团队主要由开发者构成、用 LLM 辅助编码
- 已有 pytest 基础设施

### 7.2 弱适用 / 不适用

- 纯 UI / UX 项目（Gherkin 难表达视觉细节）
- 数据探索、原型验证（业务规则尚未稳定）
- 一次性脚本、运维工具（投入产出不划算）

---

## 八、迁移路径

### 阶段 1：试点（1-2 周）

挑一个新功能走完整流程，retro 团队感受。

### 阶段 2：基础设施（1 周）

- pytest-bdd 集成进 CI
- step 函数库（DB / MQ / Mock fixture 复用）
- `.feature` 文件目录约定（如 `tests/acceptance/<module>/<feature>.feature`）

### 阶段 3：全面铺开

新需求一律走新流程；老模块按需补 .feature，不强求历史回填。

---

## 九、常见疑问

**Q：Gherkin 学习成本高吗？**

A：对会写代码的人来说，Given/When/Then 就是 setup/action/assert，一小时上手。

**Q：会不会出现"为了写 Scenario 而写 Scenario"？**

A：约定单 feature ≤25 个 Scenario、用 Outline 合并重复，能控制住。Retro 时多指出几次"这个 Scenario 没价值"，团队会快速校准。

**Q：复杂需求 1 页 brief 写不下怎么办？**

A：brief 不限页数，按需要详尽展开。但如果一个 brief 写到 10 页以上，多半是需求范围过大，应拆分。

**Q：和 ADR / DDD 等实践冲突吗？**

A：互补。ADR 记录架构决策（属于 TD 范畴），DDD 强调领域建模（在 brief 的"核心模块"部分体现）。Gherkin 解决"业务规则可执行化"，正交于这些实践。

---

## 十、相关文件

- 工作流演进背景：[workflow_evolution.md](workflow_evolution.md)
- Brief 生成 skill：[.ai/skills/pre-prd-requirement-analysis/SKILL.md](../../.ai/skills/pre-prd-requirement-analysis/SKILL.md)
- Acceptance 生成 skill：[.ai/skills/prd-generator/SKILL.md](../../.ai/skills/prd-generator/SKILL.md)
- Acceptance 样例：[.ai/skills/prd-generator/acceptance.template.feature](../../.ai/skills/prd-generator/acceptance.template.feature)
- TD 生成 skill：[.ai/skills/technical-design/SKILL.md](../../.ai/skills/technical-design/SKILL.md)
- TD 模板：[.ai/skills/technical-design/technical_design.template.md](../../.ai/skills/technical-design/technical_design.template.md)
