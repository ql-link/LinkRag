# Redis 与 LLM Runtime Cache

LLM 运行缓存只做 `config_id -> RuntimeModelConfig` 物理行快照，不保存默认选择、授权判定或数据集绑定。
MySQL `llm_model_config` 始终是最终事实源；Redis 故障时 fail-open 回源 MySQL，不改变缺失、停用、越权或能力不匹配的结果。

## Key 与版本栅栏

- 数据：`cache:llm:runtime-config:{llm-runtime:<config_id>}`
- 栅栏：`cache:fence:llm:runtime-config:{llm-runtime:<config_id>}`
- 单飞锁：`cache:lock:llm:runtime-config:{llm-runtime:<config_id>}`

引用同一 hash tag 便于 Redis Cluster 上原子 Lua 执行。缓存 envelope 携带 `fence_version` 和数据库
`snapshot_version`。Java 配置事务提交后执行失效：先递增 fence，再删数据 key。Python 慢回源只有在
`expected_fence == current_fence` 时才允许回填，因此不能把失效前的旧快照复活。

## 一致性边界

1. Python 命中缓存后仍由 resolver 检查 `is_active`、`scope/owner_user_id` 和 `capability`。
2. miss 时用短 TTL 单飞锁抑制穿透；未抢锁者短暂读取已回填值，仍可直接回源。
3. 缓存读/写/锁任意异常均不吞 MySQL 事实。
4. 用户密钥在 DB 与缓存中均为密文，只在构造 provider 前解密，不记录日志。

`src/api/recall_session_auth.py` 的并发槽计数也使用 Redis，但与 LLM runtime cache 是独立能力，不得使用
`llm:*` 宽泛删除或清空整库。
