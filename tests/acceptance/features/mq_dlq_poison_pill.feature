# 验收契约：MQ 消费 poison pill 死信与重试兜底
# 输入源：docs/MQ消费死信兜底/brief.md（已冻结 2026-05-19）
# 来源：GitHub issue #22 [P0]
#
# 术语与约定（来自 brief，非技术实现细节）：
# - 配置项：MQ_MAX_RETRIES（最大重试次数，示例取 3）、MQ_RETRY_BACKOFF
#   （固定退避间隔）、MQ_DLQ_SUFFIX（死信后缀 .DLT）；死信兜底恒启用，无开关
# - 异常分类：RetriableError 为可重试异常基类；ParseResultNotificationError 归入可重试；
#   其它从 Pipeline 逃出的异常归为终态（不可重试）
# - 死信目标：原 topic + 后缀 .DLT（Kafka 为死信 topic，RabbitMQ 为死信交换器/队列）
# - 死信消息须携带：原 topic、异常摘要、累计重试次数、原消息 key
# - 重试计数键为 (topic, partition, offset)，仅存进程内存（已确认接受）
# - "Pipeline 正常失败"指 Pipeline 已标记终态并正常返回、未抛异常的解析失败

Feature: MQ 消费 poison pill 死信与重试兜底
  作为 MQ 消费框架层
  我希望失败消息有最大重试上限、超限进死信、并精确提交位点
  以便单条坏消息不会无限重投、不会堵死整个 partition、不会被静默跳过丢数据

  Background:
    Given 消费者已订阅解析任务 topic "parse-task"
    And MQ_MAX_RETRIES == 3
    And 重试之间为固定间隔退避 MQ_RETRY_BACKOFF
    And 死信兜底恒启用（无开关）
    And 死信目标按「原 topic + 后缀 .DLT」命名

  # ==== 主流程 ====

  Scenario: 回调成功后精确提交本分区位点
    Given partition P0 待消费消息 M1，offset == 100
    When 消费回调对 M1 执行成功
    Then 仅提交 (topic="parse-task", partition=P0) 的位点至 offset 100
    And 不提交其它 partition 的位点
    And M1 不被投递到死信
    And M1 不被再次投递给回调

  Scenario: Pipeline 正常失败不进死信且正常提交
    Given partition P0 待消费消息 M1
    When 消费回调执行 Pipeline，Pipeline 标记任务终态并正常返回（未抛异常）
    Then 仅提交 (topic="parse-task", partition=P0) 的位点至 M1 的 offset
    And M1 不被投递到死信
    And M1 不被再次投递给回调

  # ==== 可重试异常：固定退避有限重试 ====

  Scenario: 可重试异常未达上限则退避后重投且不提交位点
    Given partition P0 待消费消息 M1，(parse-task,P0,M1.offset) 重试计数 == 0
    When 消费回调抛出 ParseResultNotificationError
    Then 不提交 (parse-task, P0) 的位点
    And M1 不被投递到死信
    And 等待至少一个 MQ_RETRY_BACKOFF 间隔后 M1 被再次投递给回调
    And (parse-task,P0,M1.offset) 重试计数 == 1

  Scenario: 可重试异常重试中途成功则提交位点并清理计数
    Given partition P0 的消息 M1，(parse-task,P0,M1.offset) 重试计数 == 2
    When 消费回调对 M1 第 3 次执行成功
    Then 仅提交 (parse-task, P0) 的位点至 M1 的 offset
    And M1 不被投递到死信
    And (parse-task,P0,M1.offset) 的重试计数被清理

  Scenario: 可重试异常达最大重试次数后降级死信并提交位点
    Given partition P0 的消息 M1，(parse-task,P0,M1.offset) 重试计数 == 3
    When 消费回调再次抛出 ParseResultNotificationError
    Then M1 被投递到死信目标 "parse-task.DLT"
    And 死信投递成功后才提交 (parse-task, P0) 的位点至 M1 的 offset
    And M1 不再被投递给回调
    And (parse-task,P0,M1.offset) 的重试计数被清理

  Scenario: 单条可重试消息阻塞本分区时间存在上界
    Given partition P0 的消息 M1 持续抛出 ParseResultNotificationError
    When M1 从首次失败到进入死信完成整个重试过程
    Then 回调对 M1 被调用恰好 1 + MQ_MAX_RETRIES 次
    And M1 阻塞 partition P0 的总时长 <= MQ_RETRY_BACKOFF × MQ_MAX_RETRIES
    And 期间 partition P0 不前进到 M1 之后的消息

  # ==== 终态异常：不重试直接进死信 ====

  Scenario: 终态异常不重试直接进死信并提交位点
    Given partition P0 待消费消息 M1，(parse-task,P0,M1.offset) 重试计数 == 0
    When 消费回调抛出非 RetriableError 异常（从 Pipeline 兜底之外逃出）
    Then M1 不经过任何重试
    And M1 被投递到死信目标 "parse-task.DLT"
    And 死信投递成功后才提交 (parse-task, P0) 的位点至 M1 的 offset
    And (parse-task,P0,M1.offset) 重试计数始终未自增

  Scenario Outline: 异常按可重试 / 终态正确分流
    Given partition P0 待消费消息 M1
    When 消费回调抛出 "<异常>"
    Then 该异常被判定为 "<分类>"
    And M1 的处理走 "<路径>"

    Examples:
      | 异常                          | 分类   | 路径                         |
      | ParseResultNotificationError  | 可重试 | 有限退避重试后超限才进死信   |
      | 其它 RetriableError 子类      | 可重试 | 有限退避重试后超限才进死信   |
      | 非 RetriableError 普通异常    | 终态   | 不重试直接进死信             |

  # ==== 死信内容与投递可靠性 ====

  Scenario: 死信消息携带排查所需元数据
    Given partition P0 的消息 M1，key == "K1"，原 topic == "parse-task"
    When M1 因终态异常被投递到死信
    Then 死信消息体等于 M1 的原始消息体
    And 死信消息携带原 topic == "parse-task"
    And 死信消息携带异常摘要（非空）
    And 死信消息携带累计重试次数
    And 死信消息携带原消息 key == "K1"

  Scenario: 死信投递失败则不提交位点且消息不丢失
    Given partition P0 的消息 M1 已达最大重试次数
    When 向死信目标投递 M1 失败
    Then 不提交 (parse-task, P0) 的位点
    And M1 不被静默跳过
    And M1 在后续仍可被重新处理（保留至死信投递成功）

  Scenario Outline: 死信目标在启动时被幂等创建
    Given 死信目标 "<目标>" 在 "<厂商>" 上不存在
    When 应用启动完成 MQ 装配
    Then "<目标>" 已被创建
    And 重复启动不因 "<目标>" 已存在而报错

    Examples:
      | 厂商     | 目标                         |
      | kafka    | tolink.rag.parse_task.DLT    |
      | rabbitmq | tolink.rag.parse_task.DLT    |

  # ==== Kafka 精确位点提交：消除静默跳过丢数据 ====

  Scenario: 失败未解决的消息不被后续成功消息的提交静默跳过
    Given partition P0 依次有消息 M1(offset=100) 与 M2(offset=101)
    And M1 触发可重试异常且尚未达上限
    When 系统处理 partition P0
    Then partition P0 不前进到 M2，M2 在 M1 解决前不被处理
    And 不存在"M1 未解决但位点已提交越过 offset 100"的情况

  Scenario: 某分区失败重试不阻塞也不误提交其它分区
    Given partition P0 的消息 M1 持续抛出 ParseResultNotificationError 正在重试
    And partition P1 的消息 N1 回调执行成功
    When 系统并行消费 P0 与 P1
    Then 提交 (parse-task, P1) 的位点至 N1 的 offset
    And 不提交 (parse-task, P0) 越过 M1 的位点
    And P1 的消费不被 P0 的重试阻塞

  # ==== 重试计数语义（进程内存，已确认接受）====

  Scenario: 同一消息反复触发可重试异常计数逐次累加
    Given partition P0 的消息 M1，(parse-task,P0,M1.offset) 重试计数 == 0
    When 消费回调对 M1 连续抛出 ParseResultNotificationError 3 次
    Then 每次失败后 (parse-task,P0,M1.offset) 重试计数依次为 1、2、3
    And 第 3 次失败后 M1 被投递到死信

  Scenario: 进程重启后内存计数清零并重新走一轮上限内重试
    Given partition P0 的消息 M1 此前重试计数已累计到 2 且未提交位点
    When 进程重启后从上次提交位点重放并再次消费 M1
    Then (parse-task,P0,M1.offset) 重试计数从 0 重新开始
    And M1 在本轮内最多再重试 MQ_MAX_RETRIES 次后进入死信
    And 系统不因跨重启而无限重试 M1

  # ==== 厂商行为对齐 ====

  Scenario Outline: Kafka 与 RabbitMQ 失败兜底行为一致
    Given 当前 MQ 厂商为 "<厂商>"，消息 M1 待消费
    When 消费回调抛出 "<异常>"
    Then M1 的最终去向为 "<去向>"
    And 厂商间该规则的可重试判定与最大重试次数语义一致

    Examples:
      | 厂商     | 异常                          | 去向                       |
      | kafka    | ParseResultNotificationError  | 重试 MQ_MAX_RETRIES 次后进死信 |
      | rabbitmq | ParseResultNotificationError  | 重试 MQ_MAX_RETRIES 次后进死信 |
      | kafka    | 非 RetriableError 普通异常    | 不重试直接进死信           |
      | rabbitmq | 非 RetriableError 普通异常    | 不重试直接进死信           |

  Scenario: RabbitMQ 失败不再无条件 nack 重入队
    Given 当前 MQ 厂商为 rabbitmq，队列 "parse-task" 的消息 M1
    When 消费回调抛出 ParseResultNotificationError 且已达最大重试次数
    Then M1 不被无条件 nack-requeue 回原队列
    And M1 被 reject 到死信交换器对应的死信目标
    And 原队列不再无限重新投递 M1
