# 稠密向量召回入口 acceptance 契约
# 输入：.specs/dense-vector-recall/brief.md（已冻结 2026-05-31）
# 关联 GitHub: ql-link/LinkRag#53
# 同业务域参照（严格对仗）：tests/acceptance/features/sparse_vector_recall.feature
# step 实现：tests/acceptance/steps/dense_vector_recall_steps.py

Feature: 稠密向量召回入口
  作为召回链路的调用方
  我希望通过 VectorStorageFacade.search_dense_chunks 给定 query + user_id + set_id（可选 doc_id / top_k / score_threshold）召回 chunk
  以便基于 system embedding 稠密向量检索拿到候选命中，由我自行回填 chunk 真值并参与后续融合或 rerank
  并通过 DenseRetriever 自动接入多路召回 pipeline，让 SSE 流式 API 自动产出 dense 路命中

  Background:
    Given 配置 SYSTEM_LLM_MODEL_EMBEDDING="text-embedding-v4"
    And 配置 DENSE_RETRIEVAL_TOP_K=10
    And 配置 DENSE_RETRIEVAL_SCORE_THRESHOLD=0.0
    And 配置 RECALL_ENABLED_SOURCES="bm25,sparse,dense"
    And 配置 RECALL_RESULT_LIMIT=20
    And 写入链路使用 unnamed dense vector 写入 chunk 的 dense embedding
    And system embedding HTTP 客户端可用

  # ==== 主流程 ====

  Scenario: 合法 query 命中并返回 top-k hits
    Given Qdrant 中 user_id=10002 的 bucket collection 存在 5 个 unnamed dense 向量
    When 调用 search_dense_chunks 传入 query "数据治理流程" user_id 10002 set_id 10003
    Then 返回 VectorSearchResult 长度不超过 10
    And hits 中每个 hit 必须含字段 chunk_id, doc_id, set_id, score, vector_kind
    And hits 中每个 hit 不含字段 content
    And hits 中每个 hit 不含字段 payload
    And hits 中每个 hit 的 vector_kind 等于 "dense"
    And hits 按 score 降序排列
    And 调用 ChunkEmbeddingPipeline.aembed_query 一次，输入文本等于 "数据治理流程"
    And 写入与查询使用相同的 embedding model "text-embedding-v4"

  # ==== 参数处理与默认值合并 ====

  Scenario: 不传 top_k 与 score_threshold 时使用全局默认
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then Qdrant 搜索使用 limit 等于 10
    And Qdrant 搜索使用 score_threshold 等于 0.0
    And 返回 VectorSearchResult.top_k 等于 10
    And 返回 VectorSearchResult.score_threshold 等于 0.0

  Scenario: 调用方显式覆盖 top_k 与 score_threshold
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003 top_k 20 score_threshold 0.6
    Then Qdrant 搜索使用 limit 等于 20
    And Qdrant 搜索使用 score_threshold 等于 0.6
    And 返回 VectorSearchResult.top_k 等于 20
    And 返回 VectorSearchResult.score_threshold 等于 0.6

  Scenario: per-call 覆盖优先于全局默认
    Given 配置 DENSE_RETRIEVAL_TOP_K=10
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003 top_k 5
    Then Qdrant 搜索使用 limit 等于 5
    And 返回 VectorSearchResult.top_k 等于 5

  # ==== Bucket 路由与 vector 形态一致性 ====

  Scenario: 召回侧的 bucket 路由与写入侧一致
    Given 写入链路对 user_id 10002 计算得到 bucket_id 42
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then Qdrant 搜索使用 bucket_id 等于 42
    And VectorSearchResult 不含字段 bucket_id

  Scenario: 查询使用与写入完全相同的 unnamed dense vector 形态
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then Qdrant 搜索的 query_vector_spec 类型为 DenseQueryVectorSpec
    And Qdrant 搜索的 query_vector_spec 不带 vector_name
    And 返回 VectorSearchResult.vector_name 为 None

  Scenario: query 与 chunk 写入使用同一份 embedding 客户端实例
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then aembed_query 与 aembed_chunks 共用同一个 embedder 实例
    And aembed_query 与 aembed_chunks 共用同一个 embedding_model 字符串

  # ==== Payload filter 与数据隔离 ====

  Scenario: payload filter 强制包含 user_id 与 set_id
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then Qdrant 搜索的 payload filter must 条件包含 user_id 等于 10002
    And Qdrant 搜索的 payload filter must 条件包含 set_id 等于 10003
    And Qdrant 搜索的 payload filter 不含 doc_id 条件

  Scenario: 不传 doc_id 时不加 doc_id filter
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003 不传 doc_id
    Then Qdrant 搜索的 payload filter 不含 doc_id 条件

  Scenario: 传空 doc_id 列表时不加 doc_id filter
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003 doc_id 空列表
    Then Qdrant 搜索的 payload filter 不含 doc_id 条件

  Scenario: 单个 doc_id 通过列表传入时使用 MatchAny
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003 doc_id 列表 "42"
    Then Qdrant 搜索的 payload filter doc_id MatchAny 等于 "42"

  Scenario: 多个 doc_id 通过列表传入时使用 MatchAny
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003 doc_id 列表 "42,43,44"
    Then Qdrant 搜索的 payload filter doc_id MatchAny 等于 "42,43,44"

  # ==== Score 过滤与排序 ====

  Scenario: 低于阈值的 hit 被过滤
    Given Qdrant 接收到 score_threshold 为 0.6 时仅返回 score 不低于 0.6 的命中
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003 score_threshold 0.6
    Then Qdrant 搜索使用 score_threshold 等于 0.6
    And 返回的 hits 全部满足 score 不低于 0.6

  Scenario: 命中数量被 top_k 截断
    Given Qdrant 端在 limit=5 时返回 5 条按 score 降序的命中
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003 top_k 5
    Then Qdrant 搜索使用 limit 等于 5
    And 返回 VectorSearchResult.hits 长度等于 5
    And hits 按 score 降序排列

  # ==== 异常路径：query 失败模式 ====

  Scenario Outline: 空 query 或全空白 query 直接返回空，不触发任何下游
    When 调用 search_dense_chunks 传入 空白 query 标识 "<query_token>" user_id 10002 set_id 10003
    Then 返回 VectorSearchResult.hits 为空
    And 不调用 ChunkEmbeddingPipeline.aembed_query
    And 不调用 Qdrant 客户端

    Examples:
      | query_token |
      | EMPTY       |
      | SPACES      |
      | TAB         |
      | NEWLINE     |
      | MIXED_WS    |

  # ==== 异常路径：参数值越界 ====
  # dense 比 sparse 多一组：score_threshold > 1.0（cosine 上界）

  Scenario Outline: user_id / set_id / top_k / score_threshold 越界时抛 ValueError
    When 调用 search_dense_chunks 传入越界参数 user_id <user_id> set_id <set_id> top_k <top_k> score_threshold <score_threshold>
    Then 抛出 ValueError
    And 不调用 ChunkEmbeddingPipeline.aembed_query
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
      | 10002   | 10003  | NONE  | 1.5             |

  Scenario Outline: bool 子类被识别为非整数参数（user_id / set_id）
    When 调用 search_dense_chunks 传入 bool user_id <user_id> set_id <set_id>
    Then 抛出 ValueError
    And 不调用 ChunkEmbeddingPipeline.aembed_query
    And 不调用 Qdrant 客户端

    Examples:
      | user_id | set_id |
      | True    | 10003  |
      | 10002   | False  |

  # ==== 异常路径：配置失败 ====

  Scenario: embedding_pipeline 未注入时抛 VectorRetrievalConfigurationError
    Given VectorStorageFacade 构造时 embedding_pipeline 为 None
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 抛出 VectorRetrievalConfigurationError
    And 不调用 Qdrant 客户端

  # ==== Qdrant 端容错 ====

  Scenario: 目标 bucket collection 不存在时返回空 hits
    Given Qdrant 中 user_id 10002 路由到的 bucket collection 不存在
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 返回 VectorSearchResult.hits 为空
    And 不抛任何异常
    And 调用 ChunkEmbeddingPipeline.aembed_query 一次

  Scenario: system embedding 推理失败传播为 VectorRetrievalEncodingError
    Given system embedding HTTP 客户端对任意输入抛 httpx.HTTPStatusError
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 抛出 VectorRetrievalEncodingError
    And 不调用 Qdrant 客户端

  Scenario: Qdrant 客户端故障传播为 VectorRetrievalBackendError
    Given Qdrant 客户端对搜索请求抛底层网络异常
    When 调用 search_dense_chunks 传入 query "任意" user_id 10002 set_id 10003
    Then 抛出 VectorRetrievalBackendError

  # ==== 只读语义 ====

  Scenario: 同一 query 多次调用结果稳定且不写状态
    Given Qdrant 中 user_id=10002 的 chunk 状态为已 INDEXED
    When 连续调用 search_dense_chunks 两次 query "任意" user_id 10002 set_id 10003
    Then 两次返回 hits 中 chunk_id 集合相同
    And 两次调用过程中不发生 Qdrant 写操作

  # ==== 对外暴露面 ====

  Scenario: 调用方只通过 vector_storage 包接触召回 API
    Then 从 vector_storage 包可以导入 VectorStorageFacade
    And 从 vector_storage 包可以导入 VectorSearchHit, VectorSearchResult
    And 从 vector_storage 包可以导入召回侧异常族
    And DenseVectorSearchRequest 不在 vector_storage 包的 __all__ 中
    And DenseQueryVectorSpec 不在 vector_storage 包的 __all__ 中
    And VectorRetrieval 异常族继承关系正确

  # ==== ChunkEmbeddingPipeline.aembed_query 入口契约 ====

  Scenario: aembed_query 调用参数与写入路径完全一致
    When 直接调用 ChunkEmbeddingPipeline.aembed_query 传入 query "原始 query"
    Then 底层 embedder.embed 被调用一次
    And embedder.embed 入参 texts 等于 "原始 query"
    And embedder.embed 入参 model 等于 settings.SYSTEM_LLM_MODEL_EMBEDDING
    And aembed_query 不写入 embedding_cache
    And aembed_query 不更新 last_stats

  Scenario Outline: aembed_query 收到空或全空白 query 时抛 ValueError
    When 直接调用 ChunkEmbeddingPipeline.aembed_query 传入 空白 query 标识 "<token>"
    Then 直接调用 aembed_query 抛出 ValueError
    And 不调用底层 embedder

    Examples:
      | token   |
      | EMPTY   |
      | SPACES  |
      | TAB_NL  |

  # ==== DenseRetriever 适配器（接入多路召回 pipeline）====

  Scenario: DenseRetriever 暴露 source 常量
    Then DenseRetriever.source 等于 "dense"
    And DenseRetriever.source 等同于 SOURCE_DENSE

  Scenario: DenseRetriever 把 pipeline 协议形状翻译为 facade 散参并返回 RetrieverHit
    Given DenseRetriever 已用 score_threshold 0.0 装配
    And facade 返回 hit chunk_id "c1" doc_id 42 set_id 10003 score 0.85 vector_kind "dense"
    When 调用 retriever.recall 传入 query "q" dataset_ids "10003" doc_ids 空 user_id 10002 top_k 20
    Then facade.search_dense_chunks 被调用一次
    And facade.search_dense_chunks 入参 query 等于 "q"
    And facade.search_dense_chunks 入参 user_id 等于 10002
    And facade.search_dense_chunks 入参 set_id 等于 10003
    And facade.search_dense_chunks 入参 top_k 等于 20
    And facade.search_dense_chunks 入参 score_threshold 等于 0.0
    And facade.search_dense_chunks 入参 doc_id 为 None
    And 返回 list[RetrieverHit] 长度等于 1
    And 返回 list[RetrieverHit][0] chunk_id 等于 "c1"
    And 返回 list[RetrieverHit][0] doc_id 等于 42
    And 返回 list[RetrieverHit][0] dataset_id 等于 10003
    And 返回 list[RetrieverHit][0] score 等于 0.85
    And 返回 list[RetrieverHit][0] source 等于 "dense"

  Scenario: DenseRetriever 多 dataset_ids 时逐个下发并合并
    Given DenseRetriever 装配
    When 调用 retriever.recall 传入 query "q" dataset_ids "10003,10004,10005" user_id 10002 top_k 10
    Then facade.search_dense_chunks 被调用次数等于 3
    And facade.search_dense_chunks 调用 set_id 顺序等于 "10003,10004,10005"
    And 返回 list[RetrieverHit] 按 score 降序
    And 返回 list[RetrieverHit] 长度不超过 10

  Scenario: DenseRetriever 收到空 dataset_ids 直接返空
    Given DenseRetriever 装配
    When 调用 retriever.recall 传入 query "q" dataset_ids 空 user_id 10002 top_k 10
    Then 返回 list[RetrieverHit] 等于 空列表
    And 不调用 facade.search_dense_chunks

  Scenario Outline: DenseRetriever 入参越界抛 ValueError
    Given DenseRetriever 装配
    When 调用 retriever.recall 传入越界参数 user_id <user_id> top_k <top_k>
    Then 抛出 ValueError

    Examples:
      | user_id | top_k |
      | 0       | 10    |
      | -1      | 10    |
      | 10002   | 0     |
      | 10002   | -1    |

  Scenario: DenseRetriever 装配期 score_threshold 负值抛 ValueError
    When 用 score_threshold -0.1 装配 DenseRetriever
    Then 抛出 ValueError

  # ==== 召回 pipeline provider 注册（dense 自动接入 SSE API）====

  Scenario: provider 装配在 RECALL_ENABLED_SOURCES 含 dense 时构造 DenseRetriever
    Given 配置 RECALL_ENABLED_SOURCES 等于 "bm25,sparse,dense"
    Then provider 的 _BUILDERS 含键 "dense"
    And provider 的 _BUILDERS 键集合等于 "bm25,sparse,dense"

  Scenario: provider 在 RECALL_ENABLED_SOURCES 含未知 source 时拒绝启动
    Given 配置 RECALL_ENABLED_SOURCES 等于 "bm25,sparse,dense,unknown_source"
    When 调用 provider 内部 lookup 入参 unknown_source
    Then provider 内部返回 None 表示未注册
