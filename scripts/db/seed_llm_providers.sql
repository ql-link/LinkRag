-- =============================================================
-- toLink-Service：LLM 厂商与模型目录种子数据
-- 由 scripts/import_ragflow_configs.py 自动生成，请勿手动编辑
-- 数据来源：RAGFlow conf/ 目录（2026-06-06 导出）
-- 厂商：45 个，模型能力记录：868 条
-- =============================================================

USE tolink_rag_db;

START TRANSACTION;

-- ─── 1. 厂商基本信息 ──────────────────────────────────────────
INSERT INTO llm_system_provider (provider_type, provider_name, api_base_url, is_active, priority)
VALUES
    ('302ai', '302.AI', 'https://api.302.ai', TRUE, 50),
    ('aliyun', 'Aliyun', 'https://dashscope.aliyuncs.com', TRUE, 99),
    ('claude', 'Anthropic', 'https://api.anthropic.com', TRUE, 99),
    ('astraflow', 'Astraflow', 'https://api.modelverse.cn/v1', TRUE, 50),
    ('avian', 'avian', 'https://api.avian.io', TRUE, 50),
    ('baichuan', 'Baichuan', 'https://api.baichuan-ai.com/v1', TRUE, 50),
    ('baidu', 'Baidu', 'https://qianfan.baidubce.com/v2', TRUE, 50),
    ('cohere', 'CoHere', 'https://api.cohere.com', TRUE, 50),
    ('cometapi', 'CometAPI', 'https://api.cometapi.com', TRUE, 50),
    ('deepinfra', 'DeepInfra', 'https://api.deepinfra.com', TRUE, 50),
    ('deepseek', 'DeepSeek', 'https://api.deepseek.com', TRUE, 99),
    ('futurmix', 'FuturMix', 'https://futurmix.ai', TRUE, 50),
    ('gitee', 'Gitee', 'https://api.moark.ai/v1', TRUE, 50),
    ('gemini', 'Google', 'https://generativelanguage.googleapis.com', TRUE, 99),
    ('groq', 'Groq', 'https://api.groq.com/openai/v1', TRUE, 50),
    ('huaweicloud', 'HuaweiCloud', 'https://api.modelarts-maas.com', TRUE, 50),
    ('huggingface', 'HuggingFace', 'https://router.huggingface.co/v1', TRUE, 99),
    ('hunyuan', 'HunYuan', 'https://api.hunyuan.cloud.tencent.com/v1', TRUE, 50),
    ('jiekouai', 'JieKouAI', 'https://api.jiekou.ai', TRUE, 50),
    ('jina', 'Jina', 'https://api.jina.ai/v1', TRUE, 50),
    ('longcat', 'LongCat', 'https://api.longcat.chat', TRUE, 50),
    ('minimax', 'MiniMax', 'https://api.minimaxi.com/', TRUE, 98),
    ('mistral', 'Mistral', 'https://api.mistral.ai', TRUE, 50),
    ('moonshot', 'Moonshot', 'https://api.moonshot.cn/v1', TRUE, 99),
    ('n1n', 'n1n', 'https://api.n1n.ai', TRUE, 50),
    ('novita', 'Novita', 'https://api.novita.ai', TRUE, 50),
    ('nvidia', 'Nvidia', 'https://integrate.api.nvidia.com/v1', TRUE, 50),
    ('openai', 'OpenAI', 'https://api.openai.com/v1', TRUE, 99),
    ('openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1', TRUE, 98),
    ('orcarouter', 'OrcaRouter', 'https://api.orcarouter.ai', TRUE, 50),
    ('perplexity', 'Perplexity', 'https://api.perplexity.ai', TRUE, 50),
    ('ppio', 'PPIO', 'https://api.ppio.com/openai/v1', TRUE, 50),
    ('qiniu', 'Qiniu', 'https://api.qnaigc.com/v1', TRUE, 50),
    ('replicate', 'Replicate', 'https://api.replicate.com', TRUE, 50),
    ('siliconflow', 'SiliconFlow', 'https://api.siliconflow.cn/v1', TRUE, 50),
    ('stepfun', 'StepFun', 'https://api.stepfun.ai/v1', TRUE, 50),
    ('togetherai', 'TogetherAI', 'https://api.together.ai/v1', TRUE, 50),
    ('tokenhub', 'TokenHub', 'https://aitok.cc/v1', TRUE, 50),
    ('tokenpony', 'TokenPony', 'https://api.tokenpony.cn/v1', TRUE, 50),
    ('upstage', 'Upstage', 'https://api.upstage.ai/v1', TRUE, 50),
    ('volcengine', 'VolcEngine', 'https://ark.cn-beijing.volces.com/api/v3', TRUE, 50),
    ('voyage', 'Voyage', 'https://api.voyageai.com', TRUE, 50),
    ('xai', 'xAI', 'https://api.x.ai/v1', TRUE, 99),
    ('xunfei', 'XunFei', 'https://spark-api-open.xf-yun.com', TRUE, 50),
    ('glm', 'ZHIPU-AI', 'https://open.bigmodel.cn/api/paas/v4', TRUE, 99)
