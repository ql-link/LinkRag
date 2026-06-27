-- =============================================================
-- toLink-Service：LLM 厂商与模型目录精简种子数据
-- 基于远端库 active 模型目录收敛生成（2026-06-17）
-- 厂商：15 个，模型能力记录：89 条（83 条运营白名单 + 1 条 doubao_vision + 5 条 LinkRag 系统能力）
-- 说明：只保留当前运营白名单；protocol/api_base_url 为模型能力层事实来源。
-- =============================================================

USE tolink_rag_db;

START TRANSACTION;

-- ─── 1. 厂商基本信息 ──────────────────────────────────────────
INSERT INTO llm_system_provider (
    provider_type, provider_name, api_base_url, default_protocol, is_active, priority
)
VALUES
    ('aliyun', 'Aliyun', 'https://dashscope.aliyuncs.com', 'openai', TRUE, 99),
    ('claude', 'Anthropic', 'https://api.anthropic.com', 'anthropic', TRUE, 99),
    ('deepseek', 'DeepSeek', 'https://api.deepseek.com', 'openai', TRUE, 99),
    ('gemini', 'Google', 'https://generativelanguage.googleapis.com', 'google', TRUE, 99),
    ('glm', 'ZHIPU-AI', 'https://open.bigmodel.cn/api/paas/v4', 'openai', TRUE, 99),
    ('moonshot', 'Moonshot', 'https://api.moonshot.cn/v1', 'openai', TRUE, 99),
    ('openai', 'OpenAI', 'https://api.openai.com/v1', 'openai', TRUE, 99),
    ('xai', 'xAI', 'https://api.x.ai/v1', 'openai', TRUE, 99),
    ('baichuan', 'Baichuan', 'https://api.baichuan-ai.com/v1', 'openai', TRUE, 50),
    ('baidu', 'Baidu', 'https://qianfan.baidubce.com/v2', 'openai', TRUE, 50),
    ('hunyuan', 'HunYuan', 'https://api.hunyuan.cloud.tencent.com/v1', 'openai', TRUE, 50),
    ('jina', 'Jina', 'https://api.jina.ai/v1', 'jina', TRUE, 50),
    ('linkrag', 'LinkRag', 'https://api.siliconflow.cn/v1', 'openai', TRUE, 100),
    ('mimo', 'Xiaomi MiMo Token Plan', 'https://token-plan-cn.xiaomimimo.com/v1', 'openai', TRUE, 50),
    ('volcengine', 'VolcEngine', 'https://ark.cn-beijing.volces.com/api/v3', 'openai', TRUE, 50)
ON DUPLICATE KEY UPDATE
    provider_name    = VALUES(provider_name),
    api_base_url     = VALUES(api_base_url),
    default_protocol = VALUES(default_protocol),
    is_active        = VALUES(is_active),
    priority         = VALUES(priority),
    updated_at       = CURRENT_TIMESTAMP;

-- ─── 2. 模型能力目录（一模型多能力 = 多行）──────────────────────
INSERT INTO llm_provider_model (
    provider_id, model_name, capability, protocol, api_base_url, is_active
)
    SELECT id, 'qwen3-asr-flash', 'ASR', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-flash', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-max', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v3', 'EMBEDDING', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v4', 'EMBEDDING', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'gte-rerank', 'RERANK', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-rerank', 'RERANK', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-vl-max', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-vl-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-vl-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-20250219', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-8', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-sonnet-20241022', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-8', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'deepseek-v4-flash', 'CHAT', 'openai', 'https://api.deepseek.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'deepseek'
UNION ALL
    SELECT id, 'deepseek-v4-pro', 'CHAT', 'openai', 'https://api.deepseek.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'deepseek'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'CHAT', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-embedding-001', 'EMBEDDING', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-3-pro-preview', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'glm-asr-2512', 'ASR', 'openai', 'https://open.bigmodel.cn/api/paas/v4/audio/transcriptions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6v-Flash', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.7', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.7-flashx', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-5', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-5-turbo', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-5v-turbo', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'embedding-3', 'EMBEDDING', 'openai', 'https://open.bigmodel.cn/api/paas/v4/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6v-Flash', 'VISION', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'kimi-k2-thinking', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-thinking-turbo', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.6', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-latest', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.6', 'VISION', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'whisper-1', 'ASR', 'openai', 'https://api.openai.com/v1/audio/transcriptions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.5', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING', 'openai', 'https://api.openai.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'grok-3-fast', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-4', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'Baichuan4', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4-Air', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4-Turbo', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-Text-Embedding', 'EMBEDDING', 'openai', 'https://api.baichuan-ai.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'embedding-v1', 'EMBEDDING', 'openai', 'https://qianfan.baidubce.com/v2/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'ernie-5.0', 'VISION', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'hunyuan-pro', 'CHAT', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-embedding', 'EMBEDDING', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'jina-embeddings-v4', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-text-nano', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-text-small', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-m0', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v3', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-V4-Flash', 'CHAT', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'linkrag'
