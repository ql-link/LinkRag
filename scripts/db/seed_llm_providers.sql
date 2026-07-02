-- =============================================================
-- toLink-Service：LLM 厂商与模型目录种子数据（精简主力厂商版）
-- 生成日期：2026-07-02
-- 来源：本地 Docker MySQL tolink_rag_db.llm_system_provider / llm_provider_model / llm_system_preset
-- 厂商：17 个；厂商模型能力记录：83 条；LinkRag 系统预设：6 条。
-- 策略：只保留国内/国外主力厂商与 LinkRag 系统厂商；每个厂商最多保留 5 个当前主推模型。
-- LinkRag 只注册系统厂商，不写入 llm_provider_model；其模型只写入 llm_system_preset。
-- 全新环境首次写入系统预设前需先设置加密平台 Key：
--   SET @linkrag_system_preset_api_key = '<AES-256-GCM 加密后的平台 Key 密文>';
-- display_name 保留主版本号（如 2.5 / 4.8），不保留发布日期或快照号。
-- =============================================================

USE tolink_rag_db;

START TRANSACTION;

-- 1. 厂商基本信息：直接写入系统厂商原表，并下架历史非白名单厂商。
INSERT INTO llm_system_provider (
    provider_type, provider_name, icon_url, icon_object_key, api_base_url, default_protocol, is_active, priority
)
VALUES
    ('linkrag', 'LinkRag', 'http://103.205.254.30:39000/tolink-public/providerIcon/linkrag.png', 'providerIcon/linkrag.png', 'https://api.siliconflow.cn/v1', 'openai', TRUE, 100),
    ('aliyun', 'Aliyun', 'http://103.205.254.30:39000/tolink-public/providerIcon/aliyun.svg', 'providerIcon/aliyun.svg', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'openai', TRUE, 99),
    ('claude', 'Anthropic', 'http://103.205.254.30:39000/tolink-public/providerIcon/claude.svg', 'providerIcon/claude.svg', 'https://api.anthropic.com', 'anthropic', TRUE, 99),
    ('deepseek', 'DeepSeek', 'http://103.205.254.30:39000/tolink-public/providerIcon/deepseek.svg', 'providerIcon/deepseek.svg', 'https://api.deepseek.com/v1', 'openai', TRUE, 99),
    ('gemini', 'Google', 'http://103.205.254.30:39000/tolink-public/providerIcon/gemini.svg', 'providerIcon/gemini.svg', 'https://generativelanguage.googleapis.com/v1beta', 'google', TRUE, 99),
    ('glm', 'ZHIPU-AI', 'http://103.205.254.30:39000/tolink-public/providerIcon/glm.svg', 'providerIcon/glm.svg', 'https://open.bigmodel.cn/api/paas/v4', 'openai', TRUE, 99),
    ('moonshot', 'Moonshot', 'http://103.205.254.30:39000/tolink-public/providerIcon/moonshot.svg', 'providerIcon/moonshot.svg', 'https://api.moonshot.cn/v1', 'openai', TRUE, 99),
    ('openai', 'OpenAI', 'http://103.205.254.30:39000/tolink-public/providerIcon/openai.svg', 'providerIcon/openai.svg', 'https://api.openai.com/v1', 'openai', TRUE, 99),
    ('xai', 'xAI', 'http://103.205.254.30:39000/tolink-public/providerIcon/xai.svg', 'providerIcon/xai.svg', 'https://api.x.ai/v1', 'openai', TRUE, 99),
    ('minimax', 'MiniMax', 'http://103.205.254.30:39000/tolink-public/providerIcon/minimax.svg', 'providerIcon/minimax.svg', 'https://api.minimaxi.com/', 'openai', TRUE, 98),
    ('huggingface', 'HuggingFace', 'http://103.205.254.30:39000/tolink-public/providerIcon/huggingface.svg', 'providerIcon/huggingface.svg', 'https://router.huggingface.co/v1', 'openai', TRUE, 98),
    ('openrouter', 'OpenRouter', 'http://103.205.254.30:39000/tolink-public/providerIcon/openrouter.svg', 'providerIcon/openrouter.svg', 'https://openrouter.ai/api/v1', 'openai', TRUE, 98),
    ('hunyuan', 'HunYuan', 'http://103.205.254.30:39000/tolink-public/providerIcon/hunyuan.svg', 'providerIcon/hunyuan.svg', 'https://api.hunyuan.cloud.tencent.com/v1', 'openai', TRUE, 50),
    ('jina', 'Jina', 'http://103.205.254.30:39000/tolink-public/providerIcon/jina.svg', 'providerIcon/jina.svg', 'https://api.jina.ai/v1', 'jina', TRUE, 50),
    ('volcengine', 'VolcEngine', 'http://103.205.254.30:39000/tolink-public/providerIcon/volcengine.svg', 'providerIcon/volcengine.svg', 'https://ark.cn-beijing.volces.com/api/v3', 'openai', TRUE, 50),
    ('mimo', 'Xiaomi MiMo Token Plan', 'http://103.205.254.30:39000/tolink-public/providerIcon/mimo.svg', 'providerIcon/mimo.svg', 'https://token-plan-cn.xiaomimimo.com/v1', 'openai', TRUE, 50),
    ('siliconflow', 'SiliconFlow', 'http://103.205.254.30:39000/tolink-public/providerIcon/siliconflow.svg', 'providerIcon/siliconflow.svg', 'https://api.siliconflow.cn/v1', 'openai', TRUE, 50)