ON DUPLICATE KEY UPDATE
    provider_name  = VALUES(provider_name),
    api_base_url   = VALUES(api_base_url),
    is_active      = VALUES(is_active),
    priority       = VALUES(priority);

-- ─── 2. 模型能力目录（一模型多能力 = 多行）──────────────────────
-- 用子查询取 provider_id，避免依赖具体 ID 值

-- 302.AI (302ai)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'kimi-k2.6', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'kimi-k2.6', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.5', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.2-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.2-pro', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.2', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.2', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.1', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.1', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-nano', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4.5-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-3.5-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gpt-3.5-turbo-16k-0613', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'whisper-v3-turbo', 'ASR' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'mistral-ocr-latest', 'OCR' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-embeddings-v3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-reranker-v2-base-multilingual', 'RERANK' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'deepseek-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'chatgpt-4o-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'llama3.3-70b', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'deepseek-reasoner', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gemini-2.0-flash', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-20250219', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'grok-3-beta', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'grok-3-mini-beta', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'o3', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'o4-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gemini-2.5-pro-preview-05-06', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'llama-4-maverick', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'CHAT' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'claude-opus-4-20250514', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-clip-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = '302ai'
UNION ALL
    SELECT id, 'jina-reranker-m0', 'RERANK' FROM llm_system_provider WHERE provider_type = '302ai';

-- Aliyun (aliyun)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'qwen-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v4', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-rerank', 'RERANK' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-122b-a10b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'Moonshot-Kimi-K2-Instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-v3.2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-v3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-qwen-1.5b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-qwen-14b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-qwen-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-llama-8b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'deepseek-r1-distill-llama-70b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwq-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwq-plus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus-2025-07-28', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus-2025-07-14', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwq-plus-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-flash-2025-07-28', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus-2026-02-15', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-plus-2026-02-15', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash-2026-02-23', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3.5-flash-2026-02-23', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-max', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-coder-480b-a35b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-30b-a3b-instruct-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-30b-a3b-thinking-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-30b-a3b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-vl-plus', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-vl-235b-a22b-instruct', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-vl-235b-a22b-thinking', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-instruct-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-thinking-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-thinking', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-0.6b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-1.7b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-4b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-8b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-14b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-long', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-turbo-2025-04-28', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-turbo-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-max', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus-2025-04-28', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-plus-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'text-embedding-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-vl-max', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen-vl-plus', 'VISION' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'gte-rerank', 'RERANK' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-asr-flash', 'ASR' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qwen3-asr-flash-2025-09-08', 'ASR' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'qianwen-deepresearch-30b-a3b-131k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'aliyun'
UNION ALL
    SELECT id, 'gte-rerank-v2', 'RERANK' FROM llm_system_provider WHERE provider_type = 'aliyun';

-- Anthropic (claude)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'claude-opus-4-8', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-8', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-5-20251101', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-5-20251101', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-1-20250805', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-1-20250805', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-20250514', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-opus-4-20250514', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-20250219', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-20250219', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-sonnet-20241022', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-sonnet-20241022', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-haiku-20241022', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-5-haiku-20241022', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-haiku-20240307', 'CHAT' FROM llm_system_provider WHERE provider_type = 'claude'
UNION ALL
    SELECT id, 'claude-3-haiku-20240307', 'VISION' FROM llm_system_provider WHERE provider_type = 'claude';

