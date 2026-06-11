"""Application 层：业务用例的执行 runtime 与装配。

介于 api 层（HTTP 接口面：routes / schemas / 鉴权依赖）与 core 层（领域模块）之间：

- ``recall_errors``：召回链路共享错误类型与错误码常量（与 docs/api/error_codes.md 对齐）；
- ``recall_pipeline_provider``：``RecallPipeline`` 单例装配与依赖提供者；
- ``recall_stream_runtime``：RAG 问答流 SSE 执行 runtime（/api/v1/rag/stream）；
- ``recall_json_runtime``：纯召回 JSON 执行 runtime（/api/v1/recall）；
- ``recall_serialization``：两条召回链路共用的 hits 序列化。

依赖方向：api → application → core，不得反向。
"""
