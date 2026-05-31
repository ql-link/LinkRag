---
name: incident-triage
description: 从日志/现象定位 RAG 解析与召回链路故障，按「定位阶段 → 区分配置漂移还是数据不一致 → 给修复 + 重置/回滚动作」的路径收敛，输出可执行结论。 - 当用户贴日志/报错、反映文件卡在解析中、Py 收不到解析请求、Qdrant/ES 报错、召回为空、MQ 不消费等线上/联调故障并要求排查时激活。触发示例：'为什么 py 没收到解析请求'、'解析一直失败'、'这个报错什么问题'、'文件卡在解析中'、'召回不到结果'、'帮我看下日志'
when_to_use: "当用户贴日志/报错、反映文件卡在解析中、Py 收不到解析请求、Qdrant/ES 报错、召回为空、MQ 不消费、状态机不流转等故障并要求排查时激活。触发示例：'为什么 py 没收到解析请求'、'解析一直失败'、'这个报错什么问题'、'文件卡在解析中'、'召回不到结果'、'帮我看下日志'。若用户是要新功能实现转 implementation-execution；要写迁移修数据转 alembic-migration。"
---

# 故障排查（Skill）

## 目的

把本项目高频故障的排查路径标准化：**先定位链路阶段，再判断根因属于"配置漂移"还是
"数据不一致/状态机"，最后给出可执行修复 + 必要的数据重置/回滚**。避免只看表层报错就乱改。

## 链路总览（出问题先定位在哪一段）

```
前端点击解析 → Java 建 parse task + 发 Kafka(PARSE_TASK_TOPIC)
  → Py MQ consumer(handle_parse_task) → ParseTaskPipeline.execute
    → 6 stage: cleaning → chunking → vectorizing(dense/Qdrant)
       → pretokenize → es_indexing(ES) → sparse_vectorizing(Qdrant named sparse)
  → 回发 PARSE_RESULT_TOPIC 给 Java
```

## 必读 / 必查

1. `src/core/mq/consumers/parse_task_consumer.py`（topic/group 实际订阅值）
2. `src/core/pipeline/parse_task/stages/`（失败 stage 的业务逻辑）
3. `src/config.py` + `.env`（实际生效配置，注意 .env ≠ .env.example）
4. `docs/internals/parse_task_pipeline.md` / `vectorization.md` / `mq.md`
5. 报错涉及的存储：Qdrant(`kb_bucket_<id>`)、ES、MySQL(`kb_document_chunk` 等)

## 分诊决策树

### A. "Py 收不到解析请求 / MQ 不消费"
- 核对 **topic 名两端一致**：Java publish 值 vs Py consumer 订阅值
  （注意 consumer 可能写死 `MQ_NAME`，**不读 `.env` 的 PARSE_TASK_TOPIC**）。
- 核对 consumer group、bootstrap servers、SASL 配置。
- 在 Kafka 上 `--list` / 看堆积，确认消息进了哪个 topic。
- 典型根因：**配置漂移**（env 值与代码写死值分叉；Java 与 Py 不一致）。

### B. "某个 stage 失败（日志含 stage=XXX reason=...）"
- 定位 `failed_stage`，读对应 stage 代码与 `document_parse_pipeline` 记录。
- 常见：
  - `PARSE_ENGINE_FAILED: 不支持的格式` → 文件类型/解析后端配置。
  - `SPARSE_VECTORIZING_FAILED: 404 No point with id` → **MySQL↔Qdrant 不一致**
    （见 C）。
  - dense/ES 连接错误 → 主机地址/凭据配置漂移。

### C. "Qdrant 404 / 召回为空 / 向量缺失"
- 判断 **MySQL chunk 状态 vs Qdrant 实际 point** 是否一致：
  `kb_document_chunk.dense_vector_status=SUCCESS` 但 Qdrant 无对应 point ⇒ 不一致。
- 根因常为 **清库 / 换 Qdrant 地址后未重置 MySQL 状态**：dense stage 因
  `status=SUCCESS` 跳过不再写 point，sparse stage `update_vectors` 命中 404。
- 修复：重置受影响 chunk 的 `dense_vector_status`/`sparse_vector_status` 为 PENDING
  （`lifecycle_status='ACTIVE'`，**不要动 es_status**），再重新解析。

### D. "文件卡在解析中 / 状态不终结"
- 查 `document_parse_pipeline.pipeline_status` 与各 stage 状态位、`document_parsed_log`。
- 确认是否反序列化失败进了死信（无 payload 无法回发 parse_result）。

## 输出要求

1. **定位**：故障落在链路哪一段、哪个 stage。
2. **根因分类**：配置漂移 / 数据不一致 / 代码缺陷 / 外部依赖，给出证据（日志行、配置值、表数据）。
3. **修复动作**：配置改哪行、代码改哪、是否需要重置数据。
4. **数据修复**：若需重置，给**先 SELECT 校验范围 + 再 UPDATE** 的幂等 SQL，并标注影响行与不可动的字段。
5. **预防**：指出同类问题的根因消除点（如 topic 统一、清库后同步重置状态）。

## 原则

- 先用证据定位，不臆测；区分"症状"与"根因"。
- 改 `.env` 后提醒**重启服务**生效。
- 数据修复一律先 SELECT 后 UPDATE，幂等可重放。
- 只解决问题域内的根因，跨域问题（如 Java 侧）明确指出需对端配合。