UNION ALL
    SELECT id, 'BAAI/bge-m3', 'EMBEDDING', 'openai', 'https://api.siliconflow.cn/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'linkrag'
UNION ALL
    SELECT id, 'BAAI/bge-reranker-v2-m3', 'RERANK', 'jina', 'https://api.siliconflow.cn/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'linkrag'
UNION ALL
    SELECT id, 'Qwen/Qwen3.6-27B', 'VISION', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'linkrag'
UNION ALL
    SELECT id, 'mimo-v2.5-asr', 'ASR', 'openai', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'mimo'
UNION ALL
    SELECT id, 'mimo-v2.5', 'CHAT', 'openai', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'mimo'
UNION ALL
    SELECT id, 'mimo-v2.5-pro', 'CHAT', 'openai', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'mimo'
UNION ALL
    SELECT id, 'mimo-v2.5', 'VISION', 'openai', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'mimo'
UNION ALL
    SELECT id, 'doubao-seed-2-0-pro-260215', 'CHAT', 'openai', 'https://ark.cn-beijing.volces.com/api/v3/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'volcengine'
UNION ALL
    SELECT id, 'doubao-embedding-vision-251215', 'EMBEDDING', 'openai', 'https://ark.cn-beijing.volces.com/api/v3/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'volcengine'
UNION ALL
    SELECT id, 'doubao-embedding-vision-251215', 'SPARSE_EMBEDDING', 'doubao_vision', 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal', TRUE FROM llm_system_provider WHERE provider_type = 'volcengine'
UNION ALL
    -- 稀疏向量默认走火山引擎多模态 embedding sparse 输出。
    -- 用户配置复制本目录的模型 url（无手填入口），故此处直接落完整端点；与 doubao 一致：api_base_url 即完整 url，adapter 直打不拼接。
    SELECT id, 'doubao-embedding-vision-251215', 'SPARSE_EMBEDDING', 'doubao_vision', 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal', TRUE FROM llm_system_provider WHERE provider_type = 'linkrag'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active),
    updated_at   = CURRENT_TIMESTAMP;

-- 清理历史 LinkRag 目录行。
DELETE pm
FROM llm_provider_model pm
JOIN llm_system_provider sp ON sp.id = pm.provider_id
WHERE (
    (pm.model_name = 'qwen-flash' AND pm.capability = 'CHAT')
    OR (pm.model_name = 'qwen3-vl-plus' AND pm.capability = 'VISION')
    OR (pm.model_name = 'Qwen/Qwen3.6-35B-A3B' AND pm.capability = 'CHAT')
    OR (pm.model_name = 'text-embedding-v3' AND pm.capability = 'EMBEDDING')
    OR (pm.model_name = 'gte-rerank' AND pm.capability = 'RERANK')
    OR (pm.model_name = 'zai-org/GLM-4.5V' AND pm.capability = 'VISION')
    OR (pm.model_name = 'bge-m3' AND pm.capability = 'SPARSE_EMBEDDING')
  )
  AND sp.provider_type = 'linkrag';

-- 全厂商模型展示名回填；真实调用仍使用 model_name。
DROP TEMPORARY TABLE IF EXISTS tmp_llm_model_display_names;

