---
name: implementation-execution
description: 在 toLink-Rag 中按已确认范围执行后端、HTTP/MQ 契约、配置、迁移和测试工作包。适用于 backend-delivery 直接实现或 solution.md 确认后的实施，不重新分流、规划或处理 Git 交付。
---

# 实施执行

## 进入条件

直接实现读取当前请求、来源材料、七维简报和严格检查；方案先行以当前 `solution.md` 为中心，选择契约验收时同时读取 `acceptance.feature`。不存在机器阶段、哈希或冻结字段要求。

主 Agent 的工作包必须写清目标、可观察结果、允许与禁止文件、文件所有权、依赖、严格检查和最小验证。实施者只能修改当前所有权范围；需要触碰共享契约、迁移链或其他工作包文件时停止并返回证据。

## 必读材料

读取 `AGENTS.md`、当前确认依据、目标文件与直接消费方、相关测试、`git status --short` 和当前差异。涉及 HTTP、MQ、配置、数据库、对象存储、向量库或部署时，必须读取对应契约、模型、迁移和运行配置。不要只读方案而跳过真实代码。

## 实施纪律

- 只实现确认范围，不顺带重构，不覆盖用户已有修改；
- 修改模型必须新增 forward-only Alembic revision，并同步 `docs/api/schemas/mysql.md` 与当前结构快照；不得修改 `migrations/db.sql` baseline；
- 修改 MQ 消息必须同步 `docs/api/mq_contracts.md`、`docs/internals/mq.md` 并核对 Java 消费方语义；
- 修改 parse task pipeline 必须同步 `docs/internals/parse_task_pipeline.md`；
- 契约结构和兼容影响使用 `contract-guard`，同一值多处一致性使用 `config-contract-sync`，长期事实变化使用 `doc-maintenance-sync`；
- 外部模型、存储或基础设施必须处理密钥、超时、重试上限、幂等、取消、降级和日志脱敏；默认测试使用 fake，不擅自调用真实付费服务。

每完成一个可验证单元先运行最窄检查，并补距离行为最近的测试；复杂测试设计转 `test-authoring`。实现稳定后执行 `python scripts/quality/check_docs_sync.py --working` 和必要专项检查，再转 `run-all-tests`。

## 偏差与实施报告

新行为、权限、数据、兼容、迁移、失败语义或发布决定超出确认范围时停止：直接实现返回 `backend-delivery` 重评，方案任务返回 `solution-generator` 修订并确认。普通命名、文件组织或不改变外部结果的实现调整可以继续。

方案任务只有在存在已允许的方案偏差、已接受限制或必须跨会话交接的遗留风险时，才读取 [implementation_report.template.md](implementation_report.template.md) 并写 `.specs/<KEY>/implementation_report.md`。直接实现不创建报告；空报告禁止生成。

本技能不创建分支、提交、推送、PR 或修改外部 Issue。完成后依次进入范围匹配的自动化验证、必要人工验收和质量审查。
