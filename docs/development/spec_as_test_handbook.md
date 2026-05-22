# Spec-as-Test 工作流使用手册

> 本文是日常开发的操作手册。设计原理和演进背景见 [spec_as_test_workflow.md](spec_as_test_workflow.md) 和 [workflow_evolution.md](workflow_evolution.md)；本文只回答"怎么用、注意什么"。

---

## 一、模式核心特点

### 1.1 三个产物，职责零重叠

| 产物 | 路径 | 形态 | 回答 | 受众 |
|---|---|---|---|---|
| `brief.md` | `docs/<需求名>/brief.md` | Markdown，5 章固定结构 | **为什么做** + 模块实现思路 | 开发者审阅迭代 |
| `acceptance.feature` | `docs/<需求名>/acceptance.feature` | Gherkin | **什么是做对了**（机器可验证） | 开发者审核 + LLM 实现 + pytest-bdd |
| `technical_design.md` | `docs/<需求名>/technical_design.md` | Markdown | **在哪里做、怎么做** | LLM 实现 + 开发者审核 |

**三者同目录、严格切割职责**。brief 不写验收规则，acceptance 不写背景动机，TD 不复述业务。

### 1.2 强制不模糊

`acceptance.feature` 的 `Then` 子句必须可断言：

- ✅ `Then task.status == FAILED`
- ✅ `Then MQ topic "parse-failed" 收到一条消息 task_id=T1`
- ❌ `Then 系统应正确处理`
- ❌ `Then 用户体验良好`

**写不出可断言的 `Then` 时，说明业务没想清楚，应停止生成 acceptance，回到 brief 阶段补充**。

### 1.3 可执行的验收契约

`acceptance.feature` 由 pytest-bdd 直接消费为测试用例。**所有 Scenario 通过 ≡ 代码满足验收**。代码-需求一致性从主观判断变为机器验证。

### 1.4 业务规则的追溯链

```
brief 中的核心模块
  ↓
acceptance.feature 中的 Scenario
  ↓
TD 方法级变更总表中的"对应 Scenario"列
  ↓
实现代码 + pytest-bdd 测试
```

每一层都能追到上一层。业务变更时，**先改 acceptance.feature，测试立刻指出哪些实现需要调整**。

### 1.5 brief 可迭代，acceptance 与 TD 也可迭代

每个产物都支持 Agent ↔ 开发者对话式收敛：

- 初稿生成后开发者审阅
- 有疑问 / 修改 → Agent 修订**对应章节**（不只追加在末尾）
- 反复直到开发者明确说"冻结" / "OK 这版可以"
- 冻结后才进入下一阶段

---

## 二、如何使用

### 2.1 完整流程

```
原始需求 (口头 / 文档 / 想法)
    │
    │ 触发：用户提需求、说"写个 brief"、"先分析一下"
    ▼
[Skill] brief-generator
    │
    │ 产出：docs/<需求名>/brief.md (5 章固定结构)
    │ 迭代：开发者审 → Agent 改 → 反复直到冻结
    ▼
[审核关 1] 业务方向 + 模块切割 + 风险是否合理
    │
    │ 触发：用户说"生成 acceptance"、"写测试场景"、"生成 Gherkin"
    ▼
[Skill] acceptance-generator
    │
    │ 产出：docs/<需求名>/acceptance.feature
    │ 迭代：开发者审 → 增删 Scenario → 反复直到冻结
    ▼
[审核关 2] Scenario 覆盖 + 断言精确度 + 边界完整性
    │
    │ 触发：用户说"生成技术方案"、"开始技术设计"
    ▼
[Skill] technical-design
    │
    │ 产出：docs/<需求名>/technical_design.md
    │ 迭代：开发者审 → Agent 改方案 → 反复直到冻结
    ▼
[审核关 3] 模块边界 + 方法级方案 + Scenario 全覆盖
    │
    ▼
[Skill] implementation-execution (LLM + 开发者)
    │
    │ 产出：代码 + pytest-bdd 测试
    │ 验证：所有 Scenario 测试通过
    ▼
完成
```

### 2.2 每个阶段的具体操作

