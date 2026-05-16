---
name: prd-generator
description: 仅当 brief.md 已由开发者确认冻结后，基于 brief.md 生成 Gherkin 格式的 acceptance.feature 验收契约，描述每条业务规则在"Given/When/Then"下的可机器验证断言；该文件后续由 pytest-bdd 等框架直接消费为自动化测试。本 skill 不输出散文 PRD（旧版 requirement.md 已废弃）。若用户尚未提供冻结的 brief.md，禁止使用本 skill。
when_to_use: "仅当用户已有冻结的 docs/<需求名>/brief.md，并明确要求'生成 acceptance / 生成 Gherkin / 生成验收契约 / 生成测试场景 / 生成 acceptance.feature'时激活。若 brief.md 尚未冻结、待确认问题尚未收敛，必须先转回 pre-prd-requirement-analysis。若用户已有 brief.md + acceptance.feature 并要求技术方案，转 technical-design。"
---

# Acceptance Feature Generator

## 1. 定位

本 skill 把已冻结的 `brief.md` 转化为 Gherkin 格式的 `acceptance.feature` 文件。

`acceptance.feature` 是验收契约：每条业务规则写成 `Given / When / Then` 断言，由 pytest-bdd 等框架直接编译为自动化测试。它同时是：

- **审核单位**：开发者审一条 Scenario = 审一道是非题，比审散文 PRD 快 5-10 倍
- **LLM 实现输入**：消除自然语言模糊，LLM 偏离需求会被测试直接打脸
- **可执行规约**：测试全绿 ≡ 代码满足验收

本 skill **不输出** markdown 散文 PRD。原 `requirement.md` 模板已废弃。

## 2. 触发边界

### 2.1 必须满足的前提

1. `docs/<需求名>/brief.md` 真实存在
2. brief 已由开发者确认冻结（无"待确认问题"章节，或仅剩非阻塞项且用户确认保留）
3. 用户明确要求生成 acceptance / Gherkin / 验收契约 / 测试场景

### 2.2 禁止使用场景

- brief.md 不存在 → 转 `pre-prd-requirement-analysis`
- brief.md 仍有阻塞性"待确认问题" → 转 `pre-prd-requirement-analysis` 继续收敛
- 用户要求技术方案 / 接口设计 / 代码 → 转 `technical-design` 或 `implementation-execution`
- 用户只是要改本 skill 模板

## 3. 必读文件

执行前必读：

1. `docs/<需求名>/brief.md`（输入源）
2. 同目录 `feature_info.md`（若已存在）
3. `.ai/skills/prd-generator/acceptance.template.feature`（参考样例）

按需补读：

4. 同业务域历史模块的 `acceptance.feature`（学习现有命名、术语、step 约定）
5. 项目已有的 step 实现库（`tests/acceptance/steps/` 或类似目录），避免重复实现 step

## 4. 输出位置

固定为：

```
docs/<需求名>/acceptance.feature
```

要求：

- 与 brief.md 同目录
- 文件名固定为 `acceptance.feature`
- 同时更新同目录 `feature_info.md`：状态改为 `acceptance 待审核`，列出当前 Scenario 数量、覆盖的主流程 / 异常 / 边界类别

若目录已有旧版 `acceptance.feature`：

- 先读旧版
- 判断是增量补充、整体重写还是局部修订
- 不允许无说明地覆盖关键 Scenario

## 5. 输出原则

### 5.1 Gherkin 写作规则

- 每个 `Feature:` 文件对应一次需求；多需求拆多个 `.feature` 文件
- `Background:` 写公共前置条件（如"用户已登录"），不要重复写在每个 Scenario 里
- `Scenario:` 每个对应一条业务规则，**正交**——两个 Scenario 不应该是同一规则的不同参数（用 `Scenario Outline + Examples` 表达）
- `Given` 写前置状态（数据、配置、外部系统状态）
- `When` 写触发动作（用户操作、消息到达、定时触发）
- `Then` 写**可断言**的结果（具体的状态值、数据库行、消息发出、错误码）
- `And / But` 用于扩展任一段

### 5.2 强制不模糊

`Then` 之后必须是可机器验证的断言：

- ✅ `Then task.status == FAILED`
- ✅ `Then 接口返回 400 错误码 UNSUPPORTED_TYPE`
- ✅ `Then MQ topic "parse-task" 收到一条消息 task_id=T1`
- ❌ `Then 系统应正确处理`（不可验证）
- ❌ `Then 用户体验良好`（不可验证）
- ❌ `Then 适当返回错误`（模糊）

