# 对外纯召回 JSON acceptance 契约（LINK-131）
# 范围：对外纯召回端点 POST /api/v1/recall。一次性返回 application/json，不建立 SSE、不调 CHAT 模型、
#       不回填 chunk 正文、不做并发限流。当前阶段为接口预留实现。
# 说明：与 RAG 问答流（rag_stream.feature）共用 Java access token 鉴权与实时 dataset scope 校验；
#       关键差异：不要求 config_id、出现 config_id 即拒、不建 SSE、不限流、执行期错误走 HTTP 状态码。
# 兼容：返回 payload 与 RAG 流 recall_done 帧同构——{hits, failed_sources}。

Feature: 对外纯召回 JSON
  作为已通过 Java 登录并拿到 access token 的前端
  我希望用该 token 调用 POST /api/v1/recall 获取一次性纯召回结果
  以便在不触发 LLM 生成的情况下拿到与 recall_done 同构的 hits 集合

  Background:
    Given 配置 RECALL_RESULT_LIMIT=20
    And 配置 RECALL_ENABLED_SOURCES=bm25,sparse
    And 服务端已装配 bm25 与 sparse 两路 retriever

  # ==== 主流程：一次性 JSON 召回 ====

  Scenario: 有效凭证且命中时返回 application/json 且不建立 SSE
    Given Java access token 对应用户 sub=123 dataset_ids=[1,2] 有效
    And bm25 与 sparse 两路均返回命中
    When 前端携带该 token 调用 POST /api/v1/recall body query="数据治理" dataset_ids=[1,2]
    Then HTTP 响应状态为 200
    And 响应 Content-Type 为 "application/json"
    And 响应不是 text/event-stream
    And 响应体含字段 hits 与 failed_sources
    And hits 中每个 hit 含字段 chunk_id 与 doc_id 与 dataset_id 与 fused_score 与 scores
    And hits 中每个 hit 不含字段 content
    And 不调用 CHAT 模型生成

  Scenario: 0 命中时返回 200 且 hits 为空数组
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    And bm25 与 sparse 两路均返回 0 命中
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 响应体 hits 为空数组
    And 响应体含字段 failed_sources

  Scenario: 一路召回失败时宽松降级并在 failed_sources 标记失败路
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    And bm25 路抛异常而 sparse 路返回命中
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 响应体 failed_sources 含 "bm25"
    And 响应体 hits 非空

  # ==== 与 RAG 流的关键差异：不要求 config_id，且拒绝 config_id ====

  Scenario: 不携带 config_id 时正常返回纯召回结果
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    And bm25 与 sparse 两路均返回命中
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1] 不含 config_id
    Then HTTP 响应状态为 200
    And 响应体含字段 hits 与 failed_sources

  Scenario: 请求体出现 config_id 时返回 422 且不执行 pipeline
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" config_id=9 dataset_ids=[1]
    Then HTTP 响应状态为 422
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"
    And 不调用 RecallPipeline

  Scenario Outline: 请求体出现其它非首版字段时返回 422 且不执行 pipeline
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    When 前端携带该 token 调用 POST /api/v1/recall body 额外包含字段 "<field>"
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

  # ==== 会话鉴权与授权范围（握手前返回 HTTP JSON，不执行 pipeline）====

  Scenario: 缺少 Authorization 头时返回 401 且不执行 pipeline
    When 前端不携带 Authorization 头调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 401
    And 响应体 code 等于 "ACCESS_TOKEN_UNAUTHORIZED"
    And 不调用 RecallPipeline

  Scenario: body.dataset_ids 超出 数据库当前授权范围时返回 403 且不执行 pipeline
    Given Java access token 对应用户 sub=123 dataset_ids=[1,2] 有效
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1,3]
    Then HTTP 响应状态为 403
    And 响应体 code 等于 "RECALL_SCOPE_FORBIDDEN"
    And 不调用 RecallPipeline

  Scenario: 身份取自 token，dataset_ids 取 body 子集
    Given Java access token 对应用户 sub=123 dataset_ids=[1,2] 有效
    And bm25 与 sparse 两路均返回命中
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 以 user_id=123 执行 RecallPipeline
    And 以 dataset_ids=[1] 执行 RecallPipeline

  Scenario Outline: query 为空或纯空白时返回 400 RECALL_INVALID_REQUEST
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    When 前端携带该 token 调用 POST /api/v1/recall body query 为空白标识 "<query_token>" dataset_ids=[1]
    Then HTTP 响应状态为 400
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"

    Examples:
      | query_token |
      | EMPTY       |
      | SPACES      |
      | NEWLINE     |

  # ==== 执行期错误：走 HTTP 状态码而非 SSE error 帧 ====

  Scenario: Dataset 精确绑定的 EMBEDDING 配置在召回时不可用则返回 422 RECALL_EMBEDDING_CONFIG_MISSING
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    And Dataset 1 绑定的 dense_embedding_config_id 在召回时不可用
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 422
    And 响应体 code 等于 "RECALL_EMBEDDING_CONFIG_MISSING"

  Scenario: 全部召回路失败时返回 500 RECALL_ALL_SOURCES_FAILED
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    And bm25 与 sparse 两路均执行抛异常
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 500
    And 响应体 code 等于 "RECALL_ALL_SOURCES_FAILED"
    And 响应体 message 不含内部堆栈

  Scenario: 召回超时返回 504 RECALL_TIMEOUT
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    And 召回执行超过 RECALL_STREAM_TIMEOUT_MS
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 504
    And 响应体 code 等于 "RECALL_TIMEOUT"

  Scenario: 未预期异常返回 500 RECALL_INTERNAL_ERROR
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    And 召回执行期间发生未预期异常
    When 前端携带该 token 调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 500
    And 响应体 code 等于 "RECALL_INTERNAL_ERROR"
    And 响应体 message 不含内部堆栈

  # ==== 不限流 ====

  Scenario: 纯召回不做并发限流，超过 RAG 流并发上限仍放行
    Given Java access token 对应用户 sub=123 dataset_ids=[1] 有效
    And 用户 123 已有 3 条 RAG 流在执行
    And bm25 与 sparse 两路均返回命中
    When 前端携带该 token 为用户 123 调用 POST /api/v1/recall body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 响应体含字段 hits 与 failed_sources
