---
name: cowork-issue-sync
description: 当用户要提 issue、登记 bug、记录新需求时使用；自动识别所属项目，生成结构化 issue 内容，先在 Linear 建主记录、再在 GitHub 建镜像，并双向回链。用户说"提个 issue""记一下这个 bug""把这个需求登记一下""同步到 Linear 和 GitHub""别再依赖 Linear 自动同步"时都应触发，即使没有明确说出"Linear"或"GitHub"。
when_to_use: "提 issue、登记 bug、记录新需求、同步到 Linear、同步到 GitHub、用 Cowork 建需求、把当前需求记到 Linear 和 GitHub、不要再依赖 Linear 自动同步。"
---

# Cowork Issue Sync

把一个想法或问题，落成 Linear 和 GitHub 上一对结构化、可跟踪、互相链接的 issue。

这个 skill 存在的前提是：团队**关掉了 Linear team 对 GitHub 的自动同步**，改成手动控制。所以它要替代那套自动化——在两个平台各建一条 issue，并保证它们能互相找到对方。

它不负责创建分支、写代码、发 PR（那是 `branch-pr-workflow`），也不跟踪 issue 后续的状态流转。它只做"把 issue 立起来"这一件事。

## 一条主线：Linear 是主体，GitHub 是镜像

整个流程的顺序和链接方向，都从这条原则推出来，理解了它就不用死记步骤：

```
Linear issue（主记录，先建）
   │  GitHub URL 写进 Linear 的 links 区域
   ▼
GitHub issue（镜像，后建）
   │  Linear URL 写进 GitHub 正文末尾
   ▼
两边互相可达
```

**为什么 Linear 先建**：Linear 是团队做项目管理、排期、分配的地方，是这条 issue 的"户口"。GitHub issue 只是给代码协作用的副本。先建主记录，意味着即使后面 GitHub 建失败，这条需求也已经被正式跟踪了，不会丢。反过来先建 GitHub，一旦 Linear 失败，就出现一个没人管的孤儿 issue。

**为什么链接方向是反的**（GitHub 链接放 Linear 的 links 区，Linear 链接放 GitHub 正文）：两个平台的"放外部链接"能力不一样。Linear 有专门的 links / attachments 区域，就是干这个的，用它能让正文保持干净；GitHub 没有这种结构化区域，只能写进正文，所以在末尾追加一个 `## Linear` 段落。不是随意规定，是顺着各自的原生能力来。

## 项目映射

Team 固定 `QIngluo`（key `LINK`）。三个项目和 GitHub 仓库一一对应，名字本身就是映射，不需要额外转换规则：

| 对话/仓库归属 | Linear project | GitHub repo |
| --- | --- | --- |
| Python 端 / LinkRag | `LinkRag` | `ql-link/LinkRag` |
| Java 端 / LinkRag-Service | `LinkRag-Service` | `ql-link/LinkRag-Service` |
| 前端 / LinkRag-Web | `LinkRag-Web` | `ql-link/LinkRag-Web` |

判断归属优先看当前工作区的 git remote，其次看用户明确提到的端。**只有在确实判断不出来时才追问**——把 issue 提到错仓库，比多问一句的代价大得多，这是少数值得打断用户的地方。

## issue 类型决定用哪套模板

- `Bug`：线上问题、异常、错误行为、回归 → **修复 Bug 模板**
- `Feature`：新增能力、接口、流程、页面 → **新增需求模板**
- `Improvement`：已有能力的优化、稳定性/效率/文档增强 → **新增需求模板**

类型能从上下文稳定判断时就直接定，不用每次都问。只有当 `Bug / Feature / Improvement` 之间语义真的冲突（比如"这个慢得像 bug 但其实是想优化"）才追问一次。Feature 和 Improvement 共用一套模板，因为它们的思考结构一样（要做什么、不做什么、怎么验收），区别只在标签。

## 正文模板

模板的每个字段都对应一种"想清楚"。生成时按字段填，但要理解每个字段在逼你回答什么问题——这样面对模板没覆盖的情况也知道怎么补。

**修复 Bug 模板**

```markdown
## 背景

<受影响的功能/流程，发现问题的上下文>

## 问题描述

<一句话概括现象>

## 复现路径

1.
2.
3.

## 预期行为

## 实际行为

## 影响范围

<受影响的模块、接口、用户群、频率>

## 相关位置

<Controller / Service / 表名 / MQ Topic，若已知>

## 建议修复方向

<可选>

## 验收要点

- [ ]
```

Bug 模板的重点是**复现路径**——一个能稳定复现的 bug 才是可以动手的 bug，写不出复现步骤往往说明现象还没摸清。**建议修复方向标成可选**是有意的：过早写死修复方案会锚定接手的人，让他绕过自己的判断；有把握再写，没把握就留空，别编。

