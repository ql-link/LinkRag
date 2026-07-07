# Parse Task Pipeline Module

本文说明 `src/core/pipeline/parse_task/pipeline.py` 解析任务业务流水线的端到端职责、状态边界和失败语义。

> **BM25 写入后端可切换（ES / qdrant / manticore）**：下文「ES 入库 / Elasticsearch」
> 描述的是 `es_indexing` 阶段的 BM25 关键词写入步骤，其底层后端由 `settings.BM25_BACKEND`
> 决定：`qdrant`（默认，复用向量库进程，sparse vector + `Modifier.IDF` 真 BM25）、
> `es`（Elasticsearch）或 `manticore`（实验性，见下）。qdrant 后端的 coarse 与 fine 两段
> token 编进同一 sparse 向量的隔离 hash 维度空间，单次点积即
> coarse+fine 双路，对齐 ES `multi_match(["coarse_tokens^2", "fine_tokens"])` 双字段召回；
> 独立 collection，见 `src/core/storage/qdrant_bm25/`）。三个后端鸭子兼容同一接口
> （`write_es_index` / `delete_document_index` / `recall_topk_chunks`），
> **状态机与终态语义完全一致**——阶段顺序、文档级全量重建编排、`es_status` 回写均不变。
> 差异：① 失败前缀——qdrant 用 `QDRANT_BM25_INDEXING_FAILED:`、manticore 用
> `MANTICORE_BM25_INDEXING_FAILED:`（均与 `ES_INDEXING_FAILED:` 对称）；② 类型加权机制——
> es 用 `constant_score` 加法（`BM25_TYPE_BOOST`），qdrant 用 Formula Query 乘法、manticore
> 在应用层对候选池乘法重排（两者共用 `BM25_TYPE_MULT`，命中 chunk_type 时 BM25 主分
> ×倍数；实测乘法重塑排序的能力显著强于加法）。切换经 `src/core/storage/bm25_backend.py`
> 工厂分发，回退到 `es` 零代码改动。
>
> qdrant 后端的长度归一 `avgdl` 在客户端编码时写入即冻结，务必用
> `scripts/dev/calibrate_bm25_avgdl.py` 按真实语料校准 `BM25_AVGDL` / `BM25_AVGDL_FINE`
> （变更只对之后写入的 chunk 生效，存量需重灌才完全对齐）；qdrant 与 ES 的召回一致性
> （recall@k / es-vs-qdrant overlap@k）用 `scripts/dev/eval_bm25_recall.py` 评测。
>
> **manticore 后端（实验性）**：与 qdrant「按 user 哈希分桶、128 桶共享 IDF 统计」不同，
> manticore 按 `dataset_id` **物理建表**（`src/core/storage/manticore_bm25/table_router.py`，
> 表名 `f"{MANTICORE_BM25_TABLE_PREFIX}_{dataset_id}"`），IDF 与 avgdl 天然只统计这一个
> dataset 自己的语料，不需要 tenant filter 圈统计口径。原生 `bm25f(k1, b, {coarse=coarse_boost,
> fine=1})` 做双字段真 BM25F，不需要 Qdrant 那套 hash 维度隔离编码。avgdl 用 Manticore 动态
> 计算（`index_field_lengths`），不传常量覆盖——每张表只含一个 dataset 的文档，动态平均值
> 本来就等价于"按 dataset 计算"。**建表 DDL 必须显式配置 `charset_table='non_cjk, chinese'`**：
> Manticore 默认字符集表不认中文字符，会把中文词当分隔符丢弃（实测：不配置时中文内容基本
> 等于没索引）。选型评估与 POC 见 `scripts/dev/eval_bm25_manticore_poc.py`。**表生命周期**：
> dataset 整体删除时，`DocumentDeletePurger._purge_dataset`（`src/core/pipeline/document_delete/purger.py`）
> 在逐文档清理完之后，会用 `hasattr` 探测 BM25 管线是否暴露 `delete_by_dataset(dataset_id)`——
> 只有 manticore 后端实现了这个方法（`ManticoreBm25IndexingPipeline.delete_by_dataset` →
> `ManticoreBm25Store.drop_table`，整表 `DROP TABLE IF EXISTS`），es/qdrant 没有对应的物理表
> 结构，探测不到即跳过，行为不变。逐文档删除只清行、不清表，若不补这一刀，dataset 删除后
> 空表会一直留存，只增不减。**写入校验**：`ManticoreBm25Store.upsert_chunks` 单条 `REPLACE
> INTO` 出错只记录日志、跳过，不让同批次其余成功写入被牵连判定失败；批次写完后按
> chunk_id 批量 `SELECT` 回读，只有真正查得到的行才计入返回的已确认 chunk_id 列表，
> `ManticoreBm25IndexingPipeline.write_es_index` 据此精确标记每个 chunk 的 `es_status`，
> 而不是"这批是否抛过异常"这种粗粒度判断。**连接管理**：未显式注入 `conn` 时走进程内
> `aiomysql` 连接池（`minsize=1, maxsize=10`，对齐 `src/database.py` 的 SQLAlchemy
> pool_size），并发写入/查询请求可并行拿到不同物理连接，不再排队在同一条常驻连接上。

## 1. 模块框架

`pipeline/` 顶层按概念分两个子包：

```text
src/core/pipeline/
├── parse_task/                  # 解析任务主编排
│   ├── pipeline.py              # ParseTaskPipeline 主类（薄编排）：消息分流/幂等/校验/重试 CAS，6 阶段执行委托 stages/
│   ├── constants.py             # 解析任务内部错误详情常量
│   ├── error_codes.py           # ParseFailureCode + build_failure_reason
│   ├── models.py                # ParsePipelineResult / PipelineStatus
│   ├── log_repository.py        # ParseLogRepository: document_parsed_log 仓储与终态写入
│   # notifier.py 已删除（LINK-166：parse_result 终态回传 MQ 下线，终态只写 DB）
│   ├── source.py                # ParseSourceIO: 对象存储侧源文件流式下载到 Path / Markdown 上传
│   ├── temp_workspace.py        # PARSE_TEMP_DIR 启动清理、临时文件分配、safe_unlink 幂等
│   ├── validator.py             # ParseTaskGuard: 前置校验、MQ 重投与中断状态收敛
│   ├── _utils.py                # 子包内部共享小工具（now / duration_ms / 等）
│   ├── stages/                  # 6 阶段类化编排（LINK-37）：唯一的 mark/run 模板
│   │   ├── base.py              # Stage 抽象基类（execute 模板）+ StagePipeline 编排器
│   │   ├── context.py           # StageContext（跨阶段产物）/ StageOutcome（单阶段结果）
│   │   ├── services.py          # StageServices：解析/分片/向量化/预分词/ES/稀疏等底层操作 + PreprocessorProtocol
│   │   ├── cleaning.py          # CleaningStage（下载→解析→上传 markdown）
│   │   ├── chunking.py          # ChunkingStage（分片 / 重试反查完整 chunk 集合）
│   │   ├── vectorizing.py       # VectorizingStage（dense）
│   │   ├── pretokenize.py       # PretokenizeStage（内存 plan，文件级 all-or-nothing）
│   │   ├── es_indexing.py       # EsIndexingStage（plan 缺失先重建；文档级全量重建）
│   │   └── sparse_vectorizing.py# SparseVectorizingStage（最后一段，唯一翻转 pipeline_status=SUCCESS）
│   ├── workflow_demo/           # Workflow Engine 并行 demo DAG（LINK-102）：不接管现网 ParseTaskPipeline
│   └── post_process/            # 文件级后处理子状态机（cleaning → chunking → vectorizing → pretokenize → es_indexing → sparse_vectorizing）
│       ├── constants.py         # PIPELINE_STATUS_* / STAGE_STATUS_*
│       ├── models.py            # PostProcessStageResult / PostProcessResult
│       └── repository.py        # ParsePipelineRepository（document_parse_pipeline 仓储）
```