-- Astraflow (astraflow)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'text-embedding-3-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'bge-reranker-v2-m3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'claude-sonnet-4-5-20250929', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Max', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Coder', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-32B', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-VL-235B-A22B-Instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'kimi-k2.6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'glm-5.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'MiniMax-M2.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'MiniMax-M2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'qwen3-embedding-8b', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'astraflow'
UNION ALL
    SELECT id, 'text-embedding-ada-002', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'astraflow';

-- avian (avian)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek/deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'deepseek/deepseek-v4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'z-ai/glm-5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'avian'
UNION ALL
    SELECT id, 'minimax/minimax-m2.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'avian';

-- Baichuan (baichuan)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'Baichuan4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4-Air', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan4-Turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-M3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-M3-plus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-M2-plus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-M2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan3-Turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan3-Turbo-128k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan2-Turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baichuan'
UNION ALL
    SELECT id, 'Baichuan-Text-Embedding', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'baichuan';

-- Baidu (baidu)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek-v3.2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'deepseek-v4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'qwen3-4b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'ernie-5.0', 'VISION' FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'embedding-v1', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'qwen3-reranker-4b', 'RERANK' FROM llm_system_provider WHERE provider_type = 'baidu'
UNION ALL
    SELECT id, 'paddleocr-vl-0.9b', 'OCR' FROM llm_system_provider WHERE provider_type = 'baidu';

-- CoHere (cohere)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'command-a-plus-05-2026', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-a-03-2025', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-r7b-12-2024', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-a-translate-08-2025', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-a-reasoning-08-2025', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-a-vision-07-2025', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-r-plus-08-2024', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'command-r-08-2024', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-v4.0-pro', 'RERANK' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-v4.0-fast', 'RERANK' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-v3.5', 'RERANK' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-english-v3.0', 'RERANK' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'rerank-multilingual-v3.0', 'RERANK' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-v4.0', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-english-v3.0', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-english-light-v3.0', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-multilingual-v3.0', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'embed-multilingual-light-v3.0', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'cohere'
UNION ALL
    SELECT id, 'cohere-transcribe-03-2026', 'ASR' FROM llm_system_provider WHERE provider_type = 'cohere';

-- CometAPI (cometapi)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'gpt-5.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-3-pro-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-3-pro-preview', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-v3.2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'text-embedding-3-small', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'text-embedding-ada-002', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'whisper-1', 'ASR' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'chatgpt-4o-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-5-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'o4-mini-2025-04-16', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'o3-pro-2025-06-10', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-opus-4-1-20250805', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-opus-4-1-20250805-thinking', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514-thinking', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-3-7-sonnet-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'claude-3-5-haiku-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-2.5-flash-lite', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'gemini-2.0-flash', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'grok-4-0709', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'grok-3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'grok-3-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'grok-2-image-1212', 'VISION' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-v3.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-v3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-r1-0528', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'deepseek-reasoner', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'qwen3-30b-a3b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi'
UNION ALL
    SELECT id, 'qwen3-coder-plus-2025-07-22', 'CHAT' FROM llm_system_provider WHERE provider_type = 'cometapi';

