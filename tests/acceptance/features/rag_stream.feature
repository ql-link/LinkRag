# 对外 RAG 问答流 SSE acceptance 契约（LINK-131）
# 由 recall_direct_sse.feature 改名搬迁而来：端点 POST /api/v1/recall/stream → POST /api/v1/rag/stream。
# 范围：Python 侧对外 RAG 问答流 SSE 端点。承接完整 RAG 行为：会话鉴权 → 召回 → RRF 融合 →
#       rerank 精排（不可用即降级 RRF 顺序）→ 正文回填 → 上下文组装 → CHAT 流式生成。
# 说明：在原对外直连 SSE 行为基础上，补回 #165 删除 recall_http_api.feature 后悬空的召回执行
#       语义断言（RRF 融合、命中字段形状、failed_sources 降级），并覆盖 rerank 精排终态与
#       未配置 RERANK 模型时降级为 RRF 顺序的契约。
# token 策略：短期可复用（仅校验 exp），不做一次性消费 / 防重放 / 撤销；
#       资源滥用由按 user_id 的并发上限封顶。

Feature: 对外 RAG 问答流 SSE
  作为已通过 Java 鉴权并拿到短期 recall_session_token 的前端
  我希望用该 token 直连 POST /api/v1/rag/stream 建立 SSE 连接
  以便接收召回 + LLM 流式生成的完整 RAG 问答事件，同时 Python 只信任 Java 签发的会话凭证

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

  # ==== 主流程：召回 + 生成 ====

  Scenario: 模型可用且命中且正文可回填时以 answer_delta/answer_done 返回生成答案
    Given session token claims sub=123 aud=tolink-rag-frontend iss=tolink-java scope=recall:stream dataset_ids=[1,2] 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And bm25 与 sparse 两路均返回命中
    When 前端携带该 token 以 Authorization Bearer 调用 POST /api/v1/rag/stream body query="数据治理" dataset_ids=[1,2]
    Then HTTP 响应状态为 200
    And 响应 Content-Type 为 "text/event-stream"
    And 响应头 Cache-Control 为 "no-cache"
    And 响应头 X-Accel-Buffering 为 "no"
    And 至少收到一个 SSE 事件 "answer_delta"
    And 最终收到 SSE 事件 "answer_done"
    And answer_done.data 含字段 answer 与 hits 与 failed_sources
    And 终态事件 data 的 rerank_applied 为 true
    And hits 中每个 hit 不含字段 content
    And 发送 answer_done 后关闭 SSE 流

  Scenario: 0 命中时以 recall_done 结束且不调用 CHAT 模型
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And bm25 与 sparse 两路均返回 0 命中
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 最终收到 SSE 事件 "recall_done"
    And 不收到 SSE 事件 "answer_done"
    And 不调用 CHAT 模型生成

  Scenario: 有命中但全部片段缺正文时以 recall_done 结束且不调用 CHAT 模型
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And bm25 与 sparse 两路返回命中但全部命中片段无可用正文
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 最终收到 SSE 事件 "recall_done"
    And 不调用 CHAT 模型生成

  Scenario: token 仅约束建连，建连后流执行期间 token 过期不中断流
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 合法
    And config_id 指向的 CHAT 模型对用户 123 可用
    And 已用该 token 成功建连且召回正在执行
    When token 的 exp 在流执行期间到达
    Then 当前 SSE 流不因 token 过期被中断
    And 流仍以 answer_done 或 error 正常终态结束
    And 流的最大执行时间仍由 RECALL_STREAM_TIMEOUT_MS 控制

  # ==== 召回执行语义（补回 #165 随 recall_http_api.feature 删除的断言）====

  Scenario: 多路命中经 RRF 融合后由 rerank 精排并以最小候选形状输出
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And bm25 与 sparse 两路均返回命中
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 终态事件 data 的 rerank_applied 为 true
    And 终态事件 data 中 hits 按 rerank_rank 升序排列
    And hits 中每个 hit 含字段 chunk_id 与 doc_id 与 dataset_id 与 fused_score 与 scores 与 rerank_score 与 rerank_rank
    And hits 中每个 hit 不含字段 content

  Scenario: 用户未配置 RERANK 模型时降级为 RRF 顺序候选且不报错
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And 用户 123 未配置 RERANK 模型
    And bm25 与 sparse 两路均返回命中
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 最终收到 SSE 事件 "answer_done"
    And 终态事件 data 的 rerank_applied 为 false
    And 终态事件 data 中 hits 按 fused_score 降序排列
    And hits 中每个 hit 的 rerank_score 与 rerank_rank 为 null
    And 终态事件 data 的 hits 非空

  Scenario: 一路召回失败时宽松降级用其余路融合并在 failed_sources 标记失败路
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And bm25 路抛异常而 sparse 路返回命中
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 终态事件 data 的 failed_sources 含 "bm25"
    And 终态事件 data 的 hits 非空

  # ==== 生成阶段与前置模型校验的失败终态（SSE error 帧）====

  Scenario: config_id 指向的 CHAT 模型不可用时以 error 返回且不进入召回
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 不可用
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_MODEL_CONFIG_MISSING"
    And 不调用 RecallPipeline
    And 发送 error 后关闭 SSE 流

  Scenario: 生成阶段抛异常时以 error RECALL_GENERATION_FAILED 返回
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And 召回命中且正文可回填但流式生成阶段抛异常
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_GENERATION_FAILED"
    And 不收到 SSE 事件 "answer_done"
    And error.data 的 message 不含内部堆栈

  Scenario: 发起用户无默认 EMBEDDING 配置时以 error RECALL_EMBEDDING_CONFIG_MISSING 返回
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And 用户 123 无默认 EMBEDDING 配置
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_EMBEDDING_CONFIG_MISSING"

  Scenario: 全部召回路失败时以 SSE error 返回并关流
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And bm25 与 sparse 两路均执行抛异常
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 响应 Content-Type 为 "text/event-stream"
    And 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_ALL_SOURCES_FAILED"
    And error.data 的 message 不含内部堆栈
    And 发送 error 后关闭 SSE 流

  Scenario: recall runtime 超时以 SSE error 返回并关流
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And recall runtime 执行超过 RECALL_STREAM_TIMEOUT_MS
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 收到 SSE 事件 "error"
    And error.data 的 code 等于 "RECALL_TIMEOUT"
    And 发送 error 后关闭 SSE 流

  # ==== 会话凭证鉴权（握手前，返回非 2xx JSON，不执行 pipeline）====

  Scenario: 缺少 Authorization 头时拒绝且不执行 pipeline
    When 前端不携带 Authorization 头调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 401
    And 响应体 code 等于 "RECALL_SESSION_UNAUTHORIZED"
    And 不调用 RecallPipeline

  Scenario Outline: 会话凭证校验失败时返回 401 且不执行 pipeline
    Given session token 存在缺陷 "<defect>"
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
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
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 401
    And 响应体 code 等于 "RECALL_SESSION_UNAUTHORIZED"
    And 不调用 RecallPipeline

  # ==== token 短期可复用（不做一次性 / 防重放）====

  Scenario: 未过期 token 可在有效期内重复建连（断线重连复用同一 token）
    Given session token claims sub=123 dataset_ids=[1] scope=recall:stream 未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    And 已用该 token 成功建连过一次且连接已结束
    When 前端在 token 未过期时携带同一 token 再次调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 最终收到 SSE 事件 "answer_done"

  # ==== 身份与授权范围（身份只取 claims；dataset_ids 为授权范围内子集选择）====

  Scenario: body.dataset_ids 超出 claims 授权范围时返回 403 且不执行 pipeline
    Given session token claims sub=123 dataset_ids=[1,2] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1,3]
    Then HTTP 响应状态为 403
    And 响应体 code 等于 "RECALL_SCOPE_FORBIDDEN"
    And 不调用 RecallPipeline

  Scenario: 身份取自 claims，dataset_ids 取 body 子集
    Given session token claims sub=123 dataset_ids=[1,2] 合法未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then HTTP 响应状态为 200
    And 以 user_id=123 执行 RecallPipeline
    And 以 dataset_ids=[1] 执行 RecallPipeline

  Scenario: body 省略 dataset_ids 时按 claims 全量授权范围召回
    Given session token claims sub=123 dataset_ids=[1,2] 合法未过期
    And config_id 指向的 CHAT 模型对用户 123 可用
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" 且不含 dataset_ids
    Then HTTP 响应状态为 200
    And 以 user_id=123 执行 RecallPipeline
    And 以 dataset_ids=[1,2] 执行 RecallPipeline

  # ==== 请求体校验（拒未知字段；config_id 必填）====

  Scenario Outline: 出现非首版字段时返回 422 且不执行 pipeline
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/rag/stream body 额外包含字段 "<field>"
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

  Scenario: 缺少必填 config_id 时返回 422 且不执行 pipeline
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1] 不含 config_id
    Then HTTP 响应状态为 422
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"
    And 不调用 RecallPipeline

  Scenario Outline: query 为空或纯空白时返回 400 RECALL_INVALID_REQUEST
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端携带该 token 调用 POST /api/v1/rag/stream body query 为空白标识 "<query_token>" dataset_ids=[1]
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
    When 前端从 Origin "https://app.tolink.com" 携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 响应头 Access-Control-Allow-Origin 等于 "https://app.tolink.com"

  Scenario: 来源不在允许清单内时不返回该来源的 Access-Control-Allow-Origin
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端从 Origin "https://evil.example.com" 携带该 token 调用 POST /api/v1/rag/stream body query="任意" dataset_ids=[1]
    Then 响应头 Access-Control-Allow-Origin 不等于 "https://evil.example.com"

  # ==== 限流（按 user_id 并发流数）====

  Scenario: 单用户并发流数超过上限时返回 429 且不新建 pipeline
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And 用户 123 已有 3 条召回流在执行
    When 前端携带新 token 为用户 123 发起第 4 条 POST /api/v1/rag/stream
    Then HTTP 响应状态为 429
    And 响应体 code 等于 "RECALL_RATE_LIMITED"
    And 不调用 RecallPipeline

  # ==== 断连与资源释放 ====

  Scenario: 前端断开 SSE 时 Python 停止发送事件、取消召回任务并释放并发名额
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    And recall 正在执行中
    When 前端主动断开到 Python 的 SSE 连接
    Then Python 停止继续发送 SSE 事件
    And Python 尽力取消正在执行的召回任务
    And 该流不再计入用户 123 的并发流数

  # ==== 旧路径已删除 ====

  Scenario: 旧对外 SSE 路径 POST /api/v1/recall/stream 不再命中旧 handler
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端携带该 token 调用已删除路径 POST /api/v1/recall/stream
    Then HTTP 响应状态为 404
    And 不调用 RecallPipeline

  Scenario: 旧内部 SSE 路径 POST /api/v1/internal/recall/stream 不再命中旧 handler
    When 调用已删除路径 POST /api/v1/internal/recall/stream
    Then HTTP 响应状态为 404
    And 不调用 RecallPipeline
