# Manticore BM25 上线与回滚

本文是生产切换手册。目标不是“一次改开关”，而是在 Qdrant 主读持续可用的前提下，完成
Manticore 双写、存量回填、精确对账、影子读和可回滚切换。

## 1. 上线前硬门槛

以下条件缺一项都不要切主读：

1. Manticore 固定为已验证版本 `27.1.5`，不能使用 `latest`。
2. 生产不是根 Compose 的单节点：已经配置持久卷、备份/恢复和高可用，并做过故障演练。
3. 跨主机的 9306 连接已启用鉴权和 TLS；端口不暴露到公网。应用配置
   `MANTICORE_USER/PASSWORD`、`MANTICORE_SSL_ENABLED=true` 和 `MANTICORE_SSL_CA`。
4. 服务端 `max_connections` 覆盖“应用副本数 × `MANTICORE_POOL_MAXSIZE` + 回填任务 + 运维
   连接”，同时用 cgroup/Kubernetes limit 限制内存和 CPU。
5. `/ready` 返回 200；真实 Manticore 集成测试和固定 BEIR 质量门禁通过。
6. 按真实数据集数量、最大单数据集 chunk 数做容量压测。当前设计是一数据集一张表，表数量
   随数据集线性增长，不能只测单表吞吐。

Manticore 官方说明 9306 的 MySQL 协议支持 SSL；未启用认证时不得把该端口暴露到非可信网络。
服务端 `max_connections` 默认不设限，生产应显式设定。参考：
[MySQL 协议](https://manual.manticoresearch.com/Connecting_to_the_server/MySQL_protocol)、
[searchd 设置](https://manual.manticoresearch.com/Server_settings/Searchd)。

## 2. 基线验证

```bash
TOLINK_RUN_REAL_MANTICORE_TESTS=1 pytest --run-integration -m real_env \
  tests/integration/core/storage/manticore_bm25/test_real_environment.py

python scripts/dev/eval_bm25_recall.py --from-beir /data/nfcorpus --k 10 \
  --with-manticore --manticore-min-recall 0.15 --manticore-min-ndcg 0.31
```

评测使用独立临时表并自动清理。生产固定评测集、阈值和 Manticore 版本应进入发布流水线。

## 3. 开启严格双写

先保持 Qdrant 主读：

```dotenv
BM25_BACKEND=qdrant
BM25_WRITE_BACKENDS=qdrant,manticore
BM25_SHADOW_BACKEND=
BM25_SHADOW_SAMPLE_RATE=0
```

重启所有 API 与 MQ worker。配置在进程内有懒加载缓存，不支持只改环境变量不重启。

双写不是 best-effort：两个后端都确认写入的 chunk 才会把 `es_status` 标记成功；任一后端失败，
解析阶段失败并按现有文档级重试/清理语义处理。文档删除和数据集删除也会尝试所有后端。

## 4. 回填存量

先对一个数据集做 canary，再全量执行：

```bash
python scripts/migrate/qdrant_to_manticore_bm25.py backfill \
  --dataset-id 123 --user-id 456 --page-size 500

python scripts/migrate/qdrant_to_manticore_bm25.py backfill --page-size 500
```

脚本从 MySQL `kb_document_chunk` 的 ACTIVE 记录重做与生产相同的 coarse 分词，按主键顺序分页，
写后逐批回读验证。`--after-id` 可从输出的 checkpoint 续跑；REPLACE 是幂等的。在线回填若未
检测到包含 Manticore 的双写会拒绝运行；只有写冻结的维护窗口才可显式使用
`--allow-unsafe-single-write`。

## 5. 精确对账与修复

```bash
# 只检查；有 missing/orphan 时退出码为 2
python scripts/migrate/qdrant_to_manticore_bm25.py reconcile

# 补 missing、删除 orphan、清理 owner 唯一的孤儿数据集表，再复查
python scripts/migrate/qdrant_to_manticore_bm25.py reconcile --repair
```

对账比较 MySQL ACTIVE chunk 与 Manticore 的完整 chunk_id 集合，不只比较计数；这能识别“数量
相同但内容不同”的假一致。在线写入仍可能与单次扫描交错，因此至少连续两次零差异，间隔覆盖
一轮正常写入/删除流量后，才能进入下一阶段。

## 6. 开启影子读

```dotenv
BM25_BACKEND=qdrant
BM25_WRITE_BACKENDS=qdrant,manticore
BM25_SHADOW_BACKEND=manticore
BM25_SHADOW_SAMPLE_RATE=0.05
BM25_SHADOW_TIMEOUT_SECONDS=10
```

重启后，采样请求会同时查询 Manticore，但线上仍原样返回 Qdrant 结果。日志事件
`[BM25Shadow]` 包含 top-k Jaccard overlap、top1 是否相同及两侧耗时；影子超时/失败只告警，
不降级替换主结果，也不拖慢主链路返回。

建议至少观察一个完整业务周期，并同时满足：

- 固定 qrels 评测仍过门禁；
- 线上 overlap 分布与离线基线相符（当前 NFCorpus 约 0.934，CovidRetrieval 约 0.861）；
- 影子错误/超时率、Manticore P95/P99 延迟和资源水位满足本系统 SLO；
- 再次精确对账连续两次零差异。

## 7. 切主读

保持双写，只互换主读和影子：

```dotenv
BM25_BACKEND=manticore
BM25_WRITE_BACKENDS=qdrant,manticore
BM25_SHADOW_BACKEND=qdrant
BM25_SHADOW_SAMPLE_RATE=0.05
```

滚动重启后检查 `/ready`、错误率、召回空结果率、P95/P99、CPU、RSS、磁盘和表数量。至少保留
Qdrant 双写一个回滚观察期，不要在切流当天清理旧 BM25 collection。

## 8. 回滚

回滚不需要回填，只需恢复 Qdrant 主读并继续双写：

```dotenv
BM25_BACKEND=qdrant
BM25_WRITE_BACKENDS=qdrant,manticore
BM25_SHADOW_BACKEND=manticore
```

滚动重启全部进程并确认 `/ready`。因为观察期始终双写，Qdrant 保持最新；若双写曾连续失败，
应先停止切流、修复故障并重新执行精确对账，而不是强行切换。

观察期结束后若决定只写 Manticore，设置 `BM25_WRITE_BACKENDS=manticore` 并关闭影子读。Qdrant
仍承载 dense/sparse，不能因为 BM25 切换而停止整个 Qdrant 服务；只清理独立 BM25 collection。
