# Documentation Architecture

toLink-Rag 项目文档体系的设计、组织与治理总览。

**适用读者**：贡献者、维护者，以及参与代码与文档改动的 AI Agent。

**关联文档**：
- 同步机制操作细节：[doc_sync.md](doc_sync.md)
- 项目入口：[CLAUDE.md](../../CLAUDE.md) / [AGENTS.md](../../AGENTS.md)

---

## 1. 文档体系要解决什么问题

随着代码演进，文档常见三种失败模式：

| 失败模式 | 表现 | 本体系的对策 |
| --- | --- | --- |
| **过时** | 文档描述与现状不一致 | 显式标注"代码权威来源"，文档只做摘要与索引；自动检测漏同步 |
| **重复** | 同一事实在多处叙述，相互矛盾 | 单一来源原则，按存储介质/契约层级分文件 |
| **散乱** | 找不到要看哪份 | 顶层入口（CLAUDE.md）+ 五域分类 + 任务路由表 |

本文档说明体系**怎么设计**、**为什么这样设计**、以及**如何维护**。

---

## 2. 设计原则

以下原则贯穿全部目录与文档约定。新增或重构文档时，先用这些原则校验。

### 2.1 事实性（Authority pointing）

文档不与代码并列为"真实来源"，而是代码/配置/DDL 的**摘要与索引**。每篇参考类文档开头明确"代码权威来源"路径。

```
权威来源（不可变） → 文档（可摘要、可解读、可索引，但服从权威来源）
```

当文档与代码不一致：**修文档，不动代码**。

### 2.2 就近（Proximity）

文档与它描述的实现保持靠近：
- 模块级架构 → `docs/architecture/<module>_module.md`
- 配置项解读 → `docs/guides/configuration.md`（贴近 `.env.example`）
- 数据库 schema → `docs/reference/mysql_schema.md`（贴近 `scripts/db/init.sql`）

避免"通用集合"文档（如把所有数据模型混到一个文件）—— 这是上一版 `data_models.md` 失败的根因。

### 2.3 单一来源（Single source of truth）

每个事实**只在一处**正式描述。其他文档需要时通过链接引用，不复制内容：
- 字段定义 → 只在对应 schema 文档
- 配置默认值 → 只在 `configuration.md`
- MQ 消息载荷 → 只在 `mq_integration.md`
- 同步规则 → 只在 `.claude/doc-sync-rules.yaml`

`CLAUDE.md` 第五节的人读规则与 yaml 中的机器规则是**人/机两个视图**，但事实只有一份（yaml）。

### 2.4 分层（Stability layering）

按变化频率把文档分到不同目录，避免高频变更冲刷低频稳定知识：

| 频率 | 位置 | 例 |
| --- | --- | --- |
| 极低 | `docs/architecture/` | 模块边界、流程总线 |
| 低 | `docs/conventions/` | 命名、配置约定 |
| 低 | `docs/reference/` | API、schema、错误码 |
| 中 | `docs/guides/` | 部署、接入操作指南 |
| 中 | `docs/development/` | 流程、工具、规范 |

> 已删除的 `docs/design/`、`docs/plans/` 在本项目中证明是"伪需求"——设计/计划应该走 git 历史、PR 描述、issue，而不是常驻文档。

### 2.5 强制（Enforcement）

规则若只写在文档里，会被遗忘。本体系把核心同步规则**双轨化**：

- **人读版**：[CLAUDE.md](../../CLAUDE.md) 第五节
- **机器执行版**：[.claude/doc-sync-rules.yaml](../../.claude/doc-sync-rules.yaml) + [scripts/check_docs_sync.py](../../scripts/check_docs_sync.py)

两者必须保持一致。机器规则由 pre-commit 与 CI 强制执行。详见 [doc_sync.md](doc_sync.md)。

### 2.6 可被 Agent 阅读

文档同时面向人类与 Agent。意味着：
- 避免依赖项目隐式上下文的省略
- 显式列出"改动 X 必须看 Y"的对应关系
- 提供机器可读的规则文件供 Agent 解析
- 在容易踩坑的地方加 🤖 Agent 提示

---

## 3. 整体目录结构

