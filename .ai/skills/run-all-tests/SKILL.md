---
name: run-all-tests
description: 运行当前仓库 tests 目录下的全部 pytest 测试并直接返回结果报告，不落本地测试文档。适用于用户要求“运行当前所有测试”“跑全量测试”“把 tests 全跑一遍并告诉我结果”等场景。
when_to_use: "当用户要求运行当前仓库的所有测试、全量 pytest、tests 目录下全部测试，并希望直接获得测试结果结论时激活。触发示例：'运行当前所有测试'、'把 tests 全跑一遍'、'执行全量测试并告诉我结果'"
---

# Run All Tests

## 目标

在当前仓库根目录执行 `tests` 目录下的全部 pytest 测试，并把测试结果整理成响应中的结果文档返回给用户，不创建、不修改任何本地测试结果文档。

## 仓库约定

- 本项目的集成测试位于 `tests/integration`
- 若不带 `--run-integration`，集成测试不会被收集
- 因此“运行当前所有测试”默认指执行：

```bash
pytest --run-integration tests
```

## 执行规则

1. 默认在仓库根目录执行命令。
2. 如根目录存在 `.venv`，优先使用虚拟环境中的 pytest：

```bash
. .venv/bin/activate && pytest --run-integration tests
```

3. 不要生成 `testing_delivery.md`、`test_report.md`、临时 markdown 报告或其他本地结果文件。
4. 不要因为测试失败就自动修改代码，除非用户明确要求继续修复。
5. 若命令执行失败、环境缺失、外部依赖不可达，也要照样返回结果总结，并明确失败发生在“测试失败”还是“测试无法执行”。

## 输出要求

最终响应必须直接给出一份简洁的“测试结果文档”，至少包含：

1. 执行命令
2. 执行范围（说明已覆盖 `tests`，且包含 `tests/integration`）
3. 结果概览：
   - 通过数
   - 失败数
   - 报错数
   - 跳过数（若有）
   - 总耗时（若 pytest 输出中可得）
4. 失败明细：
   - 每个失败/报错测试的路径或用例名
   - 失败原因一句话总结
5. 结论：
   - `PASS`：全部通过
   - `FAIL`：存在失败或报错
   - `BLOCKED`：环境问题导致无法完成测试

## 结果文档模板

```text
测试结果文档

执行命令:
<实际执行命令>

执行范围:
覆盖 tests 目录全部测试，包含 tests/unit 与 tests/integration

结果概览:
- pass: X
- failed: X
- error: X
- skipped: X
- duration: X

失败明细:
- <test case>: <一句话原因>

结论:
PASS | FAIL | BLOCKED
```
