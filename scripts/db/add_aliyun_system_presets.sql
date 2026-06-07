-- Add Aliyun DashScope system presets for remote dev.
-- Do not store plaintext API keys in llm_system_preset.api_key.
-- api_key below is encrypted with the current tolink.llm.api-key.secret
-- using ApiKeyEncryptService AES-256-GCM format: base64(iv + cipherText + tag).

USE tolink_rag_db;

START TRANSACTION;

-- Provider: Tongyi Qianwen uses the project's existing provider_type "aliyun".
INSERT INTO llm_system_provider (
    provider_type,
    provider_name,
    api_base_url,
    is_active,
    priority
)
VALUES (
    'aliyun',
    'Tongyi Qianwen (DashScope)',
    'https://dashscope.aliyuncs.com/compatible-mode/v1',
    TRUE,
    99
)
ON DUPLICATE KEY UPDATE
    provider_name = VALUES(provider_name),
    api_base_url = VALUES(api_base_url),
    is_active = TRUE,
    priority = GREATEST(priority, VALUES(priority));

-- Ensure the preset models exist in the provider model catalog.
INSERT INTO llm_provider_model (
    provider_id,
    model_name,
    capability,
    is_active
)
SELECT p.id, m.model_name, m.capability, TRUE
FROM llm_system_provider p
JOIN (
    SELECT 'qwen3.5-flash' AS model_name, 'CHAT' AS capability
    UNION ALL SELECT 'text-embedding-v4', 'EMBEDDING'
    UNION ALL SELECT 'qwen3-rerank', 'RERANK'
    UNION ALL SELECT 'qwen-vl-max', 'VISION'
) m
WHERE p.provider_type = 'aliyun'
ON DUPLICATE KEY UPDATE
    is_active = TRUE;

-- Active system presets are copied to new users as is_system_preset=true.
-- Existing matching presets are updated to this key and enabled.
INSERT INTO llm_system_preset (
    provider_id,
    model_name,
    capability,
    api_key,
    is_active
)
SELECT p.id, m.model_name, m.capability,
       'vIgEBTQxRc4g8WU4ghnMpwCOFiFAdN/AxaVwfGLa499SjFlsXJ/0HZ+a1A2qJdnokqPKM/yNlJ1SnF/3MU2+' AS api_key,
       TRUE
FROM llm_system_provider p
JOIN (
    SELECT 'qwen3.5-flash' AS model_name, 'CHAT' AS capability
    UNION ALL SELECT 'text-embedding-v4', 'EMBEDDING'
    UNION ALL SELECT 'qwen3-rerank', 'RERANK'
    UNION ALL SELECT 'qwen-vl-max', 'VISION'
) m
WHERE p.provider_type = 'aliyun'
ON DUPLICATE KEY UPDATE
    api_key = VALUES(api_key),
    is_active = TRUE,
    updated_at = CURRENT_TIMESTAMP;

-- Verification query.
SELECT
    p.provider_type,
    p.provider_name,
    p.api_base_url,
    s.model_name,
    s.capability,
    s.is_active
FROM llm_system_preset s
JOIN llm_system_provider p ON p.id = s.provider_id
WHERE p.provider_type = 'aliyun'
  AND (s.model_name, s.capability) IN (
      ('qwen3.5-flash', 'CHAT'),
      ('text-embedding-v4', 'EMBEDDING'),
      ('qwen3-rerank', 'RERANK'),
      ('qwen-vl-max', 'VISION')
  )
ORDER BY FIELD(s.capability, 'CHAT', 'EMBEDDING', 'RERANK', 'VISION');

COMMIT;

-- Rollback if needed:
-- DELETE s
-- FROM llm_system_preset s
-- JOIN llm_system_provider p ON p.id = s.provider_id
-- WHERE p.provider_type = 'aliyun'
--   AND (s.model_name, s.capability) IN (
--       ('qwen3.5-flash', 'CHAT'),
--       ('text-embedding-v4', 'EMBEDDING'),
--       ('qwen3-rerank', 'RERANK'),
--       ('qwen-vl-max', 'VISION')
--   );