ON DUPLICATE KEY UPDATE
    provider_name    = VALUES(provider_name),
    icon_url         = VALUES(icon_url),
    icon_object_key  = VALUES(icon_object_key),
    api_base_url     = VALUES(api_base_url),
    default_protocol = VALUES(default_protocol),
    is_active        = VALUES(is_active),
    priority         = VALUES(priority),
    updated_at       = CURRENT_TIMESTAMP;

UPDATE llm_system_provider
SET is_active = FALSE,
    updated_at = CURRENT_TIMESTAMP
WHERE provider_type NOT IN ('linkrag', 'aliyun', 'claude', 'deepseek', 'gemini', 'glm', 'moonshot', 'openai', 'xai', 'minimax', 'huggingface', 'openrouter', 'hunyuan', 'jina', 'volcengine', 'mimo', 'siliconflow');

-- 2. 模型能力目录：直接写入模型能力原表；未列入当前种子的历史模型能力会被下架。
INSERT INTO llm_provider_model (
    provider_id, model_name, display_name, capability, protocol, api_base_url, is_active
)
    SELECT sp.id, 'qwen3-asr-flash' AS model_name, 'Qwen 3 ASR Flash' AS display_name, 'ASR' AS capability, 'dashscope' AS protocol, 'https://dashscope.aliyuncs.com/api/v1' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'aliyun'
UNION ALL
    SELECT sp.id, 'qwen3-max' AS model_name, 'Qwen 3 Max' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'aliyun'
UNION ALL
    SELECT sp.id, 'qwen3-rerank' AS model_name, 'Qwen 3 Rerank' AS display_name, 'RERANK' AS capability, 'dashscope' AS protocol, 'https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'aliyun'
UNION ALL
    SELECT sp.id, 'qwen3.5-flash' AS model_name, 'Qwen 3.5 Flash' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'aliyun'
UNION ALL
    SELECT sp.id, 'qwen3.5-flash' AS model_name, 'Qwen 3.5 Flash' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'aliyun'
UNION ALL
    SELECT sp.id, 'qwen3.5-plus' AS model_name, 'Qwen 3.5 Plus' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'aliyun'
UNION ALL
    SELECT sp.id, 'qwen3.5-plus' AS model_name, 'Qwen 3.5 Plus' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'aliyun'
UNION ALL
    SELECT sp.id, 'claude-haiku-4-5-20251001' AS model_name, 'Claude Haiku 4.5' AS display_name, 'CHAT' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-haiku-4-5-20251001' AS model_name, 'Claude Haiku 4.5' AS display_name, 'VISION' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-opus-4-7' AS model_name, 'Claude Opus 4.7' AS display_name, 'CHAT' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-opus-4-7' AS model_name, 'Claude Opus 4.7' AS display_name, 'VISION' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-opus-4-8' AS model_name, 'Claude Opus 4.8' AS display_name, 'CHAT' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-opus-4-8' AS model_name, 'Claude Opus 4.8' AS display_name, 'VISION' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-sonnet-4-5-20250929' AS model_name, 'Claude Sonnet 4.5' AS display_name, 'CHAT' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-sonnet-4-5-20250929' AS model_name, 'Claude Sonnet 4.5' AS display_name, 'VISION' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-sonnet-4-6' AS model_name, 'Claude Sonnet 4.6' AS display_name, 'CHAT' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'claude-sonnet-4-6' AS model_name, 'Claude Sonnet 4.6' AS display_name, 'VISION' AS capability, 'anthropic' AS protocol, 'https://api.anthropic.com/v1/messages' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'claude'
