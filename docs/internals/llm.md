# LLM Module

本文说明 `src/core/llm` LLM 能力模块的架构、配置来源、调用链，以及新增 Provider 的方法。

## 1. 模块框架

```text
src/core/llm/
├── interfaces.py          # 能力接口：文本、向量化、重排、OCR、视觉
├── base_provider.py       # Provider 基类
├── factory.py             # ModelFactory 注册式工厂
├── response.py            # APIResponse 和模型结果对象
├── encryption.py          # API Key 加解密辅助
├── circuit_breaker.py     # Provider 熔断
├── tokenizer.py           # token 估算
├── exceptions.py          # LLM 异常类型
└── providers/
    ├── openai.py
    ├── anthropic.py
    ├── glm.py
    ├── deepseek.py
    └── qwen.py
```

相关服务：

```text
src/services/
├── config_reader_service.py # MySQL + Redis 读取用户/系统 LLM 配置
├── cache_sync_service.py    # MQ 驱动的配置缓存失效
└── usage_log_service.py     # LLM 用量统计
```

HTTP 入口：

```text
src/api/routes/llm.py       # 用户级 LLM 调用
src/api/routes/internal.py  # Java 管理端内部配置和用量查询
```

## 2. 调用链

用户级 API：

```text
/api/v1/llm/*
  -> ConfigReaderService
    -> llm_user_config / llm_system_provider
    -> Redis cache
  -> ModelFactory
    -> Provider
      -> generate / stream / embed / rerank / extract_text
```

系统内部链路：

```text
ParseTaskService / ChunkEmbeddingPipeline / MarkdownEnhancementOrchestrator
  -> ModelFactory or Provider client
  -> 解析/分块内置配置或用户配置
```

## 3. 核心角色

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `CapabilityType` | `interfaces.py` | 定义 `TEXT/EMBEDDING/RERANK/OCR/VISION/TOOL_CALLING` |
| `BaseProvider` | `base_provider.py` | Provider 公共属性和能力判断 |
| `ModelFactory` | `factory.py` | 注册 Provider，按用户配置或配置 ID 创建客户端 |
| `ConfigReaderService` | `src/services/config_reader_service.py` | 读取用户配置、系统厂商、`user_id=0` 系统预设并管理缓存 |
| `CacheSyncService` | `src/services/cache_sync_service.py` | 消费缓存同步消息，失效用户配置缓存 |
| `UsageLogService` | `src/services/usage_log_service.py` | 记录和汇总 LLM 用量 |
| Provider 实现 | `providers/*.py` | 对接具体厂商 API |

## 4. 配置来源

运行时配置统一来自：

- 数据库 `llm_system_provider`
- 数据库 `llm_user_config`
- Redis 配置缓存
- `src/config.py::Settings` 中的解析/分块内部增强配置

用户 API 使用请求头 `X-User-Id` 读取用户配置。若用户指定 `config_id`，按配置 ID 获取，且只允许读取当前用户配置或 `user_id=0` 系统预设；配置不存在、未启用、无权限时不 fallback。若用户未指定 `config_id`，按接口能力类型先查询当前用户默认配置，未命中再查询 `llm_user_config.user_id=0` 的系统预设默认配置。

用户 LLM API 不再使用 Python `SYSTEM_LLM_*` 环境变量作为默认配置兜底。`SYSTEM_LLM_*` 目前只服务于 Markdown 增强、图片增强、语义分块等解析/分块内部链路。

API Key 不应写入文档、测试或提交配置。用户配置中的密钥由数据库密文保存，读取后通过 `ConfigReaderService.decrypt_api_key()` 解密使用。

## 5. 能力映射

| API/链路 | 能力 | 典型用途 |
| --- | --- | --- |
| `/api/v1/llm/generate` | `TEXT` / `CHAT` 配置 | 非流式文本生成 |
| `/api/v1/llm/generate/stream` | `TEXT` / `CHAT` 配置 | SSE 流式文本生成 |
| `/api/v1/llm/embed` | `EMBEDDING` | 文本向量化 |
| `/api/v1/llm/rerank` | `RERANK` | 文档重排 |
| `/api/v1/llm/ocr` | `OCR` / `VISION` | 图像文本提取 |
| Markdown 图片增强 | `VISION` | 图片说明生成 |
| Markdown 表格增强 | `TEXT` | 表格摘要生成 |
| Chunk 向量化 | `EMBEDDING` | Qdrant 向量写入 |

## 6. 新增 Provider

1. 在 `src/core/llm/providers/` 下新增 Provider 文件。
2. 继承 `BaseProvider`，实现对应能力方法。
3. 在 `ModelFactory._register_default_providers()` 注册默认 Provider，或通过 `register_provider()` 在启动逻辑中注册。
4. 在 `llm_system_provider` 中维护厂商元数据和 `supported_capabilities`。
5. 如需配置示例，同步 `.env.example` 和 `docs/api/http_contracts.md`。
6. 增加 `tests/unit/core/llm` 单元测试。

## 7. 测试建议

```bash
.venv/bin/pytest tests/unit/core/llm -q
.venv/bin/pytest tests/unit/services/test_cache_sync_service.py -q
.venv/bin/pytest tests/integration/core/llm -q
```

建议覆盖：

- Provider 注册和恢复默认注册。
- 按 `config_id` 和能力类型选择配置。
- `user_id=0` 系统预设配置。
- API Key 解密和脱敏。
- Provider 异常映射、限流、连接失败和熔断。
