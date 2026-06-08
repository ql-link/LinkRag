# 前端直连 Python 召回 SSE（Java 仅签发短期 token）acceptance 契约
# 输入：.specs/recall-direct-sse/brief.md（已冻结 2026-06-06）
# 关联 Linear: LINK-40；上游 LINK-35（内部 runtime，见 recall_http_api.feature）/ LINK-56（Java 网关）
# 范围：仅 Python 侧对外直连 SSE 端点 POST /api/v1/recall/stream。
#       Java POST /api/v1/recall/sessions 与 token 签发不在本契约范围。
# 说明：召回执行内部语义（RRF 融合、命中字段形状、降级 failed_sources）已由
#       recall_http_api.feature 覆盖且本端点复用同一执行链；本契约只断言前端直连
#       新增的边界——会话凭证鉴权、密钥隔离、CORS、限流、断连，
#       以及前端可直接观测到的终态事件。
# token 策略：短期可复用（仅校验 exp），不做一次性消费 / 防重放 / 撤销；
#       资源滥用由按 user_id 的并发上限封顶。

Feature: 前端直连 Python 召回 SSE
  作为已通过 Java 鉴权并拿到短期 recall_session_token 的前端
  我希望用该 token 直连 POST /api/v1/recall/stream 建立 SSE 连接
  以便绕过 Java 中转直接接收召回事件，同时 Python 只信任 Java 签发的会话凭证

  Background:
    Given 配置 RECALL_SESSION_AUTH_ENABLED=True
    And 配置 session token 的 RECALL_SESSION_JWT_ISSUER=tolink-java
    And 配置 session token 的 RECALL_SESSION_JWT_AUDIENCE=tolink-rag-frontend
    And 配置 session token 的 RECALL_SESSION_JWT_SCOPE=recall:stream
    And session token 使用 RECALL_SESSION_JWT_SECRET 这一独立专用签名密钥
    And session token 短期可复用，有效期内只校验 exp，不做一次性消费
    And 配置 RECALL_RESULT_LIMIT=20
    And 配置 RECALL_ENABLED_SOURCES=bm25,sparse
    And 配置对外 CORS 允许来源为 ["https://app.tolink.com"]
    And 配置单用户最大并发召回流数 RECALL_SESSION_MAX_CONCURRENT=3
    And Redis 可用用于并发流计数
    And 服务端已装配 bm25 与 sparse 两路 retriever

  # ==== 主流程 ====

  Scenario: 有效会话凭证建连并以 answer_done 返回生成答案与融合候选
    Given session token claims sub=123 aud=tolink-rag-frontend iss=tolink-java scope=recall:stream dataset_ids=[1,2] 未过期
    And bm25 与 sparse 两路均返回命中
    When 前端携带该 token 以 Authorization Bearer 调用 POST /api/v1/recall/stream body query="数据治理" dataset_ids=[1,2]
    Then HTTP 响应状态为 200
    And 响应 Content-Type 为 "text/event-stream"
    And 响应头 Cache-Control 为 "no-cache"
    And 响应头 X-Accel-Buffering 为 "no"
    And 收到 SSE 事件 "answer_done"
    And answer_done.data 含字段 hits 与 failed_sources
    And hits 中每个 hit 不含字段 content
    And 发送 answer_done 后关闭 SSE 流

  Scenario: token 仅约束建连，建连后流执行期间 token 过期不中断流
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 合法
    And 已用该 token 成功建连且召回正在执行
    When token 的 exp 在流执行期间到达
    Then 当前 SSE 流不因 token 过期被中断
    And 流仍以 answer_done 或 error 正常终态结束
    And 流的最大执行时间仍由 RECALL_STREAM_TIMEOUT_MS 控制

  # ==== 会话凭证鉴权（握手前，返回非 2xx JSON，不执行 pipeline）====

  Scenario: 缺少 Authorization 头时拒绝且不执行 pipeline
    When 前端不携带 Authorization 头调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 401
    And 响应体 code 等于 "RECALL_SESSION_UNAUTHORIZED"
    And 不调用 RecallPipeline

  Scenario Outline: 会话凭证校验失败时返回 401 且不执行 pipeline
    Given session token 存在缺陷 "<defect>"
    When 前端携带该 token 调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 401
    And 响应体 code 等于 "RECALL_SESSION_UNAUTHORIZED"
    And 不调用 RecallPipeline

    Examples:
      | defect                        |
      | 签名不匹配                    |
      | iss 不是 tolink-java          |
      | aud 不是 tolink-rag-frontend  |
      | scope 不是 recall:stream      |
      | exp 已过期                    |

  Scenario: 用其它服务密钥签发的 token 被拒绝以隔离会话凭证
    Given 一个 token 用非 session 密钥的其它密钥签发 claims 全对
    When 前端携带该 token 调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 401
    And 响应体 code 等于 "RECALL_SESSION_UNAUTHORIZED"
    And 不调用 RecallPipeline

  # ==== token 短期可复用（不做一次性 / 防重放）====

  Scenario: 未过期 token 可在有效期内重复建连（断线重连复用同一 token）
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And 已用该 token 成功建连过一次且连接已结束
    When 前端在 token 未过期时携带同一 token 再次调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 收到 SSE 事件 "answer_done"

  # ==== 身份与授权范围（身份只取 claims；dataset_ids 为授权范围内子集选择）====

  Scenario: body.dataset_ids 超出 claims 授权范围时返回 403 且不执行 pipeline
    Given session token claims sub=123 dataset_ids=[1,2] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1,3]
    Then HTTP 响应状态为 403
    And 响应体 code 等于 "RECALL_SCOPE_FORBIDDEN"
    And 不调用 RecallPipeline

  Scenario: 身份取自 claims，dataset_ids 取 body 子集
    Given session token claims sub=123 dataset_ids=[1,2] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 以 user_id=123 执行 RecallPipeline
    And 以 dataset_ids=[1] 执行 RecallPipeline

  Scenario: body 省略 dataset_ids 时按 claims 全量授权范围召回
    Given session token claims sub=123 dataset_ids=[1,2] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/recall/stream body query="任意" 且不含 dataset_ids
    Then HTTP 响应状态为 200
    And 以 user_id=123 执行 RecallPipeline
    And 以 dataset_ids=[1,2] 执行 RecallPipeline

  # ==== 请求体校验（与内部端点对齐，拒未知字段）====

  Scenario Outline: 出现非首版字段时返回 422 且不执行 pipeline
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/recall/stream body 额外包含字段 "<field>"
    Then HTTP 响应状态为 422
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"
    And 不调用 RecallPipeline

    Examples:
      | field           |
      | user_id         |
      | top_k           |
      | sources         |
      | strict          |
      | doc_ids         |
      | include_content |

  Scenario Outline: query 为空或纯空白时返回 400 RECALL_INVALID_REQUEST
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/recall/stream body query 为空白标识 "<query_token>" dataset_ids=[1]
    Then HTTP 响应状态为 400
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"

    Examples:
      | query_token |
      | EMPTY       |
      | SPACES      |
      | NEWLINE     |

  # ==== CORS（对外暴露面收敛）====

  Scenario: 来源在允许清单内时响应带 Access-Control-Allow-Origin
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端从 Origin "https://app.tolink.com" 携带该 token 调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then 响应头 Access-Control-Allow-Origin 等于 "https://app.tolink.com"

  Scenario: 来源不在允许清单内时不返回该来源的 Access-Control-Allow-Origin
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端从 Origin "https://evil.example.com" 携带该 token 调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then 响应头 Access-Control-Allow-Origin 不等于 "https://evil.example.com"

  # ==== 限流（按 user_id 并发流数）====

  Scenario: 单用户并发流数超过上限时返回 429 且不新建 pipeline
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And 用户 123 已有 3 条召回流在执行
    When 前端携带新 token 为用户 123 发起第 4 条 POST /api/v1/recall/stream
    Then HTTP 响应状态为 429
    And 响应体 code 等于 "RECALL_RATE_LIMITED"
    And 不调用 RecallPipeline

  Scenario: 单用户并发流数未达上限时放行
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And 用户 123 已有 2 条召回流在执行
    When 前端携带新 token 为用户 123 发起第 3 条 POST /api/v1/recall/stream
    Then HTTP 响应状态为 200
    And 收到 SSE 事件 "answer_done"

  # ==== 前端可直接观测的失败终态 ====

  Scenario: 全部召回路失败时以 SSE error 返回并关流
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And bm25 与 sparse 两路均执行抛异常
    When 前端携带该 token 调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then 响应 Content-Type 为 "text/event-stream"
    And 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_ALL_SOURCES_FAILED"
    And error.data 的 message 不含内部堆栈
    And 发送 error 后关闭 SSE 流

  Scenario: recall runtime 超时以 SSE error 返回并关流
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And recall runtime 执行超过 RECALL_STREAM_TIMEOUT_MS
    When 前端携带该 token 调用 POST /api/v1/recall/stream body query="任意" dataset_ids=[1]
    Then 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_TIMEOUT"
    And 发送 error 后关闭 SSE 流

  # ==== 断连与资源释放 ====

  Scenario: 前端断开 SSE 时 Python 停止发送事件并取消召回任务
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And recall 正在执行中
    When 前端主动断开到 Python 的 SSE 连接
    Then Python 停止继续发送 SSE 事件
    And Python 尽力取消正在执行的召回任务
    And 该流不再计入用户 123 的并发流数