```
toLink-Rag/
├── CLAUDE.md                              # Agent/开发者统一入口
├── AGENTS.md                              # CLAUDE.md 的镜像（Codex 兼容）
├── README.md                              # 面向用户的项目宣传与快速开始
├── .claude/
│   └── doc-sync-rules.yaml                # 同步规则（事实来源）
├── scripts/
│   └── check_docs_sync.py                 # 同步检测脚本
├── .pre-commit-config.yaml                # 本地 hook
├── .github/workflows/docs-sync.yml        # CI 检查
└── docs/
    ├── architecture/                      # 稳定架构：模块边界、流程、状态机
    ├── conventions/                       # 跨模块共享规则：命名、配置、测试
    ├── reference/                         # 契约：API、schema、错误码
    ├── guides/                            # 使用方/运维向：部署、接入、调试
    └── development/                       # 贡献者向：流程、规范、工具
```

---

## 4. 入口文档

三份"顶层文档"职责不同，必须保持清晰边界。

### 4.1 角色分工

| 文档 | 受众 | 内容职责 |
| --- | --- | --- |
| [README.md](../../README.md) | 外部用户、首次访问者 | 项目宣传、价值主张、快速开始的"看一眼即懂"版本 |
| [CLAUDE.md](../../CLAUDE.md) | 贡献者、AI Agent | 项目使用 + 文档目录的统一入口；按任务路由阅读路线 |
| [AGENTS.md](../../AGENTS.md) | Codex Agent | CLAUDE.md 的字字镜像（兼容性） |

**判断准则**：
- "我想用这个项目" → README.md
- "我要改这个项目" → CLAUDE.md
- "我是 Codex Agent" → AGENTS.md（自动指向 CLAUDE.md）

### 4.2 CLAUDE.md 的双重角色

[CLAUDE.md](../../CLAUDE.md) 同时承担两件事：

1. **项目使用说明**（第一节）：代码入口、快速启动、常用命令、配置约定。
2. **文档导航目录**（第二节及之后）：按域列出所有文档入口 + 按任务的查阅路线 + 工作规则 + 同步规则。

