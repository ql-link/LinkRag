---
name: technical-design
description: 在 requirement.md 审核通过后，为当前模块当前期次目录产出 technical_design.md，并严格基于真实代码、组件文档和公共契约进行设计。
when_to_use: 当任务进入本 skill 对应阶段，或该 skill 的 description 触发条件命中时使用；进入下一阶段前，必须满足 AGENTS.md 的门禁与人工审核要求。
---

# Technical Design

## 1. 目的

本 skill 用于把已经确认的 `requirement.md` 转化成可落地的 `technical_design.md`。

它主要回答：

- 准备改哪些模块
- 复用哪些现有能力
- API、数据、缓存、消息、对象存储怎么设计
- 风险、兼容性、测试策略是什么

它不直接负责：

- 写业务代码
- 提交改造结果
- 输出测试执行结论

这些分别属于后续 `implementation-execution` 和 `test-and-delivery`。

## 2. 使用前提

只有满足以下条件时，才允许使用本 skill：

1. 已完成 `project-bootstrap`
2. 当前模块目录与当前期次目录存在
3. `requirement.md` 已经过人工审核通过
4. 当前复杂度等级为 `L2` 或 `L3`，或用户明确要求单独技术方案

如果需求文档还未审核通过，不允许提前写 `technical_design.md`。

## 3. 必读文件

执行本 skill 时，至少读取以下文件：

1. `AGENTS.md`
2. `project_info.md`
3. 当前模块当前期次目录 `feature_info.md`
4. 当前模块当前期次目录 `requirement.md`
5. `.agents/skills/technical-design/technical_design.template.md`
6. `docs/architecture/middleware_contract.md`

按需补读：

7. 对应组件说明文档
8. 同业务域历史模块目录中的 `technical_design.md`
9. 同业务域历史模块目录中的 `implementation_report.md`
10. 相关真实代码

组件文档的读取规则：

- 涉及 Redis 缓存时读 `redis_component.md`
- 涉及文件存储、公私有访问、object key 时读 `oss_component.md`
- 涉及异步消息、topic、consumer 时读 `kafka_component.md`

额外强制规则：

- 只要方案中准备“使用、修改、扩展、复用”某个组件或模块，就必须先读取对应代码或文档
- 组件级复用至少读取对应组件说明文档
- 模块级复用至少读取一个真实代码入口，例如 Controller、Service、Model、Mapper 或配置类
- 不允许仅凭类名猜测、历史印象或通用 Spring 经验直接写方案

## 4. 输出位置

输出文件固定为：

`docs/module-development-files/<domain>-<module-name>/<phase>/technical_design.md`

注意：

- 输出文件名固定为 `technical_design.md`
- 文档结构必须优先遵循 `.agents/skills/technical-design/technical_design.template.md`

若目录中已有旧版 `technical_design.md`：

- 先读旧版
- 判断是修订、覆盖还是增量更新
- 不允许无说明地重写并覆盖关键技术结论

## 5. 同时需要维护的文件

除 `technical_design.md` 外，本 skill 还应同步维护当前模块当前期次目录的 `feature_info.md`。

至少应回填：

- 当前状态：`技术设计中` / `技术方案待审核`
- 当前实际产出的文档清单
- 当前推荐阅读顺序

## 6. 输出内容要求

`technical_design.md` 必须优先遵循 `.agents/skills/technical-design/technical_design.template.md` 的结构。

最低要求包括：

1. 文档修订记录
2. 技术目标与范围
3. 当前系统分析
4. 总体方案设计
5. API 设计
6. 数据与存储设计
7. 核心实现设计
8. 组件与集成设计
9. 权限、安全与审计
10. 异常处理与降级策略
11. 测试方案
12. 发布方案

允许按功能复杂度精简某些章节的内容密度，但不要擅自删除一级章节。

## 7. 技术设计的工作步骤

### 步骤 1：把需求拆成工程问题

先从 `requirement.md` 提炼出：

- 哪些需求会改接口
- 哪些需求会改数据结构
- 哪些需求会碰中间件
- 哪些需求只影响业务逻辑

### 步骤 2：扫描真实代码

至少确认：

- 当前模块入口在哪里
- 相近功能怎么写
- 是否已有可复用组件或服务
- 是否已有同名或同类 DTO / Entity / Mapper / Controller

