-- =============================================================
-- toLink-Service：LLM 厂商与模型目录种子数据
-- 由 scripts/import_ragflow_configs.py 自动生成，请勿手动编辑
-- 数据来源：RAGFlow conf/ 目录（2026-06-06 导出）
-- 厂商：45 个，模型能力记录：868 条
-- =============================================================

USE tolink_rag_db;

START TRANSACTION;

-- ─── 1. 厂商基本信息 ──────────────────────────────────────────
INSERT INTO llm_system_provider (provider_type, provider_name, api_base_url, default_protocol, is_active, priority)
VALUES
    ('302ai', '302.AI', 'https://api.302.ai', 'openai', FALSE, 50),
    ('aliyun', 'Aliyun', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'openai', TRUE, 99),
    ('claude', 'Anthropic', 'https://api.anthropic.com', 'anthropic', TRUE, 99),
    ('astraflow', 'Astraflow', 'https://api.modelverse.cn/v1', 'openai', FALSE, 50),
    ('avian', 'avian', 'https://api.avian.io', 'openai', FALSE, 50),
    ('baichuan', 'Baichuan', 'https://api.baichuan-ai.com/v1', 'openai', TRUE, 50),
    ('baidu', 'Baidu', 'https://qianfan.baidubce.com/v2', 'openai', TRUE, 50),
    ('cohere', 'CoHere', 'https://api.cohere.com', 'openai', FALSE, 50),
    ('cometapi', 'CometAPI', 'https://api.cometapi.com', 'openai', FALSE, 50),
    ('deepinfra', 'DeepInfra', 'https://api.deepinfra.com', 'openai', FALSE, 50),
    ('deepseek', 'DeepSeek', 'https://api.deepseek.com/v1', 'openai', TRUE, 99),
    ('futurmix', 'FuturMix', 'https://futurmix.ai', 'openai', FALSE, 50),
    ('gitee', 'Gitee', 'https://api.moark.ai/v1', 'openai', FALSE, 50),
    ('gemini', 'Google', 'https://generativelanguage.googleapis.com/v1beta', 'google', TRUE, 99),
    ('groq', 'Groq', 'https://api.groq.com/openai/v1', 'openai', FALSE, 50),
    ('huaweicloud', 'HuaweiCloud', 'https://api.modelarts-maas.com', 'openai', FALSE, 50),
    ('huggingface', 'HuggingFace', 'https://router.huggingface.co/v1', 'openai', FALSE, 99),
    ('hunyuan', 'HunYuan', 'https://api.hunyuan.cloud.tencent.com/v1', 'openai', TRUE, 50),
    ('jiekouai', 'JieKouAI', 'https://api.jiekou.ai', 'openai', FALSE, 50),
    ('jina', 'Jina', 'https://api.jina.ai/v1', 'jina', TRUE, 50),
    ('longcat', 'LongCat', 'https://api.longcat.chat', 'openai', FALSE, 50),
    ('minimax', 'MiniMax', 'https://api.minimaxi.com/', 'openai', FALSE, 98),
    ('mistral', 'Mistral', 'https://api.mistral.ai', 'openai', FALSE, 50),
    ('moonshot', 'Moonshot', 'https://api.moonshot.cn/v1', 'openai', TRUE, 99),
    ('n1n', 'n1n', 'https://api.n1n.ai', 'openai', FALSE, 50),
    ('novita', 'Novita', 'https://api.novita.ai', 'openai', FALSE, 50),
    ('nvidia', 'Nvidia', 'https://integrate.api.nvidia.com/v1', 'openai', FALSE, 50),
    ('openai', 'OpenAI', 'https://api.openai.com/v1', 'openai', TRUE, 99),
    ('openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1', 'openai', FALSE, 98),
    ('orcarouter', 'OrcaRouter', 'https://api.orcarouter.ai', 'openai', FALSE, 50),
    ('perplexity', 'Perplexity', 'https://api.perplexity.ai', 'openai', FALSE, 50),
    ('ppio', 'PPIO', 'https://api.ppio.com/openai/v1', 'openai', FALSE, 50),
    ('qiniu', 'Qiniu', 'https://api.qnaigc.com/v1', 'openai', FALSE, 50),
    ('replicate', 'Replicate', 'https://api.replicate.com', 'openai', FALSE, 50),
    ('siliconflow', 'SiliconFlow', 'https://api.siliconflow.cn/v1', 'openai', FALSE, 50),
    ('stepfun', 'StepFun', 'https://api.stepfun.ai/v1', 'openai', FALSE, 50),
    ('togetherai', 'TogetherAI', 'https://api.together.ai/v1', 'openai', FALSE, 50),
    ('tokenhub', 'TokenHub', 'https://aitok.cc/v1', 'openai', FALSE, 50),
    ('tokenpony', 'TokenPony', 'https://api.tokenpony.cn/v1', 'openai', FALSE, 50),
    ('upstage', 'Upstage', 'https://api.upstage.ai/v1', 'openai', FALSE, 50),
    ('volcengine', 'VolcEngine', 'https://ark.cn-beijing.volces.com/api/v3', 'openai', TRUE, 50),
    ('voyage', 'Voyage', 'https://api.voyageai.com', 'openai', FALSE, 50),
    ('xai', 'xAI', 'https://api.x.ai/v1', 'openai', TRUE, 99),
    ('xunfei', 'XunFei', 'https://spark-api-open.xf-yun.com/v1', 'openai', TRUE, 50),
    ('glm', 'ZHIPU-AI', 'https://open.bigmodel.cn/api/paas/v4', 'openai', TRUE, 99)
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
    SELECT id, 'kimi-k2.6', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'kimi-k2.6', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.5', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.2-pro', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.2-pro', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.2', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.2', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.1', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.1', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-nano', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-nano', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.5-preview', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-3.5-turbo', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-3.5-turbo-16k-0613', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'whisper-v3-turbo', 'ASR', 'openai', 'https://api.302.ai/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'mistral-ocr-latest', 'OCR', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-embeddings-v3', 'EMBEDDING', 'openai', 'https://api.302.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-reranker-v2-base-multilingual', 'RERANK', 'openai', 'https://api.302.ai', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'deepseek-chat', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'chatgpt-4o-latest', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'llama3.3-70b', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'deepseek-reasoner', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gemini-2.0-flash', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-20250219', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-latest', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'grok-3-beta', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'grok-3-mini-beta', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'o3', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'o4-mini', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gemini-2.5-pro-preview-05-06', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'llama-4-maverick', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'CHAT', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'claude-opus-4-20250514', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION', 'openai', 'https://api.302.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-clip-v2', 'EMBEDDING', 'openai', 'https://api.302.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-reranker-m0', 'RERANK', 'openai', 'https://api.302.ai', FALSE FROM llm_system_provider WHERE provider_type = '302ai'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Aliyun (aliyun)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'qwen-flash', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v4', 'EMBEDDING', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v3', 'EMBEDDING', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-rerank', 'RERANK', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-122b-a10b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'Moonshot-Kimi-K2-Instruct', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-v3.2', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-v3', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-qwen-1.5b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-qwen-14b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-qwen-32b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-llama-8b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-llama-70b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwq-32b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwq-plus', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus-2025-07-28', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus-2025-07-14', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwq-plus-latest', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-flash-2025-07-28', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus-2026-02-15', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus-2026-02-15', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash-2026-02-23', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash-2026-02-23', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-max', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-coder-480b-a35b-instruct', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-30b-a3b-instruct-2507', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-30b-a3b-thinking-2507', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-30b-a3b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-vl-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-vl-235b-a22b-instruct', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-vl-235b-a22b-thinking', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-instruct-2507', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-thinking-2507', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-instruct', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-thinking', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-0.6b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-1.7b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-4b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-8b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-14b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-long', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-turbo', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-turbo-2025-04-28', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-turbo-latest', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-max', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus-2025-04-28', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus-latest', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v2', 'EMBEDDING', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-vl-max', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-vl-plus', 'VISION', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'gte-rerank', 'RERANK', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-asr-flash', 'ASR', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-asr-flash-2025-09-08', 'ASR', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qianwen-deepresearch-30b-a3b-131k', 'CHAT', 'openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'gte-rerank-v2', 'RERANK', 'dashscope', 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank', TRUE FROM llm_system_provider WHERE provider_type = 'aliyun'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Anthropic (claude)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'claude-opus-4-8', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-8', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-5-20251101', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-5-20251101', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-1-20250805', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-1-20250805', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-20250514', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-20250514', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-20250219', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-20250219', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-sonnet-20241022', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-sonnet-20241022', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-haiku-20241022', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-haiku-20241022', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-haiku-20240307', 'CHAT', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-haiku-20240307', 'VISION', 'anthropic', 'https://api.anthropic.com/v1/messages', TRUE FROM llm_system_provider WHERE provider_type = 'claude'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Astraflow (astraflow)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'text-embedding-3-large', 'EMBEDDING', 'openai', 'https://api.modelverse.cn/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'bge-reranker-v2-m3', 'RERANK', 'openai', 'https://api.modelverse.cn/v1', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Max', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Coder', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-32B', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-VL-235B-A22B-Instruct', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'kimi-k2.6', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'glm-5.1', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'MiniMax-M2.7', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'MiniMax-M2', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'CHAT', 'openai', 'https://api.modelverse.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'qwen3-embedding-8b', 'EMBEDDING', 'openai', 'https://api.modelverse.cn/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'text-embedding-ada-002', 'EMBEDDING', 'openai', 'https://api.modelverse.cn/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'astraflow'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- avian (avian)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek/deepseek-v4-pro', 'CHAT', 'openai', 'https://api.avian.io/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'deepseek/deepseek-v4-flash', 'CHAT', 'openai', 'https://api.avian.io/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.2', 'CHAT', 'openai', 'https://api.avian.io/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.5', 'CHAT', 'openai', 'https://api.avian.io/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'z-ai/glm-5', 'CHAT', 'openai', 'https://api.avian.io/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'minimax/minimax-m2.5', 'CHAT', 'openai', 'https://api.avian.io/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'avian'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Baichuan (baichuan)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'Baichuan4', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4-Air', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4-Turbo', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-M3', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-M3-plus', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-M2-plus', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-M2', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan3-Turbo', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan3-Turbo-128k', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan2-Turbo', 'CHAT', 'openai', 'https://api.baichuan-ai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-Text-Embedding', 'EMBEDDING', 'openai', 'https://api.baichuan-ai.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'baichuan'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Baidu (baidu)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek-v3.2', 'CHAT', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'deepseek-v4-flash', 'CHAT', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'deepseek-v4-pro', 'CHAT', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'qwen3-4b', 'CHAT', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'ernie-5.0', 'VISION', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'embedding-v1', 'EMBEDDING', 'openai', 'https://qianfan.baidubce.com/v2/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'qwen3-reranker-4b', 'RERANK', 'openai', 'https://qianfan.baidubce.com/v2', FALSE FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'paddleocr-vl-0.9b', 'OCR', 'openai', 'https://qianfan.baidubce.com/v2/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'baidu'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- CoHere (cohere)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'command-a-plus-05-2026', 'CHAT', 'openai', 'https://api.cohere.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-a-03-2025', 'CHAT', 'openai', 'https://api.cohere.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-r7b-12-2024', 'CHAT', 'openai', 'https://api.cohere.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-a-translate-08-2025', 'CHAT', 'openai', 'https://api.cohere.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-a-reasoning-08-2025', 'CHAT', 'openai', 'https://api.cohere.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-a-vision-07-2025', 'CHAT', 'openai', 'https://api.cohere.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-r-plus-08-2024', 'CHAT', 'openai', 'https://api.cohere.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-r-08-2024', 'CHAT', 'openai', 'https://api.cohere.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-v4.0-pro', 'RERANK', 'openai', 'https://api.cohere.com', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-v4.0-fast', 'RERANK', 'openai', 'https://api.cohere.com', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-v3.5', 'RERANK', 'openai', 'https://api.cohere.com', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-english-v3.0', 'RERANK', 'openai', 'https://api.cohere.com', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-multilingual-v3.0', 'RERANK', 'openai', 'https://api.cohere.com', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-v4.0', 'EMBEDDING', 'openai', 'https://api.cohere.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-english-v3.0', 'EMBEDDING', 'openai', 'https://api.cohere.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-english-light-v3.0', 'EMBEDDING', 'openai', 'https://api.cohere.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-multilingual-v3.0', 'EMBEDDING', 'openai', 'https://api.cohere.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-multilingual-light-v3.0', 'EMBEDDING', 'openai', 'https://api.cohere.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'cohere-transcribe-03-2026', 'ASR', 'openai', 'https://api.cohere.com/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'cohere'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- CometAPI (cometapi)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gpt-5.5', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-3-pro-preview', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-3-pro-preview', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-v3.2', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'text-embedding-3-small', 'EMBEDDING', 'openai', 'https://api.cometapi.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING', 'openai', 'https://api.cometapi.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'text-embedding-ada-002', 'EMBEDDING', 'openai', 'https://api.cometapi.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'whisper-1', 'ASR', 'openai', 'https://api.cometapi.com/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'chatgpt-4o-latest', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5-mini', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5-nano', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4.1', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'o4-mini-2025-04-16', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'o3-pro-2025-06-10', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-opus-4-1-20250805', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-opus-4-1-20250805-thinking', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514-thinking', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-latest', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-3-5-haiku-latest', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-2.5-flash-lite', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-2.0-flash', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'grok-4-0709', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'grok-3', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'grok-3-mini', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'grok-2-image-1212', 'VISION', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-v3.1', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-v3', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-r1-0528', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-chat', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-reasoner', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'qwen3-30b-a3b', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'qwen3-coder-plus-2025-07-22', 'CHAT', 'openai', 'https://api.cometapi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'cometapi'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- DeepInfra (deepinfra)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek-ai/DeepSeek-V3.2', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Embedding-4B', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'bosonai/HiggsAudioV2.5', 'ASR', 'openai', 'https://api.deepinfra.com/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'moonshotai/Kimi-K2-Instruct', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'mistralai/Voxtral-Small-24B-2507', 'ASR', 'openai', 'https://api.deepinfra.com/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'mistralai/Voxtral-Mini-3B-2507', 'ASR', 'openai', 'https://api.deepinfra.com/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-R1-0528-Turbo', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-235B-A22B', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-30B-A3B', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-32B', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-14B', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-V3-0324-Turbo', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-Turbo', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-4-Scout-17B-16E-Instruct', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-R1-0528', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-V3-0324', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'mistralai/Devstral-Small-2507', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'mistralai/Mistral-Small-3.2-24B-Instruct-2506', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-Guard-4-12B', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/QwQ-32B', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'anthropic/claude-4-opus', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'anthropic/claude-4-sonnet', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemini-2.5-flash', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemini-2.5-pro', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemma-3-27b-it', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemma-3-12b-it', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemma-3-4b-it', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'microsoft/Phi-4-multimodal-instruct', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-R1-Distill-Llama-70B', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-V3', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-3.3-70B-Instruct', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'microsoft/phi-4', 'CHAT', 'openai', 'https://api.deepinfra.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'openai/whisper-large-v3-turbo', 'ASR', 'openai', 'https://api.deepinfra.com/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-base-en-v1.5', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-en-icl', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-large-en-v1.5', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-m3', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-m3-multi', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Embedding-0.6B', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Embedding-8B', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'intfloat/e5-base-v2', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'intfloat/e5-large-v2', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'intfloat/multilingual-e5-large', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'intfloat/multilingual-e5-large-instruct', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/all-MiniLM-L12-v2', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/all-MiniLM-L6-v2', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/all-mpnet-base-v2', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/clip-ViT-B-32', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/clip-ViT-B-32-multilingual-v1', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/multi-qa-mpnet-base-dot-v1', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/paraphrase-MiniLM-L6-v2', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'shibing624/text2vec-base-chinese', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'thenlper/gte-base', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'thenlper/gte-large', 'EMBEDDING', 'openai', 'https://api.deepinfra.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'deepinfra'
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

