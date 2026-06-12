---
name: technical-design
description: 在用户明确要求生成技术方案、技术实现文档或 technical_design.md 时激活；输入源为同目录下的 brief.md 和 acceptance.feature，必须先校验二者存在且 acceptance.feature 已冻结，然后在同目录产出 technical_design.md，并严格基于真实代码、组件文档和公共契约进行设计。原 requirement.md (散文 PRD) 已废弃，不再作为输入。
when_to_use: 当用户明确要求"生成技术方案 / 生成技术实现文档 / 生成 technical_design.md / 开始技术设计"，且同目录已存在冻结的 brief.md + acceptance.feature 时激活。若任一上游产物缺失，必须先转回对应 skill；不允许仅凭聊天记忆生成技术文档。
---

# Technical Design

## 1. 定位

本 skill 把已确认的 `brief.md` 和 `acceptance.feature` 转化为可落地的 `technical_design.md`。

它主要回答：

- 要改 / 新增 / 删除哪些文件
- 复用哪些现有能力
- API、数据、缓存、消息、对象存储怎么设计
- 每个要修改的方法如何改、为什么这样改、需要验证什么
- 风险、兼容性、测试策略

它不负责：

- 写业务代码（→ `implementation-execution`）
- 提交改造结果
- 输出测试执行结论

## 2. 输入源（重要变更）

**新版工作流的输入源**：

1. `.specs/<feature-name>/brief.md`（业务理解 + **模块影响面判断 + 概念数据模型**）
2. `.specs/<feature-name>/acceptance.feature`（Gherkin 验收契约，机器可读的业务规则）
3. 仓库真实代码、组件文档、公共契约

**已废弃的输入源**：

- ~~`requirement.md`（旧版散文 PRD）~~ ：已废弃，新流程不再生成此文件。若发现历史目录仍存在 `requirement.md`，应在 `technical_design.md` 开头注明"基于历史 requirement.md 而非 acceptance.feature 生成"，并尽量补齐 Gherkin。

`acceptance.feature` 是技术方案最权威的"做对了"标准——TD 中的每个方法级实现都应该能对应到一条或多条 Scenario。

**brief 是"假设"，不是方案**：brief 第 3 章给出的是模块影响面判断与**概念数据模型**（关键实体 / 字段 / 关系），作为 TD 的输入假设。TD 的职责是**逐条确认或修正该假设**、而非从零重推：

- 对每条模块判断标注**沿用 / 修正**，修正的写明哪里改了、为什么。
- brief 的概念数据模型由 TD 落成**物理 schema**（类型、长度、索引、约束、迁移），对照 `docs/api/schemas/mysql.md` 与机器强制同步规则。
- 这条"与 brief 判断的差异"既避免重复设计，也是设计偏离最初理解的审计线（与 implementation-execution 的"回流规则"同一 philosophy）。

## 3. 使用前提

只有满足以下条件时才允许使用本 skill：

1. `.specs/<feature-name>/brief.md` 存在且已冻结
2. `.specs/<feature-name>/acceptance.feature` 存在且已冻结
3. 用户明确要求生成技术文档、技术方案或 `technical_design.md`

若缺失任一上游产物：

- 缺 brief.md → 转 `brief-generator`
- 缺 acceptance.feature → 转 `acceptance-generator`

不允许基于聊天记忆直接生成技术文档。

## 4. 必读文件

执行本 skill 时至少读取：

1. `AGENTS.md`
2. `.specs/<feature-name>/brief.md`
3. `.specs/<feature-name>/acceptance.feature`
4. `.specs/<feature-name>/state.yaml`（机器拥有的阶段状态，取代旧 `feature_info.md`）
5. `.ai/skills/technical-design/technical_design.template.md`
6. 公共契约文档：`docs/api/**`、`docs/internals/naming_conventions.md`、`docs/internals/mq.md`（按改动涉及面选读）

按需补读：

7. 对应组件说明文档（Redis / OSS / MQ / Qdrant 等）
8. 同业务域历史模块的 `technical_design.md`
9. 同业务域历史模块的 `implementation_report.md`
10. 相关真实代码

组件文档强制规则（路径以本项目真实文档为准）：

