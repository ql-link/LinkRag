# toLink-Rag 本地任务产物

`.specs/<KEY>/` 保存需要跨会话继续使用的本地任务产物，不保存机器阶段、文档哈希、验证快照或任务状态。目录内容除本说明外被 Git 忽略。

## 产物

| 产物 | 什么时候存在 | 职责 |
| --- | --- | --- |
| `solution.md` | `backend-delivery` 选定方案先行时 | 业务与技术中心，保存结果、流程、规则、状态、数据、契约、真实实施步骤和验证映射 |
| `acceptance.feature` | 方案选择契约验收时 | 展开需要独立确认的可观察规则；文件存在不等于自动化已通过 |
| `manual_acceptance.md` | 自动化无法覆盖必要的真实服务或跨系统结果时 | 保存人工步骤和本次真实结果 |
| `implementation_report.md` | 存在已允许偏差、已接受限制或跨会话遗留事项时 | 只补充方案之外的新事实 |

直接实现不创建 Spec。没有 Issue 时可用 `LOCAL-YYYYMMDD-SHORT-SLUG` 作为目录名。同一方案任务只有一个当前 `solution.md`，不创建“最终版”、`state.yaml`、冻结字段或阶段命令。

## 使用规则

初始来源可以是当前请求、Issue、飞书或用户指定材料。确认后的 `solution.md` 是方案任务的当前实施依据；Acceptance、人工验收和实施报告是从属附件。会改变范围、行为、权限、数据、兼容、失败语义或发布承诺时先修订方案并确认；普通文件组织和测试落点不反向修改方案。

若本地 Gherkin 适合成为长期回归测试，使用：

```bash
python scripts/acceptance/promote_acceptance.py <KEY>
```

提升后补齐 pytest-bdd steps，运行对应测试，并由 CI 的 acceptance step 门禁持续检查。不是每个方案都强制生成或提升 Acceptance。

长期事实同步到 `docs/`，实际交付、验证、风险和重要来源差异写入 PR。跨会话恢复时重新读取当前请求、方案与实际附件、Git 差异、真实代码，并重新运行当前交付需要的验证；不继承旧会话的“已通过”。