-- DeepInfra (deepinfra)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek-ai/DeepSeek-V3.2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Embedding-4B', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'bosonai/HiggsAudioV2.5', 'ASR' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'moonshotai/Kimi-K2-Instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'mistralai/Voxtral-Small-24B-2507', 'ASR' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'mistralai/Voxtral-Mini-3B-2507', 'ASR' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-R1-0528-Turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-235B-A22B', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-30B-A3B', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-32B', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-14B', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-V3-0324-Turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-Turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-4-Scout-17B-16E-Instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-R1-0528', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-V3-0324', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'mistralai/Devstral-Small-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'mistralai/Mistral-Small-3.2-24B-Instruct-2506', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-Guard-4-12B', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/QwQ-32B', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'anthropic/claude-4-opus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'anthropic/claude-4-sonnet', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemini-2.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemini-2.5-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemma-3-27b-it', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemma-3-12b-it', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'google/gemma-3-4b-it', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'microsoft/Phi-4-multimodal-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-R1-Distill-Llama-70B', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'deepseek-ai/DeepSeek-V3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'meta-llama/Llama-3.3-70B-Instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'microsoft/phi-4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'openai/whisper-large-v3-turbo', 'ASR' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-base-en-v1.5', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-en-icl', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-large-en-v1.5', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-m3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'BAAI/bge-m3-multi', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Embedding-0.6B', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Embedding-8B', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'intfloat/e5-base-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'intfloat/e5-large-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'intfloat/multilingual-e5-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'intfloat/multilingual-e5-large-instruct', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/all-MiniLM-L12-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/all-MiniLM-L6-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/all-mpnet-base-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/clip-ViT-B-32', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/clip-ViT-B-32-multilingual-v1', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/multi-qa-mpnet-base-dot-v1', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'sentence-transformers/paraphrase-MiniLM-L6-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'shibing624/text2vec-base-chinese', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'thenlper/gte-base', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra'
UNION ALL
    SELECT id, 'thenlper/gte-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'deepinfra';

-- DeepSeek (deepseek)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek-v4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepseek'
UNION ALL
    SELECT id, 'deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'deepseek';

-- FuturMix (futurmix)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'gpt-5.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-opus-4-7', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-opus-4-6', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-haiku-4-5-20251001', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-3.1-pro-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-3.1-pro-preview', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-flash-lite', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.5-flash-lite', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-sonnet-4-20250514', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'claude-3.5-haiku', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gemini-2.0-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'deepseek-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'deepseek-reasoner', 'CHAT' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'text-embedding-3-small', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'whisper-1', 'ASR' FROM llm_system_provider WHERE provider_type = 'futurmix'
UNION ALL
    SELECT id, 'jina-reranker-v2-base-multilingual', 'RERANK' FROM llm_system_provider WHERE provider_type = 'futurmix';

-- Gitee (gitee)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'qwen3-8b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'qwen3-0.6b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'glm-4.7-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'BAAI/bge-reranker-v2-m3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'BAAI/bge-m3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'GOT-OCR2_0', 'OCR' FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'DeepSeek-OCR-2', 'OCR' FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'PaddleOCR-VL-1.5', 'OCR' FROM llm_system_provider WHERE provider_type = 'gitee'
UNION ALL
    SELECT id, 'HunyuanOCR', 'OCR' FROM llm_system_provider WHERE provider_type = 'gitee';

-- Google (gemini)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'gemini-2.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'text-embedding-004', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-3-pro-preview', 'VISION' FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-flash', 'VISION' FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-pro', 'VISION' FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.5-flash-lite', 'VISION' FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.0-flash', 'VISION' FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-2.0-flash-lite', 'VISION' FROM llm_system_provider WHERE provider_type = 'gemini'
UNION ALL
    SELECT id, 'gemini-embedding-001', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'gemini';

-- Groq (groq)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'llama-3.1-8b-instant', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama-3.3-70b-versatile', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'openai/gpt-oss-120b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'openai/gpt-oss-20b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'groq/compound', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'groq/compound-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'meta-llama/llama-4-scout-17b-16e-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'qwen/qwen3-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'whisper-large-v3-turbo', 'ASR' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'whisper-large-v3', 'ASR' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'gemma2-9b-it', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama3-70b-8192', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama3-8b-8192', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama-3.1-70b-versatile', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'llama-3.3-70b-specdec', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq'
UNION ALL
    SELECT id, 'mixtral-8x7b-32768', 'CHAT' FROM llm_system_provider WHERE provider_type = 'groq';

-- HuaweiCloud (huaweicloud)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'deepseek-v4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'deepseek-v3.2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'deepseek-v3.1-terminus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'DeepSeek-V3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'deepseek-r1-250528', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen3-30b-a3b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'kimi-k2.6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'longcat-flash-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'glm-5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'glm-5.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen2.5-vl-72b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'qwen2.5-vl-72b', 'VISION' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'bge-m3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'huaweicloud'
UNION ALL
    SELECT id, 'bge-reranker-v2-m3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'huaweicloud';

