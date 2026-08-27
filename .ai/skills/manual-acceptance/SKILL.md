---
name: manual-acceptance
description: 为 toLink-Rag 生成并记录自动化无法覆盖的人工端到端验收，例如真实 MQ、MySQL、对象存储、向量库、解析链路或 Java 对接。没有真实执行证据时不得标记通过。
---

# 人工端到端验收

方案先行任务写入 `.specs/<KEY>/manual_acceptance.md`；直接实现只在会话交接中保存精简记录。读取 [manual_acceptance.template.md](manual_acceptance.template.md)，删除所有占位内容。

人工验收不能替代本应存在的自动化测试。开始前读取当前请求或 `solution.md`、适用的 `acceptance.feature`、真实实现、Git 差异、自动化测试结果和未覆盖区域。

只提取需要真实服务或人工观察的结果，例如 Java → MQ → FastAPI 消费与回执；上传、解析、分块、向量化和召回完整链路；真实 MySQL、RabbitMQ、MinIO、Qdrant 或模型配置；迁移升级、兼容窗口、重试、幂等和失败恢复；性能或长时间观察。

每项写明环境、虚构测试数据、前置条件、单步操作和具体预期。状态只允许 `未执行`、`通过`、`失败`、`阻塞`、`不适用`。只有本次真实操作、日志、截图或执行人明确确认才能标记通过。任一必要项未执行、失败或阻塞时，总结论不能写通过。

最终说明记录位置、环境、分支或提交、执行人和日期，各状态数量，失败或阻塞项，自动化证据，以及是否足以进入 `code-review-and-quality`。