#### 阶段 1：生成 brief

**输入**：原始需求（口头描述、初步想法、粗略框架）

**典型触发语**：
- "我们要做个 X 功能，先帮我写个 brief"
- "先分析一下这个需求"
- "搞清楚业务、看看影响哪些模块"

**期望产出**：5 章 brief.md
1. 需求摘要（做什么 / 为什么 / 不做什么）
2. 业务流程（Mermaid 主流程图 + 流程详解 + 异常分支）
3. 核心模块与实现思路（每个模块写位置、职责、复用、新增、决策）
4. 风险与不确定性（落到具体场景）
5. 待确认问题（迭代期保留，冻结时删除）

**冻结信号**：
- 所有阻塞性"待确认问题"已确认
- 开发者明确说"冻结" / "OK 这版可以" / "进入下一阶段"

**输出后告知开发者**："brief 已冻结，下一步可以生成 acceptance.feature。"

#### 阶段 2：生成 acceptance.feature

**输入**：冻结的 brief.md

**典型触发语**：
- "基于 brief 生成 acceptance"
- "写一下验收 Scenario"
- "生成 Gherkin"
- "生成测试场景"

**期望产出**：单个 `.feature` 文件，10-25 个 Scenario，按四类组织：
- 主流程（happy path）
- 异常处理（每条 brief 风险 → 至少一个 Scenario）
- 幂等与重试（可重试操作必有重复触发 Scenario）
- 边界条件（Outline + Examples 表）

**冻结信号**：
- 所有 brief 风险表中场景已转化为 Scenario
- 每个 `Then` 都是可断言的具体状态/输出
- 开发者明确说冻结

**输出后告知开发者**："acceptance 已冻结（共 N 个 Scenario），下一步可以生成 technical_design。"

#### 阶段 3：生成 technical_design

**输入**：冻结的 brief.md + acceptance.feature + 仓库代码

**典型触发语**：
- "生成技术方案"
- "开始技术设计"
- "生成 technical_design.md"

**期望产出**：12-14 章 technical_design.md，重点包括：
- 改动文件目录树（每个文件标注 `[新增]`/`[修改]`/`[删除]`/`[不改]`/`[待确认]`）
- 方法级变更总表（含"对应 Scenario"列）
- 逐方法实现设计（详细步骤、边界、调用关系、对应测试）
- Scenario 覆盖自检（逐条 Scenario → 承接方法 → 承接测试）

**冻结信号**：所有 Scenario 都有方法承接 + 测试承接，开发者审核通过。

#### 阶段 4：实现

**输入**：冻结的 brief + acceptance + TD

**操作**：
1. pytest-bdd 把 `.feature` 编译为测试用例骨架
2. LLM + 开发者协作实现 step 函数 + 业务代码
3. 跑测试，逐条 Scenario 从红变绿
4. 所有 Scenario 绿 = 代码满足验收

---

## 三、各阶段使用注意事项

### 3.1 brief 阶段

**应该做的**：

- ✅ **写到"另一个开发者能在脑子里跑通"为止**——不要为了短而省略关键流程
- ✅ **模块章节必须包含"位置 + 职责 + 实现思路 + 关键决策"四要素**，缺一项不合格
- ✅ **风险表落到具体场景**——"DB 查询超时 > 10 秒"而不是"注意稳定性"
- ✅ **修订要写回原章节**，不要只追加在文末
- ✅ **遇到模糊的地方就放进"待确认问题"**，宁可问也不要用模糊措辞掩盖

**不应该做的**：

- ❌ **不要写到代码层**——不写接口字段、表结构、类名、函数签名（这些留给 TD）
- ❌ **不要保留过程元数据**——状态元信息（草稿/迭代中）、推测/已确认/待确认分类、问答收敛说明、Agent 阅读指令**全部不进文档**
- ❌ **不要写营销话术**——"提升用户体验"、"优化性能"等无法验证的话
- ❌ **不要预先优化篇幅**——1 页够就 1 页，需要 8 页就 8 页，按内容必要性决定
- ❌ **不要复述原始需求**——保留必要信息即可，不要整段引用聊天记录

**典型陷阱**：

