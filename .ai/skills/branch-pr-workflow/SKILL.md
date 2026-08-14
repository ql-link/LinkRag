---
name: branch-pr-workflow
description: 当需求或 Bug 修复完成，需要从 master 创建规范业务分支，先提交 PR 到 dev 测试，再由同一业务分支提交 PR 到 master 时使用。适用于“代码写完了提 PR”“从 master 建业务分支”“提交 Dev 测试”“Dev 验收后发布”等交付收口场景。禁止 dev -> master，也禁止从 dev 派生发布分支。本 skill 是交付链终点，并在建分支、Dev PR 和 Master PR 前执行收口门槛：测试未过、契约文档失同步、acceptance 未提升或 Dev 验收证据缺失者拒绝收口。
when_to_use: "当代码实现完成、准备从 master 新建规范业务分支并发起 Dev PR，或该业务分支已在 dev 验收通过、准备发起 Master PR 时激活。触发示例：'代码写完了提个 PR'、'从 master 建分支提交'、'提交到 dev 测试'、'Dev 测试通过后发布'。进入即执行收口门槛校验：测试未全绿 / 契约改动未同步文档 / acceptance 仍停在 .specs 未提升时，停止并回退到对应 skill（run-all-tests、contract-guard、acceptance-generator），不强行收口。Master PR 必须复用已完成 Dev 验收的同一业务分支，禁止使用 dev 作为 head。"
---

# Branch PR Workflow

## Goal

在当前模块实现完成后，从最新 `master` 创建规范业务分支，先创建合并到 `dev` 的 PR；Dev
验收通过后，再由同一业务分支创建合并到 `master` 的 PR。

## Preconditions

1. 新业务分支必须基于最新远端 `master`，不能基于 `dev`。
2. 当前工作区应只包含本次模块实现需要提交的修改。
3. 不要把无关本地修改混入分支、提交或 PR。
4. Dev PR 合入后必须保留业务分支，直到对应 Master PR 合入。

如果已有业务分支，先确认它以 `master` 为基线；如果尚未创建分支，先切到最新 `master` 再创建。

## Master PR Mode

当用户要求“发布新版本”“发版”“Dev 测试通过后合入 master”或语义等价的发布收口时，进入本模式。

发布 PR 的目标是把已在 `dev` 验收通过的业务分支合入 `master`，不能把整条 `dev` 集成线发布：

1. 执行 `git fetch --all --prune`，确认业务分支、`dev` 与 `master` 的远端状态。
2. 确认该业务分支已有已合入的 Dev PR，并记录 Dev 验收对应的业务分支 head SHA 和测试证据。
3. 确认验收后业务分支没有变化；若 SHA 已变化，停止发布并重新进入 Dev PR 与测试流程。
4. 检查是否已有该业务分支到 `master` 的打开 PR；有则复用，不重复创建。
5. 使用业务分支作为 head、`master` 作为 base 创建 Master PR。
6. PR 描述必须关联 Dev PR，并列出 Dev 测试结果、数据库迁移、配置变更、文档同步项和已知风险。

禁止创建 `dev -> master` PR，禁止从 `dev` 派生 `release/<version>`，也禁止把 `dev` merge、
rebase 或 cherry-pick 到业务分支。若同步最新 `master` 或解决冲突改变了业务分支，更新后的 SHA
必须先回到 `dev` 重新验收。

Master PR 合入后，按发布计划在 `master` 合入提交上打 tag；此后才删除业务分支。

## 收口硬门槛（建分支 / 提 PR 前必须满足）

本 skill 是交付链终点，进入即先做收口门槛校验。门槛分两层——**机器层已能真正 block，prompt 层靠自觉 + 留痕**。任一门槛不满足，停止收口并回退到对应 skill，不强行建分支或提 PR。

### 机器层（pre-commit / CI 真拦截，本 skill 只负责触发与确认）

这些门槛由仓库已有机器规则强制，提交时自动执行，无需在此重写逻辑——只需确认它们已通过：

- **契约文档同步**：改动触碰 `src/models/**`、`src/core/mq/messages/**`、`src/core/pipeline/parse_task/**` 等契约点时，[scripts/quality/doc-sync-rules.yaml](../../../scripts/quality/doc-sync-rules.yaml) 要求同步对应文档，缺一即 block commit。提交前先跑 `python scripts/quality/check_docs_sync.py --staged` 确认为绿。
- **skill 质量**：若本次改了 `.ai/skills/**`，`python scripts/quality/check_skills.py` 必须为绿。
- **全量测试**：CI 跑 `tests` 全量，未全绿不得合并。

### prompt 层（机器看不见，靠自觉执行 + PR 留痕）

这些项无法被机器在提交时判定（如 `acceptance.feature` 在 git-ignored 的 `.specs/` 内，git 看不见"欠提升"），因此作为软门槛执行，并在 PR 描述的「门槛自查」中如实勾选、可追责：

