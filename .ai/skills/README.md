# Skills 注册表（toLink-Rag）

本目录下每个子目录是一个 Agent skill（`<name>/SKILL.md`）。本文件是**索引 + 治理入口**，
帮助快速查找职责、理清触发边界、安排周期复审。

> 机器校验：`python scripts/check_skills.py`（pre-commit 已接入）。检查 frontmatter 完整性、
> 死引用、技术栈一致性、孤儿目录。新增/修改 skill 后请确保该检查为绿。

## 管理约定

1. **单一职责 + 明确边界**：每个 skill 只解一类问题，`when_to_use` 必须写清「触发场景」与「转交规则」。
2. **Project-grounded**：示例、路径、命令一律用本仓库真实的（如 `tests/unit`、Qdrant 而非 Milvus）。
3. **引用真实文件**：SKILL.md 里出现的 `docs/ src/ tests/ scripts/ migrations/` 路径必须存在（占位示例用 `your_/xxx/<...>` 写法）。
4. **增删有记录**：删除 skill 要在提交说明里写明，避免悬挂的「已删未提交」状态。
5. **本表与 `agents-tree-sync` 联动**：新增/删除/重命名 skill 时同步本表与 `AGENTS.md` 结构树。

## 按类别索引

### 需求 → 交付 流程链（按顺序）
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `flow-router` | 入口分诊，按改动性质判 L1/L2/L3 车道，不产文档 | L1 直转 implementation-execution；L2/L3 转 brief-generator |
| `brief-generator` | 把新需求/想法收敛成开发者向 brief.md（L2 轻量、跳 TD；L3 完整） | 上游经 flow-router 判级；冻结后转 acceptance-generator |
| `acceptance-generator` | 基于冻结 brief.md 生成 Gherkin acceptance.feature | 需先有冻结 brief；要技术方案转 technical-design |
| `technical-design` | 基于 brief+acceptance 产出 technical_design.md | 上游缺失先回退对应 skill |
| `implementation-execution` | 需求/方案确认后执行编码，必要时产出 implementation_report.md；spec 缺口强制回写 + 留痕 | 无冻结 spec → 回 brief-generator；编码完成 → run-all-tests + code-review-and-quality |
| `run-all-tests` | 跑 `tests` 全量回归，回报结论 | 收口前的测试关口；详见「测试与质量」 |
| `code-review-and-quality` | 提交/合并前五维质量门禁 | 过关后 → branch-pr-workflow |
| `branch-pr-workflow` | 从 dev 新建规范分支、提交并发起合并 PR；收口硬门槛拦截 | 链路终点；测试未过 / 契约失同步 / acceptance 未提升则拒绝收口并回退对应 skill |

### 测试与质量
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `auto-test` | 生成 pytest 单测/集成/冒烟，强调 Mock 隔离与边界覆盖 | 只写测试；TDD 红绿循环 → 无（tdd 已下线） |
| `run-all-tests` | 跑 `tests` 全量（含 `--run-integration`）并回报结论 | 不落本地报告文件 |
| `code-review-and-quality` | 提交/合并前五维质量门禁审查 | 安全专项可叠加内置 `/security-review` |
| `feature-completion-audit` | 对照原始需求六维取证，判功能是否真做完（缺口/偏离） | 入口 A 对话内实现用子 agent 复核、入口 B 审 PR 用当前 agent；质量门禁转 code-review-and-quality、跑全量转 run-all-tests |
| `code-annotator` | 生成恰到好处的 Python Docstring 注释 | 只补注释，不改逻辑 |
| `swagger-annotation` | 为 FastAPI 路由/Pydantic 生成中文 Swagger 注解 | — |

### 数据库与数据模型
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `mysql-ddl-conventions` | 建表/字段/索引规范 | 写迁移本身转 alembic-migration |
| `alembic-migration` | 写/校验 Alembic 迁移，守 ORM+迁移链权威 | DDL 规范转 mysql-ddl-conventions；同步文档转 doc-maintenance-sync |

### 消息 / 向量 / 召回
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `mq-middleware` | MQ 中台收发、定义新消息类型、多厂商适配 | 跨端 topic/字段取值一致性转 config-contract-sync |
| `rag-recall-eval` | dense/sparse/bm25 召回质量量化评估与回归 | 召回报错故障转 incident-triage；只写单测转 auto-test |

### 契约 / 配置 / 文档治理
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `contract-guard` | 校验改动是否破坏公共契约并给文档同步清单 | 取值一致性转 config-contract-sync；泛化文档同步转 doc-maintenance-sync |
| `config-contract-sync` | 核对 topic/bucket/字段在 .env/代码/Java 三处取值一致 | 契约是否破坏转 contract-guard；运行故障转 incident-triage |
| `doc-maintenance-sync` | 代码变更后同步 docs/AGENTS 等文档 | 项目结构树同步转 agents-tree-sync |
| `agents-tree-sync` | 同步 AGENTS.md 的「当前项目结构」树（非 docs 结构变更） | docs/ 结构变化不触发 |

### 运维 / 排障
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `incident-triage` | 从日志定位解析/召回故障，分诊配置漂移 vs 数据不一致 | 新功能实现转 implementation-execution；写迁移修数据转 alembic-migration |

### issue 登记 / 同步
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `cowork-issue-sync` | 把需求/bug 落成 Linear 主记录 + GitHub 镜像并双向回链 | 只「立 issue」；建分支/写码/发 PR 转 branch-pr-workflow |

### 内容产出
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `blog-writer` | 基于真实需求/实现产出技术博客到 `.specs/blog/` | 仅指定时才参考历史博客 |

### 元能力（管理 skill 自身）
| skill | 职责 | 边界 / 转交 |
| --- | --- | --- |
| `skill-creator` | 创建/改进/评估 skill，含 eval 与 description 优化（官方） | 英文；自带 `scripts/` 评估工具 |

## 周期复审清单

每次大重构或里程碑后执行：

1. 跑 `python scripts/check_skills.py`，清掉所有 error。
2. 检查触发边界是否仍互斥（重叠的合并、过期的下线）。
3. 半年内从未触发的 skill 评估是否退役。
4. 同步更新本表与 `AGENTS.md` 结构树。
