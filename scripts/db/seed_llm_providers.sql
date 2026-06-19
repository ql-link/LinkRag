-- =============================================================
-- toLink-Service：LLM 厂商与模型目录精简种子数据
-- 基于远端库 active 模型目录收敛生成（2026-06-17）
-- 厂商：14 个，模型能力记录：83 条
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
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active),
    updated_at   = CURRENT_TIMESTAMP;

COMMIT;