UNION ALL
    SELECT sp.id, 'deepseek-v4-flash' AS model_name, 'DeepSeek V4 Flash' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.deepseek.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'deepseek'
UNION ALL
    SELECT sp.id, 'deepseek-v4-pro' AS model_name, 'DeepSeek V4 Pro' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.deepseek.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'deepseek'
UNION ALL
    SELECT sp.id, 'gemini-2.5-flash' AS model_name, 'Gemini 2.5 Flash' AS display_name, 'CHAT' AS capability, 'google' AS protocol, 'https://generativelanguage.googleapis.com/v1beta' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'gemini'
UNION ALL
    SELECT sp.id, 'gemini-2.5-flash' AS model_name, 'Gemini 2.5 Flash' AS display_name, 'VISION' AS capability, 'google' AS protocol, 'https://generativelanguage.googleapis.com/v1beta' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'gemini'
UNION ALL
    SELECT sp.id, 'gemini-2.5-pro' AS model_name, 'Gemini 2.5 Pro' AS display_name, 'VISION' AS capability, 'google' AS protocol, 'https://generativelanguage.googleapis.com/v1beta' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'gemini'
UNION ALL
    SELECT sp.id, 'gemini-3-pro-preview' AS model_name, 'Gemini 3 Pro' AS display_name, 'VISION' AS capability, 'google' AS protocol, 'https://generativelanguage.googleapis.com/v1beta' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'gemini'
UNION ALL
    SELECT sp.id, 'gemini-embedding-001' AS model_name, 'Gemini Embedding' AS display_name, 'EMBEDDING' AS capability, 'google' AS protocol, 'https://generativelanguage.googleapis.com/v1beta' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'gemini'
UNION ALL
    SELECT sp.id, 'embedding-3' AS model_name, 'GLM Embedding 3' AS display_name, 'EMBEDDING' AS capability, 'openai' AS protocol, 'https://open.bigmodel.cn/api/paas/v4/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'glm'
UNION ALL
    SELECT sp.id, 'glm-5' AS model_name, 'GLM 5' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://open.bigmodel.cn/api/paas/v4/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'glm'
UNION ALL
    SELECT sp.id, 'glm-5-turbo' AS model_name, 'GLM 5 Turbo' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://open.bigmodel.cn/api/paas/v4/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'glm'
UNION ALL
    SELECT sp.id, 'glm-5v-turbo' AS model_name, 'GLM 5V Turbo' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://open.bigmodel.cn/api/paas/v4/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'glm'
UNION ALL
    SELECT sp.id, 'glm-asr-2512' AS model_name, 'GLM ASR' AS display_name, 'ASR' AS capability, 'openai' AS protocol, 'https://open.bigmodel.cn/api/paas/v4/audio/transcriptions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'glm'
UNION ALL
    SELECT sp.id, 'kimi-k2-thinking' AS model_name, 'Kimi K2 Thinking' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.moonshot.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'moonshot'
UNION ALL
    SELECT sp.id, 'kimi-k2-thinking-turbo' AS model_name, 'Kimi K2 Thinking Turbo' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.moonshot.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'moonshot'
UNION ALL
    SELECT sp.id, 'kimi-k2.6' AS model_name, 'Kimi K2.6' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.moonshot.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'moonshot'
UNION ALL
    SELECT sp.id, 'kimi-k2.6' AS model_name, 'Kimi K2.6' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://api.moonshot.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'moonshot'
UNION ALL
    SELECT sp.id, 'kimi-latest' AS model_name, 'Kimi' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.moonshot.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'moonshot'