这样设计的好处：
- 一个文件就能让贡献者 / Agent 完成 "理解项目 + 找到文档" 的双重需求
- 不需要切换多个入口
- 与各模块详细文档保持单向引用关系（CLAUDE.md → docs/*），不重复内容

### 4.3 CLAUDE.md ↔ AGENTS.md 镜像

两者**内容完全一致**，原因：
- Codex 默认读 `AGENTS.md`，Claude 默认读 `CLAUDE.md`
- 维护两份避免 Agent 间行为差异
- 由 yaml 规则 `claude-md-mirror` / `agents-md-mirror` 强制（error 级别）

**维护方式**：改一边后 `cp CLAUDE.md AGENTS.md` 同步。pre-commit 会拦截只改单边的提交。

🤖 **Agent 提示**：修改 CLAUDE.md 时务必同步 AGENTS.md，否则 commit 会被阻止。

---

## 5. 文档分域职责

`docs/` 下五个目录的边界与典型内容。下表是判断"新文档应该放哪里"的依据。

### 5.1 职责矩阵

| 目录 | 描述对象 | 关键问题 | 受众 |
| --- | --- | --- | --- |
| `architecture/` | **代码如何实现** | 模块边界、跨模块流程、状态机、扩展点 | 内部开发者 |
| `conventions/` | **跨模块共享规则** | 命名、配置规范、测试约定 | 内部开发者 |
| `reference/` | **对外契约** | API、消息、schema、错误码 | 对接方 + 内部 |
| `guides/` | **如何使用系统** | 部署、接入、调试、运维 | 部署方、业务方 |
| `development/` | **如何参与开发** | 分支、PR、测试、文档治理 | 贡献者 |

### 5.2 判断流程图

```
新文档要写什么？
│
├─ 描述代码内部实现/边界？     → architecture/
├─ 描述跨模块的命名/规则约定？ → conventions/
├─ 描述对外契约（API/消息）？  → reference/
├─ 教别人怎么用/部署系统？      → guides/
└─ 教别人怎么参与/规范？        → development/
```

### 5.3 边界例子

容易混淆的几个典型场景：

| 写的内容 | 错误归属 | 正确归属 | 原因 |
| --- | --- | --- | --- |
| MQ 消息载荷字段定义 | architecture（写 mq_module） | **reference** + guides | 是对外契约，对接方关心 |
| 部署用 Docker Compose 步骤 | reference | **guides** | 是操作指南而非契约 |
| 命名约定 | conventions | conventions ✓ | 命名是跨模块规则 |
| 单元测试目录约定 | conventions | **development** | 是协作流程而非代码规则 |
| 数据库表结构 | architecture | **reference** | 是对 Java 侧的契约 |

### 5.4 不属于 docs/ 的内容

以下内容不应进入文档目录：

- **设计草稿、PRD、迭代计划**：放 git 分支 / PR 描述 / issue
- **会议记录、决策讨论**：放 wiki 或外部协作工具
- **临时性运维手册**：放运维系统
- **代码内部实现细节（如算法步骤）**：放代码 docstring

---

## 6. 同步治理机制

文档体系若无强制机制，再好的设计都会随时间衰退。本节是治理机制的**总览**，机制实操细节见 [doc_sync.md](doc_sync.md)。

### 6.1 三层结构

```
┌─────────────────────────────────────────────────────────┐
│  规则层：.claude/doc-sync-rules.yaml                    │  事实来源
│   - 19 条 "代码路径 → 必须同步文档" 映射                 │  人 & 机共读
│   - 每条带 severity (error/warning)                     │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│  执行层：scripts/check_docs_sync.py                     │  纯函数
│   - 解析 git diff                                        │  无副作用
│   - 对照规则                                             │
│   - 输出违规清单                                         │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│  集成层                                                  │
│   ① pre-commit hook (.pre-commit-config.yaml)           │  本地拦截
│   ② GitHub Actions (.github/workflows/docs-sync.yml)    │  CI 拦截
└─────────────────────────────────────────────────────────┘
```

### 6.2 触发时机

| 时点 | 触发器 | 范围 | 行为 |
| --- | --- | --- | --- |
| `git commit` 前 | pre-commit hook | staged 文件 | error 阻止 commit，warning 提示 |
| PR / push | GitHub Actions | 与 base 分支的 diff | error 阻止 merge |
| 手动 | `python scripts/check_docs_sync.py --staged` 等 | 视参数而定 | 输出违规清单 |

### 6.3 Severity 分级

| 级别 | 用于 | 示例规则 |
| --- | --- | --- |
| **error** | 对外契约、终态语义、双向镜像 | `mysql-schema`, `mq-contracts`, `pipeline-orchestration`, `claude-md-mirror` |
| **warning** | 内部模块行为变化 | `parser-module`, `chunking-module`, `runtime-config` |

分级的理由：契约失同步会引发集成 bug（Java 侧用错字段），内部模块文档过时只是文档质量问题（仍要修，但不阻塞）。

### 6.4 规则的演进

新增规则的标准触发条件：
- 新增了一个模块目录（如 `src/core/cache/`）且有对应文档
- 出现了新的对外契约文件
- 新增了重要配置入口

调整规则的注意点：
- 不要让单条规则过宽（如 `src/**/*.py`），会误报
- 规则缺失比规则过宽更可接受
- 修改规则后跑 `python scripts/check_docs_sync.py --self-check`

---

## 7. 维护工作流

### 7.1 新增文档

```
1. 选定目录（参见 §5.2 判断流程图）
2. 文件命名（参见 §7.4 命名约定）
3. 撰写内容（参见 §7.5 文档模板要点）
4. 更新该目录的 README.md（追加到"当前文档"列表）
5. 如属于"必须同步"类，更新：
   - .claude/doc-sync-rules.yaml 加规则
   - CLAUDE.md 第五节同步表