`ParseTaskPipeline` 由 3 个协作者通过依赖注入组合而成：

| 协作者 | 职责 |
| --- | --- |
| `ParseLogRepository` | `document_parsed_log` 创建、按 task_id 查询、success/failed 终态写入 |
| `ParseSourceIO` | 源文件下载、Markdown 上传、MinerU URL 拼接、`should_skip_source_download` 判断 |
| `ParseTaskGuard` | 消息载荷一致性校验、重复 task_id 的终态收敛、中断 pipeline 的失败收敛 |

> **终态回传 MQ 已下线（LINK-166）**：流水线只把终态写入 `document_parse_pipeline`（DB 权威源），不再发送 `tolink.rag.parse_result`。原 `ParseResultNotifier` 协作者已删除；前端通过轮询 Java `parse-results` 接口读 DB 获取终态。

`ChunkingEngine` 与 `VectorStorageFacade` 由各自模块的工厂入口装配，不再由 pipeline 自己组装：

| 工厂入口 | 位置 |
| --- | --- |
| `create_chunking_engine()` | `src/core/splitter/factory.py` |
| `create_system_embedding_client()` / `LazyEmbeddingClient` | `src/core/splitter/factory.py` |
| `compose_vector_storage_facade()` | `src/core/storage/vector/factory.py` |

上游入口：

```text
ParseTaskConsumer
  -> ParseTaskMessage.parse_msg()
  -> ParseTaskPipeline.execute()
```

下游依赖：

```text
StorageFactory / BaseObjectStorage
ParseTaskService
ChunkingEngine
VectorStorageFacade
Preprocessor / PreprocessorProtocol   # 预分词独立阶段，构建 FilePostIndexPlan；失败仅抛 PreprocessorError，不写 chunk
EsIndexingPipeline                    # 消费 FilePostIndexPlan 做 ES bulk 写入；delete_document_index 按 user+dataset+doc 文档级删除（全量重建）
ChunkRepository                       # 空 plan 兜底计数 count_es_not_success_by_doc_id（预分词失败不再标 chunk）
MQService
DocumentParsedLog / DocumentParsePipeline
```

## 2. 端到端流程

```text
parse_task message
  -> create document_parsed_log(created)
  -> validate document_parse_file context
  -> parse source file
  -> upload markdown
  -> mark document_parsed_log success
  -> create/mark document_parse_pipeline processing
  -> chunk markdown / ParseResult
  -> store chunk facts to MySQL
  -> reload persisted chunk truth rows (list[ChunkRecordDB])
  -> dense index filtered chunks to Qdrant (filter dense_vector_status != SUCCESS)
  -> pretokenize chunks
  -> index chunks to Elasticsearch
  -> reload fresh chunk truth rows
  -> sparse vectorize filtered chunks (filter sparse_vector_status != SUCCESS)
  -> mark document_parse_pipeline success   # 终态只写 DB，前端轮询读取（LINK-166）
```

失败路径：

```text
any classified failure
  -> write document_parsed_log or document_parse_pipeline failure state   # 终态只写 DB
  -> return ParsePipelineResult(status=FAILED)
```

消费者层兜底：`ParseTaskConsumer.handle_parse_task` 在 `execute()` 之外再包一层 catch-all。`execute` 逃逸的未预期异常（pipeline 内部归类兜底之外，如 DB/会话故障）记录日志后直接 `raise`，交由死信兜底（Java 端 stuck scanner 最终收敛文件状态）。终态权威源是 DB，前端轮询读取，Python 不再回发任何 parse_result 通知（LINK-166，见 [mq.md §消费者层异常兜底](mq.md)）。

## 3. 核心职责

### 编排架构（Stage 类化，LINK-37）

`ParseTaskPipeline` 退化为**薄编排**：只做消息分流、幂等屏障、上下文校验、重试 CAS 与继承式新建；6 阶段执行委托给 `stages/` 子包的 `StagePipeline`。首次执行与重试共用**同一条** StagePipeline，差异只在「建行 / 校验」准备阶段。

```text
ParseTaskPipeline._run
 ├── is_retry=True  → _handle_retry_branch（校验 + CAS supersede + 继承式新建）
 │                     → _execute_stages(ctx)
 └── is_retry=False → create log + 幂等/上下文校验
                       → _execute_stages(ctx)  （外层保留一层兜底 except）

_execute_stages（阶段执行引擎二选一，settings.PARSE_USE_WORKFLOW_DAG）
 ├── True（默认）→ _run_via_dag(ctx) → ParseWorkflowRunner # 并行 DAG
 └── False        → StagePipeline.run(ctx)               # 串行，保留作稳定回退

StagePipeline.run（串行 6 阶段编排）
 CleaningStage → ChunkingStage → VectorizingStage
   → PretokenizeStage → EsIndexingStage → SparseVectorizingStage
```

三层职责切分：

| 层 | 角色 | 职责 |
| --- | --- | --- |
| `ParseTaskPipeline` | 薄编排 | 分流 / 幂等 / 校验 / 重试 CAS / 兜底 except；`_build_stage_pipeline()` 每次执行从当前协作者装配 StagePipeline（便于测试替换协作者即时生效） |
| `Stage` 基类 | **唯一**的执行模板 | `execute`：已继承 `SUCCESS` → `on_skip`；否则 `mark_started → run → 成功 mark_success / 失败 mark_failed`（终态写 DB）。新增/调整阶段只写一个子类，不再双链路改动 |
| `StageServices` | 底层操作集合 | 解析 / 分片 / dense 向量化 / 预分词 / ES 写入 / 稀疏向量化 / chunk 反查等；**只做底层操作、不写阶段状态**（副作用边界清晰） |

