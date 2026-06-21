# language: zh-CN
# 状态：草稿（待评审冻结）。创建日期：2026-06-18。
# 来源：基于已冻结 .specs/splitter-enhancement-stage2-texttilling/brief.md 生成。
功能: Splitter Stage 2 语义细分算法 semantic_depth_window
  在不破坏 protected 实体、不退回字符串硬切的前提下，对超过 token 软上限的 mixed coarse chunk
  做基于 element_views 的语义细分：token 决定是否切与切几刀，cohesion depth valley 决定切在哪。
  算法是现状 noop 的安全超集，最终仍由 ChunkExporter 导出 list[Chunk]。

  背景:
    假如 Stage 1 candidate_boundary 已产出含 element_views 的 CoarseChunkSet
    并且 max_chunk_tokens 为 512
    并且 hard_max_tokens 为 1024
    并且 Stage 2 算法为 "semantic_depth_window"

  # ==== 配置与注册 ====

  场景: 注册新算法并保持默认安全
    那么 "semantic_depth_window" 在 SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS 注册集合内
    并且 CHUNKING_STAGE_TWO_ALGORITHM 的默认值仍为 "noop"
    当 CHUNKING_STAGE_TWO_ALGORITHM 配置为 "semantic_depth_window"
    那么 StageTwoRouter 选中 semantic_depth_window 而非 noop

  场景大纲: token 阈值配置区间校验
    当 加载配置 <field> = <value>
    那么 配置加载结果为 <result>

    例子:
      | field                     | value | result        |
      | CHUNKING_MAX_CHUNK_TOKENS | 512   | 接受          |
      | CHUNKING_MAX_CHUNK_TOKENS | 256   | 接受          |
      | CHUNKING_MAX_CHUNK_TOKENS | 2048  | 接受          |
      | CHUNKING_MAX_CHUNK_TOKENS | 255   | 拒绝并区间报错 |
      | CHUNKING_MAX_CHUNK_TOKENS | 2049  | 拒绝并区间报错 |
      | CHUNKING_HARD_MAX_TOKENS  | 1024  | 接受          |
      | CHUNKING_HARD_MAX_TOKENS  | 511   | 拒绝并区间报错 |
      | CHUNKING_HARD_MAX_TOKENS  | 8193  | 拒绝并区间报错 |

  场景: token 阈值跨字段约束
    假如 CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS 为 256
    当 CHUNKING_MAX_CHUNK_TOKENS 配置为小于 256 的值
    那么 配置加载拒绝并返回跨字段校验错误
    当 CHUNKING_HARD_MAX_TOKENS 配置为小于 CHUNKING_MAX_CHUNK_TOKENS 的值
    那么 配置加载拒绝并返回跨字段校验错误

  # ==== 门控（noop 安全超集）====

  场景: derived 元素透传
    假如 一个 role 为 "derived_element" 的 coarse chunk
    当 semantic_depth_window 运行
    那么 它被等价转换为单个 FinalChunk
    并且 该 chunk 不参与 atom timeline 或 cohesion 评分
    并且 其 source_coarse_chunk_id 被保留

  场景: 未超限 mixed 块透传且不触发 embedding
    假如 一个 role 为 "mixed" 且 token_count 为 400 的 coarse chunk
    当 semantic_depth_window 运行
    那么 它被输出为单个 FinalChunk
    并且 不进行 atomization
    并且 不调用 embedder
    并且 该 FinalChunk 的输出与 noop 算法的输出等价

  场景: 超限 mixed 块进入完整算法
    假如 一个 role 为 "mixed" 且 token_count 为 900 的 coarse chunk
    当 semantic_depth_window 运行
    那么 它基于 element_views 构造内部 atom timeline
    并且 至少产出 2 个 FinalChunk
    并且 不对 CoarseChunk.content 字符串做任意位置切分

  # ==== atom 构造与长文本 fallback ====

  场景大纲: 普通长文本按结构优先降级
    假如 一个普通文本元素的 token 数为 <tokens>
    当 atom 构造执行
    那么 该元素被降级为 <granularity> 粒度的 atom
    并且 每个产出 atom 的 token 数不超过 512

    例子:
      | tokens | granularity                |
      | 480    | paragraph（整段保留）       |
      | 700    | line（按行）                |
      | 700    | sentence（行仍超时按句）     |
      | 700    | token-safe（句仍超时兜底）   |

  场景: atom 的 display_text 可无损还原
    假如 一个超限 mixed 块进入 atom 构造
    那么 每个 atom 记录指向 CoarseChunk.content 的 content span
    并且 atom 的 display_text 等于 CoarseChunk.content 对应 span 的精确切片
    并且 候选边界只在相邻 atom 之间的 gap 上评估
    并且 min_chunk_tokens 不用于 atomization

  # ==== protected 实体 ====

  场景: 含 protected 的块不整体透传且 protected 不可内部截断
    假如 一个超限 mixed 块含 1 个 table 与 1 个 code_block
    当 semantic_depth_window 运行
    那么 table 与 code_block 各表示为一个不可拆 Protected_Atom
    并且 不在任何 Protected_Atom 内部产生切分边界
    并且 protected 元素作为 atom 参与分组而非整块透传
    并且 允许在 Protected_Atom 的前后 gap 切分

  场景: 图片与表格的语义评分与无损还原
    假如 一个 image 的 element_view 提供非空 semantic_text
    当 cohesion 计算执行
    那么 该 image atom 以 semantic_text 作为 score_text 参与 cohesion
    并且 该 image atom 的 display_text 由 CoarseChunk.content 对应 span 还原
    并且 该 image atom 的 token 统计基于 display_text 而非 score_text

  场景: semantic_text 缺失时跳过 cohesion
    假如 一个 table 的 element_view 的 semantic_text 为空
    当 cohesion 计算执行
    那么 该 table atom 不参与 cohesion 评分
    并且 该 table atom 仍计入 token 预算
    并且 该 table atom 仍为不可拆 Protected_Atom

  场景: 代码块与公式块不参与语义但计入 token
    假如 一个超限 mixed 块含 code_block 与 math_block
    当 semantic_depth_window 运行
    那么 code_block 与 math_block 不参与 score_text 与 cohesion 计算
    并且 它们的 display_text 全额计入 token 预算
    并且 token 数不超过 512 的 code_block 不被单独输出为无文本的纯保护 FinalChunk

  # ==== depth valley 与切点选择 ====

  场景: token 触发切分并按 depth 选切点
    假如 一个超限 mixed 块存在多个合法 gap
    当 累积 atom 使继续加入下一个 atom 会超过 512 时
    那么 在已累积范围的合法 gap 中选择切点
    并且 优先选择 cohesion depth 边界强度高且不产生明显短碎片的 gap
    并且 gap 两侧 heading_trail 不同不被用作高于语义的分段优先级

  场景: protected 归属按两侧 cohesion 决定
    假如 一个 Protected_Atom 夹在左右两段文本之间且必须在其相邻处切分
    当 归属判定执行
    那么 在该 Protected_Atom 两侧 cohesion 更低的一侧切开
    并且 该 Protected_Atom 留在 cohesion 更高的一侧
    当 两侧 cohesion 近似相等
    那么 该 Protected_Atom 默认归属前一个 segment
    当 该 Protected_Atom 没有 score_text
    那么 它默认归属前一个 segment

  场景: 不产生标题孤儿且 heading_trail 仅用于标注
    假如 一个超限 mixed 块内部含 heading 元素
    当 semantic_depth_window 运行
    那么 不将单个 heading 单独输出为一个 FinalChunk
    并且 heading_trail 仅用于标注输出 FinalChunk 而不驱动分段

  # ==== 三层 token 阈值 ====

  场景: 容忍带内单个 protected 整块保留为 oversized
    假如 一个单独 Protected_Atom 的 display_text token 数为 800
    当 semantic_depth_window 运行
    那么 该实体不被截断
    并且 输出一个 oversized FinalChunk
    并且 该 FinalChunk 的 metadata 含 oversized=true
    并且 该 FinalChunk 的 metadata 含 oversized_reason

  场景: 代码加引导说明超限时整块保留并携带说明
    假如 一个 code_block 与其引导说明文本合计 token 数落在 512 与 1024 之间
    当 semantic_depth_window 运行
    那么 该 code_block 与其引导说明文本被保留在同一 oversized FinalChunk
    并且 该 FinalChunk 的 metadata 含 oversized=true

  场景: 超过硬上限的不可拆 atom 按完整行截断
    假如 一个 code_block 的 display_text token 数为 1500
    当 semantic_depth_window 运行
    那么 该 code_block 在 1024 token 之内的最后一个完整行边界处截断
    并且 不在 token 中途截断
    并且 该 FinalChunk 的 metadata 含 truncated=true
    并且 该 FinalChunk 的 metadata 含 truncated_reason="code_block_over_hard_max"
    并且 该 FinalChunk 的 metadata 记录 original_token_count=1500

  场景: 普通文本不触发硬上限截断
    假如 一个超限 mixed 块仅含普通文本元素
    当 semantic_depth_window 运行
    那么 所有产出 FinalChunk 均不含 truncated=true
    并且 每个产出 FinalChunk 的 token 数不超过 512

  场景: hard_max 是所有 FinalChunk 的绝对上限
    当 semantic_depth_window 产出任意 FinalChunkSet
    那么 任何 FinalChunk 的 token 数都不超过 hard_max_tokens
    并且 oversized FinalChunk 的 token 数落在 max_chunk_tokens 与 hard_max_tokens 之间（含端点）
    并且 任何会超过 hard_max_tokens 的不可拆内容都被截断并标 truncated=true

  # ==== 无损还原 / 锚点 / 校验（P1、P4）====

  场景: 同源 final 无损覆盖原 coarse 内容
    假如 一个超限 mixed 块被切成多个 FinalChunk 且无截断
    当 切分完成
    那么 每个 FinalChunk 的 content 是来源 CoarseChunk.content 的精确切片
    并且 这些 FinalChunk content 按顺序拼接还原该 CoarseChunk.content
    并且 这些 FinalChunk content 之间无字符重叠

  场景: truncated 块豁免无损覆盖断言
    假如 一个超限 mixed 块因含超硬上限 code_block 产生了 truncated FinalChunk
    那么 标记 truncated=true 的 FinalChunk 的 content 是来源不可拆 atom display_text 在完整行边界处的前缀切片
    并且 无损覆盖断言不要求 truncated 块对应的截断尾部

  场景: derived 元素按 element_id 锚点映射到正确 final
    假如 一个含 1 个 table 引用的 mixed coarse 被切成 3 个 FinalChunk
    并且 table 引用落在第 2 个 FinalChunk
    当 ChunkExporter 导出 list[Chunk]
    那么 table 的 derived chunk 的 source_chunk_index 指向第 2 个 FinalChunk
    并且 ChunkExporter 不按 source_coarse_chunk_id 一律指向第一个 FinalChunk

  场景: FinalChunkSet 校验拦截非法输出
    假如 一个 derived chunk 的 element_id 在所有 FinalChunk 中都找不到匹配锚点
    当 FinalChunkSet 校验执行
    那么 校验抛出输出校验错误
    当 同源非 truncated FinalChunk 的 content 并集未完整覆盖来源 coarse content
    那么 校验抛出输出校验错误

  # ==== overlap 隔离与开关（P5）====

  场景: Stage 2 输出不含 neighbor overlap
    当 semantic_depth_window 产出 FinalChunkSet
    那么 base FinalChunk 不含 neighbor overlap
    并且 overlap 不计入 Stage 2 的 token 统计、窗口选择与语义评分

  场景: 含 protected 块的 overlap 由开关控制
    假如 一个 FinalChunk 含 protected element
    并且 CHUNKING_PROTECTED_NEIGHBOR_OVERLAP 为 false
    当 pipeline 后置 overlap 执行
    那么 该 FinalChunk 不被追加 neighbor overlap
    当 CHUNKING_PROTECTED_NEIGHBOR_OVERLAP 为 true
    那么 该 FinalChunk 仅在纯文本边缘被追加 overlap
    并且 overlap 不进入 protected 内部

  # ==== embedder 注入与退化（方案 B）====

  场景: Stage 2 复用与存储一致的 qwen embedder 且懒加载
    假如 factory 装配选中 semantic_depth_window
    那么 切分引擎被注入与 chunk 存储向量化同一套 qwen embedder 实例
    并且 该 embedder 在首次真正调用 embed 前不创建底层客户端
    当 Stage 2 算法为 "noop"
    那么 factory 保持不注入 embedder 的现有装配行为

  场景: Stage 2 embedding 瞬时失败按 part 重试，用尽则上抛
    假如 一个超限 mixed 块的 atom embedding 分多批进行
    并且 其中一批遭遇瞬时错误（超时 / 5xx / 429 / 连接重置）
    当 semantic_depth_window 执行 embedding
    那么 仅对失败的那一批重试，已成功批次的向量被保留
    并且 重试在用尽前成功时算法正常产出 FinalChunkSet
    当 该批 part 级重试次数用尽仍失败
    那么 算法抛出可重试错误（RetriableError 类）交由上层任务级重试
    并且 算法不静默降级为结构切分

  场景: Stage 2 embedding 永久错误立即失败不重试
    假如 embedding 调用返回永久错误（4xx，如入参或模型名非法）
    当 semantic_depth_window 执行 embedding
    那么 算法不重试该批
    并且 算法抛出不可重试错误使任务快速失败

  场景: 退化输入回退结构边界
    假如 一个超限 mixed 块的可评分 atom 过少而无法形成有效 depth 曲线
    当 semantic_depth_window 运行
    那么 算法退回结构边界与接近 token 上限的合法 gap
    当 当前窗口内不存在任何合法 gap
    那么 输出 oversized FinalChunk
    并且 该 oversized FinalChunk 的 token 数不超过 hard_max_tokens
    并且 若该不可拆内容超过 hard_max_tokens 则在完整行边界处截断并标 truncated=true