6. 如属于核心入口类，更新 CLAUDE.md 第二节文档目录
7. AGENTS.md 同步（如改了 CLAUDE.md）
8. 运行 python scripts/check_docs_sync.py --staged
```

### 7.2 修改现有文档

```
1. 改前阅读 CLAUDE.md 第五节，确认本次会触动哪些规则
2. 编辑文档
3. 检查内部链接是否仍有效
4. 如改了规则文件本身，跑 --self-check
5. 提交（pre-commit 会自动校验）
```

### 7.3 删除/重命名文档

```
1. 全仓库搜索引用：grep -rn "<old_path>" --include="*.md"
2. 更新所有引用方
3. 如属于 yaml 规则中的 must_update，同步更新规则文件
4. 如属于 CLAUDE.md 第二节列表，同步更新
5. AGENTS.md 同步
```

### 7.4 命名约定

- 文件名：snake_case，全小写，`.md` 后缀
- 域名前缀：架构模块统一 `<name>_module.md`（如 `chunking_module.md`）
- 表/索引参考：`<storage>_schema.md`（如 `mysql_schema.md`）
- 操作指南：动词或场景名词（如 `deployment.md`, `configuration.md`）
- 流程文档：领域 + 动作（如 `branching_and_pr.md`, `doc_sync.md`）

### 7.5 文档模板要点

每篇文档应包含：

```markdown
# <Title>

<一句话定位文档作用>

<可选：代码权威来源指向>

## 正文章节...

## 相关文档

- 关联文档列表
```

参考类文档额外要求：
- 开头明确"代码权威来源"路径
- 字段表用 markdown table，列：字段名 / 类型 / 必填 / 说明
- 不要复制代码注释——指向代码即可

架构类文档额外要求：
- 包含模块边界（输入、输出、依赖）
- 包含关键流程图或状态机
- 包含扩展点说明

### 7.6 跨域文档的处理

某些主题会跨越多个域。处理原则：**选定一个主域，其他域只放链接**。

例：MQ 消息载荷
- 主文档：[mq_integration.md](../guides/mq_integration.md)（业务方对接视角）
- 在 [mq_module.md](../architecture/mq_module.md) 留链接而非重复字段表
- 在 [api_contracts.md](../reference/api_contracts.md) 留链接而非重复

---

## 8. 角色与责任

### 8.1 贡献者

- 改代码时按 §7.1-7.3 流程同步文档
- 不规避 pre-commit（不使用 `--no-verify` 除非有 hotfix 理由）
- PR 描述中注明涉及的文档变更
- 评审他人 PR 时检查文档是否同步

### 8.2 Reviewer

- 验证 CI doc-sync 通过
- 检查文档是否真的反映了改动（不是空占位）
- 对违反 §2 设计原则的改动提出修改意见

### 8.3 AI Agent

🤖 **Agent 工作协议**：

```
1. 阅读阶段：
   - 始终先读 CLAUDE.md
   - 按任务从第三节查阅路线选择最小必要文档集

2. 改动阶段：
   - 改动前查 CLAUDE.md 第五节，识别本次会触发的同步规则
   - 把对应文档纳入读/改清单

3. 提交阶段：
   - 主动运行 python scripts/check_docs_sync.py --staged
   - 如有违规，先补文档再提交
   - 改了 CLAUDE.md 必须 cp 到 AGENTS.md

4. 不允许：
   - 用 --no-verify 绕过 pre-commit
   - 创建未在 README.md 列出的"占位"文档
   - 把同一事实复制到多个文档
