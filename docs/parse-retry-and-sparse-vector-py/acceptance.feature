Feature: 解析失败重试链路 + 稀疏向量阶段接入（Python 端 v2）
  作为 RAG 后端
  我希望在收到 Java 端重试请求时跳过已成功阶段、从首个失败阶段恢复执行
  并把稀疏向量化作为解析主流水线的最后一个阶段
  且让 document_parsed_log.task_status 反映整个任务的最终结果
  以便节省重复算力、保证向量索引完备性，并对外提供一致的整体终态语义

  Background:
    Given 解析主流水线 ParseTaskPipeline 已就绪
    And 阶段顺序为 PARSING → CHUNKING → VECTORIZING → PRETOKENIZE → ES_INDEXING → SPARSE_VECTORIZING
    And document_parsed_log.task_status 值域为 {created, success, failed}
    And document_post_process_pipeline.failed_stage 值域为 {PARSING, CHUNKING, VECTORIZING, PRETOKENIZE, ES_INDEXING, SPARSE_VECTORIZING, RETRY_VALIDATION}
    And ParseResultNotifier 通知体仅含 task_id 与 SUCCESS/FAILED 两个字段

  # ==== task_status 写入时机（核心语义不变量）====

  Scenario: 任务刚创建时 task_status=created
    When ParseTaskPipeline 入口为 task_id=T1 调用 _create_log_record
    Then document_parsed_log 行 task_id=T1 task_status=created
    And 同事务建立 document_post_process_pipeline 行 task_id=T1 所有 *_status=PENDING pipeline_status=PENDING

  Scenario: 解析+上传成功仅写 parsed_* 字段不动 task_status
    Given task_id=T1 task_status=created
    When 解析与 markdown 上传成功 mark_parsed 被调用
    Then document_parsed_log.parsed_bucket_name 非空
    And document_parsed_log.parsed_object_key 非空
    And document_parsed_log.parsed_at 非空
    And document_parsed_log.parse_finished_at 非空
    And document_parsed_log.task_status 仍为 created
    And pipeline.pipeline_status 仍为 PROCESSING 或 PENDING

  Scenario: 整条流水线全部 SUCCESS 后才把 task_status 翻转为 success
    Given task_id=T1 已经历 PARSING/CHUNKING/VECTORIZING/PRETOKENIZE/ES_INDEXING 全部 SUCCESS
    When sparse_vectorizing 阶段也 SUCCESS
    Then pipeline.sparse_vectorizing_status=SUCCESS
    And pipeline.pipeline_status=SUCCESS
    And document_parsed_log.task_status=success
    And document_parsed_log.parsed_object_key 已写入
    And ParseResultNotifier 收到 task_id=T1 status=SUCCESS

  Scenario: task_status 与 pipeline_status 双向耦合不变量
    Then 对任意 task_id 必满足 (task_status=success ⇔ pipeline_status=SUCCESS)
    And 必满足 (task_status=failed ⇔ pipeline_status=FAILED)
    And 必满足 (task_status=created ⇔ pipeline_status IN (PENDING, PROCESSING))

  # ==== 主流程：首次解析 ====

  Scenario: 首次解析全链路成功
    Given 收到 ParseTaskPayload(task_id=T1, is_retry=false)
    When ParseTaskPipeline.execute 被调用
    Then 依次执行 解析+上传 → chunking → vectorizing → pretokenize → es_indexing → sparse_vectorizing
    And 全部阶段 SUCCESS
    And document_parsed_log.task_status=success
    And document_parsed_log.retry_of_task_id 为 NULL
    And pipeline.pipeline_status=SUCCESS
    And ParseResultNotifier 收到 status=SUCCESS

  Scenario: 老消息缺省 is_retry 字段按首次解析处理
    Given 收到 ParseTaskPayload(task_id=T2) 未携带 is_retry 字段
    When ParseTaskPipeline.execute 被调用
    Then is_retry 默认取 false
    And 走首次解析分支
    And 不进入 ParseTaskGuard.validate_retry_context

  Scenario: 解析阶段失败 log 与 pipeline 同步落 FAILED
    Given 收到 ParseTaskPayload(task_id=T1, is_retry=false)
    And pipeline 行已在入口建好 全 PENDING
    When 解析或 markdown 上传抛出异常
    Then document_parsed_log.task_status=failed
    And document_parsed_log.failure_reason 以 "PARSING_FAILED:" 开头
    And document_parsed_log.parsed_object_key 为 NULL
    And pipeline.pipeline_status=FAILED
    And pipeline.failed_stage=PARSING
    And pipeline.failure_reason 以 "PARSING_FAILED:" 开头
    And pipeline 各阶段 *_status 保持 PENDING
    And ParseResultNotifier 收到 status=FAILED
    And 不进入任何后处理阶段

  # ==== 主流程：重试解析 ====

  Scenario: 重试场景跳过已 SUCCESS 阶段从首个失败阶段恢复
    Given 旧 task_id=T1 对应 document_parsed_log.parsed_object_key 非空
    And 旧 document_post_process_pipeline 状态为 chunking=SUCCESS vectorizing=SUCCESS pretokenize=FAILED es_indexing=PENDING sparse_vectorizing=PENDING
    And 旧 pipeline.pipeline_status=FAILED
    And 旧 pipeline.recover_from_stage=PRETOKENIZE
    And 旧 pipeline.superseded_by_task_id 为 NULL
    When 收到 ParseTaskPayload(task_id=T2, is_retry=true, previous_task_id=T1, md_bucket=B, md_object_key=K) 并 execute
    Then 不执行 _parse_file 与 _upload_markdown
    And 新 document_parsed_log 行 task_id=T2 task_status=created retry_of_task_id=T1 parsed_bucket_name=B parsed_object_key=K
    And 新 document_parsed_log.parse_started_at 为 NULL
    And 新 document_parsed_log.parse_finished_at 为 NULL
    And 新 document_post_process_pipeline 行 task_id=T2 chunking_status=SUCCESS vectorizing_status=SUCCESS pretokenize_status=PENDING es_indexing_status=PENDING sparse_vectorizing_status=PENDING
    And 新 pipeline.recover_from_stage=PRETOKENIZE
    And 新 pipeline.failed_stage 为 NULL
    And 新 pipeline.failure_reason 为 NULL
    And 跳过 chunking 与 vectorizing 阶段实际执行
    And 从 PRETOKENIZE 阶段开始执行
    And 旧 document_post_process_pipeline 行被 UPDATE superseded_by_task_id=T2 其他字段保持原值

  Scenario: 重试场景继承的 SUCCESS 阶段保留旧 duration_ms 重置阶段清空
    Given 旧 pipeline chunking_status=SUCCESS chunking_duration_ms=8000 vectorizing_status=FAILED vectorizing_duration_ms=5000
    When 收到合法重试消息并 execute 进入重试分支
    Then 新 pipeline.chunking_duration_ms == 8000
    And 新 pipeline.vectorizing_duration_ms 为 NULL
    And 重试本次实际执行的阶段在完成后写入本次 duration_ms

  Scenario: 重试场景跳过 chunking 时从 DB 反查 chunks 喂给下游
    Given 旧 pipeline chunking_status=SUCCESS vectorizing_status=FAILED
    And chunk 表存在 doc_id 对应行 vector_status IN (PENDING, FAILED) 共 5 行
    When execute 进入重试分支并跳过 chunking
    Then 编排层调用 _load_chunks_from_db(doc_id) 反查谓词为 vector_status IN (PENDING, FAILED)
    And 返回 list[Chunk] 共 5 个内存对象
    And 同一 chunks 变量传入 _store_chunk_vectors
    And vectorizing/pretokenize/es/sparse 阶段方法签名未发生变化

  Scenario: 重试全链路成功时 task_status 在 sparse SUCCESS 后才写 success
    Given 收到合法重试消息 task_id=T2 previous_task_id=T1
    When 后续 PRETOKENIZE/ES_INDEXING/SPARSE_VECTORIZING 全部 SUCCESS
    Then 期间 task_status 始终保持 created
    And 仅在 sparse 阶段 SUCCESS 后 task_status 翻转为 success
    And pipeline.pipeline_status=SUCCESS

  # ==== 重试前置校验失败（双表落库）====

  Scenario Outline: ParseTaskGuard.validate_retry_context 校验失败统一落 FAILED 并通知
    Given <前置条件>
    When 收到 ParseTaskPayload(task_id=Tnew, is_retry=true, previous_task_id=<prev>) 并 execute
    Then ParseTaskGuard 抛出 RetryValidationError
    And 新建 document_parsed_log 行 task_id=Tnew task_status=failed retry_of_task_id=<prev>
    And 新 log.failure_reason 以 "RETRY_VALIDATION_FAILED:" 开头
    And 新 log 的 parsed_bucket_name / parsed_object_key / parsed_at / parse_*_at 全部为 NULL
    And 新建 document_post_process_pipeline 行 task_id=Tnew pipeline_status=FAILED failed_stage=RETRY_VALIDATION
    And 新 pipeline.failure_reason 以 "RETRY_VALIDATION_FAILED:" 开头
    And 新 pipeline 各阶段 *_status 保持 PENDING
    And 新 pipeline.started_at == 新 pipeline.finished_at == 拒绝瞬间时间
    And 新 pipeline 各 *_duration_ms 全部为 NULL
    And 不更新任何旧 log 行
    And 不更新任何旧 pipeline 行的 superseded_by_task_id
    And ParseResultNotifier 收到一条消息 task_id=Tnew status=FAILED
    And 不进入任何后处理阶段

    Examples:
      | 前置条件                                                                | prev   |
      | previous_task_id 为空                                                   | null   |
      | task_id=T1 对应的 document_parsed_log 不存在                            | T1     |
      | 旧 log.parsed_object_key 为 NULL（即上次未上传过 markdown）             | T1     |
      | 旧 document_post_process_pipeline 不存在                                | T1     |
      | 旧 pipeline.pipeline_status=SUCCESS                                     | T1     |
      | 旧 pipeline.pipeline_status=PROCESSING                                  | T1     |
      | 旧 pipeline.recover_from_stage 为 NULL                                  | T1     |
      | 旧 pipeline.superseded_by_task_id 非空（CAS 第 1 层快速失败）           | T1     |
      | payload.md_bucket 或 md_object_key 为空                                 | T1     |

  # ==== 并发重试 CAS 第 2 层兜底 ====

  Scenario: 两次并发重试同时通过第 1 层校验后 mark_superseded 通过 rowcount 仲裁
    Given 旧 pipeline task_id=T1 superseded_by_task_id 为 NULL
    And 重试请求 R1(task_id=T2) 与 R2(task_id=T3) 并发到达 previous_task_id 均为 T1
    And R1 与 R2 在 validate_retry_context SELECT 阶段均看到 superseded_by_task_id IS NULL（第 1 层均通过）
    When R1 先执行 mark_superseded UPDATE superseded_by_task_id=T2 WHERE superseded_by_task_id IS NULL 返回 rowcount=1
    And R2 后执行 mark_superseded UPDATE superseded_by_task_id=T3 WHERE superseded_by_task_id IS NULL 返回 rowcount=0
    Then R1 继续走重试成功路径
    And R2 走"重试校验失败的落库形态"路径
    And R2 的 log.task_status=failed pipeline.failed_stage=RETRY_VALIDATION
    And ParseResultNotifier 对 R2 通知 status=FAILED
    And 旧 pipeline.superseded_by_task_id 最终为 T2

  # ==== Dense 向量化失败与重试语义 ====

  Scenario: dense 向量化首次执行任一 chunk 失败立即终止后续阶段不执行
    Given 进入 vectorizing 阶段共 10 个 chunk 状态全为 PENDING
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
    And document_parsed_log.task_status=failed
    And ParseResultNotifier 收到 status=FAILED
    And 不进入 pretokenize/es/sparse 阶段

  Scenario: 重试 vectorizing 只补做未完成 chunk 不重做 INDEXED
    Given 进入重试 vectorizing 阶段 chunk 表 doc_id 对应共 10 行 其中 2 行 INDEXED 1 行 FAILED 7 行 PENDING
    When _load_chunks_from_db 按 vector_status IN (PENDING, FAILED) 反查
    Then 反查返回 8 行待处理 chunk
    And 不对 2 行 INDEXED chunk 重新生成向量
    And 全部 8 行处理成功后 全部 chunk vector_status=INDEXED
    And pipeline.vectorizing_status=SUCCESS
    And 进入 pretokenize 阶段

  Scenario: 重试 vectorizing 若仍有 chunk 失败按首次失败路径处理
    Given 进入重试 vectorizing 阶段反查到 5 行待处理 chunk
    When 第 2 行 chunk 处理失败
    Then 立即终止本次执行
    And pipeline.vectorizing_status=FAILED
    And document_parsed_log.task_status=failed
    And ParseResultNotifier 收到 status=FAILED

  # ==== 稀疏向量阶段 ====

  Scenario: 稀疏向量阶段在 ES 成功后执行成功后通知 SUCCESS
    Given pretokenize 与 es_indexing 阶段已 SUCCESS
    And chunk 表 doc_id 对应行 vector_status=INDEXED 且 es_status=SUCCESS 且 sparse_vector_status=PENDING 共 6 行
    When _run_sparse_vectorizing 被调用
    Then 调用 SparseIndexingPipeline 文件级批量生成稀疏向量
    And 6 行 chunk sparse_vector_status=INDEXED
    And pipeline.sparse_vectorizing_status=SUCCESS
    And pipeline.sparse_vectorizing_duration_ms 已写入
    And pipeline.pipeline_status=SUCCESS
    And pipeline.finished_at 与 total_duration_ms 已写入
    And document_parsed_log.task_status=success
    And ParseResultNotifier 收到 status=SUCCESS

  Scenario: 稀疏向量阶段任一 chunk 失败整体 FAILED
    Given 稀疏向量阶段进入时反查到 4 行待处理 chunk
    When 第 2 行 chunk 处理失败
    Then 第 2 行 chunk sparse_vector_status=FAILED
    And pipeline.sparse_vectorizing_status=FAILED
    And pipeline.pipeline_status=FAILED
    And pipeline.failed_stage=SPARSE_VECTORIZING
    And pipeline.recover_from_stage=SPARSE_VECTORIZING
    And pipeline.failure_reason 以 "SPARSE_VECTORIZING_FAILED:" 开头
    And document_parsed_log.task_status=failed
    And ParseResultNotifier 收到 status=FAILED

  Scenario: 重试稀疏向量阶段只补做未完成 chunk
    Given 进入重试 sparse 阶段 chunk 表中 4 行 sparse_vector_status=INDEXED 3 行 FAILED 0 行 PENDING
    When _run_sparse_vectorizing 反查待处理 chunk
    Then 反查谓词为 sparse_vector_status IN (PENDING, FAILED) AND vector_status=INDEXED
    And 反查返回 3 行
    And 不对 4 行 INDEXED chunk 重做
    And 3 行处理成功后 pipeline.sparse_vectorizing_status=SUCCESS

  Scenario: 稀疏向量阶段进入时全部 chunk 已 INDEXED 直接判 SUCCESS
    Given 稀疏向量阶段反查待处理 chunk 结果为空
    And chunk 表 doc_id 对应行总数 > 0 且全部 sparse_vector_status=INDEXED
    When _run_sparse_vectorizing 执行
    Then 不调用 SparseVectorService
    And pipeline.sparse_vectorizing_status=SUCCESS

  Scenario: 稀疏向量阶段 chunk 总数为 0 判定状态不一致 FAILED
    Given chunk 表 doc_id 对应行总数 == 0
    When _run_sparse_vectorizing 执行
    Then 抛出文件级异常
    And pipeline.sparse_vectorizing_status=FAILED
    And pipeline.failed_stage=SPARSE_VECTORIZING
    And document_parsed_log.task_status=failed
    And ParseResultNotifier 收到 status=FAILED

  Scenario: 稀疏向量阶段单批失败时整体 FAILED 已成功批次保留
    Given 待处理 chunk 数超过单次 batch 上限 _run_sparse_vectorizing 内部分批调用
    When 第 N 批调用失败
    Then 此前已成功批次的 chunk sparse_vector_status=INDEXED 保留
    And 当前失败批次中触发失败的 chunk sparse_vector_status=FAILED
    And pipeline.sparse_vectorizing_status=FAILED
    And ParseResultNotifier 收到 status=FAILED

  # ==== 跳阶段数据完整性 ====

  Scenario: 重试跳过 chunking 后 _load_chunks_from_db 反查为空落 FAILED
    Given 旧 pipeline.chunking_status=SUCCESS
    And chunk 表 doc_id 对应行已被外部清理 反查结果为空
    When _load_chunks_from_db 被调用
    Then 显式校验失败
    And pipeline.vectorizing_status=FAILED
    And document_parsed_log.task_status=failed
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

  # ==== Schema 变更 ====

  Scenario: 数据库 schema 通过 Alembic 迁移落地新增与删除字段
    Given 仓库已包含新增的 migrations/versions/00XX_*.py
    When 迁移 upgrade 执行后
    Then document_parsed_log 表存在列 retry_of_task_id VARCHAR(36) NULL
    And document_parsed_log 存在索引 idx_parsed_log_retry_of
    And document_parsed_log.task_status 字段值域文档表述为 "整体任务最终结果"
    And document_post_process_pipeline 表存在列 sparse_vectorizing_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
    And document_post_process_pipeline 表存在列 sparse_vectorizing_duration_ms BIGINT NULL
    And document_post_process_pipeline 表存在列 superseded_by_task_id VARCHAR(36) NULL
    And document_post_process_pipeline 存在索引 idx_post_pipeline_superseded
    And document_post_process_pipeline.failed_stage 允许值集合 ⊇ {PARSING, CHUNKING, VECTORIZING, PRETOKENIZE, ES_INDEXING, SPARSE_VECTORIZING, RETRY_VALIDATION}
    And document_post_process_pipeline 不存在列 retry_count
    And document_post_process_pipeline 不存在列 last_retry_at
    And scripts/db/init.sql 未被本次改动修改