UNION ALL
    SELECT sp.id, 'gpt-5-mini' AS model_name, 'GPT 5 Mini' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'gpt-5-mini' AS model_name, 'GPT 5 Mini' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'gpt-5.1-chat-latest' AS model_name, 'GPT 5.1 Chat' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'gpt-5.1-chat-latest' AS model_name, 'GPT 5.1 Chat' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'gpt-5.4' AS model_name, 'GPT 5.4' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'gpt-5.4' AS model_name, 'GPT 5.4' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'gpt-5.5' AS model_name, 'GPT 5.5' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'gpt-5.5' AS model_name, 'GPT 5.5' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'text-embedding-3-large' AS model_name, 'OpenAI Embedding 3 Large' AS display_name, 'EMBEDDING' AS capability, 'openai' AS protocol, 'https://api.openai.com/v1/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openai'
UNION ALL
    SELECT sp.id, 'grok-3-fast' AS model_name, 'Grok 3 Fast' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.x.ai/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'xai'
UNION ALL
    SELECT sp.id, 'grok-4' AS model_name, 'Grok 4' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.x.ai/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'xai'
UNION ALL
    SELECT sp.id, 'minimax-m2.5' AS model_name, 'MiniMax M2.5' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.minimaxi.com/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'minimax'
UNION ALL
    SELECT sp.id, 'zai-org/GLM-5.2' AS model_name, 'GLM 5.2' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://router.huggingface.co/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'huggingface'
UNION ALL
    SELECT sp.id, 'deepseek-ai/DeepSeek-V4-Pro' AS model_name, 'DeepSeek V4 Pro' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://router.huggingface.co/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'huggingface'
UNION ALL
    SELECT sp.id, 'Qwen/Qwen3.6-27B' AS model_name, 'Qwen 3.6 27B' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://router.huggingface.co/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'huggingface'
UNION ALL
    SELECT sp.id, 'Qwen/Qwen3.6-27B' AS model_name, 'Qwen 3.6 27B' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://router.huggingface.co/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'huggingface'
UNION ALL
    SELECT sp.id, 'MiniMaxAI/MiniMax-M3' AS model_name, 'MiniMax M3' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://router.huggingface.co/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'huggingface'
UNION ALL
    SELECT sp.id, 'MiniMaxAI/MiniMax-M3' AS model_name, 'MiniMax M3' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://router.huggingface.co/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'huggingface'
UNION ALL
    SELECT sp.id, 'moonshotai/Kimi-K2.7-Code' AS model_name, 'Kimi K2.7 Code' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://router.huggingface.co/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'huggingface'
UNION ALL
    SELECT sp.id, 'moonshotai/Kimi-K2.7-Code' AS model_name, 'Kimi K2.7 Code' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://router.huggingface.co/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'huggingface'
UNION ALL
    SELECT sp.id, 'anthropic/claude-sonnet-5' AS model_name, 'Claude Sonnet 5' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://openrouter.ai/api/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openrouter'
UNION ALL
    SELECT sp.id, 'anthropic/claude-sonnet-5' AS model_name, 'Claude Sonnet 5' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://openrouter.ai/api/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openrouter'
UNION ALL
    SELECT sp.id, 'openai/gpt-5.5' AS model_name, 'GPT 5.5' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://openrouter.ai/api/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openrouter'
UNION ALL
    SELECT sp.id, 'deepseek/deepseek-v4-pro' AS model_name, 'DeepSeek V4 Pro' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://openrouter.ai/api/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openrouter'
UNION ALL
    SELECT sp.id, 'z-ai/glm-5.2' AS model_name, 'GLM 5.2' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://openrouter.ai/api/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openrouter'
UNION ALL
    SELECT sp.id, 'x-ai/grok-4.3' AS model_name, 'Grok 4.3' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://openrouter.ai/api/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'openrouter'
UNION ALL
    SELECT sp.id, 'hunyuan-embedding' AS model_name, 'Hunyuan Embedding' AS display_name, 'EMBEDDING' AS capability, 'openai' AS protocol, 'https://api.hunyuan.cloud.tencent.com/v1/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'hunyuan'
UNION ALL
    SELECT sp.id, 'hunyuan-lite' AS model_name, 'Hunyuan lite' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'hunyuan'
UNION ALL
    SELECT sp.id, 'hunyuan-pro' AS model_name, 'Hunyuan Pro' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'hunyuan'
UNION ALL
    SELECT sp.id, 'hunyuan-standard' AS model_name, 'Hunyuan standard' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'hunyuan'
