# LambdaMART model bundles

每个子目录是不可变的生产模型版本，必须同时包含 `model.txt`、`manifest.json`、
`feature_contract.json`、`short_fallback.json`、`test_vectors.json` 和 `SHA256SUMS`。

服务首次进入 `shadow` 或 `active` 时会校验文件哈希、特征签名、LightGBM 版本、
`alias_enabled=false` 以及全部测试向量；任一不一致都拒绝模型并保持 weighted-score
降级路径。训练数据和评测结果不放在生产仓库。