- 📌 **模块章节太浅**：只写"复用 X"，没写"复用 X 的什么能力、为什么"——读者无法判断方案是否合理
- 📌 **流程图细节过多**：把所有 if/else 都画进去，反而失去主线——只画主链路 + 关键异常
- 📌 **风险表泛泛而谈**：写"可能有并发问题"——必须落到具体场景"两个 worker 同时处理同一 task"
- 📌 **过早进入下一阶段**：还有阻塞性"待确认问题"就跳到 acceptance.feature → 后续必然返工

### 3.2 acceptance.feature 阶段

**应该做的**：

- ✅ **每个 Scenario 一个独立业务规则**——两条规则用两个 Scenario，不要塞一个
- ✅ **`Given` 写具体状态**：`Given task=T1 status=PARSING retry_count=2`，不是 `Given 一个任务`
- ✅ **`When` 写具体动作**：`When 解析器抛 TransientParseError`，不是 `When 出现异常`
- ✅ **`Then` 写可断言结果**：`Then task.status == FAILED`，不是 `Then 状态变化`
- ✅ **重复参数化用 `Scenario Outline + Examples`**：状态枚举、错误码、文件类型等
- ✅ **覆盖 brief 风险表中的每个场景**——逐条对照 brief §4

**不应该做的**：

- ❌ **不要写非功能性需求**——性能阈值、监控指标、部署细节 → 留在 brief 末尾或 NFR 段
- ❌ **不要写实现细节**——表名、类名、API 路径 → 留给 TD
- ❌ **不要复制粘贴 Scenario**——重复参数化必须用 Outline，否则维护成本爆炸
- ❌ **不要写跨 Scenario 依赖**——每个 Scenario 应独立可执行；用 `Background` 共享前置条件
- ❌ **Scenario 不要写技术语言**——用业务语言（"alice 上传文件"），不写 "test_upload_returns_200"

**典型陷阱**：

- 📌 **Then 不可断言**：写出 "应正确处理"、"按预期返回"——这是回到自然语言的失败信号，必须返工
- 📌 **Scenario 数量失控**：50 个 Scenario 多半是需求过大或重复，应拆 feature 或合并 Outline
- 📌 **遗漏边界**：只写 happy path，忘了 重复触发 / 超限 / 不支持类型 / 状态被抢先 等
- 📌 **断言里出现 UI 词汇**：`Then 页面显示成功提示`——这超出后端 Gherkin 的范畴，应转化为接口层断言

### 3.3 technical_design 阶段

**应该做的**：

- ✅ **必须扫真实代码再写方案**——目录树中的每个 `[修改]` 文件、总表中的每个 `[修改]` 方法都必须真实存在
- ✅ **每个 `[修改]` / `[新增]` 方法必须关联至少一条 Scenario**——填写"对应 Scenario"列
- ✅ **Scenario 覆盖自检必须做**——逐条 acceptance 中的 Scenario → 承接方法 → 承接测试，缺一项要在风险章节说明
- ✅ **方法级详情写到"另一个工程师能直接开始实现"**——步骤、入参、返回、事务边界、调用关系
- ✅ **`[不改]` 标注用来明确"不动"的公共契约**，避免实现阶段误改

**不应该做的**：

- ❌ **不要复述 brief 的业务背景**——直接读上游就行，不重复
- ❌ **不要写"已实现"口吻**——TD 是设计文档，不是实施报告
- ❌ **不要凭类名猜测**——通用框架经验不能代替读真实代码
- ❌ **不要只写抽象口号**——"增加校验"、"扩展逻辑"必须落到具体方法
- ❌ **不要省略不改的关键文件**——明确标注 `[不改]` 比留白安全

**典型陷阱**：

- 📌 **方法存在但 TD 写错位置**：扫代码不仔细就开写，方案与现状不符
- 📌 **新增方法没说放哪**：只写"新增 X 方法"，没说所属类/文件——实现阶段无依据
- 📌 **Scenario 没人承接**：acceptance 有 20 个 Scenario，TD 总表里只关联到 15 个——剩下 5 个无方法实现就上线，等于业务规则漏做
- 📌 **测试方案敷衍**：只写"加测试"，没写哪个 Scenario 对应哪个测试文件——后续无法验证全覆盖