CREATE TEMPORARY TABLE tmp_llm_model_display_names AS
SELECT
    id,
    CASE
        WHEN model_name = 'qwen3-asr-flash' THEN 'Qwen ASR Flash'
        WHEN model_name = 'deepseek-ai/DeepSeek-V4-Flash' THEN 'DeepSeek V4 Flash'
        WHEN model_name = 'Qwen/Qwen3.6-27B' THEN 'Qwen 3.6 27B'
        WHEN model_name = 'bge-m3' THEN 'BGE-M3'
        WHEN model_name = 'doubao-seed-2-0-pro-260215' THEN 'Doubao Seed 2.0 Pro'
        WHEN model_name = 'BAAI/bge-m3' THEN 'BGE-M3'
        WHEN model_name = 'BAAI/bge-reranker-v2-m3' THEN 'BGE Reranker M3'
        WHEN model_name = 'doubao-embedding-vision-251215' AND capability = 'SPARSE_EMBEDDING' THEN 'Doubao Sparse'
        WHEN model_name = 'doubao-embedding-vision-251215' THEN 'Doubao Vision Embedding'
        WHEN clean_name REGEXP '^chatgpt ' THEN CONCAT('ChatGPT ', REGEXP_REPLACE(clean_name, '^chatgpt ', ''))
        WHEN clean_name REGEXP '^gpt ' THEN CONCAT('GPT ', REGEXP_REPLACE(clean_name, '^gpt ', ''))
        WHEN clean_name REGEXP '^qwen' THEN CONCAT('Qwen ', REGEXP_REPLACE(clean_name, '^qwen ?', ''))
        WHEN clean_name REGEXP '^claude' THEN CONCAT('Claude ', REGEXP_REPLACE(clean_name, '^claude ?', ''))
        WHEN clean_name REGEXP '^gemini' THEN CONCAT('Gemini ', REGEXP_REPLACE(clean_name, '^gemini ?', ''))
        WHEN clean_name REGEXP '^deepseek' THEN CONCAT('DeepSeek ', REGEXP_REPLACE(clean_name, '^deepseek ?', ''))
        WHEN clean_name REGEXP '^glm' THEN CONCAT('GLM ', REGEXP_REPLACE(clean_name, '^glm ?', ''))
        WHEN clean_name REGEXP '^kimi' THEN CONCAT('Kimi ', REGEXP_REPLACE(clean_name, '^kimi ?', ''))
        WHEN clean_name REGEXP '^moonshot kimi' THEN CONCAT('Kimi ', REGEXP_REPLACE(clean_name, '^moonshot kimi ?', ''))
        WHEN clean_name REGEXP '^grok' THEN CONCAT('Grok ', REGEXP_REPLACE(clean_name, '^grok ?', ''))
        WHEN clean_name REGEXP '^jina' THEN CONCAT('Jina ', REGEXP_REPLACE(clean_name, '^jina ?', ''))
        WHEN clean_name REGEXP '^doubao' THEN CONCAT('Doubao ', REGEXP_REPLACE(clean_name, '^doubao ?', ''))
        WHEN clean_name REGEXP '^mimo' THEN CONCAT('MiMo ', REGEXP_REPLACE(clean_name, '^mimo ?', ''))
        WHEN clean_name REGEXP '^hunyuan' THEN CONCAT('Hunyuan ', REGEXP_REPLACE(clean_name, '^hunyuan ?', ''))
        WHEN clean_name REGEXP '^baichuan' THEN CONCAT('Baichuan ', REGEXP_REPLACE(clean_name, '^baichuan ?', ''))
        WHEN clean_name REGEXP '^ernie' THEN CONCAT('ERNIE ', REGEXP_REPLACE(clean_name, '^ernie ?', ''))
        WHEN clean_name REGEXP '^whisper' THEN CONCAT('Whisper ', REGEXP_REPLACE(clean_name, '^whisper ?', ''))
        WHEN clean_name REGEXP '^llama' THEN CONCAT('Llama ', REGEXP_REPLACE(clean_name, '^llama ?', ''))
        WHEN clean_name REGEXP '^mistral' THEN CONCAT('Mistral ', REGEXP_REPLACE(clean_name, '^mistral ?', ''))
        WHEN clean_name REGEXP '^mixtral' THEN CONCAT('Mixtral ', REGEXP_REPLACE(clean_name, '^mixtral ?', ''))
        WHEN clean_name REGEXP '^text embedding' THEN CONCAT('Text Embedding ', REGEXP_REPLACE(clean_name, '^text embedding ?', ''))
        WHEN clean_name REGEXP '^embedding ' THEN CONCAT('Embedding ', REGEXP_REPLACE(clean_name, '^embedding ', ''))
        WHEN clean_name REGEXP '^gte rerank' THEN CONCAT('GTE Rerank ', REGEXP_REPLACE(clean_name, '^gte rerank ?', ''))
        WHEN clean_name REGEXP '^bge ' THEN CONCAT('BGE ', REGEXP_REPLACE(clean_name, '^bge ', ''))
        WHEN clean_name REGEXP '^o[0-9]' THEN TRIM(CONCAT(UPPER(SUBSTRING(clean_name, 1, 2)), ' ', REGEXP_REPLACE(clean_name, '^o[0-9] ?', '')))
        ELSE clean_name
    END AS display_name
