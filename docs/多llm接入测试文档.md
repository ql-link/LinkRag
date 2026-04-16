# 测试规约与执行指南

本文档旨在规范 `toLink-Rag` 项目中各个模块的测试流程、依赖 Mock 策略以及如何执行测试。在此以多 LLM 接入模块 (LLM Module) 为核心切入点。

## 一、 测试分层与策略

我们在项目中主导 **测试驱动开发 (TDD)** 或 **测试先行** 思想，测试种类主要划分为：

1. **单元测试 (Unit Tests)**：
   * **目标**：验证各个核心对象、工厂类、配置解析工具在内存中的纯逻辑表现。
   * **特点**：快速执行，绝对隔离外部依赖，使用 `unittest.mock` 或 `pytest-mock` 对 HTTP 请求及数据库操作进行打桩。
2. **集成测试 (Integration Tests)**：
   * **目标**：验证多个模块或服务层的联合工作能力，例如 `ConfigReaderService` 是否正确地与 SQLAlchemy 会话交互，能否从数据库正确加载模型。
   * **特点**：可能依赖内存型 SQLite 或真实的开发数据库实例，部分测试需要挂载实际的环境变量。
3. **连通性/冒烟测试 (Connectivity/Smoke Tests)**：
   * **目标**：验证中间件与外部系统（如 Milvus, MySQL, Redis, 各家 LLM API）。
   * **特点**：例如之前执行通过的 `test_connectivity.py`，会直接消耗真实的网络请求资源并测试依赖服务的健康度。

## 二、 核心模块测试分布 (LLM Module)

当前针对多 LLM 接入模块的测试主要位于以下目录：

```text
tests/
├── core/
│   └── llm/
│       ├── test_base_provider.py      # BaseProvider 实例化与继承断言测试
│       ├── test_factory.py            # ModelFactory 注册、分发与单例生命周期测试
│       ├── test_circuit_breaker.py    # (待完善) 验证不同状态码下的重试与熔断机制
│       └── test_providers.py          # (待完善) 使用 respx 拦截各厂商 HTTP 请求，测试响应解析
└── services/
    ├── test_cache_sync_service.py     # 缓存一致性保障机制测试
    ├── test_config_reader_integration.py # 基于依赖注入的配置读取综合测试
    └── test_usage_log_service.py      # Token 异步消费日志投递与入库测试
```

## 三、 当前测试状态与真实网络连通测试

目前系统的多 LLM 核心模块包含 **68 个标准级别的测试用例**（涵盖对象鉴权单元测试、配置读取服务集成测试、LLM 工厂生命周期流转等），当网络配置就绪时，**综合通过率为 100% (68/68)**。

除了基于 Mock 的轻量级单元测试外，系统也包含并成功通过了**2 个直连真实厂商 API** 的全链路冒烟集成测试（Fallback Integration Tests）。这类测试脱离了 Mock 夹具，能够验证真实的 HTTP 流量握手、延迟以及大模型数据包的协议解析场景。


**核心真实测试脚本：**
`tests/core/llm/test_system_fallback_integration.py`

**验证内容（基于真实的 `SYSTEM_LLM_API_KEY`）：**
1. **Chat / 文本生成模块**：使用 `qwen3.5-flash` 发起真实问候并成功获取带有 Token usage 的返回包裹。
2. **Embedding / 向量化模块**：使用 `text-embedding-v4` 将短文本打入获取 `1024` 维的真实浮点数向量。

> **注意：** 运行这些真实的网络集成测试时，请确保本地的 `.env` 中填充了有效的 `API_KEY`，否则这些用例将检测到未配置状态并主动跳过 (`SKIPPED`)，防止因为伪造 Key 引起的不必要报错。

## 四、 Mock 最佳实践

### 3.1 外部 HTTP 请求的 Mock
在测试 OpenAI、Claude、Qwen 等具体提供商 (Provider) 的时候，**严禁使用真实 API Key 发起网络请求**。
建议引入 `respx` 或 `httpx-mock` 截获 HTTP 调用。

```python
import respx
import httpx

@respx.mock
async def test_openai_provider_generate():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Mocked Response"}}],
            "usage": {"total_tokens": 100}
        })
    )
    # 调用 Provider
```

### 3.2 数据库 Session 的 Mock
在测试服务层时，建议通过 `MagicMock` 覆盖 SQLAlchemy `AsyncSession`：

```python
from unittest.mock import AsyncMock

async def test_config_reader():
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    
    service = ConfigReaderService(db=mock_db)
    result = await service.get_user_default_config("user_123")
    assert result is None
```

## 四、 常用测试执行命令

执行项目测试需要使用 `pytest`。确保你已通过虚拟环境或容器激活了依赖。

1. **运行全量测试**
   ```bash
   pytest tests/ -v
   ```

2. **按目录或指定文件运行测试**
   ```bash
   pytest tests/core/llm/ -v
   # 或
   pytest tests/core/llm/test_factory.py -v
   ```

3. **执行环境连通性测试 (跳过部分不需要验证的中间件)**
   ```bash
   pytest tests/test_connectivity.py -v
   ```

4. **开启覆盖率检查 (需要安装 pytest-cov)**
    ```bash
    pytest tests/ --cov=src --cov-report=term-missing
    ```

## 六、 GitHub Actions / CI 规范
提交 PR (Pull Request) 前，应当在本地执行核心模块测试。系统将在主分支保护规则中强制要求：
- 构建过程中的 `pytest tests/core/` 不能有任何失败。
- 覆盖率维持或有所上升才允许被 Merge。
