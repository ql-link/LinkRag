---
name: acceptance-generator
description: 把用户已确认的 toLink-Rag solution.md 转换为可观察、可断言的 Gherkin 验收契约，覆盖主流程、权限、异常、状态、持久化、重试、兼容和回归；只展开已确认规则。
---

# 验收契约生成与收敛

固定输出 `.specs/<KEY>/acceptance.feature`。每个场景描述一条可以验证的业务规则；在相邻注释中引用方案的 `R`、`BR` 编号。本文件回答“什么行为算做对”，不写类名、方法名、表结构、框架选型或部署步骤。

## 停止条件

- `solution.md` 缺失、未确认、存在冲突或会改变行为的待决内容；
- 方案选择直接施工；确需增加 Gherkin 时先获得用户确认并更新方案后续路径；
- 只能写出“正确处理”“适当提示”等不可断言结果。

以上情况返回 `solution-generator`。不要根据聊天记忆替方案补规则。

## 写作规则

读取当前方案、当前请求、直接相关的实现和测试，以及 [acceptance.template.feature](acceptance.template.feature)。使用标准 Gherkin 英文关键字，场景名称、步骤和注释使用中文。

- `Given` 是可建立的前置状态，`When` 是动作或事件，`Then` 是可观察、可断言结果；
- 同一规则的多组输入使用 `Scenario Outline`；
- 按真实涉及面覆盖主流程、权限与资源归属、输入校验、状态与持久化、依赖失败、边界、并发、重试与幂等、旧数据或旧消息兼容；
- Gherkin 文件首先是验收契约，不能因为文件存在就声称自动化已通过。

每个适用的 `R` 和决定行为的 `BR` 都应有场景。用户确认后返回 `backend-delivery`。若这些场景适合成为长期回归测试，可使用 `python scripts/acceptance/promote_acceptance.py <KEY>` 提升到 `tests/acceptance/`，补齐 pytest-bdd steps 并实际运行；不是每个方案都强制提升。
