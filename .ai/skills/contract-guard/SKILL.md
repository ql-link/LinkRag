---
name: contract-guard
description: 在技术设计与代码实现阶段校验改动是否破坏跨模块/跨服务的公共契约（MySQL schema、Qdrant/ES 索引、MQ topic 与消息、OSS 路径、HTTP 接口、错误码），并对照本项目按域拆分的契约文档与机器强制同步规则给出同步清单。 - 当技术设计或编码涉及数据库表、向量/ES 索引、MQ 消息、OSS 路径、对外 HTTP 接口或错误码等公共约定，或需要确认改动是否违反跨模块契约时激活。触发示例：'这个改动会破坏公共约定吗'、'新增表字段要同步什么'、'改了消息结构对端受影响吗'、'加了错误码要更新哪些文档'
when_to_use: "当技术设计或代码实现涉及 MySQL 表、Qdrant/Elasticsearch 索引、MQ topic/消息结构、OSS 路径规则、对外 HTTP 接口或错误码等公共约定，或需要确认改动是否违反跨模块契约并触发文档同步时激活。触发示例：'这个改动会破坏公共约定吗'、'新增表字段要同步什么'、'改了消息结构对端受影响吗'、'加了错误码要更新哪些文档'。若是核对 topic/bucket/字段在 .env 与 Java 两端的具体取值一致性，转 config-contract-sync；若只是泛化的文档跟随同步，转 doc-maintenance-sync。"
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

## 边界（避免与相邻 skill 重复）

- 本 skill 关注「契约是否被破坏 + 该同步哪些文档」。
- 要核对 topic/bucket/字段在 `.env`/代码/Java 三处的**具体取值是否一致** → `config-contract-sync`。
- 要做泛化的「文档跟随代码同步」 → `doc-maintenance-sync`。
- 要写/校验迁移本身 → `alembic-migration`。
