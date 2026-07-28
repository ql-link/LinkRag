# language: zh-CN
功能: Wiki 标题树
  作为持有 LinkRag 会话凭证的调用方
  我希望按文档标题结构搜索、读取标题树并定位 Chunk
  以便在不复制正文、不改变现有 Chunk 真值的前提下获得结构化导航能力

  背景:
    假如 用户 123 持有授权数据集 [10,20] 的有效 session token
    并且 文档 D1 属于用户 123 和数据集 10
    并且 文档 D1 的最新解析流水线状态为 SUCCESS
    并且 文档 D1 的待查询 Chunk 均为 ACTIVE

  # ==== 标题树构建与持久化 ====

  场景: 按原文顺序构建 H1 到 H6 标题树
    假如 文档 D1 的 ParseResult 依次包含 H1 到 H6 且每一级都是前一级的子标题
    当 系统为文档 D1 构建 Wiki 标题树
    那么 生成 6 个类型为 HEADING 的独立节点
    并且 H2 到 H6 的直接父节点依次为前一级标题
    并且 H1 的 parent_id 为空
    并且 不为文档虚拟根生成 Wiki 节点

  场景: 同一路径的重复同名标题保持为不同节点并按位置挂载
    假如 文档 D1 在同一父标题下依次出现两个标题 "安装"
    并且 Chunk C1 和 C2 的源位置分别落在第一个和第二个 "安装" 标题下
    当 系统为文档 D1 构建 Wiki 标题树
    那么 生成两个不同的 "安装" HEADING 节点
    并且 C1 仅引用第一个 "安装" 节点
    并且 C2 仅引用第二个 "安装" 节点

  场景: Chunk 只挂到标题路径的末端标题
    假如 Chunk C1 的标题路径为 ["指南","安装"]
    当 系统为文档 D1 构建 Wiki 标题树
    那么 在 "安装" 标题下生成一个指向 C1 的直属 CHUNK_REF
    并且 在 "指南" 标题下不生成指向 C1 的直属 CHUNK_REF

  场景: 跨越多条标题路径的 Chunk 在每个末端标题下各有一个引用
    假如 Chunk C1 的源范围覆盖标题路径 ["指南","安装"] 和 ["指南","配置"]
    当 系统为文档 D1 构建 Wiki 标题树
    那么 "安装" 和 "配置" 标题下各有一个指向 C1 的直属 CHUNK_REF
    并且 系统不复制 C1 的正文

  场景: 不完整 heading trail 仍按 ParseResult 位置挂到 H6
    假如 文档 D1 含一个 H6 标题 "细节"
    并且 Chunk C1 的 heading trail 因追踪深度限制不含 "细节"
    并且 C1 的源位置落在 "细节" 标题下
    当 系统为文档 D1 构建 Wiki 标题树
    那么 "细节" HEADING 节点被保留
    并且 "细节" 标题下有且仅有一个指向 C1 的直属 CHUNK_REF

  场景: overlap 文本不增加结构归属且派生 Chunk 遵循相同挂载规则
    假如 基础 Chunk C1 的正文 overlap 中出现另一个标题 "附录"
    并且 派生 Chunk C2 的源位置位于标题 "正文" 下
    当 系统为文档 D1 构建 Wiki 标题树
    那么 "附录" 标题下不存在指向 C1 的 CHUNK_REF
    并且 "正文" 标题下有且仅有一个指向 C2 的直属 CHUNK_REF
    并且 C2 的原有 chunk_type 保持不变

  场景: 没有直属正文的标题仍保留空 Chunk 列表
    假如 标题 "概览" 后立即出现其子标题 "细节"
    并且 前一个 Chunk 的正文 overlap 中出现 "概览"
    当 系统为文档 D1 构建 Wiki 标题树
    那么 "概览" HEADING 节点被保留
    并且 "概览" 标题的直属 Chunk 列表为空
    并且 不因 overlap 为 "概览" 创建 CHUNK_REF

  场景: 无标题文档不创建占位标题
    假如 文档 D1 的 ParseResult 不含任何标题
    并且 Splitter 产出 Chunk C1
    当 系统为文档 D1 构建 Wiki 标题树
    那么 不生成 HEADING 节点
    并且 C1 的 CHUNK_REF 位于文档虚拟根下
    并且 对外返回 C1 时标题节点和标题路径均为空

  场景大纲: 首次构建或重试替换失败时 Chunk 与标题树共同回滚
    假如 文档 D1 正在执行 <operation>
    并且 提交前的持久化状态为 <before_state>
    当 <failure_point> 发生失败
    那么 本次新 Chunk 和新 Wiki 节点均未提交
    并且 提交后的持久化状态仍为 <after_state>
    并且 chunking 阶段结果为失败
    并且 文档 D1 的最新解析流水线状态不是 SUCCESS
    并且 Wiki 搜索、Chunk 定位和整树读取均不返回文档 D1 的旧版本或新版本

    例子:
      | operation | before_state | failure_point | after_state |
      | 首次构建  | 无旧数据     | Wiki 构建     | 无旧数据    |
      | 首次构建  | 无旧数据     | Wiki 写入     | 无旧数据    |
      | 重试替换  | 旧版本       | Wiki 构建     | 旧版本      |
      | 重试替换  | 旧版本       | Wiki 写入     | 旧版本      |

  场景: 从 CHUNKING 重试时重新获得同一 Markdown 的结构化解析结果
    假如 文档 D1 从 CHUNKING 阶段重试且只恢复出 Markdown
    并且 该 Markdown 同时含没有直属正文的标题和 H6 标题
    当 重试流程重建 Chunk 与 Wiki 标题树
    那么 建树输入包含与该 Markdown 对应的 ParseResult
    并且 没有直属正文的标题和 H6 标题均出现在新树中
    并且 Chunk 与新树在同一事务中共同提交
    并且 最新解析流水线达到 SUCCESS 前 Chunk 与新树均不可见
    当 最新解析流水线达到 SUCCESS
    那么 Chunk 与新树同时可见

  # ==== 标题业务标识 ====

  场景大纲: 非结构性变化不改变 heading_key
    假如 标题 "安装" 的规范化完整路径、级别和同路径同名出现次序不变
    当 文档 D1 发生 <change> 后重新解析
    那么 "安装" 标题重新生成后的 heading_key 与原值相同

    例子:
      | change                  |
      | 正文增删导致行号变化    |
      | Chunk 重新分块          |
      | chunk_id 重新分配       |
      | 标题仅改变英文大小写    |
      | 同一父标题下普通兄弟重排 |
      | 标题删除后以相同结构重新出现 |
      | 内容完全相同的重复解析  |

  场景大纲: 标题身份变化时生成新的 heading_key
    假如 文档 D1 已存在标题 "安装" 及其 heading_key
    当 该标题发生 <change> 后重新解析
    那么 变化后标题的 heading_key 与原值不同

    例子:
      | change                   |
      | 标题重命名               |
      | 标题级别改变             |
      | 移到另一个父标题下       |
      | 任一祖先标题改变         |
      | 同路径同名出现次序改变   |
      | 使用新的 doc_id 创建文档 |

  # ==== 标题搜索与结果合并 ====

  场景大纲: 精确标题不区分大小写并按服务端页大小返回
    假如 授权且就绪范围内存在 <fixture>
    并且 WIKI_SEARCH_PAGE_SIZE 配置为 <configured_page_size>
    当 用户搜索 "  快速   开始  " 且标题大小写与查询不同
    那么 返回 <heading_count> 个精确匹配标题及各自完整标题路径
    并且 返回 <chunk_count> 个去重后的直属 Chunk 正文
    并且 响应 page_size 等于 <effective_page_size>
    并且 响应 has_more 等于 <has_more>
    并且 响应 next_cursor 为 <next_cursor>
    并且 不执行标题前缀匹配
    并且 不执行 Chunk BM25

    例子:
      | fixture                                      | configured_page_size | heading_count | chunk_count | effective_page_size | has_more | next_cursor |
      | 20 个同名标题且各有 1 个不同的直属 Chunk     | DEFAULT              | 15            | 15          | 15                  | true     | PRESENT     |
      | 20 个同名标题且各有 1 个不同的直属 Chunk     | 5                    | 5             | 5           | 5                   | true     | PRESENT     |
      | 1 个同名标题且没有直属 Chunk                 | DEFAULT              | 1             | 0           | 15                  | false    | OMIT        |

  场景: 精确标题续页始终保持 SQL 短路且不启用 BM25
    假如 授权且就绪范围内存在 20 个标题为 "介绍" 的不同标题节点
    并且 WIKI_SEARCH_PAGE_SIZE 配置为默认值 15
    当 用户精确搜索 "介绍"
    那么 第一页返回前 15 个精确标题结果和 next_cursor
    并且 不执行标题前缀匹配
    并且 不执行 Chunk BM25
    当 用户携带 next_cursor 加载更多
    那么 第二页返回其余 5 个精确标题结果
    并且 第二页与第一页没有重复或遗漏
    并且 响应 has_more=false 且不返回 next_cursor
    并且 仍不执行标题前缀匹配
    并且 仍不执行 Chunk BM25

  场景: 精确未命中时同时执行标题前缀匹配和 Chunk BM25
    假如 查询 "安" 不精确命中任何规范化标题
    并且 授权且就绪范围内存在展示标题为 "Android" 的标题节点
    并且 WIKI_BM25_TOP_K_PER_DATASET 配置为默认值 50
    当 用户以不同英文大小写的前缀 "AN" 执行 Wiki 搜索
    那么 标题前缀匹配和现有 Chunk BM25 均被调用一次
    并且 标题前缀结果包含展示标题 "Android"
    并且 两路查询均限定在同一有效用户、知识库、文档和就绪范围内
    并且 不调用 dense、sparse、rerank、图检索或 LLM Wiki

  场景: 多知识库统一按系统配置分别取得 BM25 候选
    假如 有效检索范围包含知识库 10 和 20
    并且 两个知识库的个性 bm25_top_k 分别为 20 和 100
    并且 两个知识库的个性 recall_strict 分别为 true 和 false
    并且 WIKI_BM25_TOP_K_PER_DATASET 配置为 50
    并且 系统 RECALL_STRICT_DEFAULT 配置为 false
    并且 查询未精确命中标题
    当 用户执行 Wiki 搜索
    那么 知识库 10 和 20 分别请求至多 50 个 BM25 候选
    并且 不读取或应用两个知识库的个性 bm25_top_k
    并且 不读取或应用两个知识库的个性 recall_strict
    并且 当前搜索使用宽松容错模式
    并且 合并前的 BM25 候选总数不超过 100

  场景大纲: 单知识库 BM25 只对瞬时错误重试一次
    假如 精确标题没有命中
    并且 系统 RECALL_STRICT_DEFAULT 配置为 false
    并且 标题前缀查询成功
    并且 知识库 10 的 BM25 连续调用结果为 <attempt_results>
    当 用户执行 Wiki 搜索
    那么 知识库 10 的 BM25 调用次数为 <attempt_count>
    并且 HTTP 响应状态为 200
    并且 成功响应 failed_sources 为 <failed_sources>
    并且 响应结果来源为 <returned_sources>

    例子:
      | attempt_results                  | attempt_count | failed_sources | returned_sources     |
      | [TRANSIENT_ERROR,SUCCESS]        | 2             | []             | [title_prefix,bm25]  |
      | [TRANSIENT_ERROR,TRANSIENT_ERROR]| 2             | [bm25]         | [title_prefix]       |
      | [PERMANENT_ERROR]                | 1             | [bm25]         | [title_prefix]       |

  场景大纲: 搜索异常沿用严格与宽松召回容错语义
    假如 精确标题 SQL 结果为 <exact_result>
    并且 生效的召回容错模式为 <strict_mode>
    并且 标题前缀查询结果为 <prefix_result>
    并且 Chunk BM25 结果为 <bm25_result>
    当 用户执行 Wiki 搜索
    那么 HTTP 响应状态为 <status>
    并且 响应业务错误码为 <error_code>
    并且 成功响应 failed_sources 为 <failed_sources>
    并且 响应结果来源为 <returned_sources>

    例子:
      | exact_result | strict_mode | prefix_result | bm25_result | status | error_code                | failed_sources  | returned_sources |
      | ERROR        | false       | NOT_CALLED    | NOT_CALLED  | 500    | RECALL_ALL_SOURCES_FAILED | OMIT            | NONE             |
      | MISS         | false       | ERROR         | SUCCESS     | 200    | NONE                      | [title_prefix]  | [bm25]           |
      | MISS         | false       | SUCCESS       | ERROR       | 200    | NONE                      | [bm25]          | [title_prefix]   |
      | MISS         | true        | ERROR         | SUCCESS     | 500    | RECALL_ALL_SOURCES_FAILED | OMIT            | NONE             |
      | MISS         | false       | ERROR         | ERROR       | 500    | RECALL_ALL_SOURCES_FAILED | OMIT            | NONE             |

  场景: 前缀标题优先合并并按节点和 Chunk 去重
    假如 标题前缀匹配返回标题 H1 和 H1 的直属 Chunk C1
    并且 Chunk BM25 返回 C1 和 C2
    并且 C1 还被标题 H2 引用
    当 系统合并两路结果
    那么 H1 的标题结果排在 BM25 正文结果之前
    并且 H1 在结果中只出现一次
    并且 C1 的正文在结果中只出现一次
    并且 C1 的标题位置同时包含 H1 和 H2
    并且 当前页结果数不超过 WIKI_SEARCH_PAGE_SIZE

  场景: 匹配标题的首个预览在整个搜索链固定优先于 BM25
    假如 标题 H6 在第二页出现且首个直属 Chunk 为 C6
    并且 第一页 BM25 候选包含 C6 和后续候选 C7
    当 用户依次读取 Wiki 搜索第一页和第二页
    那么 C6 不作为第一页 BM25 正文结果返回
    并且 第一页使用 C7 补足被释放的 BM25 名额
    并且 C6 只在第二页作为 H6 的标题预览出现
    并且 两页之间没有重复 Chunk

  场景大纲: 标题前缀与 BM25 按每页三分之一和三分之二分配并互补空位
    假如 精确标题没有命中
    并且 WIKI_SEARCH_PAGE_SIZE 配置为默认值 15
    并且 标题前缀有 <prefix_available> 个待返回结果
    并且 BM25 有 <bm25_available> 个待返回结果
    当 系统生成当前搜索页
    那么 当前页返回 <prefix_returned> 个标题前缀结果
    并且 当前页返回 <bm25_returned> 个 BM25 结果
    并且 标题前缀结果排在本页 BM25 结果之前
    并且 当前页总结果数为 <page_count>

    例子:
      | prefix_available | bm25_available | prefix_returned | bm25_returned | page_count |
      | 20               | 20             | 5               | 10            | 15         |
      | 4                | 20             | 4               | 11            | 15         |
      | 20               | 3              | 12              | 3             | 15         |
      | 20               | 0              | 15              | 0             | 15         |
      | 0                | 20             | 0               | 15            | 15         |

  场景: BM25 在知识库内保持分数顺序并跨知识库按名次轮询
    假如 知识库 10、20、30 各有按自身 BM25 分数降序排列的候选 C10-1 到 C10-3、C20-1 到 C20-3、C30-1 到 C30-3
    并且 请求中的 dataset_ids 顺序为 [30,10,20]
    当 系统合并这些知识库的 BM25 候选
    那么 合并顺序为 [C10-1,C20-1,C30-1,C10-2,C20-2,C30-2,C10-3,C20-3,C30-3]
    并且 合并顺序不比较不同知识库候选的原始 BM25 分数

  场景: 知识库数量超过当前页 BM25 名额时跨页继续轮询
    假如 有效范围包含按 dataset_id 升序排列的 25 个知识库
    并且 每个知识库至少有 2 个 BM25 候选
    并且 每页有 10 个 BM25 名额
    当 用户读取第一页 BM25 结果
    那么 第一页依次返回知识库 1 到 10 的第 1 名
    并且 响应返回保存轮询位置的 next_cursor
    当 用户使用 next_cursor 读取第二页 BM25 结果
    那么 第二页依次返回知识库 11 到 20 的第 1 名
    当 用户继续读取第三页 BM25 结果
    那么 第三页先返回知识库 21 到 25 的第 1 名
    并且 第三页再返回知识库 1 到 5 的第 2 名
    并且 任何知识库的第 2 名都不早于其他有候选知识库的第 1 名

  场景: 跨知识库轮询跳过空库并由其他知识库补足名额
    假如 知识库 10 没有 BM25 候选
    并且 知识库 20 有候选 C20-1 和 C20-2
    并且 知识库 30 有候选 C30-1
    当 当前页有 3 个 BM25 名额
    那么 知识库 10 不占用结果名额
    并且 结果依次为 [C20-1,C30-1,C20-2]

  场景: 精确未命中后的合并结果支持继续加载
    假如 标题前缀和跨知识库 BM25 合并去重后共有 40 个结果
    并且 WIKI_SEARCH_PAGE_SIZE 配置为默认值 15
    当 用户执行 Wiki 搜索
    那么 第一页返回前 15 个结果和 next_cursor
    当 用户连续两次携带返回的 next_cursor 加载更多
    那么 三页依次返回 15、15、10 个结果
    并且 三页之间没有重复或遗漏
    并且 最后一页 has_more=false 且不返回 next_cursor

  场景: BM25 保持完整 Chunk 文本匹配语义
    假如 精确标题没有命中
    并且 Chunk C1 的标题文字命中查询而 Chunk C2 的正文命中查询
    当 现有 Chunk BM25 返回 C1 和 C2
    那么 C1 和 C2 均按 BM25 结果处理
    并且 不给标题文字命中的 Chunk 增加独立标题分数
    并且 每条正文结果回填完整 Chunk 而不按标题范围截取

  场景: 标题搜索只返回直属 Chunk 且默认不附带完整树
    假如 标题 "指南" 没有直属 Chunk 但子标题 "安装" 有直属 Chunk C1
    当 用户搜索命中标题 "指南"
    那么 返回 "指南" 的 heading_key 和完整标题路径
    并且 "指南" 的直属 Chunk 列表为空
    并且 响应不含文档 D1 的完整标题树
    并且 响应不含 C1

  场景: 标题搜索只预览首个直属 Chunk 并独立加载当前标题的其余直属 Chunk
    假如 标题 H1 按顺序直属 Chunk C1 到 C18
    并且 H1 的子标题 H1-1 直属 Chunk C19
    并且 当前搜索的另一个标题结果 H2 直属 Chunk C20
    并且 WIKI_SEARCH_PAGE_SIZE 配置为默认值 15
    当 用户搜索命中标题 H1
    那么 H1 的标题结果只内嵌完整 Chunk C1
    并且 H1 的 direct_chunk_count 为 18
    并且 H1 的 direct_chunks_has_more 为 true
    并且 H1 返回从 C2 开始的 next_direct_chunk_cursor
    当 用户使用 next_direct_chunk_cursor 加载 H1 的更多直属 Chunk
    那么 本次展开按顺序返回完整 Chunk C2 到 C16
    并且 本次展开不返回子标题 Chunk C19 或其他搜索结果 Chunk C20
    并且 本次展开不推进顶层搜索 next_cursor
    并且 本次展开返回从 C17 开始的新 next_direct_chunk_cursor
    当 用户继续加载 H1 的更多直属 Chunk
    那么 本次展开按顺序返回完整 Chunk C17 和 C18
    并且 direct_chunks_has_more 为 false
    并且 不返回 next_direct_chunk_cursor

  场景: 同名精确标题只返回授权且就绪范围内的全部匹配
    假如 标题 "介绍" 同时存在于授权就绪文档、未授权文档和未就绪文档
    当 用户精确搜索 "介绍"
    那么 当前页只返回授权就绪文档中的 "介绍" 标题
    并且 未授权文档和未就绪文档的标题及 Chunk 均不出现在响应中

  # ==== 权限、就绪状态与读取能力 ====

  场景大纲: Wiki 搜索按用户知识库文档三级范围约束标题与 BM25
    假如 用户 123 拥有知识库 10 和 20
    并且 文档 D1 属于知识库 10 而文档 D2 属于知识库 20
    并且 session token 的知识库 claims 为 <claims>
    当 用户以 dataset_ids=<dataset_ids> 和 doc_ids=<doc_ids> 执行 Wiki 搜索
    那么 有效知识库范围为 <effective_datasets>
    并且 有效文档范围为 <effective_docs>
    并且 标题 SQL 和 Chunk BM25 收到相同的 user_id=123、知识库范围和文档范围

    例子:
      | claims       | dataset_ids | doc_ids | effective_datasets | effective_docs       |
      | [10,20]      | OMIT        | OMIT    | [10,20]            | 范围内全部可见文档   |
      | [10,20]      | [20]        | OMIT    | [20]               | 知识库 20 全部可见文档 |
      | [10,20]      | OMIT        | [D1,D2] | [10,20]            | [D1,D2]              |
      | [10,20]      | [10]        | [D1]    | [10]               | [D1]                 |
      | FULL_LIBRARY | OMIT        | OMIT    | [10,20]            | 用户全部可见文档     |

  场景大纲: 无效凭证请求或越权范围在查询前被拒绝
    假如 Wiki 搜索请求满足 <condition>
    当 用户提交该 Wiki 搜索请求
    那么 HTTP 响应状态为 <status>
    并且 响应错误码为 <error_code>
    并且 不执行标题 SQL 查询
    并且 不执行 Chunk BM25

    例子:
      | condition                                  | status | error_code                  |
      | 缺少 session token                        | 401    | RECALL_SESSION_UNAUTHORIZED |
      | session token 无效或过期                  | 401    | RECALL_SESSION_UNAUTHORIZED |
      | query 为空或纯空白                        | 400    | RECALL_INVALID_REQUEST      |
      | 请求 JSON 非法                            | 422    | RECALL_INVALID_REQUEST      |
      | 请求含未知字段                            | 422    | RECALL_INVALID_REQUEST      |
      | dataset_ids 含 claims 外的知识库 30       | 403    | RECALL_SCOPE_FORBIDDEN      |
      | doc_ids 含 claims 外知识库 30 的文档 D3   | 403    | RECALL_SCOPE_FORBIDDEN      |
      | dataset_ids=[10] 但 doc_ids=[D2@知识库20] | 403    | RECALL_SCOPE_FORBIDDEN      |
      | doc_ids 含其他用户的文档 D4               | 403    | RECALL_SCOPE_FORBIDDEN      |

  场景大纲: 不可见候选在返回前被 fail closed
    假如 候选标题或 Chunk 所属数据处于 <condition>
    当 用户执行 Wiki 搜索、Chunk 定位或整树读取
    那么 该标题、Chunk 正文和标题路径均不出现在响应中

    例子:
      | condition                    |
      | 归属其他用户                 |
      | 不在请求的数据集范围内       |
      | 不在请求的文档范围内         |
      | 最新解析流水线不是 SUCCESS   |
      | Chunk 生命周期不是 ACTIVE    |

  场景: Chunk 定位返回全部直接标题位置并支持批量读取
    假如 Chunk C1 同时直属标题 H1 和 H2
    并且 Chunk C2 直属标题 H3
    当 用户批量定位 [C1,C2]
    那么 C1 返回 H1 和 H2 的两条完整标题路径
    并且 C2 返回 H3 的完整标题路径
    并且 定位过程按文档批量读取而不逐 Chunk 查询父链

  场景: 按文档读取完整树时校验授权并保持同类型节点顺序
    假如 文档 D1 的同一父标题下有两个 HEADING 和两个 CHUNK_REF
    并且 每种节点都具有明确的 sort_order
    当 用户读取文档 D1 的完整标题树
    那么 HTTP 响应状态为 200
    并且 两个 HEADING 按各自 sort_order 排序
    并且 两个 CHUNK_REF 按各自 sort_order 排序
    并且 响应不声明 HEADING 与 CHUNK_REF 之间的混合顺序
    当 同一用户读取未授权文档的完整标题树
    那么 HTTP 响应状态为 403
    并且 响应不含该文档的任何标题或 Chunk

  # ==== 生命周期清理 ====

  场景大纲: Chunk 与文档生命周期变化同步维护 Wiki 引用
    假如 文档 D1 的标题树已引用 Chunk C1
    当 执行 <action>
    那么 Wiki 数据变为 <wiki_result>
    并且 后续查询结果为 <query_result>

    例子:
      | action                    | wiki_result                   | query_result             |
      | C1 正文更新               | 原有标题节点和引用保持不变    | 返回更新后的完整 Chunk   |
      | C1 标记为 REMOVED         | C1 的全部 CHUNK_REF 被删除    | 不返回 C1                |
      | 删除文档 D1               | D1 的全部 Wiki 节点被删除     | 不返回 D1 的树和 Chunk   |
      | 删除 D1 所属的数据集      | 数据集内全部 Wiki 节点被删除  | 不返回该数据集内容       |
      | 整文档结构改变后重新解析成功 | 旧 Chunk 与旧树被新版本原子替换 | 只返回新 Chunk 与新标题树 |

  场景大纲: 单 Chunk 结构字段实际变化时在任何 mutation 前被拒绝
    假如 Chunk C1 的正文、start_line、end_line、chunk_index 和标题引用均已有持久化值
    当 单 Chunk 更新请求把 <field> 改为不同于现有记录的值
    那么 抛出 ChunkStructuralUpdateNotAllowedError
    并且 错误说明结构变化必须通过整文档重新解析
    并且 C1 的正文和全部真值字段保持不变
    并且 C1 的全部 CHUNK_REF 保持不变
    并且 不执行 embedding、Qdrant、稀疏向量或 BM25 mutation

    例子:
      | field       |
      | start_line  |
      | end_line    |
      | chunk_index |