-- HuggingFace (huggingface)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'openai/gpt-oss-120b:fastest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'huggingface';

-- HunYuan (hunyuan)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'hunyuan-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-standard', 'CHAT' FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-standard-256K', 'CHAT' FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-lite', 'CHAT' FROM llm_system_provider WHERE provider_type = 'hunyuan'
UNION ALL
    SELECT id, 'hunyuan-embedding', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'hunyuan';

-- JieKouAI (jiekouai)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek-v4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-4.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-4.5v', 'CHAT' FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-4.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-4.7-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'zai-org/glm-5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'baai/bge-reranker-v2-m3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jiekouai'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jiekouai';

-- Jina (jina)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'jina-vlm', 'CHAT' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-m0', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-colbert-v2', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v2-base-multilingual', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v4', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-text-small', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-text-nano', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-omni-small', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v5-omni-nano', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-clip-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-en', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v1-base-en', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v1-turbo-en', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-reranker-v1-tiny-en', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-colbert-v1-en', 'RERANK' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-de', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-es', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-code', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina'
UNION ALL
    SELECT id, 'jina-embeddings-v2-base-zh', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'jina';

-- LongCat (longcat)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'LongCat-Flash-Chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-Flash-Lite', 'CHAT' FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-Flash-Thinking-2601', 'CHAT' FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-Flash-Omni-2603', 'CHAT' FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-2.0-Preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'longcat'
UNION ALL
    SELECT id, 'LongCat-Flash-Thinking', 'CHAT' FROM llm_system_provider WHERE provider_type = 'longcat';

-- MiniMax (minimax)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'MiniMax-M3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.7-highspeed', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.5-highspeed', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2.1-highspeed', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'minimax-m2-her', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.7-highspeed', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.5-highspeed', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax'
UNION ALL
    SELECT id, 'MiniMax-M2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'minimax';

-- Mistral (mistral)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'mistral-large-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-medium-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-small-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'ministral-8b-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'ministral-3b-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'pixtral-large-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'pixtral-large-latest', 'VISION' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'codestral-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-mistral-nemo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-mistral-7b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-mixtral-8x7b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-mixtral-8x22b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'magistral-medium-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'magistral-small-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-embed', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-ocr-2512', 'OCR' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-saba-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-moderation-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'pixtral-12b-2409', 'VISION' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'mistral-ocr-latest', 'VISION' FROM llm_system_provider WHERE provider_type = 'mistral'
UNION ALL
    SELECT id, 'open-codestral-mamba', 'CHAT' FROM llm_system_provider WHERE provider_type = 'mistral';

-- Moonshot (moonshot)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'kimi-k2.6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.6', 'VISION' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2.5', 'VISION' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-8k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-8k', 'VISION' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-32k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-128k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-8k-vision-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-8k-vision-preview', 'VISION' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-32k-vision-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-32k-vision-preview', 'VISION' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-128k-vision-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-128k-vision-preview', 'VISION' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-thinking-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-0711-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-0905-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-thinking', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-thinking-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-k2-turbo-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'kimi-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot'
UNION ALL
    SELECT id, 'moonshot-v1-auto', 'CHAT' FROM llm_system_provider WHERE provider_type = 'moonshot';

-- n1n (n1n)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'gpt-4o-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-5.2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-5.2', 'VISION' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'claude-sonnet-4-6', 'VISION' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'deepseek-v3-0324', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'deepseek-v3-1-250821', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'deepseek-v3-1-think-250821', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'kimi-k2-250905', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'qwen3-coder-plus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'text-embedding-3-small', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'text-embedding-ada-002', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'BAAI/bge-reranker-v2-m3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Reranker-0.6B', 'RERANK' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'gpt-3.5-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n'
UNION ALL
    SELECT id, 'deepseek-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'n1n';

