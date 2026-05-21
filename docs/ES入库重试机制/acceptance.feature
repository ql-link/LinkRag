# ⚠️ 本方向已废弃（2026-05）
# 本目录文档对应的 ES 入库后台自动重试方案与项目流水线"用户驱动 + 断点续跑"契约不一致，
# 已被 leader 否决（见 issue #25 review）。实际实现改为用户手动重试路径，
# 详见 docs/ES入库手动重试/brief.md。
# 本文件仅保留作历史决策记录，不再维护，亦不反映线上代码现状。

Feature: ES入库重试机制
  作为 RAG 后处理流水线
  我希望 ES 入库失败后能够被独立补偿重试
  以便解析、分块和向量化已成功的文档最终补齐全文索引并修正业务侧状态

  Background:
    Given ES 入库重试调度已启用
    And ES_INDEXING_MAX_RETRY == 3
    And parse_result 通知使用原 topic

  # ==== 主流程 ====

  Scenario: 调度器只领取 ES 入库可恢复失败记录
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    And 后处理记录 task=T2 pipeline_status=FAILED recover_from_stage=VECTORIZING es_indexing_status=PENDING retry_count=0
    And 后处理记录 task=T3 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=3
    When ES 重试调度执行一轮扫描 limit=10
    Then task=T1 被认领进入 ES 重试
    And task=T2 不被认领
    And task=T3 不被认领

  Scenario: ES 重试成功后后处理流水线收敛为成功
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    And task=T1 的解析日志状态为 success
    And task=T1 的 chunk 真值和 dense 向量结果已存在
    When ES 重试执行 task=T1 且 ES 入库返回全部成功
    Then task=T1 的 pipeline_status == SUCCESS
    And task=T1 的 es_indexing_status == SUCCESS
    And task=T1 的 failed_stage 为空
    And task=T1 的 recover_from_stage 为空
    And task=T1 的 failure_reason 为空

  Scenario: ES 重试成功后使用原 task_id 补发 success 通知
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    And task=T1 上一次已经发送 parse_result failed
    When ES 重试执行 task=T1 且 ES 入库返回全部成功
    Then parse_result topic 收到一条 success 消息 task_id=T1
    And success 消息使用 task=T1 的原 document_parse_task_id
    And success 消息的 failure_reason 为空

  Scenario: ES 重试只执行 ES 入库阶段
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    And task=T1 的解析、Markdown 上传、分块和 dense 向量化均已成功
    When ES 重试执行 task=T1
    Then 不重新执行文件解析
    And 不重新上传 Markdown
    And 不重新执行分块
    And 不重新执行 dense 向量化
    And 重新执行 ES 入库

  # ==== 异常与终态 ====

  Scenario: ES 重试失败但未达到上限时保留可恢复失败
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    When ES 重试执行 task=T1 且 ES 入库返回失败 reason="es_bulk: timeout"
    Then task=T1 的 pipeline_status == FAILED
    And task=T1 的 recover_from_stage == ES_INDEXING
    And task=T1 的 es_indexing_status == FAILED
    And task=T1 的 retry_count == 2
    And task=T1 的 failure_reason 包含 "es_bulk: timeout"
    And task=T1 的 failure_reason 不包含 "retry_exhausted=true"
    And parse_result topic 未收到 task_id=T1 的新 failed 消息

  Scenario: ES 重试失败达到上限后标记耗尽并补发 failed
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=2
    When ES 重试执行 task=T1 且 ES 入库返回失败 reason="es_bulk: timeout"
    Then task=T1 的 pipeline_status == FAILED
    And task=T1 的 recover_from_stage == ES_INDEXING
    And task=T1 的 retry_count == 3
    And task=T1 的 failure_reason 包含 "retry_exhausted=true"
    And parse_result topic 收到一条 failed 消息 task_id=T1

  Scenario: 已达到重试上限的记录不会被自动领取
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=3
    When ES 重试调度执行一轮扫描 limit=10
    Then task=T1 不被认领
    And task=T1 的 retry_count == 3
    And 不执行 task=T1 的 ES 入库

  Scenario: 缺失原始任务上下文时记录明确失败原因
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    And task=T1 的原始解析上下文不存在
    When ES 重试执行 task=T1
    Then task=T1 的 pipeline_status == FAILED
    And task=T1 的 retry_count == 2
    And task=T1 的 failure_reason 包含 "parse task context missing"
    And 不执行 task=T1 的 ES 入库

  # ==== 幂等与并发 ====

  Scenario: 两个调度器同时扫描时同一记录只会被一个调度器认领
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    When 调度器 A 和调度器 B 同时尝试认领 task=T1
    Then 只有一个调度器认领成功
    And 另一个调度器认领失败并跳过
    And task=T1 的 ES 入库只执行一次

  Scenario: 已被认领后状态变化的记录不会被重复执行
    Given 后处理记录 task=T1 已被调度器 A 认领进入 ES 重试
    And task=T1 随后被标记为 SUCCESS
    When 调度器 B 尝试继续执行 task=T1
    Then 调度器 B 跳过 task=T1
    And task=T1 的 pipeline_status == SUCCESS
    And 不发送重复 success 通知

  Scenario: 重复扫描未耗尽失败记录会继续下一次重试
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=2
    And task=T1 的 failure_reason 不包含 "retry_exhausted=true"
    When 下一轮 ES 重试调度执行扫描
    Then task=T1 被认领进入 ES 重试
    And task=T1 的 retry_count 在认领时不增加

  # ==== 边界与配置 ====

  Scenario: 调度开关关闭时不扫描候选记录
    Given ES 入库重试调度已关闭
    And 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    When FastAPI 应用启动
    Then 不启动 ES 重试后台扫描
    And task=T1 不被认领

  Scenario: 单轮扫描遵守批量上限
    Given 存在 5 条可重试的 ES 入库失败记录
    When ES 重试调度执行一轮扫描 limit=2
    Then 只有 2 条记录被认领进入 ES 重试
    And 其余 3 条记录保持可重试失败状态

  Scenario Outline: 非 ES 恢复阶段不会进入 ES 重试
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=<stage> es_indexing_status=<es_status> retry_count=1
    When ES 重试调度执行一轮扫描 limit=10
    Then task=T1 不被认领
    And 不执行 task=T1 的 ES 入库

    Examples:
      | stage       | es_status |
      | CHUNKING    | PENDING   |
      | VECTORIZING | PENDING   |
      | PRETOKENIZE | PENDING   |
      |             | FAILED    |

  Scenario: 通知失败不回滚已成功的 ES 入库结果
    Given 后处理记录 task=T1 pipeline_status=FAILED recover_from_stage=ES_INDEXING es_indexing_status=FAILED retry_count=1
    And ES 入库重试 task=T1 已全部成功
    When 发送 parse_result success 通知失败
    Then task=T1 的 pipeline_status == SUCCESS
    And task=T1 的 es_indexing_status == SUCCESS
    And ES 索引结果不回滚
    And 通知失败按现有兜底策略记录