### 3.4 实现阶段

**应该做的**：

- ✅ **先写 step 函数让测试能跑**，再写业务代码让测试通过
- ✅ **测试驱动开发**：先看哪条 Scenario 红，针对性写代码
- ✅ **step 函数尽量复用**——DB / MQ / Mock 等通用 step 应共享
- ✅ **遇到 Scenario 难实现 = 设计有问题**——回到 TD 修订，不要硬塞

**不应该做的**：

- ❌ **不要绕过测试直接发 PR**——所有 Scenario 必须绿
- ❌ **不要为了让测试通过修改 .feature**——除非确实是业务理解错了，且要回到 brief 流程
- ❌ **不要在测试中加非 Scenario 覆盖的额外断言**——保持测试是 acceptance 的精确反映

---

## 四、常见陷阱（跨阶段）

### 陷阱 1：跳过阶段

**症状**：拿到原始需求直接要求"生成技术方案"

**问题**：跳过 brief 和 acceptance，TD 失去业务依据，LLM 会脑补业务规则

**解决**：每个 skill 在 `when_to_use` 里强制校验上游产物存在；缺失则转回上游 skill。**作为开发者也要养成顺序意识**——快不等于跳步骤

### 陷阱 2：迭代时只追加在文末

**症状**：brief 第 5 次迭代，文档末尾出现"补充说明"、"修订记录"段落

**问题**：信息分散，读者看不到最新结论

**解决**：每次修订写回**原章节**，把已确认信息从"待确认问题"删除

### 陷阱 3：审核走过场

**症状**：reviewer 不打开 .feature 看，直接 LGTM

**问题**：失去了 acceptance.feature 最大的价值——多人交叉审业务规则

**解决**：建立约定——**审 acceptance.feature 必须逐条 Scenario 看**；遇到能想到反例的就提出来

### 陷阱 4：业务变更不改 .feature 改代码

**症状**：业务方说"重试上限从 3 改成 5"，开发者直接改代码常量

**问题**：测试还在断言 3，要么 .feature 失效要么测试失败

**解决**：**先改 .feature，让测试报错指引代码修改**——这才是 spec-as-test 的正确流向

### 陷阱 5：把非业务约束塞进 Gherkin

**症状**：`Then 接口响应时间 < 200ms`、`Then 监控面板显示成功率 > 99%`

**问题**：性能/监控应该有独立测试机制；塞进 acceptance 会让 BDD 测试变慢且脆弱

**解决**：业务规则用 Gherkin；性能用专门的 benchmark；监控用专门的 alert 配置

### 陷阱 6：Skill 之间状态判断混乱

**症状**：brief 还没冻结，开发者要求"生成 acceptance"，skill 同意了

**问题**：基于未冻结 brief 生成的 acceptance 会随 brief 变化频繁返工

**解决**：依赖 `feature_info.md` 记录状态；skill 检测到 brief 未冻结时**必须转回 brief-generator**

---

## 五、操作 Checklist

### 5.1 写 brief 时

- [ ] 5 章结构齐全？
- [ ] 每个模块章节包含位置 + 职责 + 实现思路 + 关键决策？
- [ ] 流程图覆盖主链路 + 关键异常分支？
- [ ] 风险表落到具体场景？
- [ ] 没有任何模糊措辞（"按需"、"适当"、"完善"、"相关逻辑"）？
- [ ] 没有代码层细节（接口字段、表结构、类名）？
- [ ] 没有过程元数据（状态、推测/已确认分类、问答记录）？

### 5.2 写 acceptance.feature 时

- [ ] Scenario 数量在 10-25 之间？
- [ ] 每个 `Then` 都可断言？
- [ ] 主流程 / 异常 / 幂等 / 边界四类都有覆盖？
- [ ] brief 风险表中的每个场景都有 Scenario 对应？
- [ ] 重复参数化用了 `Scenario Outline + Examples`？
- [ ] 没有 UI / 性能 / 监控相关断言？
- [ ] 没有技术词汇（表名、类名、接口路径）？

