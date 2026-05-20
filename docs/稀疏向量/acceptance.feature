Feature: BGE-M3 稀疏向量入库
  作为文档解析后处理链路
  我希望在向量索引阶段为每个 chunk 生成并写入 BGE-M3 稀疏向量
  以便后续检索可以基于同一 chunk_id 使用可恢复、可验证的稀疏向量资产

  Background:
    Given 文档 D1 已完成解析并生成 3 个非空 chunk
    And chunk 顺序为 C1, C2, C3
    And 每个 chunk 都已有 user_id, set_id, doc_id 和 chunk_id
    And 稠密向量模型保持现有配置
    And ES 分词结果不可作为稀疏向量输入

  # ==== 主流程 ====

  Scenario: 默认开启稀疏向量后整份文档向量阶段成功
    Given 稀疏向量功能开关为默认开启
    And BGE-M3 对 C1, C2, C3 均返回非空 sparse vector
    And 稠密向量对 C1, C2, C3 均生成成功
    When 系统执行 D1 的向量索引阶段
    Then C1.dense_vector_status == INDEXED
    And C2.dense_vector_status == INDEXED
    And C3.dense_vector_status == INDEXED
    And C1.sparse_vector_status == INDEXED
    And C2.sparse_vector_status == INDEXED
    And C3.sparse_vector_status == INDEXED
    And C1.sparse_vector_nonzero_count > 0
    And C2.sparse_vector_nonzero_count > 0
    And C3.sparse_vector_nonzero_count > 0
    And D1.vectorizing_status == SUCCESS

  Scenario: 稀疏向量与稠密向量使用同一个 chunk_id 入库
    Given 稀疏向量功能开关为开启
    And C1 的稠密向量已生成
    And BGE-M3 对 C1 返回非空 sparse vector
    When 系统写入 C1 的向量索引
    Then Qdrant 中 C1 的 dense vector 使用 point_id=C1.chunk_id
    And Qdrant 中 C1 的 sparse vector 使用 point_id=C1.chunk_id
    And C1 的 MySQL 真值记录 chunk_id 不变

  Scenario: 关闭稀疏向量开关时保持旧稠密向量语义
    Given 稀疏向量功能开关为关闭
    And 稠密向量对 C1, C2, C3 均生成成功
    When 系统执行 D1 的向量索引阶段
    Then BGE-M3 不被调用
    And 不写入任何 sparse vector
    And C1.dense_vector_status == INDEXED
    And C2.dense_vector_status == INDEXED
    And C3.dense_vector_status == INDEXED
    And D1.vectorizing_status == SUCCESS

  Scenario: 稀疏向量生成使用 chunk 原文而不是 ES 分词结果
    Given 稀疏向量功能开关为开启
    And C1.content == "合同编号 ABC-2026 的付款条款"
    And ES analyzer 为 C1 产出 token 列表 "合同, 编号, 付款"
    When 系统为 C1 生成稀疏向量
    Then BGE-M3 收到的输入文本 == "合同编号 ABC-2026 的付款条款"
    And BGE-M3 没有收到 ES analyzer token 列表
    And C1.sparse_vector_status == INDEXED

  Scenario: CPU 复用现有 BGE-M3 encoder 以 fp32 进行稀疏向量推理
    Given 稀疏向量功能开关为开启
    And 稀疏向量推理设备配置 == "cpu"
    And 当前运行环境没有可用 CUDA 设备
    And BGE-M3 普通本地模型对 C1 返回非空 sparse vector
    When 系统为 C1 生成稀疏向量
    Then BGE-M3 使用 CPU 推理
    And 系统复用现有 BGEM3SparseVectorEncoder
    And BGE-M3 不启用 fp16
    And BGE-M3 使用 fp32 推理
    And BGE-M3 不占用 CUDA 设备
    And C1.sparse_vector_status == INDEXED
    And C1.sparse_vector_nonzero_count > 0
    And 稀疏向量推理设备配置接口允许将设备切换为 "cuda"

  # ==== 异常处理 ====

  Scenario: 当前 chunk 的稀疏向量模型调用失败会阻断文件级向量成功
    Given 稀疏向量功能开关为开启
    And C1 的 dense 和 sparse 均已成功
    And C2 的稠密向量生成成功
    When BGE-M3 为 C2 生成稀疏向量时抛出模型异常
    Then C1.dense_vector_status == INDEXED
    And C1.sparse_vector_status == INDEXED
    And C2.dense_vector_status == FAILED
    And C2.sparse_vector_status == FAILED
    And C2.sparse_vector_error_msg 包含 "SPARSE_MODEL_EXCEPTION"
    And C3.dense_vector_status == PENDING
    And C3.sparse_vector_status == PENDING
    And D1.vectorizing_status == FAILED
    And D1.failed_chunk_ids == [C2.chunk_id]

  Scenario: 稀疏向量 Qdrant 写入失败会阻断当前 chunk 成功
    Given 稀疏向量功能开关为开启
    And C1 的稠密向量写入 Qdrant 成功
    And BGE-M3 对 C1 返回非空 sparse vector
    When Qdrant 写入 C1 sparse vector 失败
    Then C1.dense_vector_status == FAILED
    And C1.sparse_vector_status == FAILED
    And C1.sparse_vector_error_msg 包含 "SPARSE_QDRANT_UPSERT_FAILED"
    And D1.vectorizing_status == FAILED
    And 系统记录 C1 的稀疏向量失败状态
    And 稀疏向量阶段不声明任何 ES 入库行为

  Scenario Outline: 非空 chunk 生成空 sparse vector 必须失败并记录原因
    Given 稀疏向量功能开关为开启
    And C1.content == "合同编号 ABC-2026 的付款条款"
    When BGE-M3 对 C1 的 sparse 输出为空且原因是 <reason>
    Then C1.sparse_vector_status == FAILED
    And C1.sparse_vector_error_msg 包含 <reason>
    And C1.sparse_vector_nonzero_count == null
    And D1.vectorizing_status == FAILED

    Examples:
      | reason                              |
      | SPARSE_MODEL_OUTPUT_MISSING          |
      | SPARSE_MODEL_OUTPUT_COUNT_MISMATCH    |
      | SPARSE_MODEL_RETURNED_EMPTY           |
      | SPARSE_FILTERED_TO_EMPTY              |
      | SPARSE_VECTOR_VALUE_INVALID           |
      | SPARSE_VECTOR_CONVERSION_FAILED       |

  Scenario: 稀疏向量输出数量与 chunk 数量不一致时整批失败
    Given 稀疏向量功能开关为开启
    And 系统一次请求 BGE-M3 处理 C1, C2, C3
    When BGE-M3 只返回 2 个 sparse 输出
    Then C1.sparse_vector_status == FAILED
    And C2.sparse_vector_status == FAILED
    And C3.sparse_vector_status == FAILED
    And 每个失败原因都包含 "SPARSE_MODEL_OUTPUT_COUNT_MISMATCH"
    And D1.vectorizing_status == FAILED

  Scenario: 稠密向量失败时不会把稀疏向量单独判定为文件成功
    Given 稀疏向量功能开关为开启
    And BGE-M3 对 C1 返回非空 sparse vector
    When C1 的稠密向量生成失败
    Then C1.dense_vector_status == FAILED
    And D1.vectorizing_status == FAILED
    And 文件级成功不只依据 C1.sparse_vector_status

  # ==== 幂等与重试 ====

  Scenario: 重试从失败 chunk 继续且跳过已完成 chunk
    Given 稀疏向量功能开关为开启
    And C1.dense_vector_status == INDEXED
    And C1.sparse_vector_status == INDEXED
    And C2.dense_vector_status == FAILED
    And C2.sparse_vector_status == FAILED
    And C3.dense_vector_status == PENDING
    When 系统重试 D1 的向量索引阶段
    Then C1 不重新调用稠密向量模型
    And C1 不重新调用 BGE-M3
    And 系统从 C2 开始继续处理
    And C2.sparse_vector_status == INDEXED
    And C3.sparse_vector_status == INDEXED
    And D1.vectorizing_status == SUCCESS

  Scenario: 重复执行同一 chunk 写入不会生成重复索引
    Given 稀疏向量功能开关为开启
    And C1 已经写入 dense vector 和 sparse vector
    When 系统再次处理 C1 且 BGE-M3 返回新的非空 sparse vector
    Then Qdrant 中 C1 仍只有一个 point_id=C1.chunk_id
    And C1 的 sparse vector 被覆盖为新结果
    And C1.sparse_vector_status == INDEXED
    And C1.sparse_vector_nonzero_count > 0

  Scenario: 状态回写被并发删除抢先时不能报告当前 chunk 成功
    Given 稀疏向量功能开关为开启
    And C1 的 dense vector 和 sparse vector 已写入 Qdrant
    And C1 在状态回写前被标记为 DELETING
    When 系统尝试完成 C1 的向量状态回写
    Then C1.dense_vector_status != INDEXED
    And C1.sparse_vector_status != INDEXED
    And D1.vectorizing_status == FAILED
    And C1 不会作为可检索成功资产返回

  # ==== 边界条件与非目标 ====

  Scenario: 首期不暴露稀疏检索或混合检索入口
    Given 稀疏向量功能已完成入库能力
    When 调用方查看本期对外能力
    Then 不存在 sparse 检索 API
    And 不存在 hybrid 检索 API
    And 不存在用户可见的 sparse 检索开关
    And 不存在用户可见的 hybrid 检索开关

  Scenario: 未来稀疏检索候选必须经过 MySQL 状态回查
    Given Qdrant sparse 检索召回候选 C1, C2, C3
    And C1.dense_vector_status == INDEXED
    And C1.sparse_vector_status == INDEXED
    And C2.dense_vector_status == INDEXED
    And C2.sparse_vector_status == FAILED
    And C3.dense_vector_status == DELETED
    When 检索链路按 chunk_id 回查 MySQL 状态
    Then 返回候选只包含 C1
    And 返回候选不包含 C2
    And 返回候选不包含 C3

  Scenario: SPLADE 不进入首期运行时开发流程
    Given 稀疏向量功能开关为开启
    When 系统执行 D1 的稀疏向量阶段
    Then 稀疏向量模型为 BGE-M3
    And 不加载 SPLADE 模型
    And 不写入 SPLADE 模型状态
    And 不生成 SPLADE sparse vector
