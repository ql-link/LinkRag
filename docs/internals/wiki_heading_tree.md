# Wiki 标题树

Wiki 标题树是内部 RAG 导航能力：每篇文档从解析期的同一份 `ParseResult` 和最终 Chunks 派生一棵 H1～H6 树，搜索时组合标题 SQL 与现有 BM25，并从 `kb_document_chunk` 回填完整正文。它不复制 Chunk 正文，不修改 Recall/MQ/Qdrant 公共契约，也不使用 Redis。

## 1. 模块与真值

| 位置 | 职责 |
| --- | --- |
| `src/core/wiki/heading_tree_builder.py` | 规范标题、生成 `heading_key`、按源位置构建标题与直属引用 |
| `src/core/storage/wiki_tree/repository.py` | `wiki_tree_node` 原子替换、scope/就绪 SQL、标题/路径/树/Chunk 批量读取 |
| `src/core/wiki/search_service.py` | 5/10 配额、跨库轮询、去重、HMAC 游标 |
| `src/application/wiki_runtime.py` | exact 短路、mixed 并发与容错、正文/路径回填 |
| `src/api/routes/wiki.py` | 四个带 session token 的 HTTP 入口 |

`wiki_tree_node` 是混合节点表：`HEADING` 保存标题结构，`CHUNK_REF` 只保存 `chunk_id` 引用。表间故意不设物理 FK，正文、租户归属、数据集和 Chunk 类型仍以 `kb_document_chunk` 为真值。虚拟文档根没有实体节点；无标题文档的引用直接使用 `parent_id=NULL`。

## 2. 构建与身份

- 标题按原文顺序构建，栈规则支持 H1～H6；同路径重复同名标题保留为不同节点。
- Chunk 只挂到其覆盖正文元素对应标题路径的末端标题；跨越多个路径时，每个末端标题各有一个引用。overlap 文本和 heading trail 不作为全局标题匹配依据。
- `heading_key` 是 64 位 SHA-256：输入包含版本域、`doc_id`、大小写折叠后的完整 `(level,title)` 路径及同路径同名出现次序。正文行号、分块或 chunk_id 变化不改 key；标题、级别、祖先、出现次序或 doc_id 变化会改 key。
- `ChunkingEngine.process_with_parse_result()` 在保持旧 `process()` 返回兼容的同时暴露实际消费的 ParseResult。首次、重试或成功文档的再次完整解析都执行 Chunk + Wiki 全量事务替换；构建发生在首次 DB mutation 前。
- 标题持久化先校验完整草稿，再按 H1～H6 非空层级批量加入 session，每层只 `flush` 一次以取得父层物理 ID；Chunk 引用另批量写入一次。标题数量增加不会把 `flush` 往返放大为逐节点调用。

## 3. 检索与分页

搜索先把 query 去首尾空白并合并连续空白。第一页执行大小写不敏感 exact 标题 SQL：命中后整个游标会话只走 exact keyset，耗尽也不降级。exact 未命中才并发执行标题 prefix 与分知识库 BM25。

mixed 页默认 15 条：标题目标 `ceil(15/3)=5`，BM25 目标 10，任一路不足由另一条补位；标题始终排在本页 BM25 前。BM25 每库最多 50 条，库内保留自身分数顺序，跨库按 `dataset_id` 升序进行 rank-major 轮询，不比较跨库原始分数。候选必须先过 MySQL 就绪门禁，隐藏候选不占页面名额。

游标是 URL-safe base64 的 `payload.signature`，签名密钥从 `RECALL_SESSION_JWT_SECRET` 通过 `wiki-search-cursor:v1` 域隔离派生。游标绑定版本、10 分钟有效期、分支、用户、规范 query、有效 scope 指纹和下一 keyset/轮询位置；任一不符返回 422。它不保存服务端状态或快照：数据不变时无重复遗漏，翻页期间数据改变时允许少量重复或遗漏，客户端按 `heading_key`/`chunk_id` 累计去重或从第一页重启。

每个标题搜索结果只预览首个可见直属 Chunk，直属总数大于 1 时签发独立 `heading_chunks` 游标，从第二条引用开始每页最多 15 条。该游标不读取子标题，也不推进顶层搜索游标。

标题精确/前缀 SQL 直接比较 `title`，大小写不敏感语义由表级 `utf8mb4_unicode_ci` 提供，禁止对索引列包装 `LOWER()`，使 `(node_type,title,doc_id,id)` 联合索引可同时使用标题键。直属预览在 MySQL 子查询中按标题执行 `COUNT() OVER` 与 `ROW_NUMBER() OVER`，外层只读取排名第一的引用；即使标题挂载大量 Chunk，Python 也只接收每标题一行和完整总数。

搜索与标题展开读取 Chunk 位置时，仓储先在 MySQL 内按 `(chunk_id,doc_id)` 计算完整总数和稳定排名，再限制为前 10 个父标题 ID，随后才水合标题与父链。批量 Chunk 定位和文档整树不传位置上限，继续返回全部直接位置。标题直属 Chunk 查询把 `ACTIVE` 条件放在 keyset 与 `LIMIT` 同一条 SQL 中，失效引用不会占用页面名额。

## 4. 权限与可见性

所有读取先解析 `EffectiveWikiScope(user_id,dataset_ids,doc_ids,doc_ids_by_dataset)`：

- claims 有限范围时，请求 dataset 必须是其子集；claims 空表示全库授权，必须先从 MySQL 展开用户实际拥有且 ACTIVE、未删除的数据集。
- 显式 doc_ids 必须全部属于有效用户和数据集范围，任一不符整体 403。
- 标题、BM25、正文、定位和整树共同要求当前 `latest_parse_task_id` 对应 pipeline `SUCCESS`；Chunk 还必须归属相同 user/dataset/doc 且 lifecycle 为 `ACTIVE`。
- SQL 查询失败 fail closed。搜索及标题展开的正文位置最多返回稳定排序的前 10 条，并提供总数/截断标记；批量定位端点返回全部直接标题位置。

## 5. 生命周期

- 单 Chunk 正文更新保持标题节点与引用；若实际改变 `start_line`、`end_line` 或 `chunk_index`，在任何 mutation 前抛 `ChunkStructuralUpdateNotAllowedError`。
- Chunk 标记 `REMOVED` 与删除其全部 CHUNK_REF 使用同一 MySQL transaction callback。
- 文档删除遵循外部索引/对象先清、DB 账本后清；最终事务按 Wiki → Chunk → parse rows 删除，失败整体回滚并由消息重试。
- 数据集删除逐文档复用相同流程。完整重解析成功后只保留新 Chunk 与新树。

## 6. 配置、观测与验证

运行时配置只有 `WIKI_SEARCH_PAGE_SIZE=15`、`WIKI_BM25_TOP_K_PER_DATASET=50`，均必须为正整数。容错统一读取系统 `RECALL_STRICT_DEFAULT`，总超时复用 `RECALL_STREAM_TIMEOUT_MS`；不读取数据集个性 strict/top-k。

日志只记录 request/task 标识、范围数量、分支、来源计数、失败来源和耗时，不记录 query、正文、token 或完整游标。发布前至少执行 Wiki 单元/acceptance、真实 MySQL repository/事务测试和 0037 upgrade→downgrade→upgrade 往返。