### 5.3 写 technical_design 时

- [ ] 改动文件目录树完整且每文件有动作标注？
- [ ] 方法级变更总表中每个方法都填了"对应 Scenario"？
- [ ] Scenario 覆盖自检中每条 Scenario 都有承接？
- [ ] 每个 `[修改]` 方法在代码中真实存在？
- [ ] 每个 `[新增]` 方法所属类已说明（新增或现有）？
- [ ] 关键技术选型有理由说明？
- [ ] 测试方案明确（哪个测试覆盖哪些 Scenario）？

### 5.4 实现完成时

- [ ] 所有 Scenario 测试通过？
- [ ] 没有跳过的测试（@skip）？
- [ ] step 函数复用合理（没有重新发明轮子）？
- [ ] PR 同时包含 brief + acceptance + TD + 代码 + 测试？

---

## 六、FAQ

**Q1：brief 写到一半发现需求太大怎么办？**

A：拆分。一个 brief 写到 10 页以上多半是范围失控。和需求方讨论拆成 N 个独立需求，每个独立走流程。

**Q2：acceptance.feature 写到一半发现某条规则没法断言？**

A：停止，回到 brief 补充。这正是 spec-as-test 的价值——它在写代码前就暴露了"业务没想清楚"。

**Q3：TD 写完发现某个 Scenario 没有方法可以承接？**

A：两种可能——（a）Scenario 本身不合理（写错了或太抽象），回到 acceptance 修订；（b）方案设计漏了模块，回到 TD 补充。无论哪种，**不要硬上线**。

**Q4：实现阶段发现测试很难写怎么办？**

A：通常意味着 step 函数库不完善，或者 TD 设计的方法边界不合理（依赖太杂、副作用太多）。先补 step，再看是否需要改 TD。

**Q5：业务方提了新需求和当前 brief 冲突？**

A：判断是补充还是变更：
- 补充 → 回到 brief 阶段，继续迭代
- 变更 → 评估是否值得返工，必要时整个流程重来（沉默成本比错误上线低）

**Q6：旧需求已经有 requirement.md（旧 PRD），还要迁移吗？**

A：不强求历史回填。新需求一律走新流程；老需求改动时按需创建 acceptance.feature 补齐验收（聚焦本次改动相关的 Scenario 即可，不必覆盖全模块）。

**Q7：审核找不出问题怎么办？**

A：审 acceptance.feature 时主动找反例——"如果用户同时上传两次会怎样？""如果上游消息丢失了呢？""如果状态推进失败呢？"。找不到反例不代表没有，团队应在 retro 时回顾"上线后发现的 bug 在 acceptance 阶段能不能更早暴露"。

---

## 七、术语对照

| 旧术语 | 新术语 |
|---|---|
| 需求预分析（pre_requirement_analysis） | brief |
| PRD / requirement.md | acceptance.feature |
| 技术方案 | technical_design（角色不变，输入源变了） |
| Agent/LLM 阅读说明 | （废弃，不再出现在文档里） |
| 待确认问题（永久章节） | 待确认问题（仅迭代期，冻结后删除） |
| 面向 TD 的输入清单 | （废弃，TD 直接读 brief + .feature） |

---

## 八、相关文档

- 工作流设计原理：[spec_as_test_workflow.md](spec_as_test_workflow.md)
- 三次迭代演进记录：[workflow_evolution.md](workflow_evolution.md)
- Brief 生成 skill：[.ai/skills/brief-generator/SKILL.md](../../.ai/skills/brief-generator/SKILL.md)
- Acceptance 生成 skill：[.ai/skills/acceptance-generator/SKILL.md](../../.ai/skills/acceptance-generator/SKILL.md)
- Acceptance 样例：[.ai/skills/acceptance-generator/acceptance.template.feature](../../.ai/skills/acceptance-generator/acceptance.template.feature)
- TD 生成 skill：[.ai/skills/technical-design/SKILL.md](../../.ai/skills/technical-design/SKILL.md)
- TD 模板：[.ai/skills/technical-design/technical_design.template.md](../../.ai/skills/technical-design/technical_design.template.md)
