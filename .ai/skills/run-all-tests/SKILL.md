---
name: run-all-tests
description: 根据 toLink-Rag 的实际改动范围选择并运行单元、集成、质量和迁移验证，区分代码失败与环境阻塞，报告真实命令、结果和未覆盖区域。
---

# 测试与验证

区分两种模式：任务范围验证只运行与改动和风险匹配的检查；PR 全量验证在当前可提交内容上运行仓库要求的完整本地门禁。较早的局部结果和共享 CI 不能替代本次本地执行。

## 选择命令

| 范围 | 命令 |
| --- | --- |
| 单元测试 | `pytest tests/unit` |
| 指定单元模块 | `pytest tests/unit/<path>` |
| 集成测试 | `pytest --run-integration tests/integration` |
| 真实环境集成 | `pytest --run-integration -m real_env`（需明确环境与授权） |
| 项目 skill | `python scripts/quality/check_skills.py` |
| AI 链接 | `python scripts/quality/check_ai_links.py` |
| 文档同步 | `python scripts/quality/check_docs_sync.py --working` 与 `--self-check` |
| Acceptance step | `python scripts/acceptance/check_acceptance_steps.py` |
| 格式与静态检查 | 按 `docs/contributing.md` 的当前命令执行 |

数据库变更还要验证 Alembic heads、空库向前升级、受支持历史 revision 到 head 的升级和目标 MySQL；不执行 downgrade。MQ、对象存储、Qdrant、模型或 Java 对接的真实链路不能由 fake 或单元测试冒充。

先读取差异与相关测试，运行最窄有区分度的检查，再扩大到任务范围。检查退出码和完整结尾。失败分为代码或断言失败、环境/依赖/权限/网络阻塞、命令或测试基础设施错误。只读请求不得自动修复；实现任务只修复本次引入的问题。

报告必须包含验证模式、实际命令、覆盖范围、结果摘要、失败明细、未覆盖区域、完整检查是否执行和下一步。计划运行不能写成已执行，Gherkin 存在、测试收集、构建或 fake 通过不能夸大为真实端到端证明。