-- FuturMix (futurmix)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gpt-5.5', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-3.1-pro-preview', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-3.1-pro-preview', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-flash-lite', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-flash-lite', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-3.5-haiku', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.0-flash', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'deepseek-chat', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'deepseek-reasoner', 'CHAT', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION', 'openai', 'https://futurmix.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'text-embedding-3-small', 'EMBEDDING', 'openai', 'https://futurmix.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING', 'openai', 'https://futurmix.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'whisper-1', 'ASR', 'openai', 'https://futurmix.ai/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'jina-reranker-v2-base-multilingual', 'RERANK', 'openai', 'https://futurmix.ai', FALSE FROM llm_system_provider WHERE provider_type = 'futurmix'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Gitee (gitee)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'qwen3-8b', 'CHAT', 'openai', 'https://api.moark.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'qwen3-0.6b', 'CHAT', 'openai', 'https://api.moark.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'glm-4.7-flash', 'CHAT', 'openai', 'https://api.moark.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'BAAI/bge-reranker-v2-m3', 'RERANK', 'openai', 'https://api.moark.ai/v1', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'BAAI/bge-m3', 'EMBEDDING', 'openai', 'https://api.moark.ai/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'GOT-OCR2_0', 'OCR', 'openai', 'https://api.moark.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'DeepSeek-OCR-2', 'OCR', 'openai', 'https://api.moark.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'PaddleOCR-VL-1.5', 'OCR', 'openai', 'https://api.moark.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'HunyuanOCR', 'OCR', 'openai', 'https://api.moark.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'gitee'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Google (gemini)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gemini-2.5-flash', 'CHAT', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'text-embedding-004', 'EMBEDDING', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-3-pro-preview', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-flash-lite', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.0-flash', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.0-flash-lite', 'VISION', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-embedding-001', 'EMBEDDING', 'google', 'https://generativelanguage.googleapis.com/v1beta', TRUE FROM llm_system_provider WHERE provider_type = 'gemini'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Groq (groq)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'llama-3.1-8b-instant', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama-3.3-70b-versatile', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'openai/gpt-oss-120b', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'openai/gpt-oss-20b', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'groq/compound', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'groq/compound-mini', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'meta-llama/llama-4-scout-17b-16e-instruct', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'qwen/qwen3-32b', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'whisper-large-v3-turbo', 'ASR', 'openai', 'https://api.groq.com/openai/v1/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'whisper-large-v3', 'ASR', 'openai', 'https://api.groq.com/openai/v1/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'gemma2-9b-it', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama3-70b-8192', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama3-8b-8192', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama-3.1-70b-versatile', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama-3.3-70b-specdec', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'mixtral-8x7b-32768', 'CHAT', 'openai', 'https://api.groq.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'groq'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- HuaweiCloud (huaweicloud)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek-v4-pro', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'deepseek-v4-flash', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'deepseek-v3.2', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'deepseek-v3.1-terminus', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'DeepSeek-V3', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'deepseek-r1-250528', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen3-30b-a3b', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'kimi-k2.6', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'longcat-flash-chat', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'glm-5', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'glm-5.1', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen2.5-vl-72b', 'CHAT', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen2.5-vl-72b', 'VISION', 'openai', 'https://api.modelarts-maas.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'bge-m3', 'EMBEDDING', 'openai', 'https://api.modelarts-maas.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'bge-reranker-v2-m3', 'RERANK', 'openai', 'https://api.modelarts-maas.com', FALSE FROM llm_system_provider WHERE provider_type = 'huaweicloud'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- HuggingFace (huggingface)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'openai/gpt-oss-120b:fastest', 'CHAT', 'openai', 'https://router.huggingface.co/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'huggingface'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- HunYuan (hunyuan)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'hunyuan-pro', 'CHAT', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-standard', 'CHAT', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-standard-256K', 'CHAT', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-lite', 'CHAT', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-embedding', 'EMBEDDING', 'openai', 'https://api.hunyuan.cloud.tencent.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'hunyuan'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- JieKouAI (jiekouai)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek-v4-flash', 'CHAT', 'openai', 'https://api.jiekou.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'deepseek-v4-pro', 'CHAT', 'openai', 'https://api.jiekou.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-4.5', 'CHAT', 'openai', 'https://api.jiekou.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-4.5v', 'CHAT', 'openai', 'https://api.jiekou.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-4.7', 'CHAT', 'openai', 'https://api.jiekou.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-4.7-flash', 'CHAT', 'openai', 'https://api.jiekou.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-5', 'CHAT', 'openai', 'https://api.jiekou.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'baai/bge-reranker-v2-m3', 'RERANK', 'openai', 'https://api.jiekou.ai', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING', 'openai', 'https://api.jiekou.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'jiekouai'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Jina (jina)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'jina-vlm', 'CHAT', 'jina', 'https://api.jina.ai/v1', FALSE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v3', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-m0', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-colbert-v2', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v2-base-multilingual', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v3', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v4', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-text-small', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-text-nano', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-omni-small', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-omni-nano', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-clip-v2', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-en', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v1-base-en', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v1-turbo-en', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v1-tiny-en', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-colbert-v1-en', 'RERANK', 'jina', 'https://api.jina.ai/v1/rerank', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-de', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-es', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-code', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-zh', 'EMBEDDING', 'jina', 'https://api.jina.ai/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'jina'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- LongCat (longcat)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'LongCat-Flash-Chat', 'CHAT', 'openai', 'https://api.longcat.chat/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-Flash-Lite', 'CHAT', 'openai', 'https://api.longcat.chat/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-Flash-Thinking-2601', 'CHAT', 'openai', 'https://api.longcat.chat/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-Flash-Omni-2603', 'CHAT', 'openai', 'https://api.longcat.chat/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-2.0-Preview', 'CHAT', 'openai', 'https://api.longcat.chat/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-Flash-Thinking', 'CHAT', 'openai', 'https://api.longcat.chat/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'longcat'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- MiniMax (minimax)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'MiniMax-M3', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.7', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.7-highspeed', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.5', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.5-highspeed', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.1', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.1-highspeed', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2-her', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.7', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.7-highspeed', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.5', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.5-highspeed', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.1', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2', 'CHAT', 'openai', 'https://api.minimaxi.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'minimax'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Mistral (mistral)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'mistral-large-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-medium-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-small-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'ministral-8b-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'ministral-3b-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'pixtral-large-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'pixtral-large-latest', 'VISION', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'codestral-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-mistral-nemo', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-mistral-7b', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-mixtral-8x7b', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-mixtral-8x22b', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'magistral-medium-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'magistral-small-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-embed', 'EMBEDDING', 'openai', 'https://api.mistral.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-ocr-2512', 'OCR', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-saba-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-moderation-latest', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'pixtral-12b-2409', 'VISION', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-ocr-latest', 'VISION', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-codestral-mamba', 'CHAT', 'openai', 'https://api.mistral.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'mistral'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Moonshot (moonshot)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'kimi-k2.6', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.6', 'VISION', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.5', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.5', 'VISION', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-8k', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-8k', 'VISION', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-32k', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-128k', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-8k-vision-preview', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-8k-vision-preview', 'VISION', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-32k-vision-preview', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-32k-vision-preview', 'VISION', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-128k-vision-preview', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-128k-vision-preview', 'VISION', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-thinking-preview', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-0711-preview', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-0905-preview', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-thinking', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-thinking-turbo', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-turbo-preview', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-latest', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-auto', 'CHAT', 'openai', 'https://api.moonshot.cn/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'moonshot'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- n1n (n1n)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-5.2', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-5.2', 'VISION', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'deepseek-v3-0324', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'deepseek-v3-1-250821', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'deepseek-v3-1-think-250821', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'kimi-k2-250905', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'qwen3-coder-plus', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'text-embedding-3-small', 'EMBEDDING', 'openai', 'https://api.n1n.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING', 'openai', 'https://api.n1n.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'text-embedding-ada-002', 'EMBEDDING', 'openai', 'https://api.n1n.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'BAAI/bge-reranker-v2-m3', 'RERANK', 'openai', 'https://api.n1n.ai', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Reranker-0.6B', 'RERANK', 'openai', 'https://api.n1n.ai', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-3.5-turbo', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'deepseek-chat', 'CHAT', 'openai', 'https://api.n1n.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'n1n'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Novita (novita)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek/deepseek-v4-pro', 'CHAT', 'openai', 'https://api.novita.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'meta-llama/llama-3.3-70b-instruct', 'CHAT', 'openai', 'https://api.novita.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'qwen/qwen3-30b-a3b-fp8', 'CHAT', 'openai', 'https://api.novita.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'qwen/qwen3-235b-a22b-fp8', 'CHAT', 'openai', 'https://api.novita.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2-instruct', 'CHAT', 'openai', 'https://api.novita.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'google/gemma-3-27b-it', 'CHAT', 'openai', 'https://api.novita.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'mistralai/mistral-nemo', 'CHAT', 'openai', 'https://api.novita.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'baai/bge-m3', 'EMBEDDING', 'openai', 'https://api.novita.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'baai/bge-reranker-v2-m3', 'RERANK', 'openai', 'https://api.novita.ai', FALSE FROM llm_system_provider WHERE provider_type = 'novita'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Nvidia (nvidia)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'abacusai/dracarys-llama-3.1-70b-instruct', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'bytedance/seed-oss-36b-instruct', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'deepseek-ai/deepseek-v4-flash', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'deepseek-ai/deepseek-v4-pro', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nv-embed-v1', 'EMBEDDING', 'openai', 'https://integrate.api.nvidia.com/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'google/codegemma-7b', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'google/gemma-2-2b-it', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'google/gemma-4-31b-it', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'meta/llama-3.2-90b-vision-instruct', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'meta/llama-3.2-90b-vision-instruct', 'VISION', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'meta/llama-4-maverick-17b-128e-instruct', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'minimaxai/minimax-m2.5', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'minimaxai/minimax-m2.7', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-7b-instruct-v0.3', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-large-3-675b-instruct-2512', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-medium-3.5-128b', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-medium-3.5-128b', 'VISION', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-nemotron', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.6', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.6', 'VISION', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2-instruct', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2-thinking', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/gliner-pii', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemoguard-8b-content-safety', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemoguard-8b-topic-control', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemotron-nano-8b-v1', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemotron-safety-guard-8b-v3', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemotron-ultra-253b-v1', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.2-nemoretriever-1b-vlm-embed-v1', 'EMBEDDING', 'openai', 'https://integrate.api.nvidia.com/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.3-nemotron-super-49b-v1', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.3-nemotron-super-49b-v1.5', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-3-nano-30b-a3b', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning', 'VISION', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-3-super-120b-a12b', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-content-safety-reasoning-4b', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-mini-4b-instruct', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nv-embedqa-e5-v5', 'EMBEDDING', 'openai', 'https://integrate.api.nvidia.com/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nv-embedqa-mistral-7b-v2', 'EMBEDDING', 'openai', 'https://integrate.api.nvidia.com/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nv-rerankqa-mistral-4b-v3', 'RERANK', 'openai', 'https://integrate.api.nvidia.com/v1', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.2-nv-rerankqa-1b-v2', 'RERANK', 'openai', 'https://integrate.api.nvidia.com/v1', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nvidia-nemotron-nano-9b-v2', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/riva-translate-4b-instruct-v1.1', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'openai/gpt-oss-120b', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'qwen/qwen3.5-122b-a10b', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'qwen/qwen3-coder-480b-a35b-instruct', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'z-ai/glm5', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'z-ai/glm-5.1', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'z-ai/glm4.7', 'CHAT', 'openai', 'https://integrate.api.nvidia.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'nvidia'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- OpenAI (openai)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gpt-5.5', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.2-pro', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.2-pro', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.2', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.2', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-nano', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-nano', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.5-preview', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-3.5-turbo', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-3.5-turbo-16k-0613', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'text-embedding-ada-002', 'EMBEDDING', 'openai', 'https://api.openai.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'text-embedding-3-small', 'EMBEDDING', 'openai', 'https://api.openai.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING', 'openai', 'https://api.openai.com/v1/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'whisper-1', 'ASR', 'openai', 'https://api.openai.com/v1/audio/transcriptions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4-turbo', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4-32k', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o3', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o3', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o4-mini', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o4-mini', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o4-mini-high', 'CHAT', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o4-mini-high', 'VISION', 'openai', 'https://api.openai.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'openai'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- OpenRouter (openrouter)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'google/gemma-4-31b-it', 'CHAT', 'openai', 'https://openrouter.ai/api/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'openrouter'
UNION ALL
    SELECT id, 'minimax/minimax-m2.5', 'CHAT', 'openai', 'https://openrouter.ai/api/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'openrouter'
