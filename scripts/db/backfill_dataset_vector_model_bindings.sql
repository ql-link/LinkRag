-- 回填历史 dataset_parse_config 的向量模型绑定。
--
-- 口径：按每个用户当前启用的默认用户配置回填，不使用系统预设。
-- - dense_embedding_config_id 取 capability='EMBEDDING'
-- - sparse_embedding_config_id 取 capability='SPARSE_EMBEDDING'
-- 若某用户缺少对应默认配置，该用户的数据集会保持 NULL，Python 解析/召回会明确失败。

UPDATE dataset_parse_config d
LEFT JOIN (
    SELECT user_id, MAX(id) AS config_id
    FROM llm_user_config
    WHERE capability = 'EMBEDDING'
      AND is_default = TRUE
      AND is_active = TRUE
      AND is_system_preset = FALSE
    GROUP BY user_id
) dense_cfg ON dense_cfg.user_id = d.user_id
LEFT JOIN (
    SELECT user_id, MAX(id) AS config_id
    FROM llm_user_config
    WHERE capability = 'SPARSE_EMBEDDING'
      AND is_default = TRUE
      AND is_active = TRUE
      AND is_system_preset = FALSE
    GROUP BY user_id
) sparse_cfg ON sparse_cfg.user_id = d.user_id
SET
    d.dense_embedding_config_id = COALESCE(d.dense_embedding_config_id, dense_cfg.config_id),
    d.sparse_embedding_config_id = COALESCE(d.sparse_embedding_config_id, sparse_cfg.config_id)
WHERE d.dense_embedding_config_id IS NULL
   OR d.sparse_embedding_config_id IS NULL;

-- 回填后检查仍未补齐的数据集。
SELECT
    d.user_id,
    d.dataset_id,
    d.dense_embedding_config_id,
    d.sparse_embedding_config_id
FROM dataset_parse_config d
WHERE d.dense_embedding_config_id IS NULL
   OR d.sparse_embedding_config_id IS NULL
ORDER BY d.user_id, d.dataset_id;
