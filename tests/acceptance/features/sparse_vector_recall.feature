# 稀疏向量召回入口 acceptance 契约
# 输入：.specs/sparse-vector-recall/brief.md（已冻结 2026-05-28）
# 关联 Linear: LINK-8 / GitHub: ql-link/LinkRag#54
# step 实现：tests/acceptance/steps/sparse_vector_recall_steps.py

Feature: 稀疏向量召回入口
  作为召回链路的调用方
  我希望通过 VectorStorageFacade.search_sparse_chunks 给定 query + user_id + set_id（可选 doc_id / top_k / score_threshold）召回 chunk
  以便基于 BGE-M3 稀疏向量检索拿到候选命中，由我自行回填 chunk 真值并参与后续融合或 rerank

  Background:
    Given 配置 SPARSE_VECTOR_ENABLED=True
    And 配置 SPARSE_RETRIEVAL_TOP_K=10
    And 配置 SPARSE_RETRIEVAL_SCORE_THRESHOLD=0.0
    And 写入链路使用 vector name "sparse_text" 写入 sparse vector
    And BGE-M3 稀疏向量编码器可用

  # ==== 主流程 ====

  Scenario: 合法 query 命中并返回 top-k hits
    Given Qdrant 中 user_id=10002 的 bucket collection 存在 5 个 sparse_text 向量
    When 调用 search_sparse_chunks 传入 query "数据治理流程" user_id 10002 set_id 10003
    Then 返回 VectorSearchResult 长度不超过 10
    And hits 中每个 hit 必须含字段 chunk_id, doc_id, set_id, score, vector_kind
    And hits 中每个 hit 不含字段 content
    And hits 中每个 hit 不含字段 payload
    And hits 中每个 hit 的 vector_kind 等于 "sparse"
    And hits 按 score 降序排列
    And 调用稀疏向量编码器一次，输入文本等于 "数据治理流程"
    And 写入与查询使用相同的 vector name "sparse_text"

  # ==== 参数处理与默认值合并 ====

  Scenario: 不传 top_k 与 score_threshold 时使用全局默认
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then Qdrant 搜索使用 limit 等于 10
    And Qdrant 搜索使用 score_threshold 等于 0.0
    And 返回 VectorSearchResult.top_k 等于 10
    And 返回 VectorSearchResult.score_threshold 等于 0.0

  Scenario: 调用方显式覆盖 top_k 与 score_threshold
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003 top_k 20 score_threshold 0.3
    Then Qdrant 搜索使用 limit 等于 20
    And Qdrant 搜索使用 score_threshold 等于 0.3
    And 返回 VectorSearchResult.top_k 等于 20
    And 返回 VectorSearchResult.score_threshold 等于 0.3

  Scenario: per-call 覆盖优先于全局默认
    Given 配置 SPARSE_RETRIEVAL_TOP_K=10
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003 top_k 5
    Then Qdrant 搜索使用 limit 等于 5
    And 返回 VectorSearchResult.top_k 等于 5

  # ==== Bucket 路由与 vector name 一致性 ====

  Scenario: 召回侧的 bucket 路由与写入侧一致
    Given 写入链路对 user_id 10002 计算得到 bucket_id 42
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then Qdrant 搜索使用 bucket_id 等于 42
    And VectorSearchResult 不含字段 bucket_id

  Scenario: 查询使用与写入完全相同的 sparse vector name
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then Qdrant 搜索使用 named sparse vector "sparse_text"
    And 返回 VectorSearchResult.vector_name 等于 "sparse_text"

  # ==== Payload filter 与数据隔离 ====

  Scenario: payload filter 强制包含 user_id 与 set_id
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then Qdrant 搜索的 payload filter must 条件包含 user_id 等于 10002
    And Qdrant 搜索的 payload filter must 条件包含 set_id 等于 10003
    And Qdrant 搜索的 payload filter 不含 doc_id 条件

  Scenario: 不传 doc_id 时不加 doc_id filter
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003 不传 doc_id
    Then Qdrant 搜索的 payload filter 不含 doc_id 条件

  Scenario: 传空 doc_id 列表时不加 doc_id filter
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003 doc_id 空列表
    Then Qdrant 搜索的 payload filter 不含 doc_id 条件

  Scenario: 单个 doc_id 通过列表传入时使用 MatchAny
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003 doc_id 列表 "42"
    Then Qdrant 搜索的 payload filter doc_id MatchAny 等于 "42"

  Scenario: 多个 doc_id 通过列表传入时使用 MatchAny
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003 doc_id 列表 "42,43,44"
    Then Qdrant 搜索的 payload filter doc_id MatchAny 等于 "42,43,44"

  # ==== Score 过滤与排序 ====

  Scenario: 低于阈值的 hit 被过滤
    Given Qdrant 接收到 score_threshold 为 0.3 时仅返回 score 不低于 0.3 的命中
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003 score_threshold 0.3
    Then Qdrant 搜索使用 score_threshold 等于 0.3
    And 返回的 hits 全部满足 score 不低于 0.3

  Scenario: 命中数量被 top_k 截断
    Given Qdrant 端在 limit=5 时返回 5 条按 score 降序的命中
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003 top_k 5
    Then Qdrant 搜索使用 limit 等于 5
    And 返回 VectorSearchResult.hits 长度等于 5
    And hits 按 score 降序排列

  # ==== 异常路径：query 失败模式 ====

  Scenario Outline: 空 query 或全空白 query 直接返回空，不触发任何下游
    When 调用 search_sparse_chunks 传入 空白 query 标识 "<query_token>" user_id 10002 set_id 10003
    Then 返回 VectorSearchResult.hits 为空
    And 不调用稀疏向量编码器
    And 不调用 Qdrant 客户端

    Examples:
      | query_token |
      | EMPTY       |
      | SPACES      |
      | TAB         |
      | NEWLINE     |
      | MIXED_WS    |

  # ==== 异常路径：参数值越界 ====

  Scenario Outline: user_id / set_id / top_k / score_threshold 越界时抛 ValueError
    When 调用 search_sparse_chunks 传入越界参数 user_id <user_id> set_id <set_id> top_k <top_k> score_threshold <score_threshold>
    Then 抛出 ValueError
    And 不调用稀疏向量编码器
    And 不调用 Qdrant 客户端

    Examples:
      | user_id | set_id | top_k | score_threshold |
      | 0       | 10003  | NONE  | NONE            |
      | -1      | 10003  | NONE  | NONE            |
      | 10002   | 0      | NONE  | NONE            |
      | 10002   | -1     | NONE  | NONE            |
      | 10002   | 10003  | 0     | NONE            |
      | 10002   | 10003  | -3    | NONE            |
      | 10002   | 10003  | NONE  | -0.1            |

  # ==== 异常路径：配置失败 ====

  Scenario: SPARSE_VECTOR_ENABLED=False 时抛配置异常
    Given 配置 SPARSE_VECTOR_ENABLED=False
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 抛出 VectorRetrievalConfigurationError
    And 不调用稀疏向量编码器
    And 不调用 Qdrant 客户端

  # ==== Qdrant 端容错 ====

  Scenario: 目标 bucket collection 不存在时返回空 hits
    Given Qdrant 中 user_id 10002 路由到的 bucket collection 不存在
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 返回 VectorSearchResult.hits 为空
    And 不抛任何异常
    And 调用稀疏向量编码器一次

  Scenario: 目标 collection 中 sparse_text 命名向量未配置时返回空 hits
    Given Qdrant 中 user_id 10002 路由到的 bucket collection 存在
    And 该 collection 未配置 named sparse vector "sparse_text"
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 返回 VectorSearchResult.hits 为空
    And 不抛任何异常

  Scenario: BGE-M3 推理失败传播为 VectorRetrievalEncodingError
    Given 稀疏向量编码器对任意输入抛底层编码异常
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 抛出 VectorRetrievalEncodingError
    And 不调用 Qdrant 客户端

  Scenario: Qdrant 客户端故障传播为 VectorRetrievalBackendError
    Given Qdrant 客户端对搜索请求抛底层网络异常
    When 调用 search_sparse_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 抛出 VectorRetrievalBackendError

  # ==== 只读语义 ====

  Scenario: 同一 query 多次调用结果稳定且不写状态
    Given Qdrant 中 user_id=10002 的 chunk 状态为已 INDEXED
    When 连续调用 search_sparse_chunks 两次 query "任意" user_id 10002 set_id 10003
    Then 两次返回 hits 中 chunk_id 集合相同
    And 两次调用过程中不发生 Qdrant 写操作

  # ==== 对外暴露面 ====

  Scenario: 调用方只通过 vector_storage 包接触召回 API
    Then 从 vector_storage 包可以导入 VectorStorageFacade
    And 从 vector_storage 包可以导入 VectorSearchHit, VectorSearchResult
    And 从 vector_storage 包可以导入召回侧异常族
    And SparseVectorSearchRequest 不在 vector_storage 包的 __all__ 中
    And SparseQueryVectorSpec 不在 vector_storage 包的 __all__ 中
    And VectorRetrieval 异常族继承关系正确
