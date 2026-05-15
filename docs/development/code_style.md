# Code Style

代码格式化与静态检查工具的统一约定。

## 工具与配置

配置集中在 [pyproject.toml](../../pyproject.toml)：

| 工具 | 版本 | 用途 | 关键配置 |
| --- | --- | --- | --- |
| `black` | `>=24.1` | 代码格式化 | `line-length=100`, `target-version=py310` |
| `isort` | `>=5.13` | import 排序 | `profile=black`, `line_length=100` |
| `mypy` | `>=1.8` | 静态类型检查 | 渐进启用 |

## 常用命令

```bash
# 一次性格式化全部源码
black src tests

# 排序所有 import
isort src tests

# 检查（不修改）
black --check src tests
isort --check-only src tests

# 类型检查
mypy src
```

提交前推荐顺序：`isort` → `black` → `mypy` → `pytest`。

## Line Length

统一 **100 字符**。`black` 与 `isort` 都已对齐这个值，IDE 配置同步即可。

## Python 版本

最低支持 **Python 3.10**。允许使用：

- 结构化模式匹配（`match`）
- 类型联合（`int | str`）
- `typing.ParamSpec`、`typing.Self`

避免使用 3.11+ 才有的特性（如 `typing.LiteralString`、`tomllib`）。

## Imports

由 `isort` 自动管理，分组规则：

1. 标准库
2. 第三方库
3. 本地（`src.*`、`tests.*`）

组内字母序，组间空行。不要手动调整组顺序。

## 类型注解

| 场景 | 要求 |
| --- | --- |
| 公共函数/方法签名 | ✅ 必须有完整类型注解 |
| Pydantic 模型字段 | ✅ 必须，否则无法序列化 |
| 私有 helper / 局部变量 | ⬜ 推荐，按需 |
| 简单 lambda / 短闭包 | ⬜ 可省 |

返回类型 `None` 也应显式写出 `-> None`，便于 mypy 检查。

## 文档字符串

- **不要**为简单 getter / setter / 自解释方法写 docstring。
- **要**为公共接口、复杂业务逻辑、非显然行为写 docstring。
- 风格：Google / NumPy 风格皆可，保持单一文件内一致。
- 中文 / 英文皆可，单一文件内一致即可。

## 异常处理

- 不要 `except:` 或 `except Exception:` 然后忽略——必须重新抛出或转换成业务异常。
- 模块内部错误应封装为模块自定义异常，参考 [src/core/mq/exceptions.py](../../src/core/mq/exceptions.py)。
- 失败时记录足够上下文（task_id、外部资源 key 等）。

## 异步代码

- 项目以 `asyncio` 为主，FastAPI 路由优先用 `async def`。
- 阻塞调用（如同步 `requests`、`pymysql`）必须放在 `run_in_executor` 或换成异步库。
- 数据库选 `aiomysql`，HTTP 选 `httpx`，Kafka 选 `aiokafka`。

## 命名

详细规则见 [docs/conventions/naming_conventions.md](../conventions/naming_conventions.md)。要点：

- 模块名：小写下划线
- 类名：PascalCase
- 函数/变量：snake_case
- 常量：UPPER_SNAKE_CASE
- 私有标识：前置单下划线 `_internal`

## 不做的事

- ❌ 不引入新的 lint / formatter（如 ruff），除非有团队决议
- ❌ 不为通过 lint 写空 docstring 占位
- ❌ 不在源码里关闭 mypy 检查（`# type: ignore`），除非有第三方库限制并加注释
- ❌ 不混用 tab 和空格

## 相关文档

- 命名约定：[../conventions/naming_conventions.md](../conventions/naming_conventions.md)
- 测试规范：[testing.md](testing.md)
