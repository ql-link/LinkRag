# Redis 运行配置缓存

MySQL 始终是事实源。Python 只缓存两类精确数据库事实：全局 `config_id` 对应的物理 LLM
运行配置，以及 Java/Python 共用的 `dataset_parse_config` 原始行快照。用户默认、SYSTEM 默认、
目录和列表查询始终读取 MySQL；Redis 故障时直接回源，不改变执行、授权或错误语义。

## Dataset 原始快照

三键与 Java 完全一致：

- 数据：`cache:dataset:parse-config:{dataset-config:<dataset_id>}`
- 栅栏：`cache:fence:dataset:parse-config:{dataset-config:<dataset_id>}`
- 单飞锁：`cache:lock:dataset:parse-config:{dataset-config:<dataset_id>}`

data 使用 `schemaVersion=1` 的 `FOUND/NOT_FOUND` envelope。FOUND value 只包含 `user_id`、
`dataset_id`、五个模型配置 ID、四类原始 JSON 和 `is_active`；Java 的响应展示默认与 Python
的运行期 `Settings` 均不得写回 value。Python 命中后才由 `DatasetConfigService` 合并 Settings，
因此同一份快照可同时服务 Java 管理接口和 Python 执行链。

正常快照 TTL 为 7 天并增加 0～300 秒抖动，NOT_FOUND 为 60 秒。未知版本、字段不全、
user/dataset 不匹配视为 MISS，并执行 `fence++ + DEL data` 后回源。全部命中时不查询
`dataset_parse_config`；Redis 读取、协调或回填失败时直接返回 MySQL 事实。

`DATASET_PARSE_CONFIG_CACHE_ENABLED` 默认关闭。只有 Java `BusinessCacheHealthIndicator` 显示
CDC mapping、补偿消费者和数据库镜像缓存全部 READY 后，Python 部署才允许开启，避免只有读缓存
而没有可靠失效链。

从旧 Java key 升级时，先关闭 Java 数据库镜像缓存和该 Python 开关，完成全部实例升级后再按
“Java health READY → Java 写缓存 → Python 读缓存”的顺序开启。旧的无 hash-tag key 让原 TTL
自然淘汰；不要使用 `cache:dataset:parse-config:*` 宽泛删除，因为它也会匹配新的共享 key。

## LLM Runtime Cache

LLM 运行缓存只做 `config_id -> RuntimeModelConfig` 物理行快照，不保存默认选择、授权判定或
数据集绑定。

- 数据：`cache:llm:runtime-config:{llm-runtime:<config_id>}`
- 栅栏：`cache:fence:llm:runtime-config:{llm-runtime:<config_id>}`
- 单飞锁：`cache:lock:llm:runtime-config:{llm-runtime:<config_id>}`

正常值 TTL 24 小时并增加 0～300 秒抖动；`NOT_FOUND` 负缓存 60 秒。版本不兼容、结构非法值
删除后回源。缓存中只保存数据库密文，不保存明文密钥、已构建 client、授权结果或 capability
判定结果。

## Key、版本栅栏与故障边界

每一类 data/fence/lock 都引用同一 hash tag，便于 Redis Cluster 上原子 Lua 执行。Java 配置事务
提交后执行失效：先递增 fence，再删数据 key。Python 慢回源只有在
`expected_fence == current_fence` 时才允许回填，因此不能把失效前的旧快照复活。

1. Dataset 命中后仍在 Python 内存中合并 Settings；LLM 命中后仍由 resolver 检查
   `is_active`、`scope/owner_user_id` 和 `capability`。
2. miss 时用短 TTL 单飞锁抑制穿透；未抢锁者短暂读取已回填值，仍可直接回源。
3. 缓存读/写/锁任意异常均不吞 MySQL 事实。
4. 用户密钥在 DB 与 LLM runtime cache 中均为密文，只在构造 provider 前解密，不记录日志。

两类缓存共用 `FencedJsonCacheStore` 的 Redis 原子实现，但各自拥有独立 key 家族、TTL 和开关。
`src/api/recall_concurrency.py` 的并发槽计数也是独立能力，不得使用宽泛删除或清空整库。
