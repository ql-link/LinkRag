---
name: branch-pr-workflow
description: 在 toLink-Rag 实现、验证和审查完成后，从最新 master 准备同一业务分支，先创建到 dev 的 PR，Dev 验收后再由未变化的同一分支创建到 master 的 PR。禁止 dev 直接发布到 master。
---

# 分支与 PR 交付

## 不变量

1. 业务分支基于最新远端 `master`，不能基于 `dev`。
2. 先由业务分支 PR 到 `dev`；Dev 验收通过后，再由未变化的同一业务分支 PR 到 `master`。
3. 禁止 `dev -> master`，禁止从 `dev` 派生发布分支，也不把 `dev` merge、rebase 或 cherry-pick 到业务分支。
4. Dev 验收后业务分支 SHA 发生变化，必须重新进入 Dev PR 与验收流程。
5. 保留并隔离用户的无关未提交修改，不覆盖、不重置、不混入提交。

## 收口门槛

创建 PR 前必须在当前可提交内容上：

- 使用 `run-all-tests` 完成范围匹配的验证，并执行仓库当前要求的完整本地门禁；
- 修改 `.ai/skills/**` 时通过 `python scripts/quality/check_skills.py`；
- 通过 `python scripts/quality/check_docs_sync.py --staged` 与 `--self-check`；
- 公共 HTTP/MQ/配置/schema 契约已核对消费方和兼容语义；
- 方案选择契约验收且场景需要成为长期自动化回归时，已使用 `python scripts/acceptance/promote_acceptance.py <KEY>` 提升、补齐 steps 并实际运行；仅存在本地 Gherkin 不算测试通过；
- 必要的真实 MQ、MySQL、对象存储、向量库、模型或 Java 联调证据已记录；没有执行时必须明确为未验证，不能伪装成通过；
- `code-review-and-quality` 没有未关闭的 Critical 或 Required 问题。

任一必要门槛失败或环境阻塞时停止创建 PR，并准确报告。共享 CI 是独立证据，不能补写本地未执行结果。

## 分支与提交

先检查当前分支、状态、差异和远端拓扑。新分支命名使用：

- `feature/<topic>`：新增能力；
- `fix/<topic>` 或 `hotfix/<topic>`：普通或紧急修复；
- `refactor/<topic>`：无业务行为变化的重构或优化；
- `chore/<topic>`：依赖、工具、文档和 CI。

只暂存本次文件，使用约定式提交。不得因为进入本技能就获得 push、PR、合并或发布授权；逐项服从用户当前请求。

## Dev PR

刷新远端引用，确认业务分支的 master 基线与净差异。创建或复用 `head=<业务分支>, base=dev` 的 PR。正文至少包含：

```markdown
## Summary
- 实际解决的问题和可观察结果

## Changes
- 主要代码、契约、迁移、配置、文档和测试改动

## Validation
- 本地实际命令与结果
- 人工或真实环境验收结果
- 未执行和未覆盖区域

## Risks
- 兼容、数据、配置、MQ、异步、回退和运行时前提

## Delivery checks
- [ ] 当前差异的本地门禁通过
- [ ] 契约和文档同步已核对，或 N/A
- [ ] Acceptance 已提升并实现，或 N/A（说明理由）
- [ ] 人工/真实环境验收完成，或明确未验证
```

存在来源 Issue 时，PR 创建后只补一条交付评论，给出 PR、实际结果、重要差异和遗留项；不改 Issue 正文或状态，不发送逐阶段进度评论。

## Master PR

用户明确要求发布收口时：

1. 刷新业务分支、`dev` 和 `master` 远端状态；
2. 确认同一业务分支的 Dev PR 已合入，并记录验收 SHA 和证据；
3. 确认验收后分支未变化；
4. 复用已有 `head=<业务分支>, base=master` PR，或创建新的 Master PR；
5. 关联 Dev PR、验收 SHA、测试结果、迁移、配置、文档、风险和回退。

若同步 master 或解决冲突改变分支 SHA，先返回 Dev 重新验收。Master PR 合入和 tag 都需要独立授权。

## 最终报告

说明分支、提交、PR URL、base/head、实际验证、Dev 验收 SHA（Master 阶段）、未纳入提交的本地修改，以及所有未验证或阻塞项。
