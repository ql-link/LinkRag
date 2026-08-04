# Manticore BM25 召回评测

BM25 运行时固定使用 Manticore，Qdrant 不再承载 BM25，因此新的质量评测只需验证 Manticore。

## 评测口径

- 使用固定版本的评测集和 qrels，记录 corpus/query 数量与版本。
- 至少报告 `Recall@10`、`nDCG@10`、P95 查询延迟、错误率和峰值内存。
- 评测表使用独立前缀，结束后删除，禁止连接生产表。
- 中文分词配置必须与生产 DDL 一致：`charset_table='non_cjk, chinese'`。
- 结果需与已发布基线比较；指标退化超过项目门禁时禁止上线。

历史 Qdrant/Manticore 对比只能作为迁移决策记录，不再作为当前实现的运行契约。原 Qdrant BM25 校准和双后端评测脚本已随实现删除。
