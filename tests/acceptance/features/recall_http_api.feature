# Python 内部多路召回 SSE 流式 API acceptance 契约
# 输入：.specs/recall-http-api/brief.md（已冻结）
# 关联 Linear: LINK-35 / GitHub: ql-link/LinkRag#90
# 仅覆盖 Python 内部 recall runtime；Java Recall Gateway（java-gateway-brief.md）不在本契约范围

Feature: 内部多路召回 SSE 流式接口
  作为 Java Recall Gateway
  我希望携带内部 JWT 调用 POST /api/v1/internal/recall/stream 触发多路召回
  以便用 SSE 一次性拿到 RRF 融合后的最终候选，或在失败时拿到明确的错误终态

  Background:
    Given 配置 RECALL_INTERNAL_AUTH_ENABLED=True
    And 配置 RECALL_INTERNAL_JWT_ISSUER=tolink-java
    And 配置 RECALL_INTERNAL_JWT_AUDIENCE=tolink-rag
    And 配置 RECALL_RESULT_LIMIT=20
    And 配置 RECALL_STRICT_DEFAULT=False
    And 配置 RECALL_ENABLED_SOURCES=bm25,sparse
    And Java 与 Python 共享同一 HS256 JWT 密钥
    And 服务端已装配 bm25 与 sparse 两路 retriever

  # ==== 主流程 ====

  Scenario: 有效内部凭证触发召回并以 recall_done 返回融合候选
    Given 内部 JWT claims sub=123 aud=tolink-rag iss=tolink-java scope=recall:execute dataset_ids=[1,2] 未过期
    And bm25 与 sparse 两路均返回命中
    When 携带该 JWT 调用 recall/stream body query="数据治理" user_id=123 dataset_ids=[1,2]
    Then HTTP 响应状态为 200
    And 响应 Content-Type 为 "text/event-stream"
    And 收到 SSE 事件 "recall_done"
    And recall_done.data 含字段 hits 与 failed_sources
    And recall_done.failed_sources 等于空列表
    And hits 中每个 hit 含字段 chunk_id, doc_id, dataset_id, fused_score, scores
    And hits 中每个 hit 的 chunk_id 为字符串
    And hits 中每个 hit 不含字段 content
    And hits 中每个 hit 的 scores 的键集合等于 {"bm25","sparse"}
    And hits 按 fused_score 降序排列
    And 发送 recall_done 后关闭 SSE 流

  Scenario: 命中数量不超过服务端 RECALL_RESULT_LIMIT
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    And 各路合计可融合出 50 个候选
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then recall_done.hits 长度不超过 20

  Scenario: claims 空 dataset_ids 表示全库授权时按全库召回
    Given 内部 JWT claims sub=123 dataset_ids=[] 合法未过期
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=123 dataset_ids=[]
    Then HTTP 响应状态为 200
    And 收到 SSE 事件 "recall_done"
    And 以 dataset_ids 空列表执行 RecallPipeline

  # ==== 内部凭证鉴权（握手前，返回非 2xx JSON）====

  Scenario: 缺少内部凭证时拒绝且不执行 pipeline
    When 不携带 Authorization 头调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then HTTP 响应状态为 401
    And 响应体 code 等于 "RECALL_INTERNAL_UNAUTHORIZED"
    And 不调用 RecallPipeline

  Scenario Outline: 内部 JWT 校验失败时返回 401 且不执行 pipeline
    Given 内部 JWT 存在缺陷 "<defect>"
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then HTTP 响应状态为 401
    And 响应体 code 等于 "RECALL_INTERNAL_UNAUTHORIZED"
    And 不调用 RecallPipeline

    Examples:
      | defect            |
      | 签名不匹配        |
      | iss 不是 tolink-java |
      | aud 不是 tolink-rag  |
      | scope 不是 recall:execute |
      | exp 已过期        |

  Scenario: body.user_id 与 claims.sub 不一致时返回 403 且不执行 pipeline
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=999 dataset_ids=[1]
    Then HTTP 响应状态为 403
    And 响应体 code 等于 "RECALL_USER_MISMATCH"
    And 不调用 RecallPipeline

  Scenario: body.dataset_ids 超出 claims 授权范围时返回 403 且不执行 pipeline
    Given 内部 JWT claims sub=123 dataset_ids=[1,2] 合法未过期
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1,3]
    Then HTTP 响应状态为 403
    And 响应体 code 等于 "RECALL_SCOPE_FORBIDDEN"
    And 不调用 RecallPipeline

  Scenario: body.dataset_ids 是 claims 授权范围子集时放行
    Given 内部 JWT claims sub=123 dataset_ids=[1,2] 合法未过期
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 收到 SSE 事件 "recall_done"

  # ==== 请求体校验 ====

  Scenario Outline: 出现非首版字段时返回 422 且不执行 pipeline
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    When 携带该 JWT 调用 recall/stream body 额外包含字段 "<field>"
    Then HTTP 响应状态为 422
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"
    And 不调用 RecallPipeline

    Examples:
      | field           |
      | top_k           |
      | sources         |
      | strict          |
      | include_content |
      | doc_ids         |

  Scenario Outline: 请求字段缺失或类型非法时返回 422 且不执行 pipeline
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    When 携带该 JWT 调用 recall/stream body 缺陷 "<defect>"
    Then HTTP 响应状态为 422
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"
    And 不调用 RecallPipeline

    Examples:
      | defect              |
      | 缺少 query 字段     |
      | 缺少 user_id 字段   |
      | 缺少 dataset_ids 字段 |
      | user_id 为字符串    |
      | dataset_ids 不是列表 |
      | JSON 格式非法       |

  Scenario Outline: query 为空或纯空白时返回 400 RECALL_INVALID_REQUEST
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    When 携带该 JWT 调用 recall/stream body query 为空白标识 "<query_token>" user_id=123 dataset_ids=[1]
    Then HTTP 响应状态为 400
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"

    Examples:
      | query_token |
      | EMPTY       |
      | SPACES      |
      | NEWLINE     |

  # ==== 降级与失败终态 ====

  Scenario: 宽松模式单路失败但有成功路时以 recall_done 报告降级
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    And bm25 路成功返回命中
    And sparse 路执行抛异常
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 收到 SSE 事件 "recall_done"
    And recall_done.failed_sources 包含 "sparse"
    And recall_done.hits 非空

  Scenario: 全部召回路失败时以 SSE error 返回
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    And bm25 与 sparse 两路均执行抛异常
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then 响应 Content-Type 为 "text/event-stream"
    And 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_ALL_SOURCES_FAILED"
    And error.data 的 message 不含内部堆栈
    And 发送 error 后关闭 SSE 流

  # ==== 超时 ====
  # 说明：recall 为终态流（方案 A，建流在前），运行期失败统一走 SSE error；
  # brief §8 中「建流前 502/504」属未来增量 pipeline 的预留契约，不在 recall-only 范围。

  Scenario: recall runtime 超时以 SSE error 返回
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    And recall runtime 执行超过 RECALL_STREAM_TIMEOUT_MS
    When 携带该 JWT 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_TIMEOUT"
    And 发送 error 后关闭 SSE 流

  # ==== 断连与资源释放 ====

  Scenario: Java 断开内部流时 Python 停止发送事件并取消召回任务
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    And recall 正在执行中
    When Java 主动断开到 Python 的 SSE 连接
    Then Python 停止继续发送 SSE 事件
    And Python 尽力取消正在执行的召回任务
    And Python 不执行后续 rerank、上下文拼装或 LLM 步骤

  # ==== 请求追踪 ====

  Scenario: 缺省 X-Request-Id 时由 Python 生成并贯穿日志
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    When 携带该 JWT 不带 X-Request-Id 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then Python 为本次请求生成 request_id
    And 日志中能通过该 request_id 关联 API 与 pipeline 执行

  Scenario: 透传的 X-Request-Id 被沿用为本次请求的 request_id
    Given 内部 JWT claims sub=123 dataset_ids=[1] 合法未过期
    When 携带该 JWT 带 X-Request-Id "req-abc" 调用 recall/stream body query="任意" user_id=123 dataset_ids=[1]
    Then 本次请求的 request_id 等于 "req-abc"
