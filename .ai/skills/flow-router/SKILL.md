---
name: flow-router
description: 在任何需要改代码的需求进入开发链之前做一次轻量分诊，按改动性质判定 L1/L2/L3 车道，决定走快车道还是全链，并把后续交接给对应 skill。本 skill 不产出文档，只给出"车道结论 + 下一站"。属于整条「需求 → 交付」链的入口前置站。
when_to_use: "当用户提出任何需要改代码的需求、想法或修改请求，且尚未确定该走快车道还是全套流程时，先用本 skill 做分诊。触发示例：'要改个东西'、'加个字段'、'实现这个需求'、'帮我做个功能'、'这个改动走什么流程'。判为 L1 → 直接转 implementation-execution；判为 L2/L3 → 转 brief-generator（在其中按车道决定 brief 详略与是否要 technical-design）。若用户已经明确在写 brief / acceptance / 技术方案 / 编码，说明车道已定，不必再回本站。"
---

# Flow Router

## 1. 定位

本 skill 是「需求 → 交付」链的**入口前置站**。它解决一个老问题：以前复杂度判断埋在第 4 站（`implementation-execution`）内部，等于排到了用不上的位置——一个加字段的小改动也要先写 brief、再写 acceptance、再写方案。

本站把复杂度判断提到入口：**进来先分诊，按改动性质选车道，小改动不再走全套。**

本 skill **不产出任何文档**。它的输出是一个**车道结论 + 推荐下一站**，然后把控制权交给对应 skill。

## 2. 触发边界

### 2.1 适合使用

- 用户提出需要改代码的需求 / 想法 / 修改请求，车道尚未确定
- 用户直接问"这个改动走什么流程 / 要不要写 brief"

### 2.2 不适合使用

- 用户已经在写 brief / acceptance / 技术方案 / 编码 → 车道已定，不必回本站
- 纯排障、纯文档、纯 issue 登记等非「改代码交付」诉求 → 转对应专职 skill

## 3. 分诊判据

按改动性质三选一。**判定从严：只要命中任一更高车道的信号，就升到更高车道，不因"看起来小"往下压级。**

| 车道 | 判据 | 走的链 |
| --- | --- | --- |
| **L1 快车道** | 单文件 / 配置 / 文案 / 小修，**无契约变更** | `implementation-execution` → `run-all-tests` → `branch-pr-workflow` |
| **L2 标准** | 单模块功能，契约小变 | `brief-generator`（轻量）→ `implementation-execution` → `run-all-tests` → `code-review-and-quality` → `branch-pr-workflow`，**跳过独立 technical-design** |
| **L3 全链** | 跨模块 / 契约 / 中间件 / 数据迁移 | 现有完整链：brief → acceptance → technical-design → impl → test → review → PR |

## 4. L3 强信号（命中即升 L3，优先级最高）

只要改动触碰下列任一处，**一律判 L3**，不得归入 L1/L2——因为这些都受 CLAUDE.md 第六节的机器强制同步规则约束，失同步会引发跨服务集成事故：

- `src/models/` 下的 ORM 模型（牵动 schema + 迁移 + `docs/api/schemas/mysql.md`）
- `src/core/mq/messages/` 下的消息契约（牵动 `docs/api/mq_contracts.md` + `docs/internals/mq.md`）
- `migrations/` 下的数据迁移
- `src/core/pipeline/parse_task/` 的状态机 / 终态语义
- 对外 HTTP 接口或错误码的新增 / 变更

这条规则把「车道分级」和「机器强制门槛」绑在一起：契约改动不可能被误判成快车道。

## 5. 工作流程

### 步骤 1：读取需求与改动范围

- 保留用户原始诉求
- 判断预计触碰哪些目录 / 文件 / 契约
- 若信息不足以判级，向用户确认 1 个最关键的问题（通常是"会不会动到上面第 4 节列的契约点"）

### 步骤 2：判定车道

1. 先过第 4 节 L3 强信号：命中任一 → L3，结束判定。
2. 否则看是否单模块功能、契约小变 → L2。
3. 否则单文件 / 配置 / 文案 / 小修、无契约 → L1。

判定不确定时**就高不就低**，并说明依据。

### 步骤 3：给出结论并交接

输出固定包含：

- **车道**：L1 / L2 / L3
- **判定依据**：命中了哪条判据（尤其 L3 要点名触碰的契约点）
- **下一站**：
  - L1 → 转 `implementation-execution`（直接编码，无需 brief）
  - L2 → 转 `brief-generator`（轻量 brief，跳过 technical-design）
  - L3 → 转 `brief-generator`（完整链起点）

## 6. 与其他 skill 的衔接

- **进入前**：用户提出改代码诉求，车道未定
- **L1 之后**：`implementation-execution` → `run-all-tests` → `branch-pr-workflow`
- **L2 / L3 之后**：`brief-generator`（L2 轻量、跳 TD；L3 走完整链）
- **不允许**：把契约改动（第 4 节强信号）当成 L1 快车道绕过文档同步
