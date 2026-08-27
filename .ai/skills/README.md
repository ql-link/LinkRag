# toLink-Rag 项目技能

`.ai/skills/` 是项目技能的唯一来源；`.agents/skills` 与 `.claude/skills` 应链接到同一份内容。长期项目事实写入 `docs/`，可执行门禁写入 `scripts/quality/`，单次任务产物写入 `.specs/<KEY>/`。

## 开发主链

| 技能 | 职责 | 下一站 |
| --- | --- | --- |
| `flow-router` | 薄入口：区分代码交付、模块规划、故障调查与只读任务，原样传递用户控制项 | `backend-delivery` / `module-planning` / `incident-triage` |
| `backend-delivery` | 当前主 Agent 完成七维判断、直接/方案路径、工作包拆分、实施调度与复核 | `implementation-execution` 或 `solution-generator` |
| `module-planning` | 整个模块目标或前提未形成时调查、逐项确认并按用户要求输出初步方案 | 获得继续授权后回 `flow-router` |
| `decision-grilling` | 一次收敛一个真实高影响选择，返回 confirmed / blocked / replan | 返回调用方 |
| `solution-generator` | 创建和修订以结果、规则、状态、数据、HTTP/MQ 契约、真实步骤和验证映射为中心的 `solution.md` | 直接施工或 `acceptance-generator` |
| `acceptance-generator` | 只在选定契约验收时把已确认规则展开为 Gherkin | 返回 `backend-delivery` |
| `implementation-execution` | 按确认范围实施代码、契约、迁移、配置、测试和必要文档 | 自动化与人工验证 |

## 测试、质量与交付

| 技能 | 职责 |
| --- | --- |
| `test-authoring` | 编写单元、集成和 pytest-bdd 测试及夹具 |
| `run-all-tests` | 按改动范围运行真实验证，区分失败与环境阻塞 |
| `manual-acceptance` | 记录自动化未覆盖的真实 MQ、数据库、对象存储、向量库、模型或 Java 联调 |
| `code-review-and-quality` | 审查正确性、契约、数据、安全、架构、性能和验证充分性 |
| `feature-completion-audit` | 对照原始需求独立核验完成度、遗漏和偏离 |
| `branch-pr-workflow` | 从 master 的同一业务分支依次交付 Dev PR 和 Master PR |

## 项目专项能力

数据库与迁移使用 `mysql-ddl-conventions`、`alembic-migration`；HTTP/MQ/schema、配置与文档分别使用 `contract-guard`、`config-contract-sync`、`doc-maintenance-sync`；解析或运行故障先用 `incident-triage`；MQ、Swagger、代码注释、Issue 同步和内容产出按对应 skill 使用，不延长所有任务的固定主链。

## 工作流控制

```text
工作流：自动 | 开启 | 关闭
路径：自动 | 直接实现 | 方案先行
后续：自动 | 直接施工 | 契约验收
```

用户更具体、更新的选择优先。直接实现不创建 Spec；方案先行以 `.specs/<KEY>/solution.md` 为中心，只有选择契约验收时增加 `acceptance.feature`。顺序是内容关系，不是机器阶段状态；不创建 `state.yaml`，也不维护冻结标记或历史测试快照。

方案与实施只向右推进：初始材料 → 当前方案 → 代码与测试 → PR。代码或方案变化时重新核实真实影响；不把实现反向同步到 Issue 或初步设计文档。存在来源 Issue 时，PR 创建后最多追加一条交付评论。

运行 `python scripts/quality/check_skills.py` 校验 frontmatter、引用、技术栈与孤儿目录。长期模块知识从 [docs/README.md](../../docs/README.md) 进入。
