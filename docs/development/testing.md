# Testing

测试分层、pytest markers、运行命令的规范。

入门级用法见 [tests/README.md](../../tests/README.md)，本文是补充规范。

## 分层

| 层级 | 目录 | 是否默认运行 | 外部依赖 |
| --- | --- | --- | --- |
| 单元 | `tests/unit/` | ✅ 默认 | Mock 隔离，绝不真实调用 |
| 集成 | `tests/integration/` | ❌ 需 `--run-integration` | 真实数据库 / MQ / 向量库 |
| 连通性 | `tests/integration/test_connectivity.py` 等 | ❌ 需 marker | 仅做基础设施 ping |

`tests/integration/` 下的所有测试由 `conftest.py` 自动加 `@pytest.mark.integration`。

## Pytest Markers

配置位置：[pyproject.toml](../../pyproject.toml) `[tool.pytest.ini_options]`。

| Marker | 含义 | 何时打 |
| --- | --- | --- |
| `unit` | 快速 Mock 单测 | 默认，可不显式标注 |
| `integration` | 需真实外部服务 | 放 `tests/integration/` 即可（自动加） |
| `connectivity` | 外部基础设施连通性烟雾测试 | 仅做 ping 类检查 |
| `real_env` | 触及真实 `.env` 中配置的服务 | 需显式 `-m real_env` 才会跑 |

## 运行命令

```bash
# 仅 unit（默认）
pytest

# 仅指定目录
pytest tests/unit/api

# 含 integration
pytest --run-integration tests/integration

# 仅连通性烟雾
pytest --run-integration tests/integration -m connectivity

# 真实环境测试（需配置好 .env）
pytest --run-integration -m real_env
```

## 目录布局约定

| 被测对象 | 放置位置 |
| --- | --- |
| `src/services/*` 纯业务逻辑 | `tests/unit/services/` |
| FastAPI 路由请求/响应、依赖注入 | `tests/unit/api/` |
| MQ 消费者、核心编排逻辑（Mock 外部） | `tests/unit/core/` |
| 真实基础设施联通、跨模块集成 | `tests/integration/<domain>/` |

文件命名：

- `test_<module>.py`（单元）
- `test_<behavior>_integration.py`（集成）

避免在一个文件混放多个层级的测试。

## Mock 与隔离原则

**单元测试中禁止**：

- ❌ 真实 HTTP 调用（包括 LLM、MinerU、内部 API）
- ❌ 真实数据库连接（包括 MySQL、Redis、Qdrant、ES）
- ❌ 真实 MQ producer/consumer
- ❌ 真实文件系统写入到非临时目录

**单元测试中应当**：

- ✅ 使用 `unittest.mock` / `pytest-mock` 替换外部依赖
- ✅ HTTP 用 `respx` / `httpx.MockTransport`
- ✅ 数据库用 in-memory 或 Mock Session
- ✅ 文件 IO 用 `tmp_path` fixture

## 集成测试启用条件

部分集成测试受单独开关控制，避免误触真实服务：

| 开关 | 影响范围 |
| --- | --- |
| `TOLINK_RUN_REAL_VECTOR_STORAGE_TESTS=true` | 真实 MySQL + Qdrant 向量存储冒烟测试 |
| `--run-integration` flag | 启用 `tests/integration/` 下所有测试 |
| `-m real_env` | 仅运行 `real_env` 标记的测试 |

## Async 测试

`pyproject.toml` 配置：

```toml
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

意味着 `async def test_xxx()` 会被自动识别，无需 `@pytest.mark.asyncio` 装饰。

## 新增测试的检查清单

- [ ] 选对了层级（unit/integration）
- [ ] 文件名符合 `test_<module>.py` 或 `test_<behavior>_integration.py`
- [ ] 单元测试无任何真实外部调用
- [ ] 关键 mock 有 `assert_called_with` 校验
- [ ] 覆盖了成功路径和至少一个失败路径
- [ ] 不依赖测试执行顺序

## 相关文档

- 入门：[tests/README.md](../../tests/README.md)
- 代码风格：[code_style.md](code_style.md)
- 分支与 PR：[branching_and_pr.md](branching_and_pr.md)