- 涉及文件 / 对象存储、object key → 读 `docs/internals/object_storage.md`
- 涉及异步消息 / topic / consumer → 读 `docs/internals/mq.md`、`docs/api/mq_contracts.md`
- 涉及向量检索 → 读 `docs/api/schemas/qdrant.md`、`docs/internals/vectorization.md`
- 涉及 ES / BM25 检索 → 读 `docs/api/schemas/elasticsearch.md`
- 涉及解析流水线 → 读 `docs/internals/parse_task_pipeline.md`
- 本项目当前不使用 Redis 公共组件；如确需引入缓存，先在 brief / TD 中说明并补对应文档

**只要方案中准备"使用、修改、扩展、复用"某组件或模块，就必须先读对应代码或文档**。不允许凭类名猜测、历史印象或通用框架经验直接写方案。

## 5. 输出位置

固定为：

```
.specs/<feature-name>/technical_design.md
```

要求：

- 与 brief.md / acceptance.feature 同目录（`.specs/` 整目录 git-ignored，feature 临时工作目录；见 [.specs/README.md](../../../.specs/README.md)）
- 文件名固定
- 结构遵循 `.ai/skills/technical-design/technical_design.template.md`
- 若已有旧版 TD：先读，判断修订 / 覆盖 / 增量，不允许无说明地重写关键技术结论

同时回写 `state.yaml`：`phase` 保持 `technical_design`；冻结时把 `artifacts.technical_design.frozen` 置为 `true`。

## 6. 输出内容要求

`technical_design.md` 结构遵循模板。最低章节：

1. 文档修订记录
2. 设计目标与范围
3. 改动范围（含**改动文件目录树**）
4. 当前系统分析
5. 总体方案设计
6. API / MQ / 数据设计
7. **方法级实现方案**（含**方法级变更总表** + 逐方法详情）
8. 组件与集成
9. 异常处理与降级
10. 测试方案（含**方法级测试映射**：每个方法对应到哪些 Scenario）
11. 发布与回滚
12. 风险与待确认问题

### 6.1 改动文件目录树（必有）

从仓库根或模块根开始展示。每个文件 / 目录后标注动作：

- `[新增]` / `[修改]` / `[删除]` / `[测试新增]` / `[测试修改]` / `[不改]` / `[待确认]`
- `[修改]` / `[新增]` 必须用一句话说明改动目的
- `[不改]` 用于明确"不动"的公共契约文件，避免实现阶段误改
- `[待确认]` 必须在"风险与待确认问题"章节解释

只列本次涉及的文件，不粘贴完整项目树。

### 6.2 方法级变更总表（必有）

| 文件 | 类 | 方法 | 动作 | 输入 | 输出 | 改动目的 | 对应 Scenario |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |

每个 `[修改]` / `[新增]` 方法的"对应 Scenario"必须填写至少一条来自 `acceptance.feature` 的 Scenario 名称。**这是新流程的核心追溯链**：业务规则 → 验收 Scenario → 方法实现 → 测试。

### 6.3 逐方法详情

对每个 `[修改]` / `[新增]` 方法说明：

- 当前行为或现有缺口
- 修改后的职责
- 关键入参和返回值
- 详细处理步骤
- 事务 / 异常 / 幂等边界
- 对其他方法的调用关系
- 对应测试用例（直接引用 acceptance.feature 中的 Scenario 名）

如果某个文件标为 `[修改]` 但没有方法级方案，TD 不合格。
如果某方法需要新增参数或返回值，必须写明调用方同步改动。

### 6.4 测试方案

新增强制规则：

- **方法级测试映射**：列出每个方法对应哪些 Scenario，确认所有 Scenario 都有方法承接
- **覆盖完整性自检**：acceptance.feature 中的每个 Scenario 是否都能由本次实现验证？是否有 Scenario 没人承接？
- **回归命令**：明确执行 `pytest tests/acceptance/<feature>.feature` 等具体命令

## 7. 工作步骤

### 步骤 1：校验输入

先用脚本做机器门禁：

```bash
python scripts/flow-guard.py check <feature-name> technical_design
```

该命令校验 `state.yaml` 合法且 `brief`、`acceptance` 均已冻结。返回 `HARD STOP` 时按 `Next:` 回上游，不得继续。通过后再确认：

- `brief.md` 存在
- `acceptance.feature` 存在
- 二者同目录
- acceptance.feature 已冻结（无显著遗漏 Scenario）
- 用户已明确要求生成技术文档

任一缺失，停止并说明，不允许凭记忆生成。

### 步骤 2：吸收 brief 与 acceptance（确认假设，不重推）

