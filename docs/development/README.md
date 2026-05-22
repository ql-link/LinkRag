# Development

面向贡献者的开发流程、工作流约定与协作规范。

## 当前文档

- [文档体系架构](documentation_architecture.md) — 文档体系的设计原则、目录职责、治理机制总览
- [测试规范](testing.md) — 分层、markers、运行命令、Mock 原则
- [代码风格](code_style.md) — black/isort/mypy 配置与提交前命令
- [分支与 PR 流程](branching_and_pr.md) — 分支命名、提交规范、PR 自检清单
- [文档同步机制](doc_sync.md) — 改代码自动校验是否漏同步文档（pre-commit + CI）

## 适合放在这里的内容

- 测试策略、覆盖率要求、Mock 约定
- 分支策略、提交规范、PR 流程
- 代码格式化与静态检查工具
- 代码评审清单与合并标准
- 发布流程与版本管理

## 不适合放在这里的内容

- 模块内部架构 → [docs/architecture](../architecture)
- 命名规范、配置规范 → [docs/conventions](../conventions)
- 使用方/接入方文档 → [docs/guides](../guides)