`StageContext` 在阶段间传递可变产物（`parse_result` / `chunks` / `plan` / `vector_result`）并收敛最终 `ParsePipelineResult`；`StageOutcome` 是单阶段成败结果（`finalized=True` 表示该阶段已自行写终态，模板不重复处理）。

### 并行 DAG 引擎（生产默认引擎）

`src/core/pipeline/parse_task/workflow_demo/` 把 6 阶段包成通用 Workflow Engine 的节点，提供两个拓扑入口：`build_parse_task_demo_workflow()`（并行）与 `build_parse_task_serial_workflow()`（穿行，在并行 DAG 上叠加定序边串成一条线）；runner 为 `ParseWorkflowRunner`。

**接入方式（开关二选一，不改既有串行逻辑）**：`ParseTaskPipeline._execute_stages` 按 `settings.PARSE_USE_WORKFLOW_DAG` 选引擎——`True`（默认）走并行 `_run_via_dag`，`False` 走串行 `StagePipeline`（保留作回退，代码不删，出问题置 `False` 秒回滚）。消费者 `ParseTaskConsumer` 与生命周期外壳（幂等/校验/重试 CAS/兜底 except）两条引擎共用，不感知差异。

**节点委托 + 状态机拆层**（让并行行为与串行等价、且并发安全）：

- **业务复用**：每个 DAG 节点（cleaning/chunking/dense/pretokenize/es/sparse）**委托对应串行 `Stage.run()`**，原样复用解析/分块/向量化等业务 **与错误码分类**（`LLM_CONFIG_MISSING` / `EMBEDDING_DIMENSION_UNSUPPORTED` / `SPARSE_VECTORIZING_FAILED` 等）及 run 内旁路（dense embed 用量上报）。`ensure_points` 无对应串行 Stage（解耦新增），直接调 `StageServices.ensure_chunk_points`。
- **每阶段状态**：节点不调串行 `mark_*`（那会改共享 ORM 的聚合字段、仅串行安全），改用 `ParsePipelineRepository.mark_stage_processing/success/failed`——**定向单列 UPDATE**（`<stage>_status` [+ `<stage>_duration_ms`]），各节点用自己的 session，并发互不串字段。
- **聚合终态**：`pipeline_status` / `failed_stage` / `failure_reason` / `started_at` / `finished_at` / `total_duration_ms` 由编排器 `_run_via_dag` **单写者**收敛——开跑前 `begin_pipeline` 翻 PROCESSING，跑完按 `RunRecord` 调 `finalize_pipeline_success` 或 `finalize_pipeline_failed`（失败阶段按 `POST_PROCESS_STAGE_ORDER` 取最靠前者，对齐串行"首个失败即终态"）。
- **cleaning 的 log 元数据**：串行在 `mark_started`/`mark_success`/`mark_failed` 写 `document_parsed_log`（`parse_started_at` / `mark_parsed` / `mark_parse_finished`）；DAG 把这几处搬进 `CleaningNode`（cleaning 为根节点、无并发；按 id 在本节点 session 内取出 log 行再写，避免跨 session 改 ORM）。

**权威源与表边界**：

- 权威状态源仍是 `document_parse_pipeline`；`pipeline_status` / `*_status` 成功失败语义、Java 侧读 DB 终态规则、不恢复 parse_result MQ 回调——均不变。
- 不删除、不替代 `document_parse_pipeline`、`document_parsed_log`、`kb_document_chunk` 等既有表。
- **不使用** workflow 专属表：runner 固定 `InMemoryWorkflowStore`，引擎 run 记录仅进程内临时记账、零 DB 写；`workflow_run` / `workflow_node_run`（`MySQLWorkflowStore`）在生产解析路径**不引用**。
- **续跑/重试不走引擎 `previous_run_id`**：节点按 `document_parse_pipeline` 继承状态快照（`inherited_status`，由 `_run_via_dag` 开跑前从继承式新 pipeline 行一次性读出）自跳过已 SUCCESS 阶段，依据同串行 `Stage.should_run`，权威源同为生产表。自跳过节点经 `restore()` 从 DB/payload 回放产物给下游（cleaning 读回 markdown、chunking 反查 chunk、pretokenize 重建 plan；dense/es/sparse 为叶子，回放为 noop）。几处并行重试要点：① chunking 自跳过反查 chunk 为空=状态不一致，抛 `_StageNodeError` 由编排器收敛 FAILED（对齐串行 `on_skip`）；② sparse 自跳过**无需**翻 `pipeline_status=SUCCESS`（串行靠 sparse.on_skip 翻，DAG 由编排器 `finalize_pipeline_success` 统一收敛，全跳过的重试也照样置 SUCCESS）；③ chunking 重试从 CHUNKING 恢复要读 `log_record` 的 markdown 坐标——节点在自己 session 内按 id 取 live 行，避免跨 session 访问 `begin_pipeline` commit 后已 expire 的 ORM。

**状态层解耦（并行正确性必需）**：dense 的 chunk 级状态写入 `mark_indexing` / `mark_indexed` / `mark_failed` 原先会**连带把 `es_status` / `sparse_vector_status` 重置为 PENDING**（假设 dense 串行排在 es/sparse 之前）。并行 DAG 下 dense∥es∥sparse，dense 的这个越界重置会与并发跑完的 es/sparse 抢同一行、把其 `SUCCESS` 冲回 `PENDING`（写写竞争）。现已改为**每个维度只写自己那列**（与 `mark_sparse_indexing` 对称）：dense 标记只动 `dense_vector_status`（+ model）。串行链路里 dense 未成功时 es/sparse 本就是 PENDING，故移除该重置对串行是 no-op；内容变更触发的 reindex 仍由 `update_chunk_for_reindex` 自行重置下游。

> **失败颗粒度差异（并行固有，非逻辑变更）**：串行遇首个失败即停、后续阶段保持 PENDING；并行下 dense/es/sparse 同时在跑，某个失败时另外两个可能已落 SUCCESS。最终 `pipeline_status=FAILED` 与重试语义一致，仅"失败那一刻已完成的子阶段更多"。

demo DAG 当前依赖关系为：`cleaning → chunking`；`chunking → ensure_points`；之后 **dense / sparse / es 三路并行**——`ensure_points → dense_vectorizing`、`ensure_points → sparse_vectorizing`、`chunking → pretokenize → es_indexing`。dense 额外声明 `CHUNKS`（向量化文本）依赖，故并行 DAG 中其上游为 `{chunking, ensure_points}`；ensure_points 本就在 chunking 之后，这条边不损失并行度，但**节点 `run()` 从 ctx 读的每个 product 都必须进 `requires`，否则续跑（resume）按声明回放上游产物时会漏 restore 导致 `KeyError`**。

