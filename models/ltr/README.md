# LambdaMART model bundles

每个子目录是不可变的生产模型版本，必须同时包含 `model.txt`、`manifest.json`、
`feature_contract.json`、`serving_contract.json`、`short_fallback.json`、`test_vectors.json`
和 `SHA256SUMS`。

服务以 `shadow` 或 `active` 启动时会在 worker thread 预加载，并校验文件哈希、特征签名、LightGBM 版本、
`alias_enabled=false`、候选生成契约以及全部测试向量；任一不一致都拒绝模型并保持
weighted-score 降级路径。候选生成契约冻结模型所依赖的召回路、阈值、融合权重、
Query 分型 TopK 和最终 TopN，防止模型文件正确但线上候选分布已经漂移。训练数据和
评测结果不放在生产仓库。