UNION ALL
    SELECT id, 'tencent/hy3-preview', 'CHAT', 'openai', 'https://openrouter.ai/api/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'openrouter'
UNION ALL
    SELECT id, 'openai/whisper-large-v3', 'ASR', 'openai', 'https://openrouter.ai/api/v1/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'openrouter'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- OrcaRouter (orcarouter)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'orcarouter/auto', 'CHAT', 'openai', 'https://api.orcarouter.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'orcarouter'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Perplexity (perplexity)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'sonar', 'CHAT', 'openai', 'https://api.perplexity.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'sonar-pro', 'CHAT', 'openai', 'https://api.perplexity.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'sonar-reasoning-pro', 'CHAT', 'openai', 'https://api.perplexity.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'sonar-deep-research', 'CHAT', 'openai', 'https://api.perplexity.ai/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'pplx-embed-v1-0.6b', 'EMBEDDING', 'openai', 'https://api.perplexity.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'pplx-embed-v1-4b', 'EMBEDDING', 'openai', 'https://api.perplexity.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'pplx-embed-context-v1-0.6b', 'EMBEDDING', 'openai', 'https://api.perplexity.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'pplx-embed-context-v1-4b', 'EMBEDDING', 'openai', 'https://api.perplexity.ai/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'perplexity'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- PPIO (ppio)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek/deepseek-v4-flash', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-v4-pro', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1/community', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3/community', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1-distill-llama-70b', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1-distill-qwen-32b', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1-distill-qwen-14b', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1-distill-llama-8b', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'qwen/qwen-2.5-72b-instruct', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'qwen/qwen-2-vl-72b-instruct', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'meta-llama/llama-3.2-3b-instruct', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'qwen/qwen2.5-32b-instruct', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'baichuan/baichuan2-13b-chat', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'meta-llama/llama-3.1-70b-instruct', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'meta-llama/llama-3.1-8b-instruct', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, '01-ai/yi-1.5-34b-chat', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, '01-ai/yi-1.5-9b-chat', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'thudm/glm-4-9b-chat', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'qwen/qwen-2-7b-instruct', 'CHAT', 'openai', 'https://api.ppio.com/openai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'ppio'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Qiniu (qiniu)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'deepseek/deepseek-v4-flash', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v4-pro', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.6', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.5', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'z-ai/glm-5.1', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'z-ai/glm-5', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax/minimax-m2.7', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax/minimax-m2.5', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax/minimax-m2.5-highspeed', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax/minimax-m2.1', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'kimi-k2-thinking', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'meituan/longcat-flash-lite', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-max', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'z-ai/glm-4.6', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'z-ai/glm-4.7', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.2-251201', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.2-exp-thinking', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.1-terminus', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.1-terminus-thinking', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-v3.1', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-v3-0324', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-r1-0528', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-r1', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-1.6-flash', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-1.5-pro-32k', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-1.6', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-2.0-pro', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-2.0-lite', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-2.0-mini', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-2.0-code', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-thinking', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-thinking-2507', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-max-2026-01-23', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-instruct', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-max-preview', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen-2.5-vl-72b-instruct', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-coder-480b-a35b-instruct', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen-turbo', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-instruct-2507', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-30b-a3b', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen-2.5-vl-7b-instruct', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen-vl-max-2025-01-25', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen2.5-max-2025-01-25', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax-m1', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'glm-4.5', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-vl-30b-a3b-instruct', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-v3', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-30b-a3b-thinking-2507', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'glm-4.5-air', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3.5-397b-a17b', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen/qwen3.5-plus', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen/qwen3.6-plus', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.2-exp', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen/qwen3.7-max', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen/qwen3.6-27b', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'tencent/hy3-preview', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3.5-35b-a3b', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-vl-30b-a3b-thinking', 'VISION', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-30b-a3b-instruct-2507', 'CHAT', 'openai', 'https://api.qnaigc.com/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'qiniu'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Replicate (replicate)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'meta/meta-llama-3-70b-instruct', 'CHAT', 'openai', 'https://api.replicate.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'replicate'
