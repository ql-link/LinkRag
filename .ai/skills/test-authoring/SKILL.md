---
name: test-authoring
description: 为 toLink-Rag 的 FastAPI、RAG pipeline、MQ、存储与数据访问代码编写或修订自动化测试和夹具。只负责测试设计与实现，最终执行和结果报告转 run-all-tests。
---

# 自动化测试编写

简单邻近测试可由 `implementation-execution` 直接补充；需要复杂 Mock、分层调整、MQ/数据库/对象存储/模型边界或用户明确要求补测试时使用。发现生产缺陷时返回 `backend-delivery`，不得降低断言让错误实现通过。

- `tests/unit/`：不访问网络、真实数据库、MQ、对象存储或模型供应商的快速测试；
- `tests/integration/`：模块组合、FastAPI HTTP、MySQL/MQ/向量库等集成边界，按 `--run-integration` 规则执行；
- `tests/acceptance/`：已提升并实现 step 的 pytest-bdd 行为契约；Gherkin 文件本身不等于测试已通过。

对外部系统使用明确夹具或替身，不读取真实密钥和用户数据。LLM、embedding、rerank 或计费服务默认使用确定性 fake；真实供应商 smoke test 必须单独授权并报告费用和数据边界。

从当前请求或 `solution.md` 的 `R/BR` 拆出成功、失败、权限、边界、幂等和回归路径；读取被测实现、直接调用方和邻近测试；选择距离行为最近的层级；先写会对错误行为失败的关键断言，再补最小数据与夹具。运行最窄测试确认新增用例被收集，全量验证交给 `run-all-tests`。
