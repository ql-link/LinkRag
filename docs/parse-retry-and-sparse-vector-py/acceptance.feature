Feature: 解析失败重试链路 + 稀疏向量阶段接入（Python 端 v3）
  作为 RAG 后端
  我希望在收到 Java 端重试请求时跳过已成功阶段、从首个失败阶段恢复执行
  并把稀疏向量化作为解析主流水线的最后一个阶段
  且把整体任务状态的权威唯一收敛到 document_post_process_pipeline.pipeline_status
  以便节省重复算力、保证向量索引完备性，对外提供一致的整体终态语义

  Background:
    Given 解析主流水线 ParseTaskPipeline 已就绪
    And 阶段顺序为 PARSING → CHUNKING → VECTORIZING → PRETOKENIZE → ES_INDEXING → SPARSE_VECTORIZING
    And document_post_process_pipeline 是文件解析流程状态表 覆盖 6 阶段全状态机
    And document_parsed_log 仅承担解析产物快照 不再含 task_status 与 failure_reason 字段
    And pipeline.pipeline_status 值域为 {PENDING, PROCESSING, SUCCESS, FAILED} 是整体任务终态唯一权威
    And pipeline.failed_stage 值域为 {PARSING, CHUNKING, VECTORIZING, PRETOKENIZE, ES_INDEXING, SPARSE_VECTORIZING, RETRY_VALIDATION}
    And 每个阶段 *_status 值域为 {PENDING, PROCESSING, SUCCESS, FAILED}
    And ParseResultNotifier 通知体仅含 task_id 与 SUCCESS/FAILED 两个字段

  # ==== 状态权威单源化（核心不变量）====

  Scenario: 行刚创建时整体处于 PENDING
    When ParseTaskPipeline 入口为 task_id=T1 调用 _create_log_record
    Then document_parsed_log 行 task_id=T1 已建立 且不含 task_status / failure_reason 字段
    And 同事务建立 document_post_process_pipeline 行 task_id=T1
    And pipeline.pipeline_status=PENDING
    And pipeline.parsing_status=PENDING
    And 其余 5 个 *_status 均为 PENDING

  Scenario: 首个 mark_*_started 把 pipeline_status 从 PENDING 翻为 PROCESSING
    Given task_id=T1 pipeline_status=PENDING parsing_status=PENDING
    When execute 进入解析阶段调用 mark_parsing_started
    Then pipeline.pipeline_status=PROCESSING
    And pipeline.parsing_status=PROCESSING
    And pipeline.started_at 已写入

  Scenario: 后续 mark_*_started 对已为 PROCESSING 的 pipeline_status 不重复翻转
    Given task_id=T1 pipeline_status=PROCESSING
    When 进入 chunking 阶段调用 mark_chunking_started
    Then pipeline.pipeline_status 仍为 PROCESSING
    And pipeline.chunking_status=PROCESSING

  Scenario: 全 6 阶段 SUCCESS 后整体终态才置 SUCCESS
    Given task_id=T1 已完成 PARSING/CHUNKING/VECTORIZING/PRETOKENIZE/ES_INDEXING 五阶段全 SUCCESS
    When sparse_vectorizing 阶段 SUCCESS
    Then pipeline.sparse_vectorizing_status=SUCCESS
    And pipeline.pipeline_status=SUCCESS
    And pipeline.finished_at 与 total_duration_ms 已写入
    And document_parsed_log.parsed_object_key 非空
    And ParseResultNotifier 收到 task_id=T1 status=SUCCESS

  # ==== 主流程：首次解析 ====

  Scenario: 首次解析全链路成功
    Given 收到 ParseTaskPayload(task_id=T1, is_retry=false)
    When ParseTaskPipeline.execute 被调用
    Then 依次执行 解析+上传 → chunking → vectorizing → pretokenize → es_indexing → sparse_vectorizing
    And 全部 6 阶段 *_status=SUCCESS
    And 各阶段 *_duration_ms 均已写入（含 parsing_duration_ms）
    And document_parsed_log.retry_of_task_id 为 NULL
    And pipeline.pipeline_status=SUCCESS
    And ParseResultNotifier 收到 status=SUCCESS

  Scenario: 老消息缺省 is_retry 字段按首次解析处理
    Given 收到 ParseTaskPayload(task_id=T2) 未携带 is_retry 字段
    When ParseTaskPipeline.execute 被调用
    Then is_retry 默认取 false
    And 走首次解析分支
    And 不进入 ParseTaskGuard.validate_retry_context

  Scenario: 解析阶段失败仅在 pipeline 落 FAILED
    Given 收到 ParseTaskPayload(task_id=T1, is_retry=false)
    And pipeline 行已在入口建好 全 *_status=PENDING
    When 解析或 markdown 上传抛出异常 mark_parsing_failed 被调用
    Then pipeline.parsing_status=FAILED
    And pipeline.pipeline_status=FAILED
    And pipeline.failed_stage=PARSING
    And pipeline.failure_reason 以 "PARSING_FAILED:" 开头
    And pipeline.parsing_duration_ms 已写入
    And 其余 5 个 *_status 保持 PENDING
    And document_parsed_log.parsed_object_key 为 NULL
    And document_parsed_log 行不含 task_status 与 failure_reason 字段
    And ParseResultNotifier 收到 status=FAILED
    And 不进入任何后处理阶段

  # ==== 主流程：重试解析 ====

  Scenario: 重试场景通过继承的 *_status=SUCCESS 跳过已成功阶段从首个失败阶段恢复
    Given 旧 task_id=T1 旧 log.parsed_object_key 非空
    And 旧 pipeline 状态 parsing_status=SUCCESS chunking_status=SUCCESS vectorizing_status=SUCCESS pretokenize_status=FAILED es_indexing_status=PENDING sparse_vectorizing_status=PENDING
    And 旧 pipeline.pipeline_status=FAILED
    And 旧 pipeline.recover_from_stage=PRETOKENIZE
    And 旧 pipeline.superseded_by_task_id 为 NULL
    When 收到 ParseTaskPayload(task_id=T2, is_retry=true, previous_task_id=T1, md_bucket=B, md_object_key=K) 并 execute
    Then ParseTaskGuard.validate_retry_context 校验通过
    And 先调用 mark_superseded 抢占旧 pipeline 行 rowcount=1
    And 之后调用 create_for_retry 建立新 log create_with_inherited_state 建立新 pipeline
    And 新 log 行 task_id=T2 retry_of_task_id=T1 parsed_bucket_name=B parsed_object_key=K
    And 新 log.parse_started_at 与 parse_finished_at 均为 NULL
    And 新 pipeline.parsing_status=SUCCESS chunking_status=SUCCESS vectorizing_status=SUCCESS pretokenize_status=PENDING es_indexing_status=PENDING sparse_vectorizing_status=PENDING
    And 新 pipeline.recover_from_stage=PRETOKENIZE
    And 新 pipeline.failed_stage 为 NULL 且 failure_reason 为 NULL
    And execute 主链路对 PARSING/CHUNKING/VECTORIZING 三阶段命中 *_status=SUCCESS 跳过分支 不实际执行
    And 不调用 _parse_file 与 _upload_markdown
    And 从 PRETOKENIZE 阶段开始实际执行
    And 旧 pipeline 行被 UPDATE superseded_by_task_id=T2 其余字段保持原值

  Scenario: 重试场景继承的 SUCCESS 阶段保留旧 duration_ms 重置阶段清空
    Given 旧 pipeline parsing_status=SUCCESS parsing_duration_ms=12000 chunking_status=SUCCESS chunking_duration_ms=8000 vectorizing_status=FAILED vectorizing_duration_ms=5000
    When 收到合法重试消息并 execute 进入重试分支创建新 pipeline
    Then 新 pipeline.parsing_duration_ms == 12000
    And 新 pipeline.chunking_duration_ms == 8000
    And 新 pipeline.vectorizing_duration_ms 为 NULL
    And 本次实际执行的阶段在完成后写入本次 duration_ms

  Scenario: 重试场景跳过 chunking 时从 DB 反查 chunks 喂给下游
    Given 旧 pipeline chunking_status=SUCCESS vectorizing_status=FAILED
    And chunk 表存在 doc_id 对应行 vector_status IN (PENDING, FAILED) 共 5 行
    When execute 进入重试分支并对 chunking 命中跳过分支
    Then 编排层调用 _load_chunks_from_db(doc_id) 反查谓词为 vector_status IN (PENDING, FAILED)
    And 返回 list[Chunk] 共 5 个内存对象
    And 同一 chunks 变量传入 _store_chunk_vectors
    And vectorizing/pretokenize/es/sparse 阶段方法签名未发生变化

  # ==== 重试前置校验失败（log + pipeline 同步落库，状态权威在 pipeline）====

  Scenario Outline: validate_retry_context 校验失败统一抛 RetryValidationError 并落 FAILED
    Given <前置条件>
    When 收到 ParseTaskPayload(task_id=Tnew, is_retry=true, previous_task_id=<prev>) 并 execute
    Then ParseTaskGuard 抛出 RetryValidationError
    And 不调用 mark_superseded
    And 新建 document_parsed_log 行 task_id=Tnew retry_of_task_id=<prev>
    And 新 log 行不含 task_status 与 failure_reason 字段
    And 新 log 的 parsed_bucket_name / parsed_object_key / parsed_at / parse_*_at 全部为 NULL
    And 新建 document_post_process_pipeline 行 task_id=Tnew pipeline_status=FAILED failed_stage=RETRY_VALIDATION
    And 新 pipeline.failure_reason 以 "RETRY_VALIDATION_FAILED:" 开头
    And 新 pipeline 各阶段 *_status 保持 PENDING（含 parsing_status）
    And 新 pipeline.started_at == 新 pipeline.finished_at == 拒绝瞬间时间
    And 新 pipeline 各 *_duration_ms 全部为 NULL
    And 不更新任何旧 log 行
    And 不更新任何旧 pipeline 行的 superseded_by_task_id
    And ParseResultNotifier 收到一条消息 task_id=Tnew status=FAILED
    And 不进入任何后处理阶段

    Examples:
      | 前置条件                                                                | prev |
      | previous_task_id 为空                                                   | null |
      | task_id=T1 对应的 document_parsed_log 不存在                            | T1   |
      | 旧 log.parsed_object_key 为 NULL                                        | T1   |
      | 旧 document_post_process_pipeline 不存在                                | T1   |
      | 旧 pipeline.pipeline_status=SUCCESS                                     | T1   |
      | 旧 pipeline.pipeline_status=PROCESSING                                  | T1   |
      | 旧 pipeline.recover_from_stage 为 NULL                                  | T1   |
      | 旧 pipeline.superseded_by_task_id 非空（CAS 第 1 层快速失败）           | T1   |
      | payload.md_bucket 或 md_object_key 为空                                 | T1   |

  # ==== 并发重试 CAS 第 2 层兜底（顺序：validate → mark_superseded → create new rows）====

  Scenario: 两次并发重试通过第 1 层校验后 mark_superseded rowcount 仲裁失败方不建新行
    Given 旧 pipeline task_id=T1 superseded_by_task_id 为 NULL
    And 重试请求 R1(task_id=T2) 与 R2(task_id=T3) 并发到达 previous_task_id 均为 T1
    And R1 与 R2 在 validate_retry_context 阶段均通过第 1 层 SELECT 校验
    When R1 先执行 mark_superseded UPDATE WHERE superseded_by_task_id IS NULL 返回 rowcount=1
    And R2 后执行 mark_superseded 返回 rowcount=0
    Then R1 继续走 create_for_retry + create_with_inherited_state 路径
    And R2 由编排层包装 rowcount=0 抛 RetryValidationError
    And R2 走"重试校验失败的落库形态"路径（新建 log + pipeline 行 pipeline_status=FAILED failed_stage=RETRY_VALIDATION）
    And R2 的失败路径不会创建带继承状态的新 pipeline 行（CAS 失败先于 create_with_inherited_state）
    And ParseResultNotifier 对 R2 通知 status=FAILED
    And 旧 pipeline.superseded_by_task_id 最终为 T2

  # ==== Dense 向量化失败与重试语义 ====

  Scenario: dense 向量化首次任一 chunk 失败立即终止后续阶段不执行
    Given 进入 vectorizing 阶段共 10 个 chunk vector_status 全为 PENDING
    When 第 3 个 chunk 处理时抛出异常
    Then 立即终止 vectorizing 后续 chunk 处理
    And 第 1、2 个 chunk vector_status=INDEXED 保留
    And 第 3 个 chunk vector_status=FAILED
    And 第 4-10 个 chunk vector_status=PENDING 保留
    And pipeline.vectorizing_status=FAILED
    And pipeline.pipeline_status=FAILED
    And pipeline.failed_stage=VECTORIZING
    And pipeline.recover_from_stage=VECTORIZING
    And pipeline.failure_reason 以 "VECTORIZING_FAILED:" 开头
    And ParseResultNotifier 收到 status=FAILED
    And 不进入 pretokenize/es/sparse 阶段

  Scenario: 重试 vectorizing 只补做未完成 chunk 不重做 INDEXED
    Given 进入重试 vectorizing 阶段 chunk 表 doc_id 对应共 10 行 其中 2 行 INDEXED 1 行 FAILED 7 行 PENDING
    When _load_chunks_from_db 按 vector_status IN (PENDING, FAILED) 反查
    Then 反查返回 8 行待处理 chunk
    And 不对 2 行 INDEXED chunk 重新生成向量
    And 全部 8 行处理成功后 chunk 表 doc_id 对应全部行 vector_status=INDEXED
    And pipeline.vectorizing_status=SUCCESS
    And 进入 pretokenize 阶段

  # ==== 稀疏向量阶段 ====

  Scenario: 稀疏向量阶段在 ES 成功后执行成功并把整体 pipeline_status 翻 SUCCESS
    Given pretokenize 与 es_indexing 阶段已 SUCCESS
    And chunk 表 doc_id 对应行 vector_status=INDEXED 且 es_status=SUCCESS 且 sparse_vector_status=PENDING 共 6 行
    When _run_sparse_vectorizing 被调用
    Then SparseIndexingPipeline 文件级批量生成稀疏向量并 upsert Qdrant
    And 6 行 chunk sparse_vector_status=INDEXED
    And pipeline.sparse_vectorizing_status=SUCCESS
    And pipeline.sparse_vectorizing_duration_ms 已写入
    And pipeline.pipeline_status=SUCCESS
    And pipeline.finished_at 与 total_duration_ms 已写入
    And ParseResultNotifier 收到 status=SUCCESS

  Scenario: 稀疏向量阶段任一 chunk 失败整体 FAILED 失败痕迹保留
    Given 稀疏向量阶段进入时反查到 4 行待处理 chunk
    When 第 2 行 chunk 处理失败
    Then 第 2 行 chunk sparse_vector_status=FAILED
    And pipeline.sparse_vectorizing_status=FAILED
    And pipeline.pipeline_status=FAILED
    And pipeline.failed_stage=SPARSE_VECTORIZING
    And pipeline.recover_from_stage=SPARSE_VECTORIZING
    And pipeline.failure_reason 以 "SPARSE_VECTORIZING_FAILED:" 开头
    And ParseResultNotifier 收到 status=FAILED

  Scenario: 稀疏向量阶段重试时只补做未完成 chunk
    Given 进入重试 sparse 阶段 chunk 表中 4 行 sparse_vector_status=INDEXED 3 行 FAILED 0 行 PENDING
    When _run_sparse_vectorizing 反查待处理 chunk
    Then 反查谓词为 sparse_vector_status IN (PENDING, FAILED) AND vector_status=INDEXED
    And 反查返回 3 行
    And 不对 4 行 INDEXED chunk 重做
    And 3 行处理成功后 pipeline.sparse_vectorizing_status=SUCCESS

  Scenario Outline: 稀疏向量阶段前置数据健康性校验
    Given chunk 表 doc_id 对应行 <数据状态>
    When _run_sparse_vectorizing 执行
    Then 实际行为为 <结果>

    Examples:
      | 数据状态                                                | 结果                                                                                                        |
      | 总行数 == 0                                             | 抛文件级异常 pipeline.sparse_vectorizing_status=FAILED failed_stage=SPARSE_VECTORIZING 通知 FAILED          |
      | 总行数 > 0 且全部 sparse_vector_status=INDEXED          | 不调用 SparseVectorService 直接 pipeline.sparse_vectorizing_status=SUCCESS                                  |

  # ==== 跳阶段数据完整性 ====

  Scenario: 重试跳过 chunking 后 _load_chunks_from_db 反查为空判状态不一致落 FAILED
    Given 旧 pipeline.chunking_status=SUCCESS
    And chunk 表 doc_id 对应行已被外部清理 反查结果为空
    When _load_chunks_from_db 被调用
    Then 显式校验失败
    And pipeline.vectorizing_status=FAILED
    And pipeline.pipeline_status=FAILED
    And pipeline.failed_stage=VECTORIZING
    And ParseResultNotifier 收到 status=FAILED
    And 不进入 pretokenize/es/sparse 阶段

  # ==== 通知契约 ====

  Scenario: 重试成功通知不回带 previous_task_id 或 retry_of_task_id
    Given 重试任务 task_id=T2 retry_of_task_id=T1 全部阶段 SUCCESS
    When ParseResultNotifier 发出通知
    Then 通知体字段集合等于 {task_id, status}
    And task_id == T2
    And status == SUCCESS
    And 通知体不包含 previous_task_id 字段
    And 通知体不包含 retry_of_task_id 字段

  # ==== Schema 变更（配套 issue #46 已先行合入为前提）====

  Scenario: 数据库 schema 通过 Alembic 迁移落地字段增删
    Given 仓库已包含本期新增的 migrations/versions/00XX_*.py
    And 配套 issue #46 的 migration 已先行 stamp
    When 迁移 upgrade 执行后
    Then document_parsed_log 表存在列 retry_of_task_id VARCHAR(36) NULL
    And document_parsed_log 存在索引 idx_parsed_log_retry_of
    And document_parsed_log 不存在列 task_status
    And document_parsed_log 不存在列 failure_reason
    And document_post_process_pipeline 表存在列 parsing_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
    And document_post_process_pipeline 表存在列 parsing_duration_ms BIGINT NULL
    And document_post_process_pipeline 表存在列 sparse_vectorizing_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
    And document_post_process_pipeline 表存在列 sparse_vectorizing_duration_ms BIGINT NULL
    And document_post_process_pipeline 表存在列 superseded_by_task_id VARCHAR(36) NULL
    And document_post_process_pipeline 存在索引 idx_post_pipeline_superseded
    And document_post_process_pipeline 不存在列 chunk_count
    And document_post_process_pipeline 不存在列 retry_count
    And document_post_process_pipeline 不存在列 last_retry_at
    And document_post_process_pipeline.failed_stage 允许值集合 ⊇ {PARSING, CHUNKING, VECTORIZING, PRETOKENIZE, ES_INDEXING, SPARSE_VECTORIZING, RETRY_VALIDATION}
    And document_post_process_pipeline 表注释为 "文件解析流程状态表"
    And scripts/db/init.sql 未被本次改动修改