- **改动范围测试已跑过且全绿**：执行了与本次改动匹配的测试（不只依赖 CI），有结论。未跑 → 回退 `run-all-tests`。
- **契约语义已核对**：若触碰公共契约，除文档同步外，还需确认改动不破坏对端消费语义。未核对 → 回退 `contract-guard`（破坏性判断）/ `config-contract-sync`（跨端取值一致）。
- **acceptance 已提升**：本 feature 的 `acceptance.feature` 已从 `.specs/<feature>/` 提升到 `tests/acceptance/features/<name>.feature`。提升用脚本完成，不再手工 copy：
  ```bash
  python scripts/acceptance/promote_acceptance.py <feature>
  ```
  它搬运 + 改名(kebab→snake) + scaffold `test_/steps` + 令两版逐字一致，并校验 0 个 undefined step；返回非 0(仍有未实现 step)→ 补全 step 后重跑。仍停在 `.specs/` → 回退 `acceptance-generator` 提升后再收口。提升后的 `tests/acceptance` 由 CI(`acceptance-steps.yml`)守 undefined step，对全员生效。

### L1 快车道豁免

`flow-router` 判为 **L1** 的改动（单文件 / 配置 / 文案 / 小修，无契约变更），契约门槛与 acceptance 提升门槛天然不触发，只需过测试门槛即可收口——避免小改动被全套门槛卡死。

## Branch Naming

分支名前缀根据修改性质选择：

- `feature/`：新增能力、新接口、新流程、新模块、新用户可见行为。
- `fix/`：普通 Bug 修复；线上紧急修复可使用 `hotfix/`。
- `refactor/`：重构、结构调整、性能优化、内部实现替换，且没有新增业务能力。
- `chore/`：依赖、工具和 CI 等工程改动。

分支主题来自当前修改内容，使用英文小写单词，并用 `-` 分割：

```text
feature/pdf-async-image-enhancement
fix/parser-entry-timeout
```

避免使用空格、中文、驼峰、连续分隔符和泛泛名称，例如 `feature/update`。

## Workflow

以下流程适用于功能 / 重构 / 修复等日常 Dev PR；发布收口使用上方 Master PR Mode。

1. 检查状态：
   - `git branch --show-current`
   - `git status --short --branch`
   - `git diff --name-only`

2. 理解当前修改：
   - 用 `git diff --stat` 和必要的文件 diff 判断改动范围。
   - 识别无关修改。若无关修改会混入提交，先向用户说明并只暂存相关文件。

3. 决定分支类型和名称：
   - 新增功能用 `feature/<topic-with-hyphens>`。
   - Bug 修复用 `fix/<topic-with-hyphens>`；线上紧急修复可用 `hotfix/`。
   - 重构/优化用 `refactor/<topic-with-hyphens>`，工程改动用 `chore/`。
   - 如果类型不明确，根据 diff 的主要意图做保守判断，并在最终说明中写明依据。

4. 从最新 `master` 创建分支：
   - 使用 `git fetch <remote> --prune` 更新远端引用。
   - 使用 `git switch master` 和 `git pull --ff-only <remote> master` 更新本地基线。
   - 使用 `git switch -c <branch-name>` 创建业务分支。
   - 不要把 `dev` 合入或 rebase 到业务分支。

5. 验证与提交：
   - 运行与改动范围匹配的测试。
   - 只暂存本次相关文件。
   - 提交信息使用约定式提交，例如：

```text
feat(parser): 支持 PDF 图片异步上传与内存增强

- 后台上传 PDF 图片资产，主解析链路不等待 MinIO
- 图片增强优先使用解析阶段内存图片
- 补充配置、文档和回归测试
```

6. 推送并创建 PR：
   - 推送当前分支到项目远端。
   - PR base 必须是 `dev`。
   - 如果 `gh` 可用，优先用 `gh pr create`。
   - 如果 `gh` 不可用但本机 GitHub 凭据可用，可调用 GitHub API 创建 PR。
   - 如果没有权限或凭据，输出可直接使用的 PR 标题和完整描述。
   - Dev PR 合入后保留业务分支；Dev 验收通过后，按 Master PR Mode 由同一分支提 PR 到 `master`。

## PR Description

PR 描述必须完整，不只写一句摘要。至少包含：

```markdown
## Summary
- 说明这次改动解决了什么问题
- 说明核心实现方式
- 说明对调用方或运行时行为的影响

## Changes
- 列出主要代码改动
- 列出配置、文档、测试改动

## Tests
- 写明实际运行的测试命令
- 写明测试结果

## Risks
- 写明兼容性、配置、异步行为、数据一致性、回滚风险
- 如果没有明显风险，也要写 `No known high-risk items`

## 门槛自查
- 车道：L1 / L2 / L3（由 flow-router 判定）
- [ ] 改动范围测试已跑过且全绿（命令与结论见 Tests）
- [ ] 契约改动已同步文档（`check_docs_sync.py` 绿）且语义已核对（contract-guard）—— L1 无契约变更可标 N/A
- [ ] acceptance 已提升到 `tests/acceptance/features/` —— L1 / 无 acceptance 可标 N/A
- [ ] Master PR 已关联 Dev PR、验收 SHA 与测试证据 —— Dev PR 阶段标 N/A
```

如果 PR 涉及外部服务、MQ、数据库、对象存储、LLM 或异步任务，必须在 `Risks` 中说明运行时前提和潜在影响。

## Final Response

最终回复包含：

- 创建的分支名。
- 提交哈希和提交信息。
- 当前阶段的 PR URL；Master PR 阶段同时给出关联 Dev PR 与验收 SHA。
- 已运行的测试命令和结果。
- 是否有未纳入本次提交的本地修改。