如果没扫代码就写方案，这份文档默认不合格。

补充要求：

- 若方案中提到“复用某组件”，必须说明读过哪个组件文档
- 若方案中提到“复用某模块现有实现”，必须说明参考了哪些代码文件
- 若方案中提到“新增代码放在哪个包”，必须基于现有包结构判断，不能空想

### 步骤 3：确定模块边界

要明确：

- 哪些改动放 `link-api`
- 哪些改动放 `link-service`
- 哪些改动放 `link-model`
- 哪些改动放 `link-mapper`
- 哪些改动放 `link-components`

原则：

- 业务逻辑优先放业务模块
- framework 能力变更才进入 `link-components`
- 不要为了某个业务需求轻易改 framework

### 步骤 4：设计接口、数据与中间件

要明确：

- API 如何暴露
- 数据如何持久化
- Redis / OSS / MQ 是否需要接入
- 组件如何复用
- 幂等、事务、一致性如何处理

### 步骤 5：给出风险与验证方案

要说明：

- 哪些是高风险点
- 如何验证改动正确
- 是否需要数据迁移、配置变更、回滚预案

## 8. 强制代码引用要求

技术方案必须引用当前仓库真实代码，不允许空想。

至少要引用：

- 相关模块或类
- 已有组件文档
- 已有实现方式或相似代码路径

只要出现以下任一内容，就必须先读对应代码或文档再写：

- 使用 Redis、OSS、MQ、鉴权、加密等组件
- 调用已有 Service、Mapper、Controller
- 扩展已有 DTO、Entity、Enum、配置类
- 复用已有上传、缓存、异步、权限、异常处理链路

应优先写清楚：

- “复用哪个已有类/接口/组件”
- “新增代码建议放在哪个包”
- “为什么不改 framework，只改业务层”

## 9. 提问门禁

以下问题如果不清楚，必须先向用户提问，不能直接产出最终 `technical_design.md`：

- 需求边界仍未定
- 权限边界不明确
- 是否需要兼容旧接口不明确
- 是否需要迁移旧数据不明确
- 是否需要新增 Redis / MQ / OSS 公共契约不明确
- 外部系统协作方式不明确
- 用户是否接受某种关键技术取舍不明确

提问规则：

- 只问会改变设计的关键问题
- 问题要短，要说明它影响哪部分技术方案
- 如果只是低风险假设，可以写入“假设与依赖”而不阻塞文档

## 10. 不允许写进技术文档的内容

以下内容不要写成“最终已经完成”的口吻：

- 已实现的代码结果
- 测试执行结论
- 最终提交说明

这些属于后续阶段。

同时也不要：

- 只写抽象概念，不落到模块和文件层
- 只写“增加接口”“增加校验”这种空话
- 把需求文档原文整段重复一遍

## 11. 输出质量标准

一份合格的 `technical_design.md` 至少要做到：

- 另一个工程师读完可以开始实现
- 另一个 AI 读完不需要重新猜模块边界
- 能明确看出复用了哪些现有代码和组件
- 能明确区分“业务层改动”和“framework 改动”

应避免的表达：

- “视情况处理”
- “适当增加校验”
- “后续再补”
- “按现有逻辑扩展”

除非已经明确指出现有逻辑具体是哪个类、哪个流程。

## 12. 写完后的停点

本 skill 完成后必须停在“人工审核技术方案”这个节点。

完成动作包括：

1. 写好 `technical_design.md`
2. 更新 `feature_info.md`
3. 明确告知用户当前已进入“技术方案待审核”
4. 等待用户确认，不允许直接跳到 `implementation-execution`

## 13. 推荐输出摘要

本 skill 完成后，对用户的摘要建议至少包含：

- 本次技术文档路径
- 本次拟改动模块摘要
- 本次组件复用点摘要
- 当前待确认技术问题（如果有）
- 下一步需要用户做什么：审核技术方案

## 14. 与其他 skill 的衔接

- 进入前：应先完成 `requirement-analysis`，且需求文档已审核通过
- 结束后：等待人工审核
- 审核通过后：再进入 `implementation-execution`

禁止行为：

- 未经审核直接进入实现
- 在本阶段提前输出改造报告或测试结论
