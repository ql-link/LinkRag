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
    ├── state.yaml           # 机器拥有的阶段状态（取代旧的手维护 feature_info.md）
    ├── brief.md
    ├── acceptance.feature
    ├── technical_design.md
    └── implementation_report.md
```

命名建议：英文 kebab-case。

### 阶段状态：`state.yaml` + `flow-guard`

`state.yaml` 是这个 feature 的**机器拥有**阶段状态：`phase`、各 artifact 的 `frozen`、`acceptance_promoted`、`verified` 等不变量都记在结构化字段里，人类可读摘要放 `notes`。它取代了过去靠 agent 记得更新的散文 `feature_info.md`。

阶段推进由 [scripts/flow-guard.py](../scripts/flow-guard.py) 兜底，**进入下游阶段前由对应 skill 主动调用**（`.specs/` 整目录 git-ignored，无法做 git hook）：

```bash
python scripts/flow-guard.py init <feature> --lane <L2|L3>   # 链起点初始化
python scripts/flow-guard.py check <feature> acceptance      # 进入 acceptance 前的前置校验
python scripts/flow-guard.py validate <feature>              # 仅校验 state.yaml 结构
python scripts/flow-guard.py status                          # 报当前 feature/phase/下一站(跨会话恢复)
```

前置不满足时打印 `HARD STOP` + 可执行的下一步并以非 0 退出。"冻结"因此从 agent 自觉降级为有脚本兜底的显式动作。

**跨会话恢复**:长 feature（尤其 L3）跨会话续做时，先跑一条 `flow-guard status`，它扫描 `.specs/` 报出当前 active feature（唯一非 `done` 项）、所在 `phase`、唯一允许的下一站和该读的单个输入文件——无需重读全部 `.specs` 产物。有多个在途 feature 时全部列出，由你指明继续哪个。

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

- 上游产物未冻结，不进入下游阶段。`brief.md` 未确认前不要生成 `acceptance.feature`——这条不变量由 `flow-guard.py check` 机器校验，不再只靠 agent 自觉（见上文「阶段状态」）。
- 短小改动（一行 bugfix、一处配置）不走全流程，直接 PR 即可，也不需要 `state.yaml`。

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
