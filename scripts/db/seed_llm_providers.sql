-- =============================================================
-- toLink-Service：LLM 厂商与模型目录种子数据
-- 数据来源：远端 dev 库导出（精简版，2026-06-19）
-- 厂商：46 个，模型能力记录：90 条（89 条远端导出 + 1 条本地新增 doubao_vision 稀疏）
-- =============================================================

USE tolink_rag_db;

START TRANSACTION;

-- ─── 1. 厂商基本信息 ──────────────────────────────────────────
INSERT INTO llm_system_provider (provider_type, provider_name, api_base_url, default_protocol, is_active, priority)
VALUES
    ('302ai', '302.AI', 'https://api.302.ai', 'openai', TRUE, 50),
    ('aliyun', 'Aliyun', 'https://dashscope.aliyuncs.com', 'openai', TRUE, 99),
    ('astraflow', 'Astraflow', 'https://api.modelverse.cn/v1', 'openai', TRUE, 50),
    ('avian', 'avian', 'https://api.avian.io', 'openai', TRUE, 50),
    ('baichuan', 'Baichuan', 'https://api.baichuan-ai.com/v1', 'openai', TRUE, 50),
    ('baidu', 'Baidu', 'https://qianfan.baidubce.com/v2', 'openai', TRUE, 50),
    ('claude', 'Anthropic', 'https://api.anthropic.com', 'anthropic', TRUE, 99),
    ('cohere', 'CoHere', 'https://api.cohere.com', 'openai', TRUE, 50),
    ('cometapi', 'CometAPI', 'https://api.cometapi.com', 'openai', TRUE, 50),
    ('deepinfra', 'DeepInfra', 'https://api.deepinfra.com', 'openai', TRUE, 50),
    ('deepseek', 'DeepSeek', 'https://api.deepseek.com', 'openai', TRUE, 99),
    ('futurmix', 'FuturMix', 'https://futurmix.ai', 'openai', TRUE, 50),
    ('gemini', 'Google', 'https://generativelanguage.googleapis.com', 'google', TRUE, 99),
    ('gitee', 'Gitee', 'https://api.moark.ai/v1', 'openai', TRUE, 50),
    ('glm', 'ZHIPU-AI', 'https://open.bigmodel.cn/api/paas/v4', 'openai', TRUE, 99),
    ('groq', 'Groq', 'https://api.groq.com/openai/v1', 'openai', TRUE, 50),
    ('huaweicloud', 'HuaweiCloud', 'https://api.modelarts-maas.com', 'openai', TRUE, 50),
    ('huggingface', 'HuggingFace', 'https://router.huggingface.co/v1', 'openai', TRUE, 99),
    ('hunyuan', 'HunYuan', 'https://api.hunyuan.cloud.tencent.com/v1', 'openai', TRUE, 50),
    ('jiekouai', 'JieKouAI', 'https://api.jiekou.ai', 'openai', TRUE, 50),
    ('jina', 'Jina', 'https://api.jina.ai/v1', 'jina', TRUE, 50),
    ('longcat', 'LongCat', 'https://api.longcat.chat', 'openai', TRUE, 50),
    ('mimo', 'Xiaomi MiMo Token Plan', 'https://token-plan-cn.xiaomimimo.com/v1', 'openai', TRUE, 50),
    ('minimax', 'MiniMax', 'https://api.minimaxi.com/', 'openai', TRUE, 98),
    ('mistral', 'Mistral', 'https://api.mistral.ai', 'openai', TRUE, 50),
    ('moonshot', 'Moonshot', 'https://api.moonshot.cn/v1', 'openai', TRUE, 99),
    ('n1n', 'n1n', 'https://api.n1n.ai', 'openai', TRUE, 50),
    ('novita', 'Novita', 'https://api.novita.ai', 'openai', TRUE, 50),
    ('nvidia', 'Nvidia', 'https://integrate.api.nvidia.com/v1', 'openai', TRUE, 50),
    ('openai', 'OpenAI', 'https://api.openai.com/v1', 'openai', TRUE, 99),
    ('openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1', 'openai', TRUE, 98),
    ('orcarouter', 'OrcaRouter', 'https://api.orcarouter.ai', 'openai', TRUE, 50),
    ('perplexity', 'Perplexity', 'https://api.perplexity.ai', 'openai', TRUE, 50),
    ('ppio', 'PPIO', 'https://api.ppio.com/openai/v1', 'openai', TRUE, 50),
    ('qiniu', 'Qiniu', 'https://api.qnaigc.com/v1', 'openai', TRUE, 50),
    ('replicate', 'Replicate', 'https://api.replicate.com', 'openai', TRUE, 50),
    ('siliconflow', 'SiliconFlow', 'https://api.siliconflow.cn/v1', 'openai', TRUE, 50),
    ('stepfun', 'StepFun', 'https://api.stepfun.ai/v1', 'openai', TRUE, 50),
    ('togetherai', 'TogetherAI', 'https://api.together.ai/v1', 'openai', TRUE, 50),
    ('tokenhub', 'TokenHub', 'https://aitok.cc/v1', 'openai', TRUE, 50),
    ('tokenpony', 'TokenPony', 'https://api.tokenpony.cn/v1', 'openai', TRUE, 50),
    ('upstage', 'Upstage', 'https://api.upstage.ai/v1', 'openai', TRUE, 50),
    ('volcengine', 'VolcEngine', 'https://ark.cn-beijing.volces.com/api/v3', 'openai', TRUE, 50),
    ('voyage', 'Voyage', 'https://api.voyageai.com', 'openai', TRUE, 50),
    ('xai', 'xAI', 'https://api.x.ai/v1', 'openai', TRUE, 99),
    ('xunfei', 'XunFei', 'https://spark-api-open.xf-yun.com', 'openai', TRUE, 50)
