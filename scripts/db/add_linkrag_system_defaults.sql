-- ===============================================
-- LinkRag 系统默认 LLM 配置更新脚本
-- ===============================================
--
-- 用途：存量环境补齐 LinkRag 系统服务厂商、系统默认预设和运行时查询索引。
-- 执行前必须确认下方变量中的真实 API 地址、协议、模型名和加密后的 Key。
--
-- 执行示例：
--   mysql -h 127.0.0.1 -P 3306 -u root -p tolink_rag_db < scripts/db/add_linkrag_system_defaults.sql
-- ===============================================

SET NAMES utf8mb4;

-- ===== 上线前按环境修改这些值 =====
SET @linkrag_api_base = 'https://api.siliconflow.cn/v1';
SET @linkrag_default_protocol = 'openai';
SET @linkrag_encrypted_api_key = 'CHANGE_ME_ENCRYPTED_SILICONFLOW_KEY';

SET @linkrag_chat_model = 'Qwen/Qwen3.6-35B-A3B';
SET @linkrag_chat_protocol = 'openai';
SET @linkrag_chat_url = CONCAT(@linkrag_api_base, '/chat/completions');

SET @linkrag_embedding_model = 'BAAI/bge-m3';
SET @linkrag_embedding_protocol = 'openai';
SET @linkrag_embedding_url = CONCAT(@linkrag_api_base, '/embeddings');

-- 稀疏向量链路需要 token_id -> weight 的 sparse lexical weights。
-- 硅基流动 OpenAI-compatible embeddings 不能直接替代当前 protocol=bge_m3 的响应结构，
-- 因此 SPARSE_EMBEDDING 仍指向 LinkRag 自部署 bge-m3-service；它不需要额外外部 API Key。
SET @linkrag_sparse_embedding_model = 'bge-m3';
SET @linkrag_sparse_embedding_protocol = 'bge_m3';
SET @linkrag_sparse_embedding_url = 'http://103.205.254.30:37997/encode';

SET @linkrag_rerank_model = 'BAAI/bge-reranker-v2-m3';
SET @linkrag_rerank_protocol = 'jina';
SET @linkrag_rerank_url = CONCAT(@linkrag_api_base, '/rerank');

SET @linkrag_vision_model = 'zai-org/GLM-4.5V';
SET @linkrag_vision_protocol = 'openai';
SET @linkrag_vision_url = CONCAT(@linkrag_api_base, '/chat/completions');

-- 1. 补结构：llm_system_preset.is_default + 查询索引
DROP PROCEDURE IF EXISTS add_linkrag_system_default_schema;

DELIMITER //
CREATE PROCEDURE add_linkrag_system_default_schema()
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'llm_system_preset'
          AND COLUMN_NAME = 'is_default'
    ) THEN
        ALTER TABLE llm_system_preset
            ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT FALSE
            COMMENT '是否为该能力当前生效的 LinkRag 系统默认预设'
            AFTER is_active;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'llm_system_preset'
          AND INDEX_NAME = 'idx_preset_provider_cap_default'
    ) THEN
        ALTER TABLE llm_system_preset
            ADD INDEX idx_preset_provider_cap_default
                (provider_type, capability, is_active, is_default);
    END IF;
END//
DELIMITER ;

CALL add_linkrag_system_default_schema();
DROP PROCEDURE IF EXISTS add_linkrag_system_default_schema;

-- 2. LinkRag 系统厂商
INSERT INTO llm_system_provider
    (provider_type, provider_name, api_base_url, default_protocol, is_active, priority)
VALUES
    ('linkrag', 'LinkRag', @linkrag_api_base, @linkrag_default_protocol, TRUE, 100)
ON DUPLICATE KEY UPDATE
    provider_name = VALUES(provider_name),
    api_base_url = VALUES(api_base_url),
    default_protocol = VALUES(default_protocol),
    is_active = TRUE,
    priority = VALUES(priority),
    updated_at = CURRENT_TIMESTAMP;

SET @linkrag_provider_id = (
    SELECT id FROM llm_system_provider WHERE provider_type = 'linkrag' LIMIT 1
);

-- 3. LinkRag 模型能力目录
INSERT INTO llm_provider_model
    (provider_id, model_name, capability, protocol, api_base_url, is_active)
VALUES
    (@linkrag_provider_id, @linkrag_chat_model, 'CHAT', @linkrag_chat_protocol, @linkrag_chat_url, TRUE),
    (@linkrag_provider_id, @linkrag_embedding_model, 'EMBEDDING', @linkrag_embedding_protocol, @linkrag_embedding_url, TRUE),
    (@linkrag_provider_id, @linkrag_sparse_embedding_model, 'SPARSE_EMBEDDING', @linkrag_sparse_embedding_protocol, @linkrag_sparse_embedding_url, TRUE),
    (@linkrag_provider_id, @linkrag_rerank_model, 'RERANK', @linkrag_rerank_protocol, @linkrag_rerank_url, TRUE),
    (@linkrag_provider_id, @linkrag_vision_model, 'VISION', @linkrag_vision_protocol, @linkrag_vision_url, TRUE)
ON DUPLICATE KEY UPDATE
    protocol = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active = TRUE,
    updated_at = CURRENT_TIMESTAMP;

-- BGE-M3 是 LinkRag 自部署能力，不再挂在第三方厂商下。
DELETE pm
FROM llm_provider_model pm
JOIN llm_system_provider sp ON sp.id = pm.provider_id
WHERE pm.model_name = @linkrag_sparse_embedding_model
  AND pm.capability = 'SPARSE_EMBEDDING'
  AND sp.provider_type <> 'linkrag';

-- 4. 同能力下 LinkRag 默认预设唯一：先清理，再写入本脚本指定的默认项
UPDATE llm_system_preset
SET is_default = FALSE,
    updated_at = CURRENT_TIMESTAMP
WHERE provider_type = 'linkrag'
  AND capability IN ('CHAT', 'EMBEDDING', 'SPARSE_EMBEDDING', 'RERANK', 'VISION');

INSERT INTO llm_system_preset
    (provider_id, model_name, capability, provider_type, protocol, api_base_url,
     api_key, is_active, is_default)
VALUES
    (@linkrag_provider_id, @linkrag_chat_model, 'CHAT', 'linkrag', @linkrag_chat_protocol,
     @linkrag_chat_url, @linkrag_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_embedding_model, 'EMBEDDING', 'linkrag',
     @linkrag_embedding_protocol, @linkrag_embedding_url, @linkrag_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_sparse_embedding_model, 'SPARSE_EMBEDDING', 'linkrag',
     @linkrag_sparse_embedding_protocol, @linkrag_sparse_embedding_url, @linkrag_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_rerank_model, 'RERANK', 'linkrag',
     @linkrag_rerank_protocol, @linkrag_rerank_url, @linkrag_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_vision_model, 'VISION', 'linkrag',
     @linkrag_vision_protocol, @linkrag_vision_url, @linkrag_encrypted_api_key, TRUE, TRUE)
ON DUPLICATE KEY UPDATE
    provider_type = VALUES(provider_type),
    protocol = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    api_key = VALUES(api_key),
    is_active = TRUE,
    is_default = TRUE,
    updated_at = CURRENT_TIMESTAMP;

-- 5. 核对：每个能力应返回且仅返回一条默认 LinkRag 预设
SELECT capability, COUNT(*) AS default_count
FROM llm_system_preset
WHERE provider_type = 'linkrag'
  AND is_active = TRUE
  AND is_default = TRUE
GROUP BY capability
ORDER BY capability;