写不出可断言的 `Then` 时，说明 brief 阶段未把规则定义清楚——**停止生成 acceptance，回到 brief 阶段补充**。

### 5.3 颗粒度控制

- 单 `.feature` 文件目标 10-25 个 Scenario
- 超过 30 个考虑：是否需求范围过大？是否可拆分？
- 重复参数化场景必须用 `Scenario Outline + Examples`，不允许复制粘贴
- Scenario 命名用业务语言，不写 "test_xxx"

### 5.4 必须覆盖的场景类型

针对每个 brief 中提到的业务流程或风险，至少覆盖：

- **主流程 happy path**：最常见的成功路径
- **异常路径**：每个 brief 风险表中的具体场景至少一个 Scenario
- **边界条件**：边界值、空值、超限、并发
- **幂等与重试**：可重试操作必须有重复触发 Scenario
- **状态转换**：状态机的每条合法 / 非法转换

### 5.5 不进入 Gherkin 的内容

- 非功能性需求（性能阈值、监控指标、部署细节）→ 留在 brief 末尾或独立 NFR 段
- UI / UX 视觉细节 → 不属于业务规则
- 实现细节（用什么数据库、什么算法）→ 留给 technical-design
- 技术选型理由 → 留给 technical-design

## 6. 工作流程

### 步骤 1：校验输入

确认：

- `docs/<需求名>/brief.md` 存在
- brief 中无阻塞性"待确认问题"
- 用户已明确要求生成 acceptance

任一缺失，停止并说明，不允许"基于聊天记忆"凭空生成。

### 步骤 2：从 brief 抽取业务规则

逐章扫描 brief：

- 第 2 章业务流程 → 提取主流程 / 异常流程 Scenario
- 第 3 章核心模块与实现思路 → 提取模块间协作 Scenario（消息、调用、状态推进）
- 第 4 章风险 → 每条风险转化为至少一个 Scenario
- 业务对象、状态、字段 → 沉淀到 `Background` 或 Scenario 前置条件

### 步骤 3：生成 Scenario 草稿

按规则分组：

```gherkin
Feature: <需求名>

  Background:
    Given <公共前置条件>

  # ==== 主流程 ====
  Scenario: ...

  # ==== 异常处理 ====
  Scenario: ...

  # ==== 幂等与重试 ====
  Scenario: ...

  # ==== 边界条件 ====
  Scenario Outline: ...
    Examples:
      | ... |
```

### 步骤 4：自检

生成后逐条 Scenario 检查：

- 每个 `Then` 是否可机器验证
- 是否所有规则都用 `Given / When / Then` 写出，没有遗留为散文
- 是否覆盖 brief 风险表中所有具体场景
- Scenario 之间是否正交，没有重复
- 单文件 Scenario 数是否在 10-25 之间

任一项不达标，修订后再展示给用户。

### 步骤 5：迭代收敛

展示给开发者后进入审核循环：

1. 默认让用户审核全文，问"是否还有遗漏的边界 / 异常 / 规则"
2. 用户反馈后：
   - **读取当前 acceptance.feature**（不要凭记忆）
   - 增删 / 修改对应 Scenario
   - 不在文件中保留"修订记录"等元数据
3. 用户明确说"OK 这版可以" / "冻结" / "进入下一阶段"后冻结

### 步骤 6：冻结

冻结时：

1. 更新 `feature_info.md`：状态改为 `acceptance 已冻结`，记录 Scenario 总数 + 分类计数
2. 告知用户下一步：进入 `technical-design`

## 7. 输出质量标准

合格的 `acceptance.feature` 必须做到：

- 另一个开发者读完，能理解所有业务规则
- pytest-bdd 能加载并生成测试用例骨架（语法正确）
- 每个 `Then` 都是可断言的具体状态 / 输出
- 覆盖 brief 风险表中的所有具体场景
- 没有"应正确处理"、"按需"、"适当"等模糊措辞
- Scenario 之间正交，参数化场景用 Outline

不合格的信号：

- 出现散文段落（应该用 Gherkin 表达）
- `Then` 是抽象描述而非具体断言
- Scenario 数量 < 8（多半是覆盖不全）或 > 30（多半是需求过大或重复）
- 引入了技术细节（表名、类名、接口路径）

## 8. 与其他 skill 的衔接

- **进入前**：必须有冻结的 `brief.md`；缺失或未冻结 → 转 `pre-prd-requirement-analysis`
- **冻结后**：转 `technical-design`，TD 直接读 `brief.md + acceptance.feature + 代码`
- **不允许**：未冻结 brief 时生成 acceptance；输出散文 PRD 或 markdown 文档；在 acceptance 中写技术实现细节
