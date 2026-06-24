---
name: component-skill-author
description: 把项目里已有的内部组件（如 MQ 中台、解析 pipeline、缓存层、对象存储）抽象成一份「项目自有 skill」，让 AI 每次接入都自动复用该组件的架构边界与约定。读组件真实代码，提炼「架构定位 / 职责边界 / 已落地清单 / 扩展点 / 红线」五要素，按统一原型生成 SKILL.md，登记到 .ai/skills/README.md 注册表并跑校验。
when_to_use: "当开发者想把某个现有组件/模块固化成 AI 可复用的 skill 时使用。触发示例：'把 MQ 组件做成 skill'、'给 pipeline 写个 skill'、'把这个模块的约定固化下来让 AI 每次都遵守'、'抽象现有组件加入 skill 体系'。边界：从零创建任意 skill、优化 description、跑 eval → 转 skill-creator（通用元能力）；只补模块文档不做 skill → 转 doc-maintenance-sync。本 skill 只做『把已有代码组件 → 项目自有 skill』这一件事。"
---

# Component Skill Author

## 1. 定位

skill 分两类：**套件托管**（flow-router、brief-generator 这种谁的项目都能用的通用方法论）和**项目自有**（mq-middleware 这种只有本项目才有的组件知识）。本 skill 专门生产后者。

它解决一个具体问题：项目里有些组件（MQ 中台、解析 pipeline、缓存层…）有自己的架构和约定，希望 **AI 每次接入都遵守、复用，而不是每次重新摸索或自由发挥**。办法就是把这份组件知识固化成一份 skill 放进 `.ai/skills/`——AI 启动会自动扫描并按 description 触发。

本 skill **不产出业务代码、不改组件本身**。它只读组件代码，把"这个组件是什么、边界在哪、有哪些约定、不能怎么做"提炼成一份给 AI 看的工作指令。

> 黄金参照：[.ai/skills/mq-middleware/SKILL.md](.ai/skills/mq-middleware/SKILL.md) 就是一份成熟的项目自有组件 skill，本 skill 的原型即从它提炼。

## 2. 触发边界

### 2.1 适合
- 开发者指着一个现有模块/目录，说"把它做成 skill / 固化它的约定让 AI 遵守"。
- 组件有稳定的架构边界和约定，值得让 AI 每次复用。

### 2.2 不适合 / 转交
- 从零创建任意 skill、优化 description、跑 eval → `skill-creator`（通用元能力）。
- 只想补一篇模块说明文档，不做 skill → `doc-maintenance-sync`。
- 组件还在剧烈变动、边界没定型 → 先稳定代码再来抽象，否则 skill 一写就过期。

## 3. 产出物：组件 skill 五要素

每份组件 skill 必须覆盖这五块（顺序固定，缺一补一）：

| 要素 | 回答什么问题 | 来源 |
| --- | --- | --- |
| **① 架构定位** | 这个组件在系统里是什么、统一入口在哪、AI 应优先调谁而不是绕过去 | 读入口文件 / 工厂 / service 层 |
| **② 职责边界** | 每个文件/子目录负责什么（**贴真实路径**） | 遍历组件目录 |
| **③ 已落地清单** | 现有的消息/阶段/接口/适配器**逐条列出**（AI 据此知道"已经有啥"） | 扫描具体实现文件 |
| **④ 扩展点** | 要新增一个同类东西，按什么步骤、放哪、改哪 | 读现有同类实现的模式 |
| **⑤ 红线** | 哪些写法是反模式、明确不要做 | 读注释/约定，或与开发者确认 |

frontmatter 额外带一个 `tracks:` 字段，声明本 skill 描述的组件对应哪些代码路径——用于将来代码改动时提醒"组件变了，回来更新这份 skill"（呼应 §6 的防过期）。

## 4. 工作步骤

**步骤 1 — 圈定组件范围**。和开发者确认要抽象的组件目录/入口（如 `src/core/mq/`、`src/core/pipeline/parse_task/`）。范围要清晰：一个组件一份 skill，不要把两个无关组件塞进一份。

**步骤 2 — 读代码、提炼五要素**。遍历组件目录，按 §3 的五要素逐项填。要求：
- 职责边界和已落地清单**贴真实文件路径与符号名**，不写"某模块""某消息"。
- 已落地清单**逐条核对当前真实存在的实现**，不照搬记忆、不列已删除的东西。
- 拿不准的红线/约定，**问开发者**，不要编。

**步骤 3 — 生成 SKILL.md**。用 §5 原型填好 frontmatter（`name` = 目录名、`description`、`when_to_use`、`tracks`）和五要素正文。

**步骤 4 — 落盘 + 登记 + 校验**：
1. 写到 `.ai/skills/<component-name>/SKILL.md`。
2. 在 [.ai/skills/README.md](.ai/skills/README.md) 注册表对应类别加一行（职责 + 边界/转交）。
3. 跑 `python scripts/quality/check_skills.py`，确保 0 error（会校验 frontmatter、死路径引用、技术栈一致性）。
4. 若项目结构树需同步，转 `agents-tree-sync`。

## 5. 组件 skill 原型模板

照填即可（`<...>` 替换成真实内容）：

```markdown
---
name: <component-name>
description: <这个组件是什么 + 本 skill 让 AI 在接入时复用它的哪些边界/约定>
when_to_use: "<触发示例：'接入<组件>'、'新增<组件里的东西>'、'改<组件>'>。边界：<什么情况转给谁>。"
tracks:
  - src/your_component/**          # 替换成组件真实目录
---

# <组件名> Skill

## 1. 架构定位
<组件在系统里的角色；统一入口（service/factory）；AI 应优先调谁，不要绕过去直接 new 底层>

## 2. 职责边界
- `<path/to/entry.py>`：<职责>
- `<path/to/sub/>`：<职责>
（逐个文件/子目录贴真实路径）

## 3. 当前已落地清单
- `<path/to/impl_a.py>`：<名称/标识，如 Topic、阶段名、接口路径>
- `<path/to/impl_b.py>`：<...>
（逐条列现有实现，AI 据此知道已经有啥）

## 4. 扩展点：要新增一个同类的怎么做
1. <在哪建文件>
2. <继承/实现什么、注册到哪>
3. <要同步改的清单（如 __init__ 导出、工厂注册、本 skill 的已落地清单）>

## 5. 红线（不要这样做）
- <反模式 1>
- <反模式 2>
```

## 6. 质量门禁（不满足就重做）

- **路径真实**：职责边界/清单里的 `src/ scripts/ migrations/` 路径必须存在（`check_skills.py` 会扫死链报错）。
- **清单可核对**：每条已落地项对应一个真实文件/符号，不列已删除或想象的东西（避免重蹈"引用已删文件"的坑）。
- **红线明确**：至少给出该组件的关键反模式，否则 AI 仍会自由发挥。
- **tracks 准确**：声明的代码路径就是该组件的真实目录，将来才能据此提醒同步。
- **只写组件专属**：通用方法论不要塞进来（那是套件托管 skill 的事）；本 skill 只装"这个组件特有的边界和约定"。

## 7. 与其他 skill 衔接

- 通用创建 / description 优化 / eval → `skill-creator`
- 抽象完组件后要补模块说明文档 → `doc-maintenance-sync`
- 新增 skill 后同步项目结构树 → `agents-tree-sync`
