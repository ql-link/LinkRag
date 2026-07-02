-- ===============================================
-- LinkRag 系统默认 LLM 配置更新脚本
-- ===============================================
--
-- 用途：存量环境补齐 LinkRag 系统服务厂商、系统默认预设和运行时查询索引。
-- 约定：LinkRag 只注册系统厂商，不写入 llm_provider_model；其模型只写入 llm_system_preset。
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
SET @linkrag_volcengine_encrypted_api_key = 'CHANGE_ME_ENCRYPTED_VOLCENGINE_KEY';

SET @linkrag_asr_model = 'qwen3-asr-flash';
SET @linkrag_asr_display_name = 'Qwen ASR Flash';
SET @linkrag_asr_protocol = 'dashscope';
SET @linkrag_asr_url = 'https://dashscope.aliyuncs.com/api/v1';

SET @linkrag_chat_model = 'deepseek-ai/DeepSeek-V4-Flash';
SET @linkrag_chat_display_name = 'DeepSeek V4 Flash';
SET @linkrag_chat_protocol = 'openai';
SET @linkrag_chat_url = CONCAT(@linkrag_api_base, '/chat/completions');

SET @linkrag_embedding_model = 'BAAI/bge-m3';
SET @linkrag_embedding_display_name = 'BGE-M3';
SET @linkrag_embedding_protocol = 'openai';
SET @linkrag_embedding_url = CONCAT(@linkrag_api_base, '/embeddings');

SET @linkrag_sparse_embedding_model = 'doubao-embedding-vision-251215';
SET @linkrag_sparse_embedding_display_name = 'Doubao Sparse';
SET @linkrag_sparse_embedding_protocol = 'doubao_vision';
SET @linkrag_sparse_embedding_url = 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal';

SET @linkrag_rerank_model = 'BAAI/bge-reranker-v2-m3';
SET @linkrag_rerank_display_name = 'BGE Reranker M3';
SET @linkrag_rerank_protocol = 'jina';
SET @linkrag_rerank_url = CONCAT(@linkrag_api_base, '/rerank');

SET @linkrag_vision_model = 'Qwen/Qwen3.6-27B';
SET @linkrag_vision_display_name = 'Qwen 3.6 27B';
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
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'llm_provider_model'
          AND COLUMN_NAME = 'display_name'
    ) THEN
        ALTER TABLE llm_provider_model
            ADD COLUMN display_name VARCHAR(64) NULL
            COMMENT '模型展示名'
            AFTER model_name;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'llm_system_preset'
          AND COLUMN_NAME = 'display_name'
    ) THEN
        ALTER TABLE llm_system_preset
            ADD COLUMN display_name VARCHAR(64) NULL
            COMMENT '模型展示名'
            AFTER model_name;
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

-- 3. LinkRag 不再写入模型能力目录；清理历史脚本留下的 LinkRag 目录行。
DELETE pm
FROM llm_provider_model pm
JOIN llm_system_provider sp ON sp.id = pm.provider_id
WHERE sp.provider_type = 'linkrag';

-- 4. 同能力下 LinkRag 默认预设唯一：先清理，再写入本脚本指定的默认项
UPDATE llm_system_preset
SET is_default = FALSE,
    updated_at = CURRENT_TIMESTAMP
WHERE provider_type = 'linkrag'
  AND capability IN ('ASR', 'CHAT', 'EMBEDDING', 'SPARSE_EMBEDDING', 'RERANK', 'VISION');

INSERT INTO llm_system_preset
    (provider_id, model_name, display_name, capability, provider_type, protocol, api_base_url,
     api_key, is_active, is_default)
VALUES
    (@linkrag_provider_id, @linkrag_asr_model, @linkrag_asr_display_name, 'ASR', 'linkrag',
     @linkrag_asr_protocol, @linkrag_asr_url, @linkrag_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_chat_model, @linkrag_chat_display_name, 'CHAT', 'linkrag', @linkrag_chat_protocol,
     @linkrag_chat_url, @linkrag_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_embedding_model, @linkrag_embedding_display_name, 'EMBEDDING', 'linkrag',
     @linkrag_embedding_protocol, @linkrag_embedding_url, @linkrag_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_sparse_embedding_model, @linkrag_sparse_embedding_display_name, 'SPARSE_EMBEDDING', 'linkrag',
     @linkrag_sparse_embedding_protocol, @linkrag_sparse_embedding_url, @linkrag_volcengine_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_rerank_model, @linkrag_rerank_display_name, 'RERANK', 'linkrag',
     @linkrag_rerank_protocol, @linkrag_rerank_url, @linkrag_encrypted_api_key, TRUE, TRUE),
    (@linkrag_provider_id, @linkrag_vision_model, @linkrag_vision_display_name, 'VISION', 'linkrag',
     @linkrag_vision_protocol, @linkrag_vision_url, @linkrag_encrypted_api_key, TRUE, TRUE)
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    provider_type = VALUES(provider_type),
    protocol = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    api_key = VALUES(api_key),
    is_active = TRUE,
    is_default = TRUE,
    updated_at = CURRENT_TIMESTAMP;

-- 清理上一版 LinkRag 系统预设，避免前端看到已废弃的只读配置。
DELETE p
FROM llm_system_preset p
JOIN llm_system_provider sp ON sp.id = p.provider_id
WHERE (
    (p.model_name = 'qwen-flash' AND p.capability = 'CHAT')
    OR (p.model_name = 'qwen3-vl-plus' AND p.capability = 'VISION')
    OR (p.model_name = 'Qwen/Qwen3.6-35B-A3B' AND p.capability = 'CHAT')
    OR (p.model_name = 'text-embedding-v3' AND p.capability = 'EMBEDDING')
    OR (p.model_name = 'gte-rerank' AND p.capability = 'RERANK')
    OR (p.model_name = 'bge-m3' AND p.capability = 'SPARSE_EMBEDDING')
    OR (p.model_name = 'zai-org/GLM-4.5V' AND p.capability = 'VISION')
  )
  AND sp.provider_type = 'linkrag';

-- 5. 核对：每个能力应返回且仅返回一条默认 LinkRag 预设
SELECT capability, COUNT(*) AS default_count
FROM llm_system_preset
WHERE provider_type = 'linkrag'
  AND is_active = TRUE
  AND is_default = TRUE
GROUP BY capability
ORDER BY capability;