FROM (
    SELECT
        id,
        provider_type,
        model_name,
        capability,
        TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(
                REGEXP_REPLACE(raw_name, ' [0-9]{4} [0-9]{2} [0-9]{2}$', ''),
                ' [0-9]{8}$', ''
            ),
            ' [0-9]{2} [0-9]{2}$', ''
        )) AS clean_name
    FROM (
        SELECT
            pm.id,
            sp.provider_type,
            pm.model_name,
            pm.capability,
            TRIM(REGEXP_REPLACE(
                REPLACE(REPLACE(REPLACE(LOWER(SUBSTRING_INDEX(pm.model_name, '/', -1)), '_', ' '), '-', ' '), ':', ' '),
                ' +', ' '
            )) AS raw_name
        FROM llm_provider_model pm
        JOIN llm_system_provider sp ON sp.id = pm.provider_id
    ) raw_models
) normalized_models;

UPDATE tmp_llm_model_display_names
SET display_name = TRIM(REGEXP_REPLACE(display_name, ' +', ' '));

UPDATE tmp_llm_model_display_names
SET display_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   display_name,
                   ' flash', ' Flash'),
                   ' pro', ' Pro'),
                   ' mini', ' Mini'),
                   ' nano', ' Nano'),
                   ' turbo', ' Turbo'),
                   ' latest', ' Latest'),
                   ' preview', ' Preview'),
                   ' embedding', ' Embedding'),
                   ' embeddings', ' Embeddings'),
                   ' reranker', ' Reranker'),
                   ' sonnet', ' Sonnet'),
                   ' opus', ' Opus'),
                   ' haiku', ' Haiku'),
                   ' thinking', ' Thinking'),
                   ' instruct', ' Instruct'),
                   ' vision', ' Vision'),
                   ' chat', ' Chat'),
                   ' large', ' Large'),
                   ' small', ' Small'),
                   ' max', ' Max');

UPDATE tmp_llm_model_display_names
SET display_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   display_name,
                   ' asr', ' ASR'),
                   ' vl', ' VL'),
                   ' r1', ' R1'),
                   ' r2', ' R2'),
                   ' k2', ' K2'),
                   ' v1', ' V1'),
                   ' v2', ' V2'),
                   ' v3', ' V3'),
                   ' v4', ' V4'),
                   ' v5', ' V5');

UPDATE tmp_llm_model_display_names
SET display_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   display_name,
                   ' plus', ' Plus'),
                   ' long', ' Long'),
                   ' coder', ' Coder'),
                   ' reasoner', ' Reasoner'),
                   ' distill', ' Distill'),
                   ' base', ' Base'),
                   ' multilingual', ' Multilingual'),
                   ' maverick', ' Maverick'),
                   ' air', ' Air'),
                   ' seed', ' Seed');

UPDATE tmp_llm_model_display_names
SET display_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   display_name,
                   ' rerank', ' Rerank'),
                   ' clip', ' CLIP'),
                   ' beta', ' Beta'),
                   ' instruct', ' Instruct'),
                   ' a3b', ' A3B');

UPDATE tmp_llm_model_display_names
SET display_name = LEFT(display_name, 64);

UPDATE llm_provider_model pm
JOIN tmp_llm_model_display_names d ON d.id = pm.id
SET pm.display_name = d.display_name,
    pm.updated_at = CURRENT_TIMESTAMP
WHERE d.display_name IS NOT NULL
  AND d.display_name <> '';

UPDATE llm_system_preset p
JOIN llm_provider_model pm
  ON pm.provider_id = p.provider_id
 AND pm.model_name = p.model_name
 AND pm.capability = p.capability
SET p.display_name = pm.display_name,
    p.updated_at = CURRENT_TIMESTAMP
WHERE pm.display_name IS NOT NULL
  AND pm.display_name <> '';

DROP TEMPORARY TABLE IF EXISTS tmp_llm_model_display_names;

COMMIT;
