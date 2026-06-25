# weighted_score 融合策略 acceptance 契约（LINK-203 / GitHub #258）
# 范围：召回 pipeline 在 RRF 之外新增 weighted_score 可选融合策略。
# 约束：默认仍为 RRF；weighted_score 只发生在 BM25/sparse/dense 三路召回后、rerank 前；
#       HTTP 请求体不开放 fusion_strategy / fusion_weights；对外 hit 结构保持兼容。

Feature: weighted_score 召回融合策略
  作为 RAG 后端开发者
  我希望召回 pipeline 支持可配置的 weighted_score 融合策略
  以便在保留默认 RRF 行为的同时，按三路归一化分数和权重融合候选

  Background:
    Given 服务端支持召回源 "bm25"、"sparse"、"dense"
    And 系统默认 RECALL_FUSION_STRATEGY 为 "rrf"
    And 系统默认 RECALL_FUSION_BM25_WEIGHT 为 0.2
    And 系统默认 RECALL_FUSION_SPARSE_WEIGHT 为 0.3
    And 系统默认 RECALL_FUSION_DENSE_WEIGHT 为 0.5
    And RecallHit 输出字段为 chunk_id、doc_id、dataset_id、fused_score、scores

  # ==== 默认兼容：RRF 行为不变 ====

  Scenario: 未显式配置融合策略时仍按 RRF 计算
    Given bm25 路按顺序返回 chunk "c1" score 9.0
    And sparse 路按顺序返回 chunk "c1" score 0.8
    And dense 路返回 0 命中
    When 执行 RecallPipeline 且未设置 fusion_strategy 覆盖
    Then 返回 hit "c1" 的 fused_score 等于 2/61
    And 返回 hit "c1" 的 scores.bm25 等于 9.0
    And 返回 hit "c1" 的 scores.sparse 等于 0.8
    And 返回 hit "c1" 的 scores.dense 等于 null

  Scenario: 显式配置 rrf 时忽略 weighted_score 权重
    Given fusion_strategy 配置为 "rrf"
    And fusion 权重配置为 bm25=0.0 sparse=0.0 dense=1.0
    And bm25 路按顺序返回 chunk "c1" score 10.0
    And dense 路按顺序返回 chunk "c2" score 0.9
    When 执行 RecallPipeline
    Then 返回 hit "c1" 的 fused_score 等于 1/61
    And 返回 hit "c2" 的 fused_score 等于 1/61
    And 返回 hits 按 RRF 分数排序而不是按 dense 权重排序

  # ==== weighted_score 主流程 ====

  Scenario: 三路正常命中时按 log1p、min-max 与默认权重融合
    Given fusion_strategy 配置为 "weighted_score"
    And fusion 权重配置为 bm25=0.2 sparse=0.3 dense=0.5
    And bm25 路按顺序返回:
      | chunk_id | score |
      | cA       | 100.0 |
      | cB       | 0.0   |
    And sparse 路按顺序返回:
      | chunk_id | score |
      | cB       | 9.0   |
      | cC       | 0.0   |
    And dense 路按顺序返回:
      | chunk_id | score |
      | cC       | 0.9   |
      | cA       | 0.4   |
    When 执行 RecallPipeline
    Then hit "cA" 的 fused_score 等于 0.2
    And hit "cB" 的 fused_score 等于 0.3
    And hit "cC" 的 fused_score 等于 0.5
    And hits 顺序为 "cC,cB,cA"

  Scenario: weighted_score 输出保留各路原始 score 而不输出 normalized score
    Given fusion_strategy 配置为 "weighted_score"
    And bm25 路返回 chunk "c1" score 100.0
    And sparse 路返回 chunk "c1" score 9.0
    And dense 路返回 chunk "c1" score 0.7
    When 执行 RecallPipeline
    Then 返回 hit "c1" 的 scores.bm25 等于 100.0
    And 返回 hit "c1" 的 scores.sparse 等于 9.0
    And 返回 hit "c1" 的 scores.dense 等于 0.7
    And 返回 hit "c1" 不含 normalized_scores 字段

  Scenario: 某一路无命中时仅按 active source 权重归一
    Given fusion_strategy 配置为 "weighted_score"
    And fusion 权重配置为 bm25=0.2 sparse=0.3 dense=0.5
    And bm25 路按顺序返回 chunk "cA" score 7.0
    And sparse 路返回 0 命中
    And dense 路按顺序返回 chunk "cB" score 0.9
    When 执行 RecallPipeline
    Then active sources 为 "bm25,dense"
    And hit "cA" 的 fused_score 等于 0.2/0.7
    And hit "cB" 的 fused_score 等于 0.5/0.7
    And hit "cA" 的 scores.sparse 等于 null

  Scenario: chunk 未命中某一路时该路贡献为 0 且不按 chunk 命中路重分配
    Given fusion_strategy 配置为 "weighted_score"
    And fusion 权重配置为 bm25=0.2 sparse=0.3 dense=0.5
    And bm25 路按顺序返回 chunk "cA" score 10.0
    And sparse 路按顺序返回 chunk "cB" score 8.0
    And dense 路按顺序返回 chunk "cC" score 0.9
    When 执行 RecallPipeline
    Then hit "cA" 的 fused_score 等于 0.2
    And hit "cB" 的 fused_score 等于 0.3
    And hit "cC" 的 fused_score 等于 0.5
    And 不把缺失 source 的权重重新分配给单个 chunk 已命中的 source

  # ==== 归一化边界 ====

  Scenario Outline: 单命中 source 的 normalized score 等于 1.0
    Given fusion_strategy 配置为 "weighted_score"
    And 只启用召回源 "<source>"
    And <source> 路按顺序返回 chunk "c1" score <score>
    When 执行 RecallPipeline
    Then hit "c1" 的 fused_score 等于 1.0

    Examples:
      | source | score |
      | bm25   | 12.0  |
      | sparse | 5.0   |
      | dense  | 0.8   |

  Scenario Outline: 同一路所有 transformed score 相等时该路命中项 normalized score 都等于 1.0
    Given fusion_strategy 配置为 "weighted_score"
    And 只启用召回源 "<source>"
    And <source> 路按顺序返回:
      | chunk_id | score |
      | c1       | <score> |
      | c2       | <score> |
    When 执行 RecallPipeline
    Then hit "c1" 的 fused_score 等于 1.0
    And hit "c2" 的 fused_score 等于 1.0

    Examples:
      | source | score |
      | bm25   | 3.0   |
      | sparse | 2.0   |
      | dense  | 0.6   |

  Scenario: 极端 BM25 与 sparse 分数先经过 log1p 再做 min-max
    Given fusion_strategy 配置为 "weighted_score"
    And 只启用召回源 "bm25"
    And bm25 路按顺序返回:
      | chunk_id | score       |
      | cHigh    | 1000000000.0 |
      | cLow     | 0.0         |
    When 执行 RecallPipeline
    Then hit "cHigh" 的 fused_score 等于 1.0
    And hit "cLow" 的 fused_score 等于 0.0
    And 融合计算未因极端 BM25 分数溢出

  Scenario: BM25 或 sparse 出现非法负 raw score 时融合失败而不静默修正
    Given fusion_strategy 配置为 "weighted_score"
    And bm25 路按顺序返回 chunk "cBad" score -2.0
    When 执行 RecallPipeline
    Then 本次融合失败并报告配置或数据异常
    And 不返回使用修正后分数的 hit

  # ==== 权重与配置边界 ====

  Scenario: 部分 active source 权重为 0 且 active 权重和大于 0 时融合成功
    Given fusion_strategy 配置为 "weighted_score"
    And fusion 权重配置为 bm25=0.0 sparse=0.0 dense=1.0
    And bm25 路按顺序返回 chunk "cA" score 100.0
    And dense 路按顺序返回 chunk "cB" score 0.9
    When 执行 RecallPipeline
    Then 本次融合成功
    And hit "cA" 的 fused_score 等于 0.0
    And hit "cA" 的 scores.bm25 等于 100.0
    And hit "cB" 的 fused_score 等于 1.0

  Scenario: active source 权重和为 0 时拒绝本次 weighted_score 融合
    Given fusion_strategy 配置为 "weighted_score"
    And fusion 权重配置为 bm25=0.0 sparse=0.0 dense=0.0
    And bm25 路按顺序返回 chunk "cA" score 100.0
    When 执行 RecallPipeline
    Then 本次融合失败并报告 active source 权重和必须大于 0
    And 不静默回退到 RRF

  Scenario Outline: 非法融合配置在配置解析阶段被拒绝
    Given 配置项 "<field>" 的值为 "<value>"
    When 加载 Settings 或 dataset recall_config
    Then 配置解析失败
    And 错误信息包含 "<field>"

    Examples:
      | field                         | value          |
      | RECALL_FUSION_STRATEGY        | unknown        |
      | RECALL_FUSION_BM25_WEIGHT     | -0.1           |
      | RECALL_FUSION_SPARSE_WEIGHT   | NaN            |
      | RECALL_FUSION_DENSE_WEIGHT    | Infinity       |

  Scenario: settings 默认融合配置映射到 RecallPipelineConfig
    Given Settings 中 RECALL_FUSION_STRATEGY="weighted_score"
    And Settings 中 RECALL_FUSION_BM25_WEIGHT=0.2
    And Settings 中 RECALL_FUSION_SPARSE_WEIGHT=0.3
    And Settings 中 RECALL_FUSION_DENSE_WEIGHT=0.5
    When 装配 RecallPipeline 单例
    Then RecallPipelineConfig.fusion_strategy 等于 "weighted_score"
    And RecallPipelineConfig.fusion_bm25_weight 等于 0.2
    And RecallPipelineConfig.fusion_sparse_weight 等于 0.3
    And RecallPipelineConfig.fusion_dense_weight 等于 0.5

  Scenario: dataset recall_config 覆盖融合策略与三路权重
    Given Settings 默认 RECALL_FUSION_STRATEGY="rrf"
    And dataset_parse_config.recall_config 包含:
      | key                    | value          |
      | recall_fusion_strategy | weighted_score |
      | fusion_bm25_weight     | 0.1            |
      | fusion_sparse_weight   | 0.2            |
      | fusion_dense_weight    | 0.7            |
    When RAG 流或纯召回 JSON 入口解析该数据集配置
    Then 构造的 RecallRequest.fusion_strategy_override 等于 "weighted_score"
    And 构造的 RecallRequest.fusion_bm25_weight_override 等于 0.1
    And 构造的 RecallRequest.fusion_sparse_weight_override 等于 0.2
    And 构造的 RecallRequest.fusion_dense_weight_override 等于 0.7

  Scenario Outline: HTTP 请求体不接受 fusion 策略或权重字段
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端调用 POST /api/v1/recall 或 POST /api/v1/rag/stream body 额外包含字段 "<field>"
    Then HTTP 响应状态为 422
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"
    And 不调用 RecallPipeline

    Examples:
      | field                 |
      | fusion_strategy       |
      | fusion_weights        |
      | recall_fusion_strategy |
      | fusion_bm25_weight    |
      | fusion_sparse_weight  |
      | fusion_dense_weight   |

  # ==== source 收窄、截断与稳定排序 ====

  Scenario: 只启用部分 source 时只按启用且 active 的 source 权重归一
    Given fusion_strategy 配置为 "weighted_score"
    And fusion 权重配置为 bm25=0.2 sparse=0.3 dense=0.5
    And 本次 enabled_sources 为 "sparse,dense"
    And bm25 路配置存在但本次不启用
    And sparse 路按顺序返回 chunk "cS" score 5.0
    And dense 路按顺序返回 chunk "cD" score 0.9
    When 执行 RecallPipeline
    Then 不调用 bm25 路
    And hit "cS" 的 fused_score 等于 0.3/0.8
    And hit "cD" 的 fused_score 等于 0.5/0.8
    And hit 的 scores 键集合等于 "sparse,dense"

  Scenario: weighted_score 融合后仍按 RecallRequest.top_k 截断
    Given fusion_strategy 配置为 "weighted_score"
    And RecallRequest.top_k 等于 2
    And dense 路按顺序返回:
      | chunk_id | score |
      | c3       | 0.9   |
      | c2       | 0.8   |
      | c1       | 0.7   |
    When 执行 RecallPipeline
    Then 返回 hits 数量等于 2
    And 返回 hits 顺序为 "c3,c2"

  Scenario: fused_score 完全相同时按 chunk_id 升序稳定排序
    Given fusion_strategy 配置为 "weighted_score"
    And 只启用召回源 "dense"
    And dense 路按顺序返回:
      | chunk_id | score |
      | cB       | 0.8   |
      | cA       | 0.8   |
    When 执行 RecallPipeline
    Then hit "cA" 的 fused_score 等于 hit "cB" 的 fused_score
    And 返回 hits 顺序为 "cA,cB"

  # ==== rerank 链路消费融合结果 ====

  Scenario: rerank 生效时消费 weighted_score 融合后的 RecallHit
    Given fusion_strategy 配置为 "weighted_score"
    And weighted_score 融合后 hits 顺序为 "cDense,cSparse,cBm25"
    And 用户已配置可用 RERANK 模型
    When RAG 流进入 rerank 阶段
    Then RerankRequest.hits 顺序为 "cDense,cSparse,cBm25"
    And RerankRequest.hits 中每个 hit 保留 fused_score 与 scores
    And rerank_score 不参与 weighted_score 融合计算

  Scenario: rerank 不可用时按当前融合策略顺序降级
    Given fusion_strategy 配置为 "weighted_score"
    And weighted_score 融合后 hits 顺序为 "cDense,cSparse,cBm25"
    And 用户未配置 RERANK 模型
    When RAG 流进入 rerank 阶段
    Then 终态事件 data 的 rerank_applied 为 false
    And 终态事件 data 中 hits 顺序为 "cDense,cSparse,cBm25"
    And hits 中每个 hit 的 rerank_score 与 rerank_rank 为 null
