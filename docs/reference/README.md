# Reference

契约类、生成类与参考类文档，按主题就近实现。

## 当前文档

### 数据模型（按存储介质拆分）

- [MySQL Schema](mysql_schema.md) — 12 张业务表，按用户 / LLM / 数据集 / 解析 / 索引 5 个业务域分组
- [Qdrant Schema](qdrant_schema.md) — 向量库 collection、分桶规则、point payload、payload 索引
- [Elasticsearch Schema](elasticsearch_schema.md) — ES 索引、文档结构、入库结果模型

### 接口契约

- [API contracts](api_contracts.md) — HTTP 接口契约
- [Error codes](error_codes.md) — 错误码表

## 文档原则

- **事实性**：以代码 / 配置 / DDL 为唯一权威，文档是浓缩与索引，不是平行真值。
- **可搜索**：字段、表名、错误码等关键词都应能在文档中字面命中。
- **就近**：与实现保持靠近——代码改 schema、改契约时，本目录文档同步更新。
- **不混搭**：按"存储介质 / 协议层 / 错误类型"分文件，避免一个文件承载多种类型的内容。

## 适合放在这里

- HTTP API 契约、错误码
- MQ 消息契约（细节见 [docs/guides/mq_integration.md](../guides/mq_integration.md)，演进语义见 `src/core/mq/messages/`）
- 数据库表结构、索引（按存储介质分文件）
- 半生成的参考资料（如 OpenAPI 文件）

## 不适合放在这里

- 模块内部架构 → [docs/architecture](../architecture)
- 命名 / 编码 / 测试约定 → [docs/conventions](../conventions)
- 部署 / 接入 / 运维 → [docs/guides](../guides)
- Python 内存模型（如 `Chunk`、`IndexedPoint`、Pydantic 内部模型） → 留在 `src/` 的代码就近 docstring，不在 reference 中重复
