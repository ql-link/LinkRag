# 需求信息：解析失败重试链路 + 稀疏向量阶段接入（Java 端）

- **当前阶段**：brief 已冻结
- **冻结时间**：2026-05-21
- **产物清单**：
  - `brief.md` — 已冻结 brief（Java 端改造说明）
- **推荐阅读顺序**：
  1. `brief.md`（本目录）
  2. [Python 端 brief（已冻结）](../parse-retry-and-sparse-vector-py/brief.md)
- **关联资料**：
  - Python 端 brief：`docs/parse-retry-and-sparse-vector-py/brief.md`（已冻结 2026-05-21）
  - 关联 issue：
    - #38 Python 端 chunking 落库与 dense 向量化时机改造
    - #41 kb_document_chunk 与 document_post_process_pipeline 职责拆分
    - #42 删除 claim_failed_for_retry 预留方法
    - #44 Java 端 parse_result 通知接收的幂等与丢失/乱序兜底
- **下一步**：
  - Python brief 可进入 `acceptance-generator` 生成 acceptance.feature
  - Java brief 由 Java 团队据此自行落地（独立项目，不在本仓库走 acceptance-generator 流程）
