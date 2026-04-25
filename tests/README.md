# Tests

当前测试目录按执行成本分成两层：

- `tests/unit`：单元测试，默认执行，优先通过 Mock 隔离外部依赖。
- `tests/integration`：集成测试，依赖真实数据库、缓存、中间件或完整应用装配，需显式开启。

建议约定：

- 测 `src/services/*` 的纯业务逻辑，优先放到 `tests/unit/services`。
- 测 FastAPI 路由的请求/响应和依赖注入，放到 `tests/unit/api`。
- 测 MQ 消费者、核心组件编排、真实基础设施联通性，按性质放到 `tests/unit/core` 或 `tests/integration/*`。
- 测试文件名保持 `test_<module>.py` 或 `test_<behavior>_integration.py`，避免一个文件同时混放多层级职责。

运行方式：

```bash
pytest
pytest tests/unit
pytest --run-integration tests/integration
pytest --run-integration tests/integration/test_connectivity.py -m connectivity
```