UNION ALL
    SELECT sp.id, 'hunyuan-standard-256K' AS model_name, 'Hunyuan standard 256k' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'hunyuan'
UNION ALL
    SELECT sp.id, 'jina-embeddings-v5-omni-nano' AS model_name, 'Jina Embedding 5 Omni Nano' AS display_name, 'EMBEDDING' AS capability, 'jina' AS protocol, 'https://api.jina.ai/v1/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'jina'
UNION ALL
    SELECT sp.id, 'jina-embeddings-v5-omni-small' AS model_name, 'Jina Embedding 5 Omni Small' AS display_name, 'EMBEDDING' AS capability, 'jina' AS protocol, 'https://api.jina.ai/v1/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'jina'
UNION ALL
    SELECT sp.id, 'jina-embeddings-v5-text-nano' AS model_name, 'Jina Embedding 5 Text Nano' AS display_name, 'EMBEDDING' AS capability, 'jina' AS protocol, 'https://api.jina.ai/v1/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'jina'
UNION ALL
    SELECT sp.id, 'jina-embeddings-v5-text-small' AS model_name, 'Jina Embedding 5 Text Small' AS display_name, 'EMBEDDING' AS capability, 'jina' AS protocol, 'https://api.jina.ai/v1/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'jina'
UNION ALL
    SELECT sp.id, 'jina-reranker-v3' AS model_name, 'Jina Reranker 3' AS display_name, 'RERANK' AS capability, 'jina' AS protocol, 'https://api.jina.ai/v1/rerank' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'jina'
UNION ALL
    SELECT sp.id, 'doubao-embedding-vision-251215' AS model_name, 'Doubao Vision Embedding' AS display_name, 'EMBEDDING' AS capability, 'openai' AS protocol, 'https://ark.cn-beijing.volces.com/api/v3/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'volcengine'
UNION ALL
    SELECT sp.id, 'doubao-embedding-vision-251215' AS model_name, 'Doubao Vision Embedding' AS display_name, 'SPARSE_EMBEDDING' AS capability, 'doubao_vision' AS protocol, 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'volcengine'
UNION ALL
    SELECT sp.id, 'doubao-seed-2-0-pro-260215' AS model_name, 'Doubao Seed 2.0 Pro' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://ark.cn-beijing.volces.com/api/v3/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'volcengine'
UNION ALL
    SELECT sp.id, 'mimo-v2.5' AS model_name, 'MiMo 2.5' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'mimo'
UNION ALL
    SELECT sp.id, 'mimo-v2.5' AS model_name, 'MiMo 2.5' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'mimo'
UNION ALL
    SELECT sp.id, 'mimo-v2.5-asr' AS model_name, 'MiMo 2.5 ASR' AS display_name, 'ASR' AS capability, 'openai' AS protocol, 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'mimo'
UNION ALL
    SELECT sp.id, 'mimo-v2.5-pro' AS model_name, 'MiMo 2.5 Pro' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'mimo'
UNION ALL
    SELECT sp.id, 'BAAI/bge-reranker-v2-m3' AS model_name, 'BGE Reranker M3' AS display_name, 'RERANK' AS capability, 'jina' AS protocol, 'https://api.siliconflow.cn/v1/rerank' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'siliconflow'
UNION ALL
    SELECT sp.id, 'Pro/deepseek-ai/DeepSeek-V4-Flash' AS model_name, 'DeepSeek V4 Flash' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.siliconflow.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'siliconflow'
UNION ALL
    SELECT sp.id, 'Pro/deepseek-ai/DeepSeek-V4-Pro' AS model_name, 'DeepSeek V4 Pro' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.siliconflow.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'siliconflow'
UNION ALL
    SELECT sp.id, 'Pro/moonshotai/Kimi-K2.6' AS model_name, 'Kimi K2.6' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.siliconflow.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'siliconflow'
UNION ALL
    SELECT sp.id, 'Pro/moonshotai/Kimi-K2.6' AS model_name, 'Kimi K2.6' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://api.siliconflow.cn/v1/chat/completions' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'siliconflow'
UNION ALL
    SELECT sp.id, 'Qwen/Qwen3-Embedding-0.6B' AS model_name, 'Qwen 3 Embedding 0.6b' AS display_name, 'EMBEDDING' AS capability, 'openai' AS protocol, 'https://api.siliconflow.cn/v1/embeddings' AS api_base_url, TRUE AS is_active FROM llm_system_provider sp WHERE sp.provider_type = 'siliconflow'
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    is_active    = VALUES(is_active),
    updated_at   = CURRENT_TIMESTAMP;

