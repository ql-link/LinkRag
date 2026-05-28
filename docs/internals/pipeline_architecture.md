# Pipeline 架构

本文说明 `src/core/pipeline/` 包的内部架构：组件如何组合、各自的职责边界、依赖关系，以及加新阶段或替换实现时的扩展路径。

与本文互补：
- 端到端业务流程、状态语义、失败码 → [parse_task_pipeline.md](parse_task_pipeline.md)
- 分块策略 → [chunking.md](chunking.md)
- 向量化存储 → [vectorization.md](vectorization.md)
- MQ 集成 → [mq.md](mq.md)

---

## 1. 设计目标

`pipeline/` 包承接 Java 通过 MQ 投递的 `parse_task` 消息，把"一次解析任务"的所有副作用（日志、对象存储、分块、向量化、ES、通知）收敛到单一编排入口 `ParseTaskPipeline`。设计上遵循三条规则：

1. **概念边界用目录表达**：解析主编排（`parse_task`）和文件级后处理子状态机（`post_process`）拆成两个子包，避免在同一层用文件名前缀区分。
2. **god class 拆为协作者**：`ParseTaskPipeline` 只做编排，所有"DB 仓储 / MQ 通知 / OSS I/O / 前置守卫"通过组合注入。
3. **基础设施装配归属各自模块**：`ChunkingEngine` / `VectorStorageFacade` 由 splitter / vector_storage 模块自己提供工厂入口，pipeline 不再持有装配代码。

---

## 2. 包结构

```text
src/core/pipeline/
├── __init__.py                  # 对外门面：ParseTaskPipeline / ParsePipelineResult / PipelineStatus
└── parse_task/                  # 解析任务主编排
    ├── pipeline.py              # ParseTaskPipeline（编排骨架）
    ├── constants.py             # 解析任务状态字面量 + 用户提示文案
    ├── error_codes.py           # ParseFailureCode + build_failure_reason
    ├── models.py                # ParsePipelineResult / PipelineStatus
    ├── log_repository.py        # ParseLogRepository
    ├── notifier.py              # ParseResultNotifier + ParseResultNotificationError
    ├── source.py                # ParseSourceIO
    ├── validator.py             # ParseTaskGuard
    ├── _utils.py                # 子包内部小工具（now / duration_ms / coerce_optional_int / 等）
    └── post_process/            # 文件级后处理子状态机（parse_task 内部）
        ├── constants.py         # PIPELINE_STATUS_* / STAGE_STATUS_* / POST_PROCESS_STAGE_*
        ├── models.py            # PostProcessStageResult / PostProcessResult
        └── repository.py        # ParsePipelineRepository
```

后续如新增检索链路 pipeline，按相同模式在顶层添加 `retrieval/` 子包：

```text
src/core/pipeline/
├── parse_task/    # 解析编排（含内部 post_process 子状态机）
└── retrieval/     # 检索编排（未来）
```

### 2.1 为什么 `post_process/` 嵌在 `parse_task/` 下

它的生命周期由 parse_task 创建并驱动（行级 `document_parse_pipeline` 与 `document_parsed_log` 1:1 绑定），不是一个独立 pipeline，所以归属为 parse_task 的内部子状态机，而不是顶层 `pipeline/` 的并列子包。这样顶层只放真正的"独立 pipeline"，层级语义干净。

---

## 3. ParseTaskPipeline 组件构成

```text
                ParseTaskConsumer
                       │
                       ▼
              ParseTaskPipeline.execute()
                       │
        ┌──────────────┴──────────────┐
        │                              │
   __init__ 装配                    _run 编排
        │                              │
        ▼                              ▼
┌───────────────────┐    ┌──────────────────────────────┐
│  ParseLogRepo     │◄───┤  1. log_repo.create()        │
│  ParseSourceIO    │◄───┤  2. guard.handle_duplicate() │
│  ParseResultNotif │◄───┤  3. guard.validate()         │
│  ParseTaskGuard   │    │  4. source_io.download()     │
└───────────────────┘    │  5. _parse_file()            │
                         │  6. source_io.upload_md()    │
                         │  7. log_repo.mark_success()  │
                         │  8. post_process.processing  │
                         │  9. _run_chunking()          │
                         │ 10. _store_chunk_vectors()   │
                         │ 11. es_indexing.index()      │
                         │ 12. notifier.send_or_raise() │
                         └──────────────────────────────┘
```

