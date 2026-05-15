# Branching & PR Workflow

分支策略、提交规范、PR 流程。

## 分支结构

| 分支 | 角色 | 谁能推 |
| --- | --- | --- |
| `main` | 稳定发布分支 | 仅通过 PR 合入，不直接推 |
| `dev` | 当前迭代集成分支 | 多人协作，通过 PR 合入 |
| `feature/<topic>` | 功能开发分支 | 开发者本人 |
| `refactor/<topic>` | 重构 / 文档同步分支 | 开发者本人 |
| `chore/<topic>` | 杂项（依赖、工具、配置） | 开发者本人 |
| `optimize-<topic>` | 性能或局部优化（无强制 prefix）| 开发者本人 |

实际仓库中可观察到的分支模式：

```
feature/document_parse
feature/markdown_parser
feature/pdf_async_image_enhancement
refactor/parse-task-pipeline
refactor/docs_update
chore/skills
```

## 命名规则

- 用 `/` 区分类型与主题，主题用 kebab-case 或 snake_case 二选一并保持一致。
- 主题要描述**结果**，不是过程：
  - ✅ `feature/pdf-async-image-upload`
  - ❌ `feature/fix-pdf-bug`（"fix bug" 太笼统）
- 一个分支只做一件事；跨多个主题应拆分多个分支。

## 提交信息

格式：

```
<类型>(<可选范围>): <动作> <对象>
```

类型与项目历史保持一致：

| 类型 | 何时用 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | bug 修复 |
| `refactor` | 重构（不改变行为） |
| `docs` | 文档变更 |
| `test` | 测试变更 |
| `chore` | 依赖、工具、CI、杂项 |
| `perf` | 性能优化 |

示例（来自实际历史）：

```
feat(parser): 支持 PDF 图片异步上传与内存增强
feat(pipeline): 记录解析后处理流程状态
docs: 同步 architecture documentation
refactor: 更新解析模块架构与文档结构
```

要点：

- 主题行 ≤ 70 字符，正文按需补充"为什么"。
- 中文 / 英文皆可，单仓库内保持一致。
- 一次提交一个原子改动，避免"杂烩"提交。

## PR 流程

### 1. 创建分支

```bash
git checkout dev
git pull
git checkout -b feature/<topic>
```

### 2. 开发与提交

按"提交信息"规范多次小步提交。**不要**在 PR 准备阶段做无关清理。

### 3. 同步上游

```bash
git fetch
git rebase dev   # 或 git merge dev，团队选一种
```

### 4. 自检清单

提交 PR 前确保：

- [ ] `black src tests` 通过
- [ ] `isort src tests` 通过
- [ ] `mypy src` 无新增报错
- [ ] `pytest tests/unit` 全部通过
- [ ] 改动覆盖了对应测试（新增/修改路径）
- [ ] 涉及契约/配置/DDL 时，文档已同步（见 [CLAUDE.md](../../CLAUDE.md) 第五节）
- [ ] 不引入未使用的依赖

### 5. 创建 PR

- **基线分支**：通常是 `dev`（feature/refactor/chore 都合入 dev）。
- **标题**：与提交信息同风格，≤ 70 字符。
- **正文**：说明改动动机、关键设计选择、风险点；不要重复 diff 已表达的信息。
- **关联**：链接 issue / PRD / 设计文档（如有）。

### 6. 评审与合入

- 评审过程中按反馈追加 commit，不要 rebase 抹掉历史（除非 reviewer 要求）。
- 合并方式由仓库设置决定（squash / rebase / merge），不要绕过设置。

### 7. 合并后

- 删除已合并的本地与远程分支：
  ```bash
  git checkout dev && git pull
  git branch -d feature/<topic>
  git push origin --delete feature/<topic>
  ```

## 禁忌

- ❌ 直接推 `main` 或 `dev`（即使有权限）
- ❌ 在 PR 中夹带不相关改动（"顺便"清理无关文件）
- ❌ 用 `--force` 推已被他人 review 的分支
- ❌ 跳过 pre-commit hook（`--no-verify`）
- ❌ 提交未通过单元测试的代码

## 文档同步

代码改动若涉及以下范围，PR 中必须同步对应文档（见 [CLAUDE.md 第五节](../../CLAUDE.md#五文档同步规则)）：

| 改动 | 同步位置 |
| --- | --- |
| 模块边界、流程、状态机 | `docs/architecture/*_module.md` |
| API、错误码、消息契约 | `docs/reference/` |
| 命名、配置、测试规则 | `docs/conventions/` |
| 部署、接入步骤 | `docs/guides/` |
| 项目目录结构 | `docs/architecture/project_structure.md` |
| 入口/导航变化 | `CLAUDE.md` 与 `AGENTS.md` |

## 相关文档

- 测试规范：[testing.md](testing.md)
- 代码风格：[code_style.md](code_style.md)
