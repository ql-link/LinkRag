# ES入库重试机制 Feature Info

## 当前阶段

实现完成，进入 test-and-delivery 阶段

## 产物清单

| 产物 | 路径 | 状态 |
| :--- | :--- | :--- |
| Brief | `docs/ES入库重试机制/brief.md` | 已冻结 |
| Acceptance | `docs/ES入库重试机制/acceptance.feature` | 已冻结 |
| Technical Design | `docs/ES入库重试机制/technical_design.md` | 已冻结 |
| Implementation Report | `docs/ES入库重试机制/implementation_report.md` | 已产出 |

## 冻结信息

- brief 冻结时间：2026-05-20 CST
- acceptance 冻结时间：2026-05-20 CST
- technical_design 冻结时间：2026-05-20 CST
- 实现完成时间：2026-05-20 CST
- brief 冻结决策：后台定时扫描随 FastAPI 启动；普通重试失败不重复通知 Java；成功通知沿用原 `parse_result` topic 和原 `task_id`；TD 阶段按当前代码状态处理预分词独立阶段兼容。
- 下一阶段：交付收口；如需创建 PR，可先处理 issue/分支提交。

## Acceptance 覆盖情况

- Scenario 总数：15
- 主流程：4
- 异常与终态：4
- 幂等与并发：3
- 边界与配置：4

## 推荐阅读顺序

1. `docs/ES入库重试机制/brief.md`
2. `docs/architecture/parse_task_pipeline_module.md`
3. `docs/reference/elasticsearch_schema.md`
4. `docs/reference/mysql_schema.md`
5. `docs/guides/configuration.md`

## 上游材料

- GitHub Issue: `https://github.com/ql-link/LinkRag/issues/25`
- `src/core/pipeline/parse_task/pipeline.py`
- `src/core/pipeline/parse_task/post_process/repository.py`
- `src/core/pipeline/parse_task/validator.py`
- `src/core/es_index_storage/pipeline.py`
