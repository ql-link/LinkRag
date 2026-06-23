# 轻量流程编排引擎验收契约 — 对应 Linear LINK-102 / GitHub ql-link/LinkRag#135

Feature: 轻量流程编排引擎
  作为流程编排框架的使用方
  我希望只声明每个节点的输入产物(requires)与输出产物(provides)
  以便引擎自动推导依赖、并发执行无依赖步骤，并在失败后断点续跑

  Background:
    Given 一个进程内的流程编排引擎
    And 节点通过 requires / provides 声明输入与输出产物，引擎据此推导依赖，而非手写"谁依赖谁"
    And 产物 key 对引擎是不透明字符串，引擎不理解其业务含义
    And 引擎为每一轮 run 记录整体状态、每个节点的状态与成功节点的产物引用(output_ref)

  Scenario: 合法流程定义加载成功并推导出依赖边
    Given 节点 clean: requires=[source], provides=[md]
    And 节点 chunk: requires=[md], provides=[chunks]
    When 加载该流程定义
    Then 加载成功
    And 推导出依赖边 clean → chunk
    And 不在加载阶段执行任何节点

  Scenario: 依赖成环在加载期被拒绝
    Given 节点 A: requires=[y], provides=[x]
    And 节点 B: requires=[x], provides=[y]
    When 加载该流程定义
    Then 加载失败，错误码 == CYCLE
    And 不创建任何 run

  Scenario: 同一产物被多个节点 provides 在加载期被拒绝
    Given 节点 A: provides=[chunks]
    And 节点 B: provides=[chunks]
    When 加载该流程定义
    Then 加载失败，错误码 == DUPLICATE_PRODUCER
    And 错误信息指明产物 "chunks"

  Scenario: requires 的产物无人 provides 在加载期被拒绝
    Given 节点 chunk: requires=[md], provides=[chunks]
    And 没有任何节点 provides "md"，且 "md" 不是外部初始产物
    When 加载该流程定义
    Then 加载失败，错误码 == DANGLING_REQUIRES
    And 错误信息指明产物 "md"

  Scenario: allow_failure 节点提供了被他人 requires 的产物在加载期被拒绝
    Given 节点 opt: allow_failure=true, provides=[x]
    And 节点 down: requires=[x]
    When 加载该流程定义
    Then 加载失败，错误码 == ALLOW_FAILURE_PROVIDES_REQUIRED
    And 错误信息指明节点 "opt" 与产物 "x"

  Scenario: 按产物依赖推导执行顺序
    Given 合法流程 clean(source→md) 与 chunk(md→chunks)
    And 外部初始产物 "source" 已提供
    When 运行该流程
    Then clean 的执行早于 chunk
    And run.status == SUCCESS
    And clean.status == SUCCESS
    And chunk.status == SUCCESS

  Scenario: 无依赖的就绪节点在同一批并发执行
    Given chunk 产出产物 "chunks"
    And 节点 dense / sparse / tokenize 三者均 requires=[chunks]，互不依赖
    When 运行该流程
    Then 存在某一时刻 dense、sparse、tokenize 同时处于 RUNNING
    And 三者各执行恰好一次
    And 三者最终 status 均 == SUCCESS

  Scenario: 多上游汇聚的节点在全部输入产物齐备后才执行一次
    Given 节点 index: requires=[dense_vectors, tokens]
    And 节点 dense 产出 dense_vectors，节点 tokenize 产出 tokens
    When 运行该流程
    Then 在 dense_vectors 与 tokens 均登记之前，index 不被放行（保持 PENDING）
    And index 执行恰好一次
    And index.status == SUCCESS

  Scenario: 节点成功后其产物登记进本轮上下文供下游消费
    Given 节点 clean: provides=[md]
    When clean 执行成功
    Then 本轮上下文包含产物 "md"
    And 下游节点可从本轮上下文读取 "md"

  Scenario: 两个上游几乎同时完成时下游只被调度一次
    Given 节点 join: requires=[a, b]
    And 节点 pa 产出 "a"、节点 pb 产出 "b"，pa 与 pb 并发执行
    When pa 与 pb 几乎同时完成
    Then join 只被调度执行一次
    And join.status == SUCCESS

  Scenario: 同时运行的节点数不超过 max_concurrency
    Given 4 个互不依赖且同时就绪的节点
    And max_concurrency == 2
    When 运行该流程
    Then 任一时刻处于 RUNNING 的节点数 <= 2
    And 4 个节点最终 status 均 == SUCCESS

  Scenario: 必需节点失败后阻断下游并收敛为 FAILED
    Given 节点 chunk: requires=[md], provides=[chunks]
    And 节点 dense: requires=[chunks]
    When chunk 执行抛出异常
    Then chunk.status == FAILED
    And dense 不被放行，dense.status == PENDING
    And run.status == FAILED
    And run.failure_phase == RUN

  Scenario: 必需节点失败时已在运行的并发节点不被强杀
    Given 节点 a 与节点 b 互不依赖且并发运行
    And a 会执行较久后成功，b 会立即抛出异常
    When b 失败
    Then 引擎不取消 a
    And a 执行至自然结束，a.status == SUCCESS
    And run.status == FAILED

  Scenario: allow_failure 节点失败不阻断整体流程
    Given 节点 opt: allow_failure=true，且其产物不被任何节点 requires
    And 其余必需节点均会成功
    When opt 执行抛出异常
    Then opt.status == FAILED
    And opt 被标记为「容忍失败」
    And run.status == SUCCESS

  Scenario: 续跑跳过上一轮已成功且下游仍需其产物的节点并恢复产物
    Given 上一轮 run R1 中 clean=SUCCESS 且 provides "md"，chunk=FAILED
    When 基于 previous_run=R1 新建 run R2 并运行
    Then clean 在 R2 不重新执行业务逻辑
    And 引擎调用 clean.restore 从 output_ref 把产物 "md" 恢复进 R2 上下文
    And clean 在 R2 的 status == SKIPPED
    And chunk 在 R2 正常执行

  Scenario: 续跑只重跑上一轮失败或未执行的节点且不修改上一轮记录
    Given 上一轮 run R1：clean=SUCCESS，chunk=SUCCESS，dense=FAILED
    When 基于 R1 续跑得到 R2
    Then clean 与 chunk 在 R2 的 status == SKIPPED，均不重新执行业务逻辑
    And dense 在 R2 重新执行
    And R1 的任何节点记录与整体状态保持不变

  Scenario: restore 失败导致本轮整体失败
    Given 上一轮 run R1 中 clean=SUCCESS，但其 output_ref 指向的产物已被清理
    When 基于 R1 续跑得到 R2，且 R2 中有下游需要 clean 的产物 "md"
    Then clean.restore 在 R2 失败
    And clean 在 R2 的 status == FAILED
    And run.failure_phase == RESTORE
    And run.status == FAILED

  Scenario: 续跑中产物无下游消费的成功节点被跳过且不触发 restore
    Given 上一轮 run R1 中节点 A=SUCCESS 且 provides "x"
    And 本轮没有任何待执行节点 requires "x"
    When 基于 R1 续跑
    Then A 的 status == SKIPPED
    And 引擎不调用 A.restore
    And 本轮上下文不包含产物 "x"

  Scenario Outline: 节点终态由本轮处置结果决定
    Given 一个必需节点 N 处于某条合法流程中
    When <处置>
    Then N 的 status == <终态>

    Examples:
      | 处置                                | 终态     |
      | 本轮执行成功                        | SUCCESS  |
      | 本轮执行抛出异常                    | FAILED   |
      | 上一轮成功、本轮被跳过并成功 restore | SKIPPED  |
      | 上游失败导致本轮从未就绪            | PENDING  |