UNION ALL
    SELECT id, 'meta/meta-llama-3-8b-instruct', 'CHAT', 'openai', 'https://api.replicate.com/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'replicate'
UNION ALL
    SELECT id, 'replicate/all-mpnet-base-v2:b6b7585c9640cd7a9572c6e129c9549d79c9c31f0d3fdce7baac7c67ca38f305', 'EMBEDDING', 'openai', 'https://api.replicate.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'replicate'
UNION ALL
    SELECT id, 'yxzwayne/bge-reranker-v2-m3:7f7c6e9d18336e2cbf07d88e9362d881d2fe4d6a9854ec1260f115cabc106a8c', 'RERANK', 'openai', 'https://api.replicate.com', FALSE FROM llm_system_provider WHERE provider_type = 'replicate'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- SiliconFlow (siliconflow)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'Pro/deepseek-ai/DeepSeek-V4-Pro', 'CHAT', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Pro/deepseek-ai/DeepSeek-V4-Flash', 'CHAT', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Pro/moonshotai/Kimi-K2.6', 'CHAT', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Pro/moonshotai/Kimi-K2.6', 'VISION', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Pro/zai-org/GLM-5.1', 'CHAT', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'qwen/qwen3-8b', 'CHAT', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'qwen/qwen3.5-4b', 'CHAT', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'tencent/hunyuan-mt-7b', 'CHAT', 'openai', 'https://api.siliconflow.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'BAAI/bge-reranker-v2-m3', 'RERANK', 'openai', 'https://api.siliconflow.cn/v1', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Embedding-0.6B', 'EMBEDDING', 'openai', 'https://api.siliconflow.cn/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'FunAudioLLM/SenseVoiceSmall', 'ASR', 'openai', 'https://api.siliconflow.cn/v1/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'siliconflow'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- StepFun (stepfun)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'step-3.5-flash', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-3.5-flash-paid', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-2-16k', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-256k', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-128k', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-32k', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-8k', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-flash', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1v-32k', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1v-32k', 'VISION', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1v-8k', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1v-8k', 'VISION', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1o-vision-32k', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1o-vision-32k', 'VISION', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-3', 'VISION', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-2-mini', 'CHAT', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-r1-v-mini', 'VISION', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1o-turbo-vision', 'VISION', 'openai', 'https://api.stepfun.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-asr', 'ASR', 'openai', 'https://api.stepfun.ai/v1/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'stepfun'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- TogetherAI (togetherai)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'openai/gpt-oss-20b', 'CHAT', 'openai', 'https://api.together.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'CHAT', 'openai', 'https://api.together.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8', 'CHAT', 'openai', 'https://api.together.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'intfloat/multilingual-e5-large-instruct', 'EMBEDDING', 'openai', 'https://api.together.ai/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'BAAI/bge-large-en-v1.5', 'EMBEDDING', 'openai', 'https://api.together.ai/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'BAAI/bge-base-en-v1.5', 'EMBEDDING', 'openai', 'https://api.together.ai/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'mixedbread-ai/mxbai-rerank-large-v2', 'RERANK', 'openai', 'https://api.together.ai/v1', FALSE FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'openai/whisper-large-v3', 'ASR', 'openai', 'https://api.together.ai/v1/audio/transcriptions', FALSE FROM llm_system_provider WHERE provider_type = 'togetherai'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- TokenHub (tokenhub)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'gpt-4o-mini', 'CHAT', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4', 'CHAT', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4-turbo', 'CHAT', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'claude-3-5-sonnet', 'CHAT', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'claude-3-5-sonnet', 'VISION', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gemini-1.5-pro', 'CHAT', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gemini-1.5-flash', 'CHAT', 'openai', 'https://aitok.cc/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenhub'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- TokenPony (tokenpony)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'qwen3-8b', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-v3-0324', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'kimi-k2-instruct-0905', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-r1-0528', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-coder-480b', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'hunyuan-a13b-instruct', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-instruct', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-v3.2-exp', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-v3.1-terminus', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-vl-235b-a22b-instruct', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-vl-30b-a3b-instruct', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-ocr', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-instruct-2507', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'glm-4.6', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'minimax-m2', 'CHAT', 'openai', 'https://api.tokenpony.cn/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'tokenpony'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Upstage (upstage)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'solar-pro3', 'CHAT', 'openai', 'https://api.upstage.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-pro2', 'CHAT', 'openai', 'https://api.upstage.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-pro', 'CHAT', 'openai', 'https://api.upstage.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-mini', 'CHAT', 'openai', 'https://api.upstage.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-embedding-1-large-query', 'EMBEDDING', 'openai', 'https://api.upstage.ai/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-embedding-1-large-passage', 'EMBEDDING', 'openai', 'https://api.upstage.ai/v1/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-1-mini-chat', 'CHAT', 'openai', 'https://api.upstage.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-1-mini-chat-ja', 'CHAT', 'openai', 'https://api.upstage.ai/v1/chat/completions', FALSE FROM llm_system_provider WHERE provider_type = 'upstage'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- VolcEngine (volcengine)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'doubao-seed-2-0-pro-260215', 'CHAT', 'openai', 'https://ark.cn-beijing.volces.com/api/v3/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'volcengine'
