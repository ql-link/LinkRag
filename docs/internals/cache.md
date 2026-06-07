# 缓存基础设施

本文说明 `src/cache/`：基于 Redis 的缓存层，主要服务于 LLM 配置/系统厂商的读多写少场景，并配合 MQ 缓存同步消息做失效。

```text
src/cache/
├── __init__.py        # 导出 redis_client / cache_manager 两个全局单例
├── redis_client.py    # 异步 Redis 连接单例
└── cache_manager.py   # CacheManager + 后端抽象（Redis / Null）
```

---

## 1. Redis 客户端（redis_client.py）

`RedisClient` 是进程级单例（`__new__` 控制），封装 `redis.asyncio`：

- `initialize()`：懒建连接，`redis.from_url(REDIS_URL or REDIS_HOST, password=REDIS_PASSWORD, db=REDIS_DB, decode_responses=True)`。在应用启动（[src/main.py](../../src/main.py)）时调用。
- `close()`：应用关闭时释放连接。
- 模块级全局 `redis_client` 供 `cache_manager` 使用。

配置项：`REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD`，或直接给 `REDIS_URL`（`config.py` 有 `field_validator` 在未显式提供时由 host/port/db/password 拼装）。

---

## 2. 缓存管理器（cache_manager.py）

### 2.1 后端抽象

`CacheBackend`（ABC）定义 `get` / `set` / `delete` / `keys` 四个异步方法，两个实现：

| 后端 | 用途 |
| --- | --- |
| `RedisCacheBackend` | 生产环境，委托给全局 `redis_client` |
| `NullCacheBackend` | 测试环境，所有操作 no-op（`get` 返 `None`，`keys` 返 `[]`） |

抽象后端的意义：测试不必起 Redis，注入 `NullCacheBackend` 即可让缓存逻辑"透明穿透"。

### 2.2 `CacheManager`

在后端之上提供序列化、键管理与失效：

- **JSON 序列化**：`set` 用 `json.dumps(value, default=str)` 写入；`get` 读出后 `json.loads`，解析失败回退原始字符串。
- **TTL**：默认 `DEFAULT_TTL = 600`（10 分钟），`set(key, value, ttl=...)` 可覆盖。
- **键前缀**（集中定义，避免散落硬编码）：
  - `llm:user:{user_id}:config` / `:configs` / `:default` —— 用户 LLM 配置
  - `llm:system:providers` / `llm:system:provider:<type>` —— 系统厂商
  - 配套静态方法 `user_config_key` / `user_configs_key` / `user_default_key` / `system_providers_key` / `system_provider_key` 生成键。
- **批量失效**：`clear_user_cache(user_id)` 按 `llm:user:{id}:*` 删除，`clear_system_cache()` 按 `llm:system:*` 删除。
- 模块级全局 `cache_manager = CacheManager()`，默认 `RedisCacheBackend`。

`__init__.py` 导出 `redis_client` 与 `cache_manager` 两个单例。

---

## 3. 谁在用

| 调用方 | 用途 |
| --- | --- |
| [src/main.py](../../src/main.py) | 启动/关闭时初始化、释放 Redis |
| [src/services/config_reader_service.py](../../src/services/config_reader_service.py) | 读 LLM 用户配置/系统厂商，缓存命中优先 |
| [src/services/cache_sync_service.py](../../src/services/cache_sync_service.py) | 消费 MQ 缓存同步消息后失效对应键 |
| [src/api/recall_session_auth.py](../../src/api/recall_session_auth.py) | 召回会话鉴权相关缓存 |

LLM 配置读取链路见 [llm.md](llm.md)，缓存同步消息契约见 [mq_contracts.md](../api/mq_contracts.md)。

---

## 4. 测试约定

涉及缓存的服务测试注入 `NullCacheBackend`（或 `CacheManager(backend=NullCacheBackend())`），不连真实 Redis；Redis 连通性属于集成测试范围。