ON DUPLICATE KEY UPDATE
    provider_name    = VALUES(provider_name),
    api_base_url     = VALUES(api_base_url),
    default_protocol = VALUES(default_protocol),
    is_active        = VALUES(is_active),
    priority         = VALUES(priority);

-- ─── 2. 模型能力目录（一模型多能力 = 多行）──────────────────────
-- 用子查询取 provider_id，避免依赖具体 ID 值

-- 302.AI (302ai)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'claude-3-7-sonnet-20250219', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-embeddings-v3', 'EMBEDDING', 'openai', 'https://api.302.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'mistral-ocr-latest', 'OCR', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'whisper-v3-turbo', 'ASR', 'openai', 'https://api.302.ai/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Aliyun (aliyun)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gte-rerank', 'RERANK', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-flash', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-vl-max', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-vl-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-asr-flash', 'ASR', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-max', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-rerank', 'RERANK', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-vl-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v3', 'EMBEDDING', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v4', 'EMBEDDING', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Baichuan (baichuan)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'Baichuan-Text-Embedding', 'EMBEDDING', 'openai', 'https://api.baichuan-ai.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4-Air', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4-Turbo', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Baidu (baidu)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'embedding-v1', 'EMBEDDING', 'openai', 'https://qianfan.baidubce.com/v2/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'ernie-5.0', 'VISION', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'paddleocr-vl-0.9b', 'OCR', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Anthropic (claude)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'claude-3-5-sonnet-20241022', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-20250219', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-8', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-8', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- DeepSeek (deepseek)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek-v4-flash', 'CHAT', 'openai', 'https://api.deepseek.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'deepseek'
UNION ALL
    SELECT id, 'deepseek-v4-pro', 'CHAT', 'openai', 'https://api.deepseek.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'deepseek'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Google (gemini)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gemini-2.5-flash', 'CHAT', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-3-pro-preview', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-embedding-001', 'EMBEDDING', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- ZHIPU-AI (glm)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'embedding-3', 'EMBEDDING', 'openai', 'https://open.bigmodel.cn/api/paas/v4/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6v-Flash', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6v-Flash', 'VISION', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
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
    SELECT id, 'glm-asr-2512', 'ASR', 'openai', 'https://open.bigmodel.cn/api/paas/v4/audio/transcriptions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-ocr', 'OCR', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- HunYuan (hunyuan)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'hunyuan-embedding', 'EMBEDDING', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-pro', 'CHAT', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Jina (jina)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'jina-embeddings-v4', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-text-nano', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-text-small', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-m0', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v3', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Xiaomi MiMo Token Plan (mimo)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'mimo-v2.5', 'CHAT', 'openai', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'mimo'
UNION ALL
    SELECT id, 'mimo-v2.5', 'VISION', 'openai', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'mimo'
UNION ALL
    SELECT id, 'mimo-v2.5-asr', 'ASR', 'openai', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'mimo'
UNION ALL
    SELECT id, 'mimo-v2.5-pro', 'CHAT', 'openai', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'mimo'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Moonshot (moonshot)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'kimi-k2-thinking', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-thinking-turbo', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.6', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.6', 'VISION', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-latest', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- OpenAI (openai)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.5', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING', 'openai', 'https://api.openai.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'whisper-1', 'ASR', 'openai', 'https://api.openai.com/v1/audio/transcriptions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- VolcEngine (volcengine)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'doubao-embedding-vision-251215', 'EMBEDDING', 'openai', 'https://ark.cn-beijing.volces.com/api/v3/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'volcengine'
UNION ALL
    SELECT id, 'doubao-embedding-vision-251215', 'SPARSE_EMBEDDING', 'doubao_vision', 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal', TRUE FROM llm_system_provider WHERE provider_type = 'volcengine'
UNION ALL
    SELECT id, 'doubao-seed-2-0-pro-260215', 'CHAT', 'openai', 'https://ark.cn-beijing.volces.com/api/v3/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'volcengine'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- xAI (xai)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'grok-3-fast', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-4', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

COMMIT;
