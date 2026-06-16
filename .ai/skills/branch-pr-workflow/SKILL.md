---
name: branch-pr-workflow
description: 当用户认为当前模块代码实现完毕，且当前分支应为 dev，需要从 dev 基于当前修改创建规范分支、提交并发起合并到 dev 的 GitHub PR 时使用。适用于“从 dev 新建分支”“把当前修改提 PR”“实现完成后创建 feature/refactor 分支并 PR”等交付收口场景。本 skill 是交付链终点，并在建分支/提 PR 前执行收口门槛：测试未过、契约文档失同步、acceptance 未提升者拒绝收口。
when_to_use: "当代码实现完成、准备从 dev 新建规范分支并发起合并 PR 时（交付链终点）激活。触发示例：'代码写完了提个 PR'、'从 dev 建个分支提交'、'实现完成创建 feature 分支并 PR'。进入即执行收口门槛校验：测试未全绿 / 契约改动未同步文档 / acceptance 仍停在 .specs 未提升时，停止并回退到对应 skill（run-all-tests、contract-guard、acceptance-generator），不强行收口。"
---

# Branch PR Workflow

## Goal

在当前模块实现完成后，把 `dev` 上的当前修改安全迁移到规范分支，并创建合并回 `dev` 的 PR。

## Preconditions

1. 当前仓库必须在 `dev` 分支。
2. 当前工作区应包含本次模块实现需要提交的修改。
3. 不要把无关本地修改混入分支、提交或 PR。

如果当前分支不是 `dev`，停止并说明当前分支；不要自动切分支。

## 收口硬门槛（建分支 / 提 PR 前必须满足）

本 skill 是交付链终点，进入即先做收口门槛校验。门槛分两层——**机器层已能真正 block，prompt 层靠自觉 + 留痕**。任一门槛不满足，停止收口并回退到对应 skill，不强行建分支或提 PR。

### 机器层（pre-commit / CI 真拦截，本 skill 只负责触发与确认）

这些门槛由仓库已有机器规则强制，提交时自动执行，无需在此重写逻辑——只需确认它们已通过：

- **契约文档同步**：改动触碰 `src/models/**`、`src/core/mq/messages/**`、`src/core/pipeline/parse_task/**` 等契约点时，[scripts/doc-sync-rules.yaml](../../../scripts/doc-sync-rules.yaml) 要求同步对应文档，缺一即 block commit。提交前先跑 `python scripts/check_docs_sync.py --staged` 确认为绿。
- **skill 质量**：若本次改了 `.ai/skills/**`，`python scripts/check_skills.py` 必须为绿。
- **全量测试**：CI 跑 `tests` 全量，未全绿不得合并。

### prompt 层（机器看不见，靠自觉执行 + PR 留痕）

这些项无法被机器在提交时判定（如 `acceptance.feature` 在 git-ignored 的 `.specs/` 内，git 看不见"欠提升"），因此作为软门槛执行，并在 PR 描述的「门槛自查」中如实勾选、可追责：

- **改动范围测试已跑过且全绿**：执行了与本次改动匹配的测试（不只依赖 CI），有结论。未跑 → 回退 `run-all-tests`。
- **契约语义已核对**：若触碰公共契约，除文档同步外，还需确认改动不破坏对端消费语义。未核对 → 回退 `contract-guard`（破坏性判断）/ `config-contract-sync`（跨端取值一致）。
- **acceptance 已提升**：本 feature 的 `acceptance.feature` 已从 `.specs/<feature>/` 提升到 `tests/acceptance/features/<name>.feature`。提升用脚本完成，不再手工 copy：
  ```bash
  python scripts/promote_acceptance.py <feature>
  ```
  它搬运 + 改名(kebab→snake) + scaffold `test_/steps` + 令两版逐字一致，并校验 0 个 undefined step；返回非 0(仍有未实现 step)→ 补全 step 后重跑。仍停在 `.specs/` → 回退 `acceptance-generator` 提升后再收口。提升后的 `tests/acceptance` 由 CI(`acceptance-steps.yml`)守 undefined step，对全员生效。

### L1 快车道豁免

`flow-router` 判为 **L1** 的改动（单文件 / 配置 / 文案 / 小修，无契约变更），契约门槛与 acceptance 提升门槛天然不触发，只需过测试门槛即可收口——避免小改动被全套门槛卡死。

## Branch Naming

分支名前缀根据修改性质选择：

- `feature/`：新增能力、新接口、新流程、新模块、新用户可见行为。
- `refactor/`：重构、结构调整、性能优化、内部实现替换，且没有新增业务能力。

分支主题来自当前修改内容，使用英文小写单词，并用 `_` 分割：

```text
feature/pdf_async_image_enhancement
refactor/parser_entry_pipeline
```

避免使用空格、中文、驼峰、连续分隔符和泛泛名称，例如 `feature/update`。

## Workflow

1. 检查状态：
   - `git branch --show-current`
   - `git status --short --branch`
   - `git diff --name-only`

2. 理解当前修改：
   - 用 `git diff --stat` 和必要的文件 diff 判断改动范围。
   - 识别无关修改。若无关修改会混入提交，先向用户说明并只暂存相关文件。

3. 决定分支类型和名称：
   - 新增功能用 `feature/<topic_with_underscores>`。
   - 重构/优化用 `refactor/<topic_with_underscores>`。
   - 如果类型不明确，根据 diff 的主要意图做保守判断，并在最终说明中写明依据。

4. 从当前 `dev` 创建分支：
   - 使用 `git switch -c <branch-name>`。
   - 当前未提交改动会随工作区留在新分支上。

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
```

如果 PR 涉及外部服务、MQ、数据库、对象存储、LLM 或异步任务，必须在 `Risks` 中说明运行时前提和潜在影响。

## Final Response

最终回复包含：

- 创建的分支名。
- 提交哈希和提交信息。
- PR URL；如果无法创建 PR，给出原因和可手动使用的标题/描述。
- 已运行的测试命令和结果。
- 是否有未纳入本次提交的本地修改。
