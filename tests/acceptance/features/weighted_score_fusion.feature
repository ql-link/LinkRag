# 固定 weighted score 融合 acceptance 契约（LINK-203 / GitHub #258）
# 范围：BM25 / sparse / dense 三路召回固定以归一化分数和权重融合，不再暴露 RRF 策略开关。

Feature: 固定 weighted score 召回融合
  作为 RAG 后端开发者
  我希望召回 pipeline 只有一套经过评测冻结的融合规则
  以避免数据集配置切回未验收的旧排序口径

  Background:
    Given 服务端支持召回源 "bm25"、"sparse"、"dense"
    And 系统默认 RECALL_FUSION_BM25_WEIGHT 为 0.2
    And 系统默认 RECALL_FUSION_SPARSE_WEIGHT 为 0.3
    And 系统默认 RECALL_FUSION_DENSE_WEIGHT 为 0.5
    And RecallHit 输出字段为 chunk_id、doc_id、dataset_id、fused_score、scores

  Scenario: 三路正常命中时按 log1p、min-max 与默认权重融合
    Given fusion 权重配置为 bm25=0.2 sparse=0.3 dense=0.5
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

  Scenario: 某一路无命中时仅按 active source 权重归一
    Given fusion 权重配置为 bm25=0.2 sparse=0.3 dense=0.5
    And bm25 路按顺序返回 chunk "cA" score 7.0
    And sparse 路返回 0 命中
    And dense 路按顺序返回 chunk "cB" score 0.9
    When 执行 RecallPipeline
    Then active sources 为 "bm25,dense"
    And hit "cA" 的 fused_score 等于 0.2/0.7
    And hit "cB" 的 fused_score 等于 0.5/0.7
    And hit "cA" 的 scores.sparse 等于 null

  Scenario: active source 权重和为 0 时拒绝融合
    Given fusion 权重配置为 bm25=0.0 sparse=0.0 dense=0.0
    And bm25 路按顺序返回 chunk "cA" score 100.0
    When 执行 RecallPipeline
    Then 本次融合失败并报告 active source 权重和必须大于 0
    And 不返回使用修正后分数的 hit

  Scenario: settings 默认权重映射到 RecallPipelineConfig
    Given Settings 中 RECALL_FUSION_BM25_WEIGHT=0.2
    And Settings 中 RECALL_FUSION_SPARSE_WEIGHT=0.3
    And Settings 中 RECALL_FUSION_DENSE_WEIGHT=0.5
    When 装配 RecallPipeline 单例
    Then RecallPipelineConfig.fusion_bm25_weight 等于 0.2
    And RecallPipelineConfig.fusion_sparse_weight 等于 0.3
    And RecallPipelineConfig.fusion_dense_weight 等于 0.5

  Scenario: dataset recall_config 只覆盖三路权重
    Given dataset_parse_config.recall_config 包含:
      | key                  | value |
      | fusion_bm25_weight   | 0.1   |
      | fusion_sparse_weight | 0.2   |
      | fusion_dense_weight  | 0.7   |
    When RAG 流或纯召回 JSON 入口解析该数据集配置
    Then 构造的 RecallRequest.fusion_bm25_weight_override 等于 0.1
    And 构造的 RecallRequest.fusion_sparse_weight_override 等于 0.2
    And 构造的 RecallRequest.fusion_dense_weight_override 等于 0.7

  Scenario Outline: HTTP 请求体不接受融合内部字段
    Given session token claims sub=123 dataset_ids=[1] 合法未过期
    When 前端调用 POST /api/v1/recall 或 POST /api/v1/rag/stream body 额外包含字段 "<field>"
    Then HTTP 响应状态为 422
    And 响应体 code 等于 "RECALL_INVALID_REQUEST"
    And 不调用 RecallPipeline

    Examples:
      | field                  |
      | fusion_strategy        |
      | fusion_weights         |
      | recall_fusion_strategy |
      | rrf_k                  |
      | fusion_bm25_weight     |
      | fusion_sparse_weight   |
      | fusion_dense_weight    |

  Scenario: rerank 不可用时按固定融合顺序降级
    Given weighted_score 融合后 hits 顺序为 "cDense,cSparse,cBm25"
    And Dataset 精确 RERANK config_id 在执行期不可用
    When RAG 流进入 rerank 阶段
    Then 终态事件 data 的 rerank_applied 为 false
    And 终态事件 data 中 hits 顺序为 "cDense,cSparse,cBm25"
    And hits 中每个 hit 的 rerank_score 与 rerank_rank 为 null