UNION ALL
    SELECT id, 'doubao-embedding-vision-251215', 'EMBEDDING', 'openai', 'https://ark.cn-beijing.volces.com/api/v3/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'volcengine'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- Voyage (voyage)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'voyage-4-large', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-4', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-4-lite', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-3.5', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-3.5-lite', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-3-large', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-code-3', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-law-2', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-finance-2', 'EMBEDDING', 'openai', 'https://api.voyageai.com/embeddings', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'rerank-2.5', 'RERANK', 'openai', 'https://api.voyageai.com', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'rerank-2.5-lite', 'RERANK', 'openai', 'https://api.voyageai.com', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'rerank-2', 'RERANK', 'openai', 'https://api.voyageai.com', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'rerank-2-lite', 'RERANK', 'openai', 'https://api.voyageai.com', FALSE FROM llm_system_provider WHERE provider_type = 'voyage'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- xAI (xai)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'grok-4', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-3', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-3-fast', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-3-mini', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-3-mini-mini-fast', 'CHAT', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-2-vision', 'VISION', 'openai', 'https://api.x.ai/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xai'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- XunFei (xunfei)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'spark-x', 'CHAT', 'openai', 'https://spark-api-open.xf-yun.com/v1/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'xunfei'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

-- ZHIPU-AI (glm)
INSERT INTO llm_provider_model (provider_id, model_name, capability, protocol, api_base_url, is_active)
    SELECT id, 'glm-5', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-5-turbo', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-5v-turbo', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.7', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.7-flashx', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6v-Flash', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6v-Flash', 'VISION', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5-x', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5-air', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5-airx', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5-flash', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5v', 'VISION', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-plus', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-0520', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-airx', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-air', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-flash', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-flashx', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-long', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4v', 'VISION', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-9b', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'embedding-2', 'EMBEDDING', 'openai', 'https://open.bigmodel.cn/api/paas/v4/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'embedding-3', 'EMBEDDING', 'openai', 'https://open.bigmodel.cn/api/paas/v4/embeddings', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-asr-2512', 'ASR', 'openai', 'https://open.bigmodel.cn/api/paas/v4/audio/transcriptions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-ocr', 'OCR', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'rerank', 'RERANK', 'openai', 'https://open.bigmodel.cn/api/paas/v4', FALSE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-3-turbo', 'CHAT', 'openai', 'https://open.bigmodel.cn/api/paas/v4/chat/completions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-asr', 'ASR', 'openai', 'https://open.bigmodel.cn/api/paas/v4/audio/transcriptions', TRUE FROM llm_system_provider WHERE provider_type = 'glm'
ON DUPLICATE KEY UPDATE
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active);

COMMIT;
