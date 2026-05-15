# Documentation Sync

如何在改动代码时自动保证对应文档同步更新。

## 为什么需要这套机制

`CLAUDE.md` 第五节列了"改 X 必须改 Y"的规则，但**纯文字约定容易被遗忘**——尤其是 Agent 频繁改动时。

本机制把这些规则结构化为**机器可读的映射**，由检测脚本在两个时点强制：

| 时点 | 工具 | 强度 |
| --- | --- | --- |
| 本地提交前 | pre-commit hook | 阻止漏同步的 commit |
| PR / push 后 | GitHub Actions | 阻止漏同步的合并 |

## 组成

```
.claude/doc-sync-rules.yaml      # 规则定义（事实来源）
scripts/check_docs_sync.py       # 检测脚本
.pre-commit-config.yaml          # 本地 hook 配置
.github/workflows/docs-sync.yml  # CI 配置
```

## 规则格式

`.claude/doc-sync-rules.yaml` 中每条规则结构：

```yaml
- id: mysql-schema                            # 唯一标识
  description: MySQL DDL 或 ORM 变更         # 简短说明
  when_changed:                                # 触发条件（任一命中）
    - scripts/db/init.sql
    - src/models/**/*.py
  must_update:                                 # 必须同步（任一缺失即违规）
    - docs/reference/mysql_schema.md
  severity: error                              # error 阻止 / warning 提醒
  rationale: 数据库 schema 是契约...           # 为什么这条规则重要
```

### Severity 取值

| 值 | 行为 |
| --- | --- |
| `error` | 违规时退出码 1，阻止 commit / merge |
| `warning` | 违规时打印提示，不阻止 |

当前规则集（19 条）的分级原则：
- **error**：对外契约（DDL、MQ 消息、流水线终态、入口文档双向同步）
- **warning**：内部模块行为变化（解析器、分块、向量化等）

## 安装本地 hook

```bash
# 一次性：安装 pre-commit 工具
pip install pre-commit

# 在仓库内启用
pre-commit install
```

之后每次 `git commit` 都会先运行检测脚本。漏同步时：

```
[ERROR] mysql-schema: MySQL DDL 或 ORM 变更
  ↳ changed: scripts/db/init.sql
  ✗ missing update: docs/reference/mysql_schema.md
  why: 数据库 schema 是 Java/Python 双方契约...
```

修好后再 `git add` 对应文档，重新 commit 即可。

## 手动运行

```bash
# 检查暂存区（pre-commit 内部用的就是这个）
python scripts/check_docs_sync.py --staged

# 检查工作区所有改动（含未 staged）
python scripts/check_docs_sync.py --working

# 检查相对某分支的 diff（CI 用的就是这个）
python scripts/check_docs_sync.py --base origin/dev

# 仅验证规则文件本身合法
python scripts/check_docs_sync.py --self-check

# 把 warning 也当 error
python scripts/check_docs_sync.py --staged --warning-as-error
```

退出码：
- `0` — 无 error 级违规（warning 不影响）
- `1` — 有 error 级违规
- `2` — 配置或运行错误（yaml 不合法、git 不可用等）

## CI 集成

`.github/workflows/docs-sync.yml` 在以下事件触发：
- PR 到 `main` / `dev`：比对 PR base 与 head 的 diff
- push 到 `dev` / `main`：比对前一个 commit 的 diff

检测失败时 PR 会显示红叉，需要补齐文档后重新推送。

## 新增规则

**何时新增**：当一个新的"代码改动 → 文档同步"关系出现时。例如新增一个 `src/core/cache/` 模块，且有对应架构文档：

1. 编辑 `.claude/doc-sync-rules.yaml`，追加一条规则：
   ```yaml
   - id: cache-module
     description: 缓存模块变更
     when_changed:
       - src/core/cache/**/*.py
     must_update:
       - docs/architecture/cache_module.md
     severity: warning
   ```

2. 验证 yaml 合法：
   ```bash
   python scripts/check_docs_sync.py --self-check
   ```

3. 同步本文件的"组成"或"规则集"描述（如有必要）。

## Glob 语法

| 模式 | 匹配 |
| --- | --- |
| `*.py` | 当前目录所有 `.py` 文件 |
| `src/**/*.py` | `src/` 下任意层级的 `.py` 文件 |
| `src/core/mq/messages/*.py` | 仅 `messages/` 直接子文件 |
| `scripts/db/init.sql` | 精确路径 |
| `?` | 单个非 `/` 字符 |

不支持 gitignore 的 `!` 否定、字符类 `[abc]`。

## 边界情况

### 重命名文件

`git diff` 默认会把 `R`（renamed）视作 ACMR 的一部分，规则把"新旧两份路径"都纳入 changed 集合。如果新路径仍命中 `when_changed`，要求会保留。

### 一次大型改动

一个 commit / PR 改了几十个文件时，违规清单可能很长。脚本会全部列出。建议拆分 PR——一次只改一个主题，文档变更自然限定在小范围。

### 误触发

如果一条规则太"广"导致误报（如 `src/**/*.py` 触发了不相关的文档要求），考虑：
- 缩小 `when_changed` 范围（用更精确的子目录）
- 拆成多条规则，按子模块归集

### 紧急 hotfix

需要绕过时（如阻塞 P0 修复）：
- 本地：`git commit --no-verify` 跳过 pre-commit
- CI：合并 PR 时手动 override（仓库策略允许的话）

但事后**必须**补 follow-up PR 同步文档，否则规则形同虚设。

## 与 CLAUDE.md 的关系

`CLAUDE.md` 第五节是**人读的规则总览**，本机制是**机器执行的强制版本**。两者必须保持一致：

- 增加机器规则后，回头确认 `CLAUDE.md` 第五节是否覆盖该场景
- 调整 `CLAUDE.md` 第五节时，考虑是否能落到 yaml 规则

`claude-md-mirror` 与 `agents-md-mirror` 两条规则确保了 `CLAUDE.md` 和 `AGENTS.md` 永远双向同步。

## 相关文档

- 规则文件：[.claude/doc-sync-rules.yaml](../../.claude/doc-sync-rules.yaml)
- 检测脚本：[scripts/check_docs_sync.py](../../scripts/check_docs_sync.py)
- 项目入口：[CLAUDE.md](../../CLAUDE.md)
- 分支与 PR 流程：[branching_and_pr.md](branching_and_pr.md)