**named-dense 解耦（让 dense / sparse 真正并行的前提）**：dense 向量从 Qdrant **匿名默认向量**改为**命名向量 `dense`**（`settings.DENSE_VECTOR_QDRANT_VECTOR_NAME`）。命名向量下 collection 无强制默认向量，于是可由 `EnsurePointsNode` 先建只含 payload 的空 point（`QdrantIndexStore.ensure_points`，create-if-missing 幂等、单写者防并发建点相互覆盖），dense 与 sparse 再各自 `update_vectors` 写自己的命名向量（`dense` / `sparse_text`），互不覆盖、顺序无关。`sparse_vectorizing` 因此不再依赖 dense（旧实现里 sparse 依赖 dense 仅因 sparse 向量需追加在 dense 建出的 point 上）。这一存储层改动同样作用于生产 StagePipeline（见 §3 表 dense / sparse 行）。穿行 DAG 在此真实数据边上叠加 `dense_vectorizing → pretokenize`、`es_indexing → sparse_vectorizing` 两条纯定序边，把并行分支串成一条线。

各阶段的特例（均封装在对应 Stage 子类内，对编排循环透明）：

- **CleaningStage**：`cleaning_status != SUCCESS` 才执行（首次恒执行）；下载/解析/上传失败按错误码归类（`TEMP_DISK_FULL` / `SOURCE_FILE_NOT_FOUND` / `PARSE_ENGINE_FAILED` / `PARSED_FILE_UPLOAD_FAILED`）。**数据集级配置注入（LINK-148）**：解析前按 `(user_id, dataset_id)` 经 `DatasetConfigService.get_config` 读数据集配置（无行/DB 故障降级系统默认，只读不写库），把 PDF 后端（`payload 显式 > 数据集 pdf_config > settings.PDF_PARSER_BACKEND` 三层）与 Markdown 增强配置注入 `parse_file`。Markdown 增强配置 `enhancement_config` 只控制是否开启表格/图片增强（`enable_table_enhancement` / `enable_image_enhancement`），**不再在数据集层选择增强模型**：表格增强统一用发起用户 CHAT 默认模型、图片增强用 VISION 默认模型。开启对应增强但用户未配该能力默认模型 → `ENHANCEMENT_MODEL_MISSING`（**不回退系统兜底模型**，表格与图片对称失败，图片增强不再静默跳过）；数据集 JSON 字段类型非法 → 归 `PARSE_ENGINE_FAILED`（reason 含字段名）。成功在 `mark_success` 写 `mark_parsed + mark_cleaning_success + mark_post_cleaning`。临时文件早删 + `finally` 兜底封装在 `run` 内。
  - **`md` / `markdown` 透传**：cleaning 的职责是把多源文件「解析为 md」，而 md 源文件本身即目标格式——经 `payload.is_markdown_passthrough` 判定后 `_read_markdown_passthrough` 直接读取已下载的源文件文本作为 markdown 产物（`parse_result=None`，下游 chunking 走纯 markdown 分片路径），**跳过解析引擎**；且 md 在上传阶段已存入对象存储，cleaning **不再重复写输出桶**。透传仍走完整成功收口（`mark_parsed + mark_cleaning_success + mark_post_cleaning`），`cleaning_status=SUCCESS`，状态语义与正常清洗一致。
    读取文本后、进入 chunking 前，`CleaningStage.run` 调 `StageServices.upload_md_images()` 扫描 markdown 中的 `data:image/...;base64,...` 内联图片，将其上传到 `MINIO_PRIVATE_BUCKET`（私有桶），并替换为对象 URL。**单张失败不阻断整篇**（best-effort）：上传异常时保留原始 base64 并记录 warning，不修改 `cleaning_status`。
  - **markdown 产物坐标解析**：markdown 真实所在位置由 `ParseTaskPayload.markdown_bucket` / `markdown_object_key` 统一解析——**md/markdown 取上传位置 `source_*`，其余格式取 Python 侧 `MINIO_PRIVATE_BUCKET` + 消息中的 `md_object_key`**。`mark_parsed`（写 `parsed_bucket_name`/`parsed_object_key`）、`StageServices.load_markdown`（重试从 CHUNKING 恢复读回旧 markdown）、重试 `create_for_retry` 的预写坐标三处一致取用，确保「清洗完成、分片失败」重试时 md 按真实产物位置读回，不会误用历史 `md_bucket` 字段。