从 `brief.md` 提取，并对每条**模块影响面判断标注沿用 / 修正**（不从零重写）：

- 业务流程主链路 + 异常分支
- 涉及的模块、各自承担的职责、复用还是新增（作为**假设**，逐条确认或修正）
- 概念数据模型（关键实体 / 字段 / 关系）→ 由本步及步骤 4 落成物理 schema
- 范围决策（改变范围 / 用户拿到什么的决策）；纯实现取舍由 TD 在此定夺
- 风险表

修正过的假设记一行"与 brief 判断的差异"（哪里改了、为什么），写入文档修订记录或输入依据映射表。

从 `acceptance.feature` 提取：

- 所有需要被验证的业务规则（Scenario 列表）
- 状态值、字段名、错误码、消息 topic 等具体术语
- 边界条件、幂等场景

把 Scenario 列表作为"必须满足的契约清单"——TD 中的每个方法实现都应该指向至少一条 Scenario。

### 步骤 3：扫描真实代码

至少确认：

- 当前模块入口在哪里
- 相近功能怎么写
- 是否已有可复用组件 / 服务
- 是否已有同名或同类 DTO / Entity / Mapper / Controller
- 改动文件目录树中每个 `[修改]` 文件是否真实存在
- 每个 `[新增]` 文件的父目录是否符合现有项目结构
- 方法级变更总表中每个 `[修改]` 方法是否真实存在
- 每个 `[新增]` 方法所属类是否真实存在或已说明新建原因

未扫代码就写方案 → TD 默认不合格。

### 步骤 4：设计接口、数据、中间件

- API 如何暴露
- 数据如何持久化
- Redis / OSS / MQ / Qdrant 是否需要接入
- 组件如何复用
- 幂等、事务、一致性如何处理

### 步骤 5：确认 Scenario 全覆盖

逐条 acceptance.feature 中的 Scenario 自查：

- 它由哪个方法实现？
- 它由哪个测试验证？
- 是否有 Scenario 在本次实现中无对应承接？若有，必须在"风险与待确认问题"中说明。

### 步骤 6：风险与验证方案

- 高风险点
- 数据迁移 / 配置变更 / 回滚预案
- 每个方法级改动对应的测试覆盖

### 步骤 7：迭代收敛

展示给开发者后进入审核循环：

1. 用户审阅、提出修改 / 疑问
2. Agent 修订对应章节（不只追加在末尾）
3. 用户明确"OK"或"冻结"后停止

### 步骤 8：冻结

- 回写 `state.yaml`：把 `artifacts.technical_design.frozen` 置为 `true`，`phase` 推进到 `implementation`
- 告知用户下一步：进入 `implementation-execution`

## 8. 提问门禁

以下问题不清楚时必须先向用户提问，不允许直接产出最终 TD：

- 是否需要兼容旧接口
- 是否需要迁移旧数据
- 是否需要新增 Redis / MQ / OSS 公共契约
- 外部系统协作方式不明
- 关键技术取舍待用户决定
- acceptance.feature 中存在无法对应到具体实现的 Scenario

提问规则：

- 只问会改变设计的关键问题
- 问题要短，说明它影响哪部分技术方案
- 低风险假设可以写入"假设与依赖"而不阻塞文档

## 9. 不允许写进技术文档的内容

- 已实现的代码结果
- 测试执行结论
- 最终提交说明
- 抽象口号（"增加接口"、"增加校验"）
- brief.md 或 acceptance.feature 原文整段重复

## 10. 输出质量标准

合格的 TD 必须做到：

- 另一个工程师读完可以开始实现
- 改动文件目录树清楚标明每个文件的状态
- 方法级变更总表中每个方法都关联到至少一条 Scenario
- acceptance.feature 中的每个 Scenario 都有对应实现 + 测试承接
- 复用的现有代码和组件被明确点出
- 业务层改动和 framework 改动被明确区分

应避免的表达：

- "视情况处理"
- "适当增加校验"
- "后续再补"
- "按现有逻辑扩展"

除非已经明确指出现有逻辑具体是哪个类、哪个流程。

## 11. 与其他 skill 的衔接

- **进入前**：必须有冻结的 `brief.md + acceptance.feature`；缺失任一 → 转上游 skill
- **冻结后**：等待用户审核；审核通过后进入 `implementation-execution`
- **禁止**：未经审核直接进入实现；在本阶段输出代码或测试执行结论
