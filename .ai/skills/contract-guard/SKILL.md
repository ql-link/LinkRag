---
name: contract-guard
description: 契约治理三件套的「结构层」。判定一处改动是否破坏跨模块/跨服务公共契约的结构与语义（MySQL schema、Qdrant/ES 索引、MQ topic 与消息结构、OSS 路径、HTTP 接口、错误码），并据此列出必须同步的契约文档 + migration 清单。本 skill 只做「判定 + 列清单」，不核对同一物理值在多处是否逐字一致（那是值层，转 config-contract-sync），也不亲自改写文档内容（那是文档层，转 doc-maintenance-sync）。
when_to_use: "当技术设计或代码实现改到 MySQL 表/字段、Qdrant/Elasticsearch 索引结构、MQ topic 或消息字段结构、OSS 路径规则、对外 HTTP 接口、错误码等公共约定，需要回答『这个改动会不会破坏对端、要同步哪些契约文档』时激活。触发示例：'这个改动会破坏公共约定吗'、'新增表字段要同步什么'、'改了消息结构对端受影响吗'、'加了错误码要更新哪些文档'。三件套切分：只是核对同一个 topic/bucket/字段名在 .env/代码/Java 多处取值是否逐字一致（值层）→ config-contract-sync；判定完拿到清单后要真正改写 docs/AGENTS 内容（文档层）→ doc-maintenance-sync；写/校验迁移本身 → alembic-migration。"
---

# Contract Guard

## 目的

在「技术设计」与「编码实现」阶段，确保改动不会悄悄破坏跨模块/跨服务的**公共契约**，
并按本项目**按域拆分的契约文档**与 **CLAUDE.md §6 机器强制同步规则**给出必须同步的清单。
本项目没有单一的 `middleware_contract.md`；契约分散在 `docs/api/**` 与若干 `docs/internals/**`。

## 契约面与权威文档（必读，按改动涉及的面选读）

| 契约面 | 代码位置 | 权威文档 |
| --- | --- | --- |
| MySQL 表结构 / ORM | `src/models/**.py` | `docs/api/schemas/mysql.md` |
| Qdrant 向量索引（collection / named vector / payload） | `src/core/qdrant_vector_storage/**` | `docs/api/schemas/qdrant.md` |
| Elasticsearch 索引 | `src/core/**`（ES 入库阶段） | `docs/api/schemas/elasticsearch.md` |
| MQ topic / 消息结构 | `src/core/mq/messages/**` | `docs/api/mq_contracts.md` + `docs/internals/mq.md` |
| 对外 HTTP 接口 | `src/api/routes/**` | `docs/api/http_contracts.md` |
| 错误码 / 失败通知语义 | `src/core/**`（error_codes） | `docs/api/error_codes.md` |
| OSS 路径 / 桶 / 公私有 | `src/core/**`（object storage） | `docs/internals/object_storage.md` |
| 命名 / 配置 / DB 来源约定 | `src/config.py` 等 | `docs/internals/naming_conventions.md` |
| 解析任务流水线阶段契约 | `src/core/pipeline/parse_task/**` | `docs/internals/parse_task_pipeline.md` |

## 机器强制同步规则（违反会被 pre-commit / CI 拦截，见 CLAUDE.md §6）

- 改 `src/models/**.py` → 必同步 `docs/api/schemas/mysql.md` **且**新增 `migrations/versions/*.py`。
- 改 `src/core/mq/messages/**` → 必同步 `docs/api/mq_contracts.md` + `docs/internals/mq.md`。
- 改 `src/core/pipeline/parse_task/**` → 必同步 `docs/internals/parse_task_pipeline.md`。
- `migrations/db.sql` **禁止修改**（0001 baseline 冻结）。

## 检查清单

逐项判断本次改动是否触碰公共契约（任一为「是」即需同步对应文档）：

- [ ] 新增/改名/删除 **MySQL 表或字段**，或改了类型/默认值/索引/枚举取值？
- [ ] 改了 **Qdrant** collection 命名规则、向量维度、named sparse vector 名、payload 结构？
- [ ] 改了 **ES** index 名、mapping、文件级 document 结构？
- [ ] 新增/修改 **MQ topic / group**，或改了消息字段、别名、必填性、语义？
- [ ] 改了**对外 HTTP** 路由、请求/响应结构、状态语义？
- [ ] 新增/修改**错误码**或失败通知语义（回发 Java 的 parse_result 等）？
- [ ] 改了 **OSS** bucket / object key 拼接规则或公私有访问？
- [ ] 改了**命名/配置约定**（env key、Redis key/TTL 等通用规则）？

## 执行流程

1. 按改动涉及的契约面，读上表对应权威文档与代码现状。
2. 对每个面判定：**复用现有约定** / **新增约定** / **破坏性变更**（不向后兼容）。
3. 破坏性变更要显式标注对端影响（尤其 MQ 消息、错误码、HTTP 结构会波及 Java 侧）。
4. 列出机器强制同步项（mysql.md / migration / mq_contracts.md / mq.md / parse_task_pipeline.md）。
5. 收尾提示自检：`python scripts/check_docs_sync.py --staged`。

## 输出要求

- 一张「契约面 × 判定（复用/新增/破坏）× 需同步文档」清单。
- 若全部复用：明确说明「未新增或破坏公共契约，无需同步」。
- 若新增/破坏：列出必须同步的文档与（如涉及 model）必须新增的 migration；标注对端是否需配合。
- 提示运行 `check_docs_sync.py --staged`。

## 边界（契约治理三件套的分工）

三者按「同一改动的不同层面」分工，不重叠：

| 层面 | skill | 回答的问题 | 产物 |
| --- | --- | --- | --- |
| **结构层（本 skill）** | `contract-guard` | 结构/语义/必填性变了没有？破坏对端兼容没有？该同步哪些契约文档？ | 判定 + 同步清单（不改文档） |
| **值层** | `config-contract-sync` | 同一个 topic/bucket/字段名/路径在 `.env`/代码/Java 多处取值是否**逐字相等**？ | 取值对照表 + 统一方案 |
| **文档层** | `doc-maintenance-sync` | 文档内容是否已落后于代码现状？ | 实际改写后的文档 |

- 本 skill 给出清单后，若要真正动手改写 `docs/**`、`AGENTS.md` 内容 → 转 `doc-maintenance-sync` 执行。
- 判定中若怀疑某个值两端对不上（而非结构变化）→ 转 `config-contract-sync` 核值。
- 要写/校验迁移本身 → `alembic-migration`。