-- Novita (novita)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek/deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'meta-llama/llama-3.3-70b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'qwen/qwen3-30b-a3b-fp8', 'CHAT' FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'qwen/qwen3-235b-a22b-fp8', 'CHAT' FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'google/gemma-3-27b-it', 'CHAT' FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'mistralai/mistral-nemo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'baai/bge-m3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'novita'
UNION ALL
    SELECT id, 'baai/bge-reranker-v2-m3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'novita';

-- Nvidia (nvidia)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'abacusai/dracarys-llama-3.1-70b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'bytedance/seed-oss-36b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'deepseek-ai/deepseek-v4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'deepseek-ai/deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nv-embed-v1', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'google/codegemma-7b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'google/gemma-2-2b-it', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'google/gemma-4-31b-it', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'meta/llama-3.2-90b-vision-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'meta/llama-3.2-90b-vision-instruct', 'VISION' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'meta/llama-4-maverick-17b-128e-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'minimaxai/minimax-m2.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'minimaxai/minimax-m2.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-7b-instruct-v0.3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-large-3-675b-instruct-2512', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-medium-3.5-128b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-medium-3.5-128b', 'VISION' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'mistralai/mistral-nemotron', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.6', 'VISION' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2-thinking', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/gliner-pii', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemoguard-8b-content-safety', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemoguard-8b-topic-control', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemotron-nano-8b-v1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemotron-safety-guard-8b-v3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.1-nemotron-ultra-253b-v1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.2-nemoretriever-1b-vlm-embed-v1', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.3-nemotron-super-49b-v1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.3-nemotron-super-49b-v1.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-3-nano-30b-a3b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning', 'VISION' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-3-super-120b-a12b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-content-safety-reasoning-4b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nemotron-mini-4b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nv-embedqa-e5-v5', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nv-embedqa-mistral-7b-v2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nv-rerankqa-mistral-4b-v3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/llama-3.2-nv-rerankqa-1b-v2', 'RERANK' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/nvidia-nemotron-nano-9b-v2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'nvidia/riva-translate-4b-instruct-v1.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'openai/gpt-oss-120b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'qwen/qwen3.5-122b-a10b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'qwen/qwen3-coder-480b-a35b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'z-ai/glm5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'z-ai/glm-5.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia'
UNION ALL
    SELECT id, 'z-ai/glm4.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'nvidia';

-- OpenAI (openai)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'gpt-5.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.5', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.4-nano', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.2-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.2-pro', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.2', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5.1-chat-latest', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-nano', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-5-chat-latest', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.1-nano', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4.5-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-3.5-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-3.5-turbo-16k-0613', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'text-embedding-ada-002', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'text-embedding-3-small', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'text-embedding-3-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'whisper-1', 'ASR' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'gpt-4-32k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o3', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o4-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o4-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o4-mini-high', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openai'
UNION ALL
    SELECT id, 'o4-mini-high', 'VISION' FROM llm_system_provider WHERE provider_type = 'openai';

-- OpenRouter (openrouter)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'google/gemma-4-31b-it', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openrouter'
UNION ALL
    SELECT id, 'minimax/minimax-m2.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openrouter'
UNION ALL
    SELECT id, 'tencent/hy3-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'openrouter'
UNION ALL
    SELECT id, 'openai/whisper-large-v3', 'ASR' FROM llm_system_provider WHERE provider_type = 'openrouter';

-- OrcaRouter (orcarouter)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'orcarouter/auto', 'CHAT' FROM llm_system_provider WHERE provider_type = 'orcarouter';

-- Perplexity (perplexity)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'sonar', 'CHAT' FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'sonar-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'sonar-reasoning-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'sonar-deep-research', 'CHAT' FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'pplx-embed-v1-0.6b', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'pplx-embed-v1-4b', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'pplx-embed-context-v1-0.6b', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'perplexity'
UNION ALL
    SELECT id, 'pplx-embed-context-v1-4b', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'perplexity';

