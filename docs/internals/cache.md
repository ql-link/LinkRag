# Redis 基础设施

`src/cache/` 保留通用异步 Redis 客户端和缓存后端抽象，但 LLM 配置与系统厂商不再使用 Redis 缓存。

```text
src/cache/
├── __init__.py
├── redis_client.py    # 异步 Redis 连接单例
└── cache_manager.py   # 通用 CacheManager + Redis/Null 后端抽象
```

## 当前边界

- `ConfigReaderService` 的用户配置、系统预设、系统厂商和模型目录读取均直接执行 MySQL 查询；构造函数不再接受 `CacheManager`，读方法不再接受 `use_cache`。
- 已删除 LLM 专用 key 常量、key 生成方法、批量失效方法和 `cache_sync_service.py`。
- 已删除 `CacheSyncMessage`、`tolink.rag.cache_sync` topic 初始化和 `/api/v1/mq/send/cache-sync` HTTP 调试入口。
- 加密 API Key 只保存在共享 MySQL 中。读取后仅在 `user_model_resolver` 构造模型客户端时解密，不写 Redis、不记录日志。

## 仍在使用 Redis 的能力

- 应用生命周期仍初始化并关闭 `RedisClient`。
- `src/api/recall_session_auth.py` 使用 Redis 原子计数维护召回 session 并发槽位；这属于跨实例协调，不是 MySQL 数据副本，不能随业务缓存删除。
- `CacheBackend`、`RedisCacheBackend`、`NullCacheBackend` 与通用 `CacheManager.get/set/delete` 保留，供独立缓存需求复用。

历史 `llm:user:*`、`llm:system:*` key 由 Java 仓发布清理脚本统一清理；不得使用宽泛 `llm:*` 或清空整个 Redis DB，以免误删召回并发计数等其他数据。