```

---

## 9. 反模式与边界情况

### 9.1 反模式

| 反模式 | 为什么不好 | 正确做法 |
| --- | --- | --- |
| 创建空目录 + 仅 README | 等于在告诉读者"这里有东西"但其实没有 | 等真有内容时再建 |
| 在多个文档复制相同字段表 | 修改时必然漏改一处 | 选主文档，其他位置只放链接 |
| 把设计草稿、PRD 长期放 docs/ | 文档与决策记录混淆 | 决策放 PR 描述/issue |
| 文档与代码注释互相重复 | 维护成本翻倍 | 文档摘要 + 链接到代码 |
| 用文档替代代码 docstring | 找不到文档时也找不到 docstring | 公共接口必须有 docstring |
| 把 `docs/architecture/` 写成教程 | 混淆"架构"与"指南"边界 | 教程放 `docs/guides/` |

### 9.2 边界情况

**Q: 一个改动同时触发多条规则，但只能改其中部分文档怎么办？**

→ 如果是 error 级别规则，必须全部满足。如果确实有理由暂时跳过，在 PR 描述中说明，并立即创建 follow-up issue。

**Q: 文档和代码出现真正的冲突，谁对？**

→ 一律以代码为准修文档。如果代码本身就是 bug，先在 issue/PR 中明确"代码是 bug"再决定修哪边。

**Q: 是否所有文档都要由 yaml 规则覆盖？**

→ 不是。yaml 规则只覆盖"高频会改且容易漏同步"的部分。低频文档（如设计原则本身）靠人评审。

**Q: 项目早期文档很少时，体系是否过度？**

→ 是。当前项目规模适用本体系。更小项目可只保留 README + 一两个 doc。本体系适合 10+ 模块、跨语言对接、有 Agent 协作的中型项目。

---

## 10. 附录

### 10.1 当前文档清单

| 域 | 文档 | 主要内容 |
| --- | --- | --- |
| 入口 | [CLAUDE.md](../../CLAUDE.md) | 项目使用 + 文档导航 |
| 入口 | [AGENTS.md](../../AGENTS.md) | CLAUDE.md 镜像 |
| 入口 | [README.md](../../README.md) | 项目介绍、快速开始 |
| architecture | [project_structure.md](../architecture/project_structure.md) | 项目目录结构 |
| architecture | [parse_task_pipeline_module.md](../architecture/parse_task_pipeline_module.md) | 解析流水线模块 |
| architecture | [file_parser_module.md](../architecture/file_parser_module.md) | 文件解析模块 |
| architecture | [markdown_parser_module.md](../architecture/markdown_parser_module.md) | Markdown 解析模块 |
| architecture | [chunking_module.md](../architecture/chunking_module.md) | 分块模块 |
| architecture | [vectorization_module.md](../architecture/vectorization_module.md) | 向量化模块 |
| architecture | [mq_module.md](../architecture/mq_module.md) | MQ 模块 |
| architecture | [llm_module.md](../architecture/llm_module.md) | LLM 模块 |
| architecture | [object_storage_module.md](../architecture/object_storage_module.md) | 对象存储模块 |
| conventions | [naming_conventions.md](../conventions/naming_conventions.md) | 命名约定 |
| reference | [api_contracts.md](../reference/api_contracts.md) | HTTP API 契约 |
| reference | [error_codes.md](../reference/error_codes.md) | 错误码 |
| reference | [mysql_schema.md](../reference/mysql_schema.md) | MySQL 12 张表结构 |
| reference | [qdrant_schema.md](../reference/qdrant_schema.md) | Qdrant 向量库结构 |
| reference | [elasticsearch_schema.md](../reference/elasticsearch_schema.md) | ES 索引结构 |
| guides | [deployment.md](../guides/deployment.md) | 部署指南 |
| guides | [configuration.md](../guides/configuration.md) | 配置详解 |
| guides | [mq_integration.md](../guides/mq_integration.md) | MQ 接入指南 |
| development | [testing.md](testing.md) | 测试规范 |
| development | [code_style.md](code_style.md) | 代码风格 |
| development | [branching_and_pr.md](branching_and_pr.md) | 分支与 PR 流程 |
| development | [doc_sync.md](doc_sync.md) | 文档同步机制（操作） |
| development | documentation_architecture.md（本文） | 文档体系（设计） |

### 10.2 配套工具

| 文件 | 作用 |
| --- | --- |
| [.claude/doc-sync-rules.yaml](../../.claude/doc-sync-rules.yaml) | 同步规则（事实来源） |
| [scripts/check_docs_sync.py](../../scripts/check_docs_sync.py) | 检测脚本 |
| [.pre-commit-config.yaml](../../.pre-commit-config.yaml) | 本地 pre-commit 配置 |
| [.github/workflows/docs-sync.yml](../../.github/workflows/docs-sync.yml) | CI 检查 |

### 10.3 演进记录

| 版本 | 日期 | 关键变化 |
| --- | --- | --- |
| 1.0 | 2026-05-16 | 初版：建立五域分类、入口文档双轨化、引入三层同步治理机制 |

未来重大调整（如新增文档域、调整入口策略、引入文档生成器）应在此追加记录并在 PR 中显式标注。

---

**维护者**：项目开发组  
**最近修订**：2026-05-16  
**反馈渠道**：GitHub Issue（标签 `documentation`）