-- PPIO (ppio)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek/deepseek-v4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1/community', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3/community', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1-distill-llama-70b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1-distill-qwen-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1-distill-qwen-14b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'deepseek/deepseek-r1-distill-llama-8b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'qwen/qwen-2.5-72b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'qwen/qwen-2-vl-72b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'meta-llama/llama-3.2-3b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'qwen/qwen2.5-32b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'baichuan/baichuan2-13b-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'meta-llama/llama-3.1-70b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'meta-llama/llama-3.1-8b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, '01-ai/yi-1.5-34b-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, '01-ai/yi-1.5-9b-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'thudm/glm-4-9b-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio'
UNION ALL
    SELECT id, 'qwen/qwen-2-7b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'ppio';

-- Qiniu (qiniu)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'deepseek/deepseek-v4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v4-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.6', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'moonshotai/kimi-k2.5', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'z-ai/glm-5.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'z-ai/glm-5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax/minimax-m2.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax/minimax-m2.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax/minimax-m2.5-highspeed', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax/minimax-m2.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'kimi-k2-thinking', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'meituan/longcat-flash-lite', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-max', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'z-ai/glm-4.6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'z-ai/glm-4.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.2-251201', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.2-exp-thinking', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.1-terminus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.1-terminus-thinking', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-v3.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-v3-0324', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-r1-0528', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-r1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-1.6-flash', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-1.5-pro-32k', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-1.6', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-2.0-pro', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-2.0-lite', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-2.0-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'doubao-seed-2.0-code', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-thinking', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-thinking-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-max-2026-01-23', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-max-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen-2.5-vl-72b-instruct', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-coder-480b-a35b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-instruct-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-30b-a3b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-235b-a22b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen-2.5-vl-7b-instruct', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen-vl-max-2025-01-25', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen2.5-max-2025-01-25', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'minimax-m1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'glm-4.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-vl-30b-a3b-instruct', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek-v3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-30b-a3b-thinking-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'glm-4.5-air', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3.5-397b-a17b', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen/qwen3.5-plus', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen/qwen3.6-plus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'deepseek/deepseek-v3.2-exp', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen/qwen3.7-max', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen/qwen3.6-27b', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'tencent/hy3-preview', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3.5-35b-a3b', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-vl-30b-a3b-thinking', 'VISION' FROM llm_system_provider WHERE provider_type = 'qiniu'
UNION ALL
    SELECT id, 'qwen3-30b-a3b-instruct-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'qiniu';

-- Replicate (replicate)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'meta/meta-llama-3-70b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'replicate'
UNION ALL
    SELECT id, 'meta/meta-llama-3-8b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'replicate'
UNION ALL
    SELECT id, 'replicate/all-mpnet-base-v2:b6b7585c9640cd7a9572c6e129c9549d79c9c31f0d3fdce7baac7c67ca38f305', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'replicate'
UNION ALL
    SELECT id, 'yxzwayne/bge-reranker-v2-m3:7f7c6e9d18336e2cbf07d88e9362d881d2fe4d6a9854ec1260f115cabc106a8c', 'RERANK' FROM llm_system_provider WHERE provider_type = 'replicate';

-- SiliconFlow (siliconflow)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'Pro/deepseek-ai/DeepSeek-V4-Pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Pro/deepseek-ai/DeepSeek-V4-Flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Pro/moonshotai/Kimi-K2.6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Pro/moonshotai/Kimi-K2.6', 'VISION' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Pro/zai-org/GLM-5.1', 'CHAT' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'qwen/qwen3-8b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'qwen/qwen3.5-4b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'tencent/hunyuan-mt-7b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'BAAI/bge-reranker-v2-m3', 'RERANK' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Embedding-0.6B', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'siliconflow'
UNION ALL
    SELECT id, 'FunAudioLLM/SenseVoiceSmall', 'ASR' FROM llm_system_provider WHERE provider_type = 'siliconflow';

-- StepFun (stepfun)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'step-3.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-3.5-flash-paid', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-2-16k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-256k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-128k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-32k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-8k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1v-32k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1v-32k', 'VISION' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1v-8k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1v-8k', 'VISION' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1o-vision-32k', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1o-vision-32k', 'VISION' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-3', 'VISION' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-2-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-r1-v-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-1o-turbo-vision', 'VISION' FROM llm_system_provider WHERE provider_type = 'stepfun'
UNION ALL
    SELECT id, 'step-asr', 'ASR' FROM llm_system_provider WHERE provider_type = 'stepfun';

