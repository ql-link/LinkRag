# .specs/ — Feature 临时交付物（本地，不入 git）

存放 spec-as-test 工作流的中间产物。**整个目录已 git-ignored**——除本 README 外，`.specs/` 下任何内容都不会进入版本控制。

## 为什么不入 git

这些文件按设计就是**临时**的：

- `brief.md` / `technical_design.md` / `implementation_report.md` — 决策快照，代码合并后随实现演进而过时。
- 长期价值由其他渠道承载：
  - **决策上下文** → PR 描述 + commit message
  - **执行的验收规约** → `tests/acceptance/features/<name>.feature`（由 pytest-bdd 驱动）
  - **沉淀的架构 / 契约 / 配置** → `docs/internals/` `docs/api/` `docs/ops/`

保留在 git 里只会形成"被维护半年后就成为误导信息"的死档案，违反 [docs/contributing.md §七](../docs/contributing.md#七文档体系约定修改-docs-前必读) 的"不应放进 docs/ 的内容"约定。

## 目录约定

```
.specs/
├── README.md                # 本文（唯一会被 git 跟踪的文件）
└── <feature-name>/          # 当前在开发的 feature（本地工作目录，不入 git）
    ├── brief.md
    ├── acceptance.feature
    ├── technical_design.md
    └── implementation_report.md
```

命名建议：英文 kebab-case。

## 工作流

| 阶段 | 产物 | 工具（`.ai/skills/`） |
| --- | --- | --- |
| 1. 需求理解 | `brief.md` | `brief-generator` |
| 2. 验收契约 | `acceptance.feature` | `acceptance-generator` |
| 3. 技术方案 | `technical_design.md` | `technical-design` |
| 4. 实施 | 代码 + `implementation_report.md` | `implementation-execution` |
| 5. 合并前沉淀 | 见下文 | 人工 |
| 6. 合并后清理 | `rm -rf .specs/<feature>/` | 人工 |

**约束**：

- 上游产物未冻结，不进入下游阶段。`brief.md` 未确认前不要生成 `acceptance.feature`。
- 短小改动（一行 bugfix、一处配置）不走全流程，直接 PR 即可。

## 合并前必须沉淀的内容

合并 PR 前，把 `.specs/<feature>/` 里**有长期价值**的东西搬出去；否则信息就只活在你本地：

| `.specs/` 里 | 沉淀到 |
| --- | --- |
| 关键设计决策、风险、权衡 | PR 描述 |
| 可执行的 Gherkin 验收场景 | `tests/acceptance/features/<name>.feature` + `tests/acceptance/test_<name>.py` + step 实现 |
| 新模块或边界变化 | `docs/internals/<module>.md` |
| 新对外契约 | `docs/api/` 对应文件 |
| 新配置项 | `docs/ops/configure.md` |
| 数据库表变化 | `docs/api/schemas/mysql.md` + Alembic 迁移 |

详细规则见 [docs/contributing.md §六](../docs/contributing.md#六spec-as-test-工作流feature-开发)。

## 历史记录在哪

旧 feature 的 brief/design/report 不在主分支了。需要查阅时：

```bash
# 看过去某 feature 目录的所有 commit
git log --all --oneline -- 'docs/<feature-name>/'

# 把旧文件 checkout 到本地查看（不影响工作区）
git show <commit-sha>:docs/<feature-name>/brief.md
```

更早的归档目录已在 commit `<refactor-commit-sha>` 中从主分支删除；通过 git 历史仍可追溯。