UPDATE llm_provider_model pm
JOIN llm_system_provider sp ON sp.id = pm.provider_id
SET pm.is_active = FALSE,
    pm.updated_at = CURRENT_TIMESTAMP
WHERE NOT (
  (sp.provider_type = 'aliyun' AND pm.model_name = 'qwen3-asr-flash' AND pm.capability = 'ASR')
  OR (sp.provider_type = 'aliyun' AND pm.model_name = 'qwen3-max' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'aliyun' AND pm.model_name = 'qwen3-rerank' AND pm.capability = 'RERANK')
  OR (sp.provider_type = 'aliyun' AND pm.model_name = 'qwen3.5-flash' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'aliyun' AND pm.model_name = 'qwen3.5-flash' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'aliyun' AND pm.model_name = 'qwen3.5-plus' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'aliyun' AND pm.model_name = 'qwen3.5-plus' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-haiku-4-5-20251001' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-haiku-4-5-20251001' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-opus-4-7' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-opus-4-7' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-opus-4-8' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-opus-4-8' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-sonnet-4-5-20250929' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-sonnet-4-5-20250929' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-sonnet-4-6' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'claude' AND pm.model_name = 'claude-sonnet-4-6' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'deepseek' AND pm.model_name = 'deepseek-v4-flash' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'deepseek' AND pm.model_name = 'deepseek-v4-pro' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'gemini' AND pm.model_name = 'gemini-2.5-flash' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'gemini' AND pm.model_name = 'gemini-2.5-flash' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'gemini' AND pm.model_name = 'gemini-2.5-pro' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'gemini' AND pm.model_name = 'gemini-3-pro-preview' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'gemini' AND pm.model_name = 'gemini-embedding-001' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'glm' AND pm.model_name = 'embedding-3' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'glm' AND pm.model_name = 'glm-5' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'glm' AND pm.model_name = 'glm-5-turbo' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'glm' AND pm.model_name = 'glm-5v-turbo' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'glm' AND pm.model_name = 'glm-asr-2512' AND pm.capability = 'ASR')
  OR (sp.provider_type = 'moonshot' AND pm.model_name = 'kimi-k2-thinking' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'moonshot' AND pm.model_name = 'kimi-k2-thinking-turbo' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'moonshot' AND pm.model_name = 'kimi-k2.6' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'moonshot' AND pm.model_name = 'kimi-k2.6' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'moonshot' AND pm.model_name = 'kimi-latest' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'gpt-5-mini' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'gpt-5-mini' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'gpt-5.1-chat-latest' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'gpt-5.1-chat-latest' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'gpt-5.4' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'gpt-5.4' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'gpt-5.5' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'gpt-5.5' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'openai' AND pm.model_name = 'text-embedding-3-large' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'xai' AND pm.model_name = 'grok-3-fast' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'xai' AND pm.model_name = 'grok-4' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'minimax' AND pm.model_name = 'minimax-m2.5' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'huggingface' AND pm.model_name = 'zai-org/GLM-5.2' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'huggingface' AND pm.model_name = 'deepseek-ai/DeepSeek-V4-Pro' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'huggingface' AND pm.model_name = 'Qwen/Qwen3.6-27B' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'huggingface' AND pm.model_name = 'Qwen/Qwen3.6-27B' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'huggingface' AND pm.model_name = 'MiniMaxAI/MiniMax-M3' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'huggingface' AND pm.model_name = 'MiniMaxAI/MiniMax-M3' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'huggingface' AND pm.model_name = 'moonshotai/Kimi-K2.7-Code' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'huggingface' AND pm.model_name = 'moonshotai/Kimi-K2.7-Code' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'openrouter' AND pm.model_name = 'anthropic/claude-sonnet-5' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openrouter' AND pm.model_name = 'anthropic/claude-sonnet-5' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'openrouter' AND pm.model_name = 'openai/gpt-5.5' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openrouter' AND pm.model_name = 'deepseek/deepseek-v4-pro' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openrouter' AND pm.model_name = 'z-ai/glm-5.2' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'openrouter' AND pm.model_name = 'x-ai/grok-4.3' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'hunyuan' AND pm.model_name = 'hunyuan-embedding' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'hunyuan' AND pm.model_name = 'hunyuan-lite' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'hunyuan' AND pm.model_name = 'hunyuan-pro' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'hunyuan' AND pm.model_name = 'hunyuan-standard' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'hunyuan' AND pm.model_name = 'hunyuan-standard-256K' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'jina' AND pm.model_name = 'jina-embeddings-v5-omni-nano' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'jina' AND pm.model_name = 'jina-embeddings-v5-omni-small' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'jina' AND pm.model_name = 'jina-embeddings-v5-text-nano' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'jina' AND pm.model_name = 'jina-embeddings-v5-text-small' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'jina' AND pm.model_name = 'jina-reranker-v3' AND pm.capability = 'RERANK')
  OR (sp.provider_type = 'volcengine' AND pm.model_name = 'doubao-embedding-vision-251215' AND pm.capability = 'EMBEDDING')
  OR (sp.provider_type = 'volcengine' AND pm.model_name = 'doubao-embedding-vision-251215' AND pm.capability = 'SPARSE_EMBEDDING')
  OR (sp.provider_type = 'volcengine' AND pm.model_name = 'doubao-seed-2-0-pro-260215' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'mimo' AND pm.model_name = 'mimo-v2.5' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'mimo' AND pm.model_name = 'mimo-v2.5' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'mimo' AND pm.model_name = 'mimo-v2.5-asr' AND pm.capability = 'ASR')
  OR (sp.provider_type = 'mimo' AND pm.model_name = 'mimo-v2.5-pro' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'siliconflow' AND pm.model_name = 'BAAI/bge-reranker-v2-m3' AND pm.capability = 'RERANK')
  OR (sp.provider_type = 'siliconflow' AND pm.model_name = 'Pro/deepseek-ai/DeepSeek-V4-Flash' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'siliconflow' AND pm.model_name = 'Pro/deepseek-ai/DeepSeek-V4-Pro' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'siliconflow' AND pm.model_name = 'Pro/moonshotai/Kimi-K2.6' AND pm.capability = 'CHAT')
  OR (sp.provider_type = 'siliconflow' AND pm.model_name = 'Pro/moonshotai/Kimi-K2.6' AND pm.capability = 'VISION')
  OR (sp.provider_type = 'siliconflow' AND pm.model_name = 'Qwen/Qwen3-Embedding-0.6B' AND pm.capability = 'EMBEDDING')
);

DELETE pm
FROM llm_provider_model pm
JOIN llm_system_provider sp ON sp.id = pm.provider_id
WHERE sp.provider_type = 'linkrag';

-- 3. LinkRag 系统兜底预设：独立维护，每个 capability 一条默认。
--    api_key 不写明文；已有预设会复用原密文，全新库需在 SOURCE 前设置 @linkrag_system_preset_api_key。
INSERT INTO llm_system_preset (
    provider_id, model_name, display_name, capability, provider_type,
    protocol, api_base_url, api_key, is_active, is_default
)
SELECT
    preset_rows.provider_id, preset_rows.model_name, preset_rows.display_name, preset_rows.capability, 'linkrag',
    preset_rows.protocol, preset_rows.api_base_url, preset_rows.api_key, TRUE, TRUE
FROM (
    SELECT
        sp.id AS provider_id,
        seed.model_name,
        seed.display_name,
        seed.capability,
        seed.protocol,
        seed.api_base_url,
        COALESCE(
            NULLIF(@linkrag_system_preset_api_key, ''),
            exact_preset.api_key,
            default_preset.api_key
        ) AS api_key
    FROM (
        SELECT 'qwen3-asr-flash' AS model_name, 'Qwen ASR Flash' AS display_name, 'ASR' AS capability, 'dashscope' AS protocol, 'https://dashscope.aliyuncs.com/api/v1' AS api_base_url
        UNION ALL SELECT 'deepseek-ai/DeepSeek-V4-Flash' AS model_name, 'DeepSeek V4 Flash' AS display_name, 'CHAT' AS capability, 'openai' AS protocol, 'https://api.siliconflow.cn/v1/chat/completions' AS api_base_url
        UNION ALL SELECT 'BAAI/bge-m3' AS model_name, 'BGE-M3' AS display_name, 'EMBEDDING' AS capability, 'openai' AS protocol, 'https://api.siliconflow.cn/v1/embeddings' AS api_base_url
        UNION ALL SELECT 'BAAI/bge-reranker-v2-m3' AS model_name, 'BGE Reranker M3' AS display_name, 'RERANK' AS capability, 'jina' AS protocol, 'https://api.siliconflow.cn/v1/rerank' AS api_base_url
        UNION ALL SELECT 'doubao-embedding-vision-251215' AS model_name, 'Doubao Sparse' AS display_name, 'SPARSE_EMBEDDING' AS capability, 'doubao_vision' AS protocol, 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal' AS api_base_url
        UNION ALL SELECT 'Qwen/Qwen3.6-27B' AS model_name, 'Qwen 3.6 27B' AS display_name, 'VISION' AS capability, 'openai' AS protocol, 'https://api.siliconflow.cn/v1/chat/completions' AS api_base_url
    ) seed
    JOIN llm_system_provider sp
      ON sp.provider_type = 'linkrag'
    LEFT JOIN llm_system_preset exact_preset
      ON exact_preset.provider_id = sp.id
     AND exact_preset.model_name = seed.model_name
     AND exact_preset.capability = seed.capability
    LEFT JOIN llm_system_preset default_preset
      ON default_preset.provider_type = 'linkrag'
     AND default_preset.capability = seed.capability
     AND default_preset.is_active = TRUE
     AND default_preset.is_default = TRUE
) preset_rows
WHERE preset_rows.api_key IS NOT NULL
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    provider_type = VALUES(provider_type),
    protocol     = VALUES(protocol),
    api_base_url = VALUES(api_base_url),
    api_key      = VALUES(api_key),
    is_active    = VALUES(is_active),
    is_default   = VALUES(is_default),
    updated_at   = CURRENT_TIMESTAMP;

UPDATE llm_system_preset preset
JOIN llm_system_provider sp
  ON sp.provider_type = 'linkrag'
JOIN (
    SELECT 'qwen3-asr-flash' AS model_name, 'ASR' AS capability
    UNION ALL SELECT 'deepseek-ai/DeepSeek-V4-Flash' AS model_name, 'CHAT' AS capability
    UNION ALL SELECT 'BAAI/bge-m3' AS model_name, 'EMBEDDING' AS capability
    UNION ALL SELECT 'BAAI/bge-reranker-v2-m3' AS model_name, 'RERANK' AS capability
    UNION ALL SELECT 'doubao-embedding-vision-251215' AS model_name, 'SPARSE_EMBEDDING' AS capability
    UNION ALL SELECT 'Qwen/Qwen3.6-27B' AS model_name, 'VISION' AS capability
) seed
  ON seed.capability = preset.capability
SET preset.is_default = FALSE,
    preset.updated_at = CURRENT_TIMESTAMP
WHERE preset.provider_type = 'linkrag'
  AND preset.is_default = TRUE
  AND NOT (
      preset.provider_id = sp.id
      AND preset.model_name = seed.model_name
      AND preset.capability = seed.capability
  );

UPDATE llm_system_preset preset
JOIN llm_system_provider sp
  ON sp.provider_type = 'linkrag'
LEFT JOIN (
    SELECT 'qwen3-asr-flash' AS model_name, 'ASR' AS capability
    UNION ALL SELECT 'deepseek-ai/DeepSeek-V4-Flash' AS model_name, 'CHAT' AS capability
    UNION ALL SELECT 'BAAI/bge-m3' AS model_name, 'EMBEDDING' AS capability
    UNION ALL SELECT 'BAAI/bge-reranker-v2-m3' AS model_name, 'RERANK' AS capability
    UNION ALL SELECT 'doubao-embedding-vision-251215' AS model_name, 'SPARSE_EMBEDDING' AS capability
    UNION ALL SELECT 'Qwen/Qwen3.6-27B' AS model_name, 'VISION' AS capability
) seed
  ON seed.model_name = preset.model_name
 AND seed.capability = preset.capability
SET preset.is_active = FALSE,
    preset.is_default = FALSE,
    preset.updated_at = CURRENT_TIMESTAMP
WHERE preset.provider_type = 'linkrag'
  AND preset.provider_id = sp.id
  AND seed.model_name IS NULL;

COMMIT;
