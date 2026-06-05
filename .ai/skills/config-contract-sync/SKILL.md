---
name: config-contract-sync
description: 核对 Java 与 Py 两端、以及 .env/.env.example/代码三处之间的「物理契约值」是否一致（MQ topic/group、OSS bucket、消息字段别名、内部 HTTP 路径等），防止配置漂移导致消息收不到/取不到文件。
when_to_use: "当用户改动 MQ topic/queue/group、OSS bucket、MQ 消息字段名/别名、内部 HTTP 路径等跨服务物理契约值，或排查「Java 与 Py 对不上」「收不到消息」「.env 改了没生效」类问题时激活。触发示例：'topic 改了对端要不要同步'、'为什么收不到消息'、'这个字段名两端一致吗'、'.env 和代码哪个生效'、'换了 bucket 名'。若是检查改动是否破坏公共契约并触发文档同步，转 contract-guard；若是定位运行故障转 incident-triage。"
---

# 配置契约一致性（Skill）

## 目的

`contract-guard` 管的是「公共约定文档是否被破坏」，本 skill 管的是**具体物理值在多处是否一致**。
本项目踩过的典型坑：`PARSE_TASK_TOPIC` 在 `.env`、代码写死值、Java 端三处分叉 → Py 永远收不到消息。
核心原则：**生效值以代码实际读取的为准，`.env.example` 只是模板，`.env` 才生效。**

## 三类高危漂移点

1. **配置值 vs 代码生效值**：`.env` 里设了某 key，但代码**写死常量、没读这个 env**。
   - 例：`parse_task_consumer.py` 订阅 `ParseTaskMessage.MQ_NAME`（写死），不读 `PARSE_TASK_TOPIC`。
2. **`.env` vs `.env.example`**：模板更新了值，实际 `.env` 没改（或反之），且空字符串无法解析为 int/float 会直接崩配置加载。
3. **Py 端 vs Java 端**：topic/group、bucket、消息字段名（含别名）、内部 HTTP 路径，两端必须逐字一致。

## 必查清单

- **MQ topic / group**：
  - `src/config.py`（PARSE_TASK_TOPIC / PARSE_RESULT_TOPIC 等）
  - `src/core/mq/messages/*.py`（`MQ_NAME` 写死值）
  - `src/core/mq/consumers/*.py`（实际 `subscribe(topic=..., group_id=...)`）
  - `.env` 与 `.env.example` 对应行
  - **对端 Java** publish/consume 的 topic 配置
- **消息字段别名**：`ParseTaskPayload` 的 `validation_alias` / `serialization_alias`
  是否覆盖 Java 实际投递字段名（如 `document_parse_file_id` vs `document_parse_task_id`）。
- **OSS bucket / object key 规则**：两端拼接规则一致。
- **内部文件接口路径**：`/api/v1/internal/files/{id}/content` 等两端一致。

## 执行流程

1. 列出本次改动涉及的物理契约值（topic/bucket/字段/路径）。
2. 对每个值，**逐处核对**：代码实际读取点 → `.env` → `.env.example` → 对端配置。
3. 找出分叉：明确「哪个是生效值、哪个是死值、对端用的哪个」。
4. 给统一方案：定哪个为准，列出所有需要改的位置。
5. 校验：
   - 空 `.env` 值会否打断 Settings 加载（Optional[int]/float 不能是空串）。
   - 改 `.env` 后提醒**重启服务**。
   - 若改了 `src/core/mq/messages/**`，提醒同步 `docs/api/mq_contracts.md` + `docs/internals/mq.md`（机器强制）。

## 输出要求

- 一张「契约值 × 各处取值」对照表，标红不一致项。
- 指明生效值与根因（配置漂移/死值/对端不一致）。
- 给出统一到哪个值 + 全部改动点清单 + 是否需重启/对端配合。

## 原则

- 以**代码实际读取的值**为生效真值，不被 `.env` 表象误导。
- 跨服务值的最终一致需要对端确认，明确标注「需 Java 侧同步」。
- 能消除分叉根因的（如让 consumer 读 env 而非写死）优先建议根治。