**新增需求模板**（Feature / Improvement）

```markdown
## 背景

<为什么需要，现状什么问题或机会，附代码/日志/截图证据>

## 目标 / 本 issue 范围

- [ ]

## 不做什么

<明确边界，防止范围蔓延>

## 影响范围

<受影响的模块、接口、依赖方>

## 改进建议 / 实现思路

<可选>

## 风险 / 待确认

<需要拍板的决策点>

## 验收要点

- [ ]
```

需求模板里最容易被忽略、却最值钱的是**"不做什么"**——需求最常见的失败是范围悄悄蔓延，明确划出边界能挡住一大半。**验收要点必须写成可断言的勾选项**，否则"做完了"就成了一句主观判断，没法验收。

生成正文时几条通用判断：

- **标题用中文、要具体**。一屏 50 条 issue 里，标题是唯一能扫读的东西。"修复 bug""优化性能"这种等于没写；要让人不点开就大致知道是什么事。
- **背景尽量引用真实证据**——具体到文件、commit、日志、表字段。凭记忆写的背景容易失真，引用真实位置既可核对，也省得接手的人重新摸一遍上下文。
- 同目录的 `example-bug.md` 和 `example-feature.md` 是质量基准，拿不准时对照它们的颗粒度。

## 标签：固定映射，缺了就补，不降级

| Linear | GitHub |
| --- | --- |
| `Bug` | `bug` |
| `Feature` | `feature` |
| `Improvement` | `Improvement` |

如果某个平台缺这个标签，**补建它**，而不是退而求其次用一个近似的（比如 GitHub 上没有 `feature` 就用 `enhancement`）。原因是两个系统要靠标签做跨平台的筛选和统计，一旦某次悄悄降级，两边的标签体系就开始漂移，以后按标签查就对不上了。补一个标签是一次性成本，标签漂移是长期的坑。

## 工作步骤

**1 — 识别项目归属**。看 git remote 或用户描述，定位到三个项目之一。判断不出来才追问（见上文，这是值得打断的少数情况）。

**2 — 生成类型和正文**。判断 Bug / Feature / Improvement，按对应模板填出标题和正文，**先展示给用户预览**。让用户在内容定稿后、真正写库前有个确认的机会。

**3 — 确认负责人**。调用 `list_users`（team = `QIngluo`）拉取当前成员，列出来让用户选。

- **为什么动态拉取而不写死名单**：团队成员会变，写死的名单会过期，可能把 issue 派给已经离开的人。
- **为什么放在生成正文之后问**：用户得先看到 issue 是什么，才能判断该谁负责。还没看到内容就问"谁来负责"是反的——内容决定归属。
- 等用户回复后再继续，不要替他猜。

**4 — 创建 Linear issue（主记录）**。写入 team、project、assignee、labels、title、description。记下返回的 issue key（如 `LINK-35`）、id、URL，后面要用。

**5 — 创建 GitHub issue（镜像）**。正文用步骤 2 的内容，**末尾追加一个 `## Linear` 段落**写入 Linear URL。同步打上映射后的标签。**不要给 GitHub issue 设 assignee**——负责人只在 Linear 跟踪：GitHub 的登录名和 Linear 的 displayName 经常对不上，强行 `--assignee` 要么直接报错、要么指派给错的人，还白费一次调用。需要 GitHub 也显示负责人时，由用户手动补。记下 issue number 和 URL。

**6 — 把 GitHub 链接写回 Linear**。用 `save_issue` 的 `links` 字段，以 `{url, title: "GitHub #<number>"}` 的形式加到 Linear issue 的 links 区域。不改 Linear 正文，不发 comment——links 区域就是干这个的，正文保持干净。

**7 — 报告**。给用户一份清单：识别到的项目、Linear key + URL、GitHub 编号 + URL、issue 类型、负责人、用到/新建的标签，以及是否有任何一步部分失败。

## 失败了怎么办

这套流程有外部副作用（真的在两个系统建数据），所以失败要诚实报告，不能假装全成功，否则用户以为同步好了、实际只建了一半。

- **Linear 建失败** → 整个终止，不要去建 GitHub。主记录都没立起来，建镜像没意义，只会留下孤儿。
- **Linear 成功、GitHub 失败** → 保留 Linear issue，明确告诉用户 GitHub 没建成，让他决定是重试还是手动补。
- **GitHub 建成、但写回 Linear links 失败** → 不要回滚已经建好的两条 issue，报告"两条 issue 都在，只是 Linear 的 links 区域没挂上 GitHub 链接"，这是最轻的一种残缺，手动补一下即可。