- **ChunkingStage**：`chunking_status == SUCCESS` → `on_skip` 调 `StageServices.load_all_chunks_from_db` 反查完整 chunk truth set；反查为空按历史语义落 `vectorizing_failed` 终态（`finalized`）。否则进入 `run`：有本轮 cleaning 产物用其分片；无 cleaning 产物但旧 markdown 坐标可用（**重试从 CHUNKING 恢复**，LINK-32）则经 `StageServices.load_markdown` 读回旧 markdown 重新分片；二者皆无（无产物也无 markdown 坐标）才视为状态不一致落 `chunking_failed`（`failure_reason` 含 `chunking_not_success_in_retry`）。
- **VectorizingStage / PretokenizeStage / SparseVectorizingStage**：`*_status != SUCCESS` 才执行。SparseVectorizingStage 是 `pipeline_status=SUCCESS` 的**唯一**翻转点——即便继承 SUCCESS 被跳过，也在 `on_skip` 翻转整体终态。
  - **用量上报（旁路，不影响状态机）**：VectorizingStage `run` 后按 task 聚合 dense embed 的输入 token，经 `src/services/usage_reporter.py` 发 `tolink.rag.usage_report`（`stage=parse`/`operation=embed`，token 由模型返回、仅 cache miss 计入）。这是 fire-and-forget 的旁路遥测，发送失败仅告警、**不参与阶段成败判定与终态语义**。表格/图片增强的用量在 cleaning 阶段的增强 provider client 内同样上报（`operation=table`/`vision`）；详见 [mq_contracts.md §用量上报](../api/mq_contracts.md#用量上报pythonjava统计侧)。
- **EsIndexingStage**：依赖 pretokenize 的内存态 `FilePostIndexPlan`，`ctx.plan` 缺失（pretokenize 继承 SUCCESS 被跳过）时先重做 pretokenize 重建再消费（见 §4 重试恢复起点）。

| 阶段 | StageServices 主要方法 | 说明 |
| --- | --- | --- |
| 幂等屏障 | `ParseLogRepository.create()` | 先插入 `document_parsed_log`，依赖 task_id 唯一索引阻止重复解析 |
| 重投处理 | `ParseTaskGuard.handle_duplicate()` | 已有终态直接按现状返回；对中断后处理在 DB 中收敛为可恢复失败 |
| 上下文校验 | `ParseTaskGuard.validate()` | 校验 MQ payload 与 Java 侧 `document_parse_file` 记录一致 |
| 源文件处理 | `ParseSourceIO.should_skip_source_download()` / `.download_to_path()` + `temp_workspace.*` | MinerU URL API 跳过本地下载（`source_path=None`）；其他后端流式下载到 `PARSE_TEMP_DIR/parse-{task_id}-{rand}.{file_type}`，非法/缺失后缀回退 `.tmp`。保留后缀是为了兼容 OpenDataLoader 等按扩展名识别 PDF 的本地解析器。拿到 markdown 后立即 `safe_unlink` 早删，`finally` 二次兜底 |
| 文件解析 | `StageServices.parse_file()` | 调 `ParseTaskService.aprocess()` 生成 Markdown；首次与 `recover_from_stage=CLEANING` 重试同序 |
| MD 内嵌图片上传 | `StageServices.upload_md_images()` | 仅 md/markdown 透传路径执行：扫描 markdown 中 `data:image/...;base64,...` 块，上传至私有桶（`MINIO_PRIVATE_BUCKET`）并替换为对象 URL；单张失败 best-effort 保留 base64，不影响 `cleaning_status` |
| 分片 | `StageServices.run_chunking()` / `._chunk_markdown()` / `.load_markdown()` / `._reload_chunks_from_db()` | 优先消费上游 `ParseResult`，否则重新解析 Markdown；分片成功后单事务批量写入 `kb_document_chunk` 真值记录，**commit 后立即按 `doc_id` 反查 ORM 行（`_reload_chunks_from_db`）作为返回值 `list[ChunkRecordDB]`**——使首次链路与 retry 链路（`load_all_chunks_from_db`）的 chunks 形态完全一致，下游 dense / sparse 用同一套字段契约消费。`_reload_chunks_from_db` 的 SELECT 带 **`execution_options(populate_existing=True)`**：session 配置为 `expire_on_commit=False`，而后续阶段可能在**独立 session** 推进 chunk 级产物状态；若不强制刷新，身份映射里同主键 ORM 实例会保留旧值，导致后续阶段按过期状态判断补做范围。`populate_existing` 用查询结果覆盖已加载实例属性，确保读到最新真值。**重试时**（`payload.is_retry`）`_persist_chunk_facts` 先 `ChunkRepository.delete_by_doc_id(doc_id)` 清本文档残留再全量写入，同事务原子重建 chunk truth set（`chunk_id` 由内容派生且全局唯一，不清残留会撞唯一键）。`load_markdown` 经 `download_to_path` 流式读回旧 markdown（守 OOM 约束），供「重试从 CHUNKING 恢复」重新分片。**数据集级分块配置（LINK-148）**：ChunkingStage 按 `(user_id, dataset_id)` 读 `dataset_parse_config.chunking_config` 注入 `run_chunking`/`create_chunking_engine`，未配置数据集取系统 `CHUNKING_*` 默认（L1 fallback），JSON 字段非法归 `PARSE_ENGINE_FAILED`。**二阶段语义细分 embedder（#235 / LINK-219）**：`stage_two_algorithm` 优先取数据集级 `chunking_config.stage_two_algorithm`，未配置回退系统 `CHUNKING_STAGE_TWO_ALGORITHM`；当其值为 `semantic_depth_window` 时，`run_chunking` 按 `payload.user_id` 读取用户默认 `EMBEDDING` 配置并经 adapter 构造 embedder；不再使用 `SYSTEM_LLM_*`，用户缺默认 EMBEDDING 配置归类 `LLM_CONFIG_MISSING` |
| 向量化（dense） | `StageServices.store_chunk_vectors()` | 接收 `list[ChunkRecordDB]`，**现场过滤 `dense_vector_status != SUCCESS`** 后通过 `VectorStorageFacade.index_chunks(chunks=...)` 写 Qdrant；dense 模块不再自查 SQL、不感知首次/retry（`index_document_chunks(include_failed=...)` 已删除）。多值 CAS（`mark_indexing(allowed_statuses=(PENDING, FAILED))`）在 SQL 层兜底：若现场过滤口径错误把已 SUCCESS chunk 混入，UPDATE rowcount 不达预期进失败路径，不会把 SUCCESS chunk 拉回 INDEXING。全部已 SUCCESS 时短路幂等成功。**embedder 按数据集绑定解析**：`index_chunks` 用 `(user_id, set_id)` 读取 `dataset_parse_config.dense_embedding_config_id`，再按该 `llm_user_config.id` 精确构造稠密 embedder；字段缺失、配置不存在/停用/非当前用户/系统预设/能力非 `EMBEDDING` 均抛 `DenseEmbeddingConfigMissingError`，错误信息包含 `dataset_id` 与字段名，且不回退用户当前默认 EMBEDDING。**维度方案 A**：写入前校验用户模型输出维度须等于 `settings.DENSE_VECTOR_DIMENSION`（per-bucket 共享 collection、维度固定），不符抛 `DenseEmbeddingDimensionError` → `EMBEDDING_DIMENSION_UNSUPPORTED`。**named-dense（解耦）**：dense 写入 Qdrant **命名向量 `dense`**（非匿名默认）；`upsert_points` 内部先 `ensure_points`（payload-only 空 point，create-if-missing）再 `update_vectors({dense: ...})`，只动 dense 维度不触碰 sparse，故 dense 与 sparse 可独立 / 并行写入。召回侧 dense query 同样按数据集绑定模型编码 |
| 预分词 | `StageServices.build_pretokenize_plan()` | 聚合 doc 下 chunk token 为内存 `FilePostIndexPlan`（不持久化、不写状态）。**plan 覆盖该文档全部有效 chunk（不按 `es_status` 过滤，Issue #57）**。文件级 all-or-nothing：成功置 `ctx.plan`，失败返回 `(None, reason)`，由 PretokenizeStage 统一写失败终态，**不写任何 chunk es_status** |
| ES 入库 | `StageServices.run_es_indexing()` | **前置删除 → 全量写入 → 失败清理**（Issue #57）；前置删除失败 `es_delete:` 前缀；写入未全部成功再 delete 清理半成品（best-effort）。失败由 EsIndexingStage 统一写失败终态，**不计数、不设上限** |
| 稀疏向量化 | `StageServices.run_sparse_vectorizing()` → `SparseIndexingPipeline.run(chunks=...)` | **named-dense 解耦后不再依赖 dense**：重新 load chunks 后**现场只过滤 `sparse != SUCCESS`**（去掉旧的 `dense=SUCCESS AND` 前缀），入口**不再前置断言 `dense=SUCCESS`**（fail-fast 已移除）。sparse 用 `update_vectors` 只写 `sparse_text` 命名向量；`upsert_sparse_vectors` 内部先 `ensure_points` 保证 point 存在，故 sparse 可独立 / 先于 dense 写入。sparse 模块不再自查 SQL（`count_by_doc_id` / `list_sparse_candidates_by_doc_id` 不再调用），`bucket_id` 从 `chunks[0].bucket_id` 取（不再误传 `payload.dataset_id`，关闭 #95）；多值 CAS `allowed_statuses=(PENDING, FAILED)` 切 INDEXING；空集短路幂等成功。**sparse encoder 按数据集绑定解析**：读取 `dataset_parse_config.sparse_embedding_config_id` 指向的 `llm_user_config.id`，字段缺失或配置无效时抛 `SparseEmbeddingConfigMissingError`，错误信息包含 `dataset_id` 与字段名，且不回退用户当前默认 SPARSE_EMBEDDING。**代价**：dense / sparse 严格共存不变量弱化（允许"有 sparse 无 dense"的部分态）；存量旧 collection（匿名 dense schema）需迁移到 named-dense schema 后召回才生效 |
| 重试抢占 | `ParsePipelineRepository.mark_superseded()` | CAS 第 2 层只执行 `UPDATE ... WHERE superseded_by_task_id IS NULL` 并返回 rowcount，不主动 commit；调用方必须与新 retry log / pipeline 建行放在同一事务内提交 |
| 结果落库 | `ParsePipelineRepository.mark_*` | 终态只写 `document_parse_pipeline`（DB 权威源），前端轮询 Java 查询读取；不再发送 parse_result MQ（LINK-166） |

## 4. 状态语义

整体任务状态的**权威单源**是 `document_parse_pipeline.pipeline_status`，覆盖 **文档清洗 → 分片 → 向量化 → 预分词 → ES 入库 → 稀疏向量化** 六段状态机。`document_parsed_log` 退化为"文件解析产物快照表"，只承载解析产物（Markdown 文件位置、解析起止时间）与触发上下文；重试链路由 `retry_of_task_id` 串接（migration 0009）。

> **术语对照表**（brief / acceptance ↔ 代码 / schema）：
>
> | brief / acceptance | 代码 / schema | 备注 |
> | --- | --- | --- |
> | `parsing_status` / `parsing_duration_ms` | `cleaning_status` / `cleaning_duration_ms` | migration 0007 落地时选择 cleaning 词根；统一重命名由 issue [#48](https://github.com/ql-link/LinkRag/issues/48) 跟踪 |
> | `STAGE_PARSING` | `POST_PROCESS_STAGE_CLEANING` | 同上 |
> | `mark_parsing_*` | `mark_cleaning_*` | 同上 |

| 字段 | 状态 |
| --- | --- |
| `pipeline_status` | `PENDING/PROCESSING/SUCCESS/FAILED`（整体任务状态，Java 侧判定"上次任务是否整体成功"的唯一字段） |
| `cleaning_status` | `PENDING/PROCESSING/SUCCESS/FAILED`（文档清洗=解析+上传阶段；brief 称 `parsing_status`） |
| `chunking_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `vectorizing_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `pretokenize_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `es_indexing_status` | `PENDING/PROCESSING/SUCCESS/FAILED` |
| `sparse_vectorizing_status` | `PENDING/PROCESSING/SUCCESS/FAILED`（migration 0009 新增） |
| `superseded_by_task_id` | `VARCHAR(36) NULL`（重试 CAS 第 2 层目标列；migration 0009 新增） |

阶段顺序：`CLEANING(PARSING) → CHUNKING → VECTORIZING(dense/Qdrant) → PRETOKENIZE → ES_INDEXING → SPARSE_VECTORIZING`。`pipeline_status=SUCCESS` 是整体成功语义：6 阶段全部成功才算整体成功；任一阶段失败即写 `pipeline_status=FAILED`。终态只写 DB，前端轮询 Java 查询读取（LINK-166）。

**`pipeline_status` 三态翻转**（整体唯一权威）：
- **`PENDING → PROCESSING`**：首个 `mark_<stage>_started` 触发（幂等，已 PROCESSING 不重复翻转）。
- **`* → SUCCESS`**：6 阶段全部 SUCCESS 后由 `mark_sparse_vectorizing_success` **唯一**翻转；`mark_es_success` 不再触碰 `pipeline_status`（本期重要变更，与 sparse 阶段对称）。
- **`* → FAILED`**：任一阶段 `mark_<stage>_failed` 触发，同时写 `failed_stage` / `recover_from_stage` / `failure_reason` / `finished_at`。

**Java 侧消费规则**：
- 整体任务是否成功 → 读 `document_parse_pipeline.pipeline_status == SUCCESS`
- Markdown 是否已上传 → 读 `document_parsed_log.parsed_object_key IS NOT NULL`
- 失败原因 → 读 `document_parse_pipeline.failure_reason`

### 失败即终态与恢复入口（无内部自动重试）

任一阶段失败即终态：只把结果写入 `document_parse_pipeline`（阶段状态 FAILED、`failed_stage`、`recover_from_stage`、`failure_reason`、`finished_at`、耗时）。终态写 DB 即为权威，前端轮询读取。系统**不计数、不设上限、不写 retry_exhausted、不自动重试**。

> **耗时计算的时区归一化（issue #164）**：`_utils.duration_ms()` 对 `started_at` / `finished_at` 统一做 UTC 归一化（naive 视为 UTC、aware 换算到 UTC）后再相减。`now()` 返回 tz-aware UTC，而 MySQL `DATETIME` 经 SQLAlchemy 读出为 naive；中断任务收敛（`handle_duplicate` → `_mark_incomplete_pipeline_failed`，`started_at` 来自 DB）若直接相减会抛 `TypeError: can't subtract offset-naive and offset-aware datetimes`，导致非终态 `PROCESSING` 无法收敛为 `FAILED` 而被投递到 `tolink.rag.parse_task.DLT`。归一化后该路径稳定收敛。注意：parse_task 相关时间字段均由应用层 UTC 写入（`now()` / `utc_now`），故 naive 语义即 UTC；**勿**将 DB 端 `func.now()`（服务器本地时区）写入的字段交给 `duration_ms`。

- **文档清洗失败**：`mark_cleaning_failed` 落 `cleaning_status=FAILED` + `failed_stage=CLEANING` + `recover_from_stage=CLEANING`。`failure_reason` 含前缀 `INVALID_TASK_CONTEXT:` / `SOURCE_FILE_NOT_FOUND:` / `PARSE_ENGINE_FAILED:` / `PARSED_FILE_UPLOAD_FAILED:` / `INTERRUPTED_TASK:` / `INTERNAL_UNKNOWN_ERROR:` / `PARSING_FAILED:` 等。
- **预分词失败**（`StageServices.build_pretokenize_plan` 捕获 `PreprocessorError`，或空 plan 但仍有未完成 chunk）：`PretokenizeStage` 落 `mark_pretokenize_failed`（`pretokenize_status=FAILED` + `recover_from_stage=PRETOKENIZE`）；**绝不写任何 chunk es_status**（文件级 all-or-nothing）。
- **chunking 写入失败**：`_persist_chunk_facts` 回滚整批 chunk 真值，`mark_chunking_failed` 落 `chunking_status=FAILED` + `recover_from_stage=CHUNKING`，不进入 vectorizing。该终态可由「重试从 CHUNKING 恢复」链路（读回旧 markdown 重新分片，见 §重试分支）链式恢复，无需重新上传源文件。
- **chunking 二阶段模型配置缺失（#235）**：启用 `semantic_depth_window` 时，二阶段语义打分使用发起用户默认 `EMBEDDING` 配置；用户缺默认 EMBEDDING 配置时抛 `DenseEmbeddingConfigMissingError`，由 ChunkingStage 归类 `LLM_CONFIG_MISSING`，不回退系统级 `SYSTEM_LLM_*`。
- **vectorizing 失败**：当前失败 chunk 的 dense 状态标 `FAILED`，已成功 chunk 保持 `SUCCESS`，未处理 chunk 保持 `PENDING`；文件级 `vectorizing_status=FAILED`。稀疏向量不在 vectorizing 阶段执行。用户侧人工重试进入 VECTORIZING 时由 `store_chunk_vectors` 现场过滤出 dense `PENDING` 与 `FAILED` chunk 透传给 `index_chunks`，已 `SUCCESS` 的 chunk 被过滤掉不重复向量化（多值 CAS `allowed_statuses=(PENDING, FAILED)` 在 SQL 层兜底）。
- **vectorizing 配置/维度失败**：数据集缺少 `dense_embedding_config_id` 或绑定配置无效时，`index_chunks` 在 embed 前抛 `DenseEmbeddingConfigMissingError`（不触碰任何 chunk 状态），`store_chunk_vectors` 透传、VectorizingStage 归类 `LLM_CONFIG_MISSING`（写 DB 终态）；用户模型输出维度与 `DENSE_VECTOR_DIMENSION` 不一致时当前批标 `FAILED` 后抛 `DenseEmbeddingDimensionError`，归类 `EMBEDDING_DIMENSION_UNSUPPORTED`。两者区别于普通 `VECTORIZING_FAILED`，使前端能提示用户补齐数据集模型绑定 / 换模型。
- **ES 前置删除失败**（`delete_document_index` 抛异常，如 ES 不可达）：直接判 ES 阶段失败、不进入写入，`failure_reason` 以 `es_delete:` 前缀。
- **ES 基础设施故障**（`_ensure_index` 等）：文件级，不标 chunk，`failure_reason` 以 `ensure_index:` 前缀。
- **ES chunk 级写失败**：逐 chunk 标 `es_status=FAILED`，文件级 `es_indexing_status=FAILED`，前缀 `ES_INDEXING_FAILED:`；失败后触发文档级删除清理半成品（best-effort），避免 ES 残留部分写入。
- **稀疏向量阶段失败**（`SparseIndexingPipeline.run` 抛 `SparseIndexingError`）：触发失败的 chunk 标 `sparse_vector_status=FAILED` 留审计痕迹；文件级 `mark_sparse_vectorizing_failed` 落 `sparse_vectorizing_status=FAILED` + `failed_stage=SPARSE_VECTORIZING`，前缀 `SPARSE_VECTORIZING_FAILED:`。
- **恢复入口** `_infer_recover_stage()` 取首个非 SUCCESS 阶段（cleaning→chunking→vectorizing→pretokenize→es→sparse_vectorizing）。所有 `*_status` 跨重投持久，不被 `mark_<stage>_started` 清空（只清 `failed_stage` / `failure_reason` 等失败痕迹）。
- **用户侧重试**：重试由 Java 端负责，重试链通过 `document_parsed_log.retry_of_task_id` 与 `document_parse_pipeline.superseded_by_task_id` 双向追溯（migration 0009）。Python 侧已不再维护 `retry_count` / `last_retry_at`（migration 0007 下线）。

### 重试分支（`is_retry=true`）

收到 `payload.is_retry=true` 时，`ParseTaskPipeline._run` 顶部进入重试分支：

1. `ParseTaskGuard.validate_retry_context(payload, db)`：严格校验（含 CAS 第 1 层快速失败 `superseded_by_task_id IS NULL`），失败抛 `RetryValidationError`。若旧 pipeline 的 `recover_from_stage=CLEANING`，不要求旧 log 已有 `parsed_object_key`；若恢复点晚于 CLEANING，则要求旧 markdown 坐标存在。
2. `ParsePipelineRepository.mark_superseded(old_pipeline, new_task_id)`：CAS 第 2 层真原子，`UPDATE ... WHERE superseded_by_task_id IS NULL` 依赖 rowcount 仲裁；rowcount=0 抛 `RetryValidationError("RETRY_VALIDATION_FAILED:concurrent_supersede")`。该方法不主动 commit，只把抢占写入当前事务。
3. `ParseLogRepository.create_for_retry(...)` + `ParsePipelineRepository.create_with_inherited_state(old_pipeline, new_log)`：建新 log + 新 pipeline，复制 6 阶段 SUCCESS 状态与 duration，重置非 SUCCESS 阶段。`mark_superseded`、新 log、新 pipeline 三步在同一事务内统一 commit；若新 log 或新 pipeline 创建抛异常，编排层 rollback 整个事务，旧 pipeline 不应残留 `superseded_by_task_id`。若从 CLEANING 恢复，新 log 初始不写 `parsed_*` 字段，等待重新上传 markdown 成功后写真实值。
4. 进入 `StagePipeline.run()`（与首次执行**共用同一编排**），跳过继承到的 SUCCESS 阶段、从首个非 SUCCESS 阶段恢复执行；若恢复点是 CLEANING，则 `CleaningStage` 重新下载源文件、解析、上传 markdown，成功后继续 chunking。**若恢复点是 CHUNKING**（旧 chunking 失败但 markdown 已上传，LINK-32）：cleaning 继承 SUCCESS 被跳过、不重跑解析上传，由 `ChunkingStage.run` 经 `StageServices.load_markdown` 读回旧 markdown 重新分片，`_persist_chunk_facts` 内先 `delete_by_doc_id(doc_id)` 清残留再全量写入、原子重建 chunk truth set，随后继续 dense→pretokenize→es→sparse。chunking 被跳过（继承 SUCCESS）时则由 `ChunkingStage.on_skip` 经 `StageServices.load_all_chunks_from_db(doc_id)` 反查当前文档**完整有效** chunk 真值表（按 `doc_id` + `lifecycle_status=ACTIVE` 过滤，按 `chunk_index` 排序）返回 `list[ChunkRecordDB]` 喂给下游（不再 `chunk_from_record` 包成 splitter `Chunk`），语义等价于首次执行的 chunking 输出。下游 dense / sparse 入口由 `StageServices` 在**编排层现场过滤**决定补做范围：dense 过滤 `dense_vector_status != SUCCESS`，sparse 过滤 `sparse_vector_status != SUCCESS`；named dense 解耦后 sparse 不再要求 dense 已成功，Qdrant point 由 `ensure_points` 兜底创建。dense/sparse 模块不再自查 SQL；多值 CAS 在 SQL 层兜底过滤口径错误。**ES 阶段为文档级全量重建（Issue #57）——不按 `es_status` 补做子集，而是先删该文档全部 ES 索引再基于完整 chunk 集全量重写**（首次执行与重试同一编排）。

校验或 CAS 失败时走 `_handle_retry_validation_failure`：双表落 FAILED 终态（`pipeline_status=FAILED` + `failed_stage=RETRY_VALIDATION` + 前缀 `RETRY_VALIDATION_FAILED:`），不更新任何旧表行（终态写 DB，前端轮询读取）。

## 5. MinerU URL 直拉

当 payload 满足：

```text
file_type == "pdf"
pdf_parser_backend == "mineru"
```

流水线会：

1. 跳过本服务下载源 PDF。
2. 使用 `storage.build_object_url(source_bucket, source_object_key)` 构造 `source_file_url`。
3. 将 URL 传给 `PdfParser` 和 `MinerUBackend`。

生产环境必须保证该 URL 能被 MinerU 官方云端访问，否则 MinerU 任务创建或轮询会失败。

## 6. 失败码

解析和上传阶段使用 `ParseFailureCode`：

- `INVALID_TASK_CONTEXT`
- `DUPLICATE_TASK`
- `INTERRUPTED_TASK`
- `SOURCE_FILE_NOT_FOUND`
- `UNSUPPORTED_FILE_TYPE`
- `PARSE_ENGINE_FAILED`
- `PARSED_FILE_UPLOAD_FAILED`
- `INTERNAL_UNKNOWN_ERROR`
- `LLM_CONFIG_MISSING`（发起用户缺少必配能力的默认 LLM 配置：稠密向量化缺 EMBEDDING 默认配置（仅「确实未配置」时归此码，读取失败仍走 `PARSE_ENGINE_FAILED`），LINK-91。解析增强缺 CHAT/VISION 默认模型现归 `ENHANCEMENT_MODEL_MISSING`）
- `ENHANCEMENT_MODEL_MISSING`（数据集开启表格/图片增强，但发起用户未配对应能力（表格→CHAT，图片→VISION）的默认模型；数据集层不再选择增强模型，统一用用户默认模型，开启增强即要求已配。按约定不回退系统兜底模型，直接失败。表格与图片对称——图片增强模型缺失不再静默跳过）
- `EMBEDDING_DIMENSION_UNSUPPORTED`（稠密向量化：用户模型维度 ≠ `DENSE_VECTOR_DIMENSION`，LINK-91）

后处理阶段还会构造文件级失败原因，并以来源前缀区分（纯内部排障，Java 仅展示不解析）：

- `VECTORIZING_FAILED`
- `pretokenize:`（预分词失败 / 空 plan 但仍有未完成 chunk）
- `es_delete:`（ES 文档级全量重建前置删除失败，如 ES 不可达）
- `ensure_index:`（ES 确保索引存在等基础设施故障）
- `ES_INDEXING_FAILED:`（ES bulk chunk 级写失败）

失败原因统一写入 `failure_reason`，最大长度按数据库字段控制为 512。

## 7. 修改原则

- 不要在 MQ consumer 中直接拼接业务流程，业务编排应留在 `ParseTaskPipeline`。
- `pipeline_status=SUCCESS` 终态写库必须晚于 Markdown、分片、dense 向量化、预分词、ES 入库和 sparse 向量化全部完成。
- 新增阶段时应同步更新 `document_parse_pipeline` 表结构、`docs/api/schemas/mysql.md` 和 `docs/api/error_codes.md`。
- 重投场景必须保持幂等，不应重复解析同一 `task_id`。

## 8. 测试建议

```bash
.venv/bin/pytest tests/unit/core/pipeline/parse_task tests/unit/core/pipeline/stages -q
.venv/bin/pytest tests/unit/core/storage/vector tests/unit/core/storage/chunks -q
.venv/bin/pytest tests/acceptance/test_mq_dlq_poison_pill.py -q
```

建议覆盖：

- 新任务正常全链路。
- 重复 task 的补发、跳过和中断收敛。
- 解析、上传、分片、向量化、ES 失败的终态落库。
- chunking 成功后已批量落库 chunk 真值；SQL 批量落库失败时回滚且不进入向量化。
- vectorizing 只调用 `index_chunks(chunks=...)`（接收 pipeline 现场过滤好的 `list[ChunkRecordDB]`），不再创建 chunk 真值、不再自查 SQL。
- MinerU 后端跳过源文件下载并注入 `source_file_url`；旁路下 `source_path` 在整条链路中保持 `None`，不创建临时文件、不需要清理。
- 预分词失败为文件级 all-or-nothing：落 `pretokenize_status=FAILED`，不写任何 chunk es_status。
- ES 基础设施故障（`ensure_index`）文件级不标 chunk；ES chunk 级失败逐 chunk 标记。
- ES 入库为文档级全量重建（Issue #57）：前置删除 + 全量写入 + 失败清理，首次/重试同一编排；不按 `es_status` 补做子集。
- 失败即终态：ES 失败无 retry_exhausted；各阶段的 `mark_<stage>_started`（如 `mark_cleaning_started`）只清 `failed_stage` / `failure_reason` 等失败痕迹，不清各阶段 `*_status`。所有阶段失败均由对应 `Stage`（经 `Stage.execute` 模板）统一写库（首次/重试同一 `StagePipeline`）。
- 恢复入口推断按首个非 SUCCESS 阶段，`pretokenize_status` 与其他阶段状态列一样跨重投持久。
