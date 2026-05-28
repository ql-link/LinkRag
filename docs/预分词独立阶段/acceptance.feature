# 验收契约：预分词独立阶段
# 输入源：docs/预分词独立阶段/brief.md（已冻结 2026-05-18）
# 状态命名来自 brief：pipeline 记录字段 chunking_status / vectorizing_status /
# pretokenize_status / es_indexing_status / pipeline_status / failed_stage /
# recover_from_stage / failure_reason / pretokenize_duration_ms；
# chunk 行字段 vector_status / es_status / es_error_msg。

Feature: 预分词独立阶段
  作为解析后处理流水线
  我希望预分词成为有独立状态、独立失败语义、独立恢复入口的一等阶段
  以便多个下游消费者（ES 倒排、未来稀疏向量化）可清晰依赖"分词已就绪"，且失败可精确定位与续跑

  Background:
    Given Java 已投递文档 D1 的 parse_task 解析任务
    And D1 已完成解析与分块，pipeline.chunking_status == SUCCESS
    And 后处理阶段顺序为 CHUNKING → VECTORIZING → PRETOKENIZE → ES_INDEXING

  # ==== 主流程 ====

  Scenario: 全链路成功并通知 Java
    Given D1 含 chunk C1 C2 C3，三者 vector_status == SUCCESS 且 es_status == PENDING
    And pipeline.vectorizing_status == SUCCESS
    When 运行 D1 的后处理流水线
    Then 分词器对 C1 C2 C3 各被调用恰好一次
    And pipeline.pretokenize_status == SUCCESS
    And pipeline.pretokenize_duration_ms 非空且 >= 0
    And C1 C2 C3 的 es_status == SUCCESS
    And pipeline.es_indexing_status == SUCCESS
    And pipeline.pipeline_status == SUCCESS
    And 向 Java 发出一条 parse_task 结果消息 task=D1 status=SUCCESS

  Scenario: 单趟扇出只分词一次且产物不持久化
    Given D1 含 chunk C1 C2，二者 vector_status == SUCCESS 且 es_status == PENDING
    And pipeline.vectorizing_status == SUCCESS
    When 运行 D1 的后处理流水线并成功完成
    Then 同一次执行内 C1 C2 各只被分词一次
    And 没有任何 token 列或 token 表被写入（产物不持久化）
    And ES 写入的文档来自预分词产出的内存计划

  # ==== 预分词阶段：文件级 all-or-nothing ====

  Scenario: 任一 chunk 分词失败则整文件预分词失败且不污染 chunk
    Given D1 含 chunk C1 C2 C3，三者 vector_status == SUCCESS 且 es_status == PENDING
    And pipeline.vectorizing_status == SUCCESS
    When 运行 D1 的后处理流水线，且 C2 触发分词失败
    Then pipeline.pretokenize_status == FAILED
    And pipeline.failed_stage == PRETOKENIZE
    And pipeline.recover_from_stage == PRETOKENIZE
    And pipeline.failure_reason 以 "pretokenize:" 开头
    And C1 C2 C3 的 es_status 仍为 PENDING（未被修改）
    And 未进入 ES_INDEXING，没有发生任何 ES bulk 写入
    And pipeline.es_indexing_status == PENDING
    And 向 Java 发出一条 parse_task 结果消息 task=D1 status=FAILED

  Scenario Outline: 各类分词失败触发条件均按文件级终态处理
    Given D1 含 chunk C1 C2，二者 vector_status == SUCCESS 且 es_status == PENDING
    And pipeline.vectorizing_status == SUCCESS
    When 运行预分词，且 C1 触发 "<失败类型>"
    Then pipeline.pretokenize_status == FAILED
    And pipeline.failure_reason 以 "pretokenize:" 开头
    And pipeline.failure_reason 不包含 "retry_exhausted"
    And C1 C2 的 es_status 仍为 PENDING
    And 失败处不写入 pipeline.retry_count（列保留，仅用户侧重试时由 claim 自增）

    Examples:
      | 失败类型          |
      | chunk_index 非法  |
      | 粗粒度 token 为空 |
      | 细粒度 token 为空 |
      | 分词器抛出异常    |

  # ==== 与 dense 向量化的耦合（保持耦合）====

  Scenario: 仅 dense 向量化成功的 chunk 进入预分词与 ES
    Given D1 含 chunk C1 C2，C1 vector_status == SUCCESS，C2 vector_status == FAILED
    And C1 C2 的 es_status == PENDING
    When 运行 D1 的后处理流水线
    Then 分词器仅对 C1 被调用
    And C1 的 es_status == SUCCESS
    And C2 的 es_status 仍为 PENDING（未进入预分词与 ES）

  Scenario: 仍有 dense 未成功的待索引 chunk 时文件级 ES 不被误判成功
    Given D1 含 chunk C1，C1 es_status == PENDING 且 C1 vector_status != SUCCESS
    And pipeline.vectorizing_status == SUCCESS
    When 运行预分词
    Then 预分词产出空计划
    And pipeline.es_indexing_status == FAILED
    And pipeline.pipeline_status == FAILED
    And pipeline.failure_reason 以 "pretokenize:" 开头且包含 "pending"
    And 向 Java 发出一条 parse_task 结果消息 task=D1 status=FAILED

  # ==== ES 入库：chunk 级失败语义 ====

  Scenario: 部分 chunk 写 ES 失败不中止整批且只标失败 chunk
    Given D1 含 chunk C1 C2 C3，三者 vector_status == SUCCESS 且 es_status == PENDING
    And pipeline.vectorizing_status == SUCCESS 且预分词全部成功
    When 执行 ES 入库，且 C2 的 bulk 写入失败、C1 C3 写入成功
    Then C1 C3 的 es_status == SUCCESS
    And C2 的 es_status == FAILED 且 C2.es_error_msg 非空
    And pipeline.es_indexing_status == FAILED
    And pipeline.failed_stage == ES_INDEXING
    And pipeline.recover_from_stage == ES_INDEXING
    And pipeline.failure_reason 以 "ES_INDEXING_FAILED:" 开头
    And 向 Java 发出一条 parse_task 结果消息 task=D1 status=FAILED

  Scenario: ES 基础设施故障按文件级处理不标 chunk
    Given D1 含 chunk C1 C2，二者 vector_status == SUCCESS 且 es_status == PENDING
    And pipeline.vectorizing_status == SUCCESS 且预分词全部成功
    When 执行 ES 入库，但确保索引存在失败（ES 不可达）
    Then pipeline.es_indexing_status == FAILED
    And C1 C2 的 es_status 仍为 PENDING（未被标 FAILED）
    And pipeline.failed_stage == ES_INDEXING
    And pipeline.failure_reason 以 "ensure_index:" 开头
    And 向 Java 发出一条 parse_task 结果消息 task=D1 status=FAILED

  Scenario: ES 全部成功收敛为文件级成功
    Given D1 含 chunk C1 C2，二者 vector_status == SUCCESS 且 es_status == PENDING
    And pipeline.vectorizing_status == SUCCESS 且预分词全部成功
    When 执行 ES 入库，C1 C2 全部写入成功
    Then C1 C2 的 es_status == SUCCESS
    And pipeline.es_indexing_status == SUCCESS
    And pipeline.pipeline_status == SUCCESS
    And 向 Java 发出一条 parse_task 结果消息 task=D1 status=SUCCESS

  # ==== 失败即终态：无 ES 内部重试计数 / 上限 / exhausted ====

  Scenario Outline: 任一失败均为终态且不产生 ES 内部重试计数语义
    Given D1 处于可触发 "<失败场景>" 的前置状态
    When 运行后处理流水线触发该失败
    Then pipeline.pipeline_status == FAILED
    And pipeline.failure_reason 不包含 "retry_exhausted"
    And 失败处不写入 pipeline.retry_count / pipeline.last_retry_at（两列保留，仅供用户侧重试计数）
    And 流程未读取 ES_INDEXING_MAX_RETRY 配置
    And 系统不自动重试该任务

    Examples:
      | 失败场景          |
      | 预分词文件级失败  |
      | ES 基础设施故障   |
      | ES chunk 级写失败 |

  Scenario: 同一文件多次失败不被次数拦截
    Given D1 此前已失败并被外部重新投递 5 次
    When 第 6 次外部重新投递 D1 且本趟仍失败
    Then pipeline.pipeline_status == FAILED
    And 系统按终态记录结果，不因失败次数拒绝处理
    And pipeline.failure_reason 不包含 "retry_exhausted" 或 "MAX_RETRY"

  # ==== 外部重投：按 recover_from_stage（首个非 SUCCESS 阶段）幂等续跑 ====

  Scenario: 预分词成功但 ES 部分失败后重投只补失败子集
    Given pipeline.pretokenize_status == SUCCESS 且 pipeline.recover_from_stage == ES_INDEXING
    And D1 含 chunk C1 C2 C3，vector_status 均 == SUCCESS
    And C1.es_status == SUCCESS，C2.es_status == FAILED，C3.es_status == PENDING
    When D1 被外部重新投递
    Then 续跑从 ES_INDEXING 开始
    And 分词器仅对 C2 C3 被调用（C1 不被重新分词）
    And C1 的 es_status 保持 SUCCESS 未被改写
    And C2 C3 写入成功后 es_status == SUCCESS
    And pipeline.es_indexing_status == SUCCESS
    And pipeline.pipeline_status == SUCCESS

  Scenario: 预分词失败后重投从预分词整篇重入
    Given pipeline.pretokenize_status == FAILED 且 pipeline.recover_from_stage == PRETOKENIZE
    And D1 含 chunk C1 C2 C3，vector_status 均 == SUCCESS 且 es_status 均 == PENDING
    When D1 被外部重新投递且本趟分词全部成功
    Then 续跑从 PRETOKENIZE 开始
    And 分词器对 C1 C2 C3 全部被调用
    And pipeline.pretokenize_status == SUCCESS
    And 进入 ES_INDEXING 并最终 pipeline.pipeline_status == SUCCESS

  Scenario Outline: recover_from_stage 取首个非 SUCCESS 阶段
    Given pipeline.chunking_status == <分块> 且 pipeline.vectorizing_status == <向量化>
    And pipeline.pretokenize_status == <预分词> 且 pipeline.es_indexing_status == <ES入库>
    When 推断该中断流水线的恢复入口
    Then pipeline.recover_from_stage == <恢复入口>

    Examples:
      | 分块    | 向量化  | 预分词  | ES入库  | 恢复入口     |
      | SUCCESS | SUCCESS | SUCCESS | FAILED  | ES_INDEXING  |
      | SUCCESS | SUCCESS | FAILED  | PENDING | PRETOKENIZE  |
      | SUCCESS | FAILED  | PENDING | PENDING | VECTORIZING  |
      | FAILED  | PENDING | PENDING | PENDING | CHUNKING     |

  Scenario: 全部已成功的文件被重投为幂等空操作
    Given D1 含 chunk C1 C2，二者 es_status == SUCCESS
    And pipeline.pipeline_status == SUCCESS
    When D1 被外部重新投递
    Then 预分词产出空计划
    And 分词器不被调用
    And 没有发生任何 ES bulk 写入
    And C1 C2 的 es_status 保持 SUCCESS
    And pipeline.pipeline_status 保持 SUCCESS

  # ==== 失败来源前缀（纯内部排障，不涉对外契约）====

  Scenario Outline: 失败来源映射到 failure_reason 前缀
    Given D1 处于可触发 "<失败来源>" 的前置状态
    When 运行后处理流水线触发该失败
    Then pipeline.failure_reason 以 "<前缀>" 开头
    And 向 Java 的结果消息为 status=FAILED 且消息体不依赖该前缀解析

    Examples:
      | 失败来源            | 前缀                 |
      | 预分词分词失败      | pretokenize:         |
      | ES 确保索引失败     | ensure_index:        |
      | ES bulk chunk 失败  | ES_INDEXING_FAILED:  |