`ParseTaskPipeline.__init__` 的参数面向消费者（`storage` / `session_factory` / `mq_service` / `post_process_repository` / `vector_storage` / `es_indexing_pipeline`），4 个协作者在 `__init__` 内部据此装配。这样 consumer 侧不感知协作者的存在，测试侧可以通过传 fake `mq_service` 或 fake `post_process_repository` 间接替换。

---

## 4. 协作者职责矩阵

| 协作者 | 输入依赖 | 主要职责 | 副作用 |
| --- | --- | --- | --- |
| `ParseLogRepository` | `ParsePipelineRepository` | `document_parsed_log` CRUD；首次创建时同步生成 `document_parse_pipeline` 行 | MySQL |
| `ParseSourceIO` | `BaseObjectStorage` | 源文件下载、Markdown 上传、MinerU URL 构造、判断是否跳过下载 | OSS |
| `ParseResultNotifier` | `MQService`, `ParseLogRepository` | 发 `parse_result` 终态消息；发送失败时把日志兜底为 `RESULT_NOTIFY_FAILED` | MQ + MySQL |
| `ParseTaskGuard` | `ParseLogRepository`, `ParsePipelineRepository`, `ParseResultNotifier` | 消息载荷一致性校验；重复 task_id 终态补发；非终态 pipeline 收敛 | 通过依赖产生副作用 |

依赖方向（自上而下）：

```text
ParseTaskPipeline
   └── ParseTaskGuard
         ├── ParseResultNotifier ── ParseLogRepository ── ParsePipelineRepository
         └── ParsePipelineRepository
```

---

## 5. 工厂层与基础设施装配

pipeline 自己不持有"怎么按 settings 造 ChunkingEngine"这类装配代码。所有此类逻辑归属各自模块：

| 工厂入口 | 位置 | 用途 |
| --- | --- | --- |
| `create_chunking_engine()` | `src/core/splitter/factory.py` | 按 `CHUNKING_*` 配置组装 ChunkingEngine，高级语义初始化失败时降级规则分块 |
| `create_system_embedding_client()` | `src/core/splitter/factory.py` | 按 `SYSTEM_LLM_*` 配置造 LLM 客户端并校验 EMBEDDING 能力 |
| `create_lazy_system_embedding_client()` / `LazyEmbeddingClient` | `src/core/splitter/factory.py` | 延迟构造 embedding 客户端，避免主链路因向量配置缺失而提前失败 |
| `create_chunk_embedding_pipeline()` | `src/core/splitter/factory.py` | 装配 `ChunkEmbeddingPipeline`（lazy embedder + AST 分块兜底） |
| `compose_vector_storage_facade()` | `src/core/vector_storage/factory.py` | 一站式装配 `VectorStorageFacade`；未传 embedding_pipeline 时自动调 splitter 工厂 |
| `create_vector_storage_facade()` | `src/core/vector_storage/factory.py` | 老入口，要求调用方自带 embedding_pipeline，主要用于测试 |

pipeline 内部按需调用：

```python
# parse_task/pipeline.py
def _get_vector_storage(self):
    if self._vector_storage is None:
        self._vector_storage = compose_vector_storage_facade()
    return self._vector_storage

@staticmethod
def _chunk_markdown(markdown, source_file, parse_result=None):
    processor = create_chunking_engine()
    ...
```

---

## 6. 后处理子状态机

`document_parse_pipeline` 行随 `document_parsed_log` 在 `ParseLogRepository.create()` 内同事务创建（1:1 绑定）。`ParsePipelineRepository` 提供按阶段写状态的细粒度入口：