-- TogetherAI (togetherai)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'openai/gpt-oss-20b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8', 'CHAT' FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'intfloat/multilingual-e5-large-instruct', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'BAAI/bge-large-en-v1.5', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'BAAI/bge-base-en-v1.5', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'mixedbread-ai/mxbai-rerank-large-v2', 'RERANK' FROM llm_system_provider WHERE provider_type = 'togetherai'
UNION ALL
    SELECT id, 'openai/whisper-large-v3', 'ASR' FROM llm_system_provider WHERE provider_type = 'togetherai';

-- TokenHub (tokenhub)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'gpt-4o-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4o-mini', 'VISION' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4o', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4o', 'VISION' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gpt-4-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'claude-3-5-sonnet', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'claude-3-5-sonnet', 'VISION' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gemini-1.5-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenhub'
UNION ALL
    SELECT id, 'gemini-1.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenhub';

-- TokenPony (tokenpony)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'qwen3-8b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-v3-0324', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-32b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'kimi-k2-instruct-0905', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-r1-0528', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-coder-480b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'hunyuan-a13b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-next-80b-a3b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-v3.2-exp', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-v3.1-terminus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-vl-235b-a22b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-vl-30b-a3b-instruct', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'deepseek-ocr', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'qwen3-235b-a22b-instruct-2507', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'glm-4.6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony'
UNION ALL
    SELECT id, 'minimax-m2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'tokenpony';

-- Upstage (upstage)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'solar-pro3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-pro2', 'CHAT' FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-pro', 'CHAT' FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-embedding-1-large-query', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-embedding-1-large-passage', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-1-mini-chat', 'CHAT' FROM llm_system_provider WHERE provider_type = 'upstage'
UNION ALL
    SELECT id, 'solar-1-mini-chat-ja', 'CHAT' FROM llm_system_provider WHERE provider_type = 'upstage';

-- VolcEngine (volcengine)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'doubao-seed-2-0-pro-260215', 'CHAT' FROM llm_system_provider WHERE provider_type = 'volcengine'
UNION ALL
    SELECT id, 'doubao-embedding-vision-251215', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'volcengine';

-- Voyage (voyage)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'voyage-4-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-4', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-4-lite', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-3.5', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-3.5-lite', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-3-large', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-code-3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-law-2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'voyage-finance-2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'rerank-2.5', 'RERANK' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'rerank-2.5-lite', 'RERANK' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'rerank-2', 'RERANK' FROM llm_system_provider WHERE provider_type = 'voyage'
UNION ALL
    SELECT id, 'rerank-2-lite', 'RERANK' FROM llm_system_provider WHERE provider_type = 'voyage';

-- xAI (xai)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'grok-4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-3', 'CHAT' FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-3-fast', 'CHAT' FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-3-mini', 'CHAT' FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-3-mini-mini-fast', 'CHAT' FROM llm_system_provider WHERE provider_type = 'xai'
UNION ALL
    SELECT id, 'grok-2-vision', 'VISION' FROM llm_system_provider WHERE provider_type = 'xai';

-- XunFei (xunfei)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'spark-x', 'CHAT' FROM llm_system_provider WHERE provider_type = 'xunfei';

-- ZHIPU-AI (glm)
INSERT IGNORE INTO llm_provider_model (provider_id, model_name, capability)
    SELECT id, 'glm-5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-5-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-5v-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.7', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.7-flashx', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6v-Flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.6v-Flash', 'VISION' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5-x', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5-air', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5-airx', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4.5v', 'VISION' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-plus', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-0520', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-airx', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-air', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-flash', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-flashx', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-long', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4v', 'VISION' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-4-9b', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'embedding-2', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'embedding-3', 'EMBEDDING' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-asr-2512', 'ASR' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-ocr', 'OCR' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'rerank', 'RERANK' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-3-turbo', 'CHAT' FROM llm_system_provider WHERE provider_type = 'glm'
UNION ALL
    SELECT id, 'glm-asr', 'ASR' FROM llm_system_provider WHERE provider_type = 'glm';

COMMIT;