| 阶段 | success 入口 | failed 入口 |
| --- | --- | --- |
| chunking | `mark_chunking_success` | `mark_chunking_failed` |
| vectorizing | `mark_vectorizing_success` | `mark_vectorizing_failed` |
| es_indexing | `mark_es_success` | `mark_es_failed` |

`ParseTaskGuard` 在处理"已 success 但 pipeline 仍 PROCESSING/PENDING"的中断场景时，会通过 `_infer_recover_stage` 推断恢复入口，调对应阶段的 `mark_*_failed`，把整体 pipeline 收敛到 FAILED 并填好 `recover_from_stage`。

---

## 7. 扩展指南

### 7.1 新增一个后处理阶段（例如知识图谱抽取）

1. 在 `post_process/constants.py` 加阶段常量与状态字段名。
2. `document_parse_pipeline` 表加 `xxx_status` / `xxx_duration_ms` 字段（DDL 入 `scripts/db/init.sql`）。
3. `ParsePipelineRepository` 加 `mark_xxx_success` / `mark_xxx_failed`。
4. `ParseTaskPipeline._run` 在 ES 阶段之后追加新阶段，沿用现有的"failed → mark_xxx_failed + notifier.send_or_raise + return FAILED"模式。
5. `ParseTaskGuard._infer_recover_stage` 加新阶段的判断顺序。
6. 同步 [docs/api/schemas/mysql.md](../api/schemas/mysql.md)、[parse_task_pipeline.md](parse_task_pipeline.md)。

### 7.2 替换某个协作者实现

构造时传入替身即可。例如要换通知机制：

```python
class HttpResultNotifier:
    async def send(self, ...): ...
    async def send_or_raise(self, ...): ...

pipeline = ParseTaskPipeline(...)
pipeline._notifier = HttpResultNotifier(...)  # 测试场景
```

生产场景更建议把构造参数加到 `ParseTaskPipeline.__init__`（保持向后兼容），而不是 hack 私有属性。

### 7.3 接入新的对象存储后端

只动 `src/services/storage/`：实现 `BaseObjectStorage`，让 `StorageFactory` 按配置返回新实例。`ParseSourceIO` 不需要改。

### 7.4 替换分块策略

只动 `src/core/splitter/factory.create_chunking_engine`。pipeline 透传。

---

## 8. 测试约定

| 测试目标 | 推荐入口 |
| --- | --- |
| pipeline 编排骨架（不依赖真实 OSS/DB） | `tests/unit/core/pipeline/test_parse_task_pipeline.py`，构造 `ParseTaskPipeline` 传 fake `storage` / `session_factory` / `mq_service` / `post_process_repository` |
| 单个协作者 | 直接 import 协作者类做单测（log_repo / notifier / source / validator）；不要去 patch `ParseTaskPipeline` 私有方法 |
| splitter 工厂 | `tests/unit/core/splitter/test_factory.py` |
| post_process 仓储 | `tests/unit/core/pipeline/test_post_process_repository.py` |
| 端到端（含真实 Kafka） | `tests/integration/core/mq/test_kafka_parse_task_pipeline_integration.py` |

**反模式**：不要再用 `@patch("...parse_task.pipeline.ParseTaskPipeline._某私有方法")`。如果你发现需要 patch 某个私有方法才能测，那是协作者抽取不彻底的信号——应该把它抽成构造器注入的对象，再传 fake。

---

## 9. 修改原则

- pipeline 内只做编排：新增"调外部系统"的代码请先确认归到哪个协作者，或抽新的协作者，不要直接写在 `_run` 里。
- 装配代码归属各自模块：`pipeline` 不持有 `settings.CHUNKING_* / SYSTEM_LLM_*` 等"造对象"的配置读取，全部走 splitter / vector_storage 的 factory。
- 对外契约只暴露 `ParseTaskPipeline / ParsePipelineResult / PipelineStatus`（顶层 `__init__.py`），子包内部类调整不应破坏外部 import。
- 解析任务的幂等性以 `document_parsed_log.task_id` 唯一索引为唯一屏障，不要在应用层做"先 select 后 insert"的伪幂等。
