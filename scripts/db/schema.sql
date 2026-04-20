-- ===============================================
-- 1. 初始化系统厂商数据 (2026 真实可靠配置)
-- ===============================================
INSERT INTO llm_system_provider (provider_type, provider_name, api_base_url, supported_models, config_schema, is_active, priority)
VALUES
    ('openai', 'OpenAI', 'https://api.openai.com/v1',
     '{"gpt-4o":["CHAT","OCR","VISION"], "gpt-4-turbo":["CHAT"], "o1-preview":["REASONING"]}',
     '{"temperature":{"type":"float","default":0.7,"min":0,"max":2}, "max_tokens":{"type":"int","default":2000,"min":1,"max":128000}}',
     TRUE, 100),

    ('claude', 'Anthropic Claude', 'https://api.anthropic.com/v1',
     '{"claude-3-5-sonnet":["CHAT","OCR"], "claude-3-opus":["CHAT"]}',
     '{"temperature":{"type":"float","default":0.7,"min":0,"max":1}, "max_tokens":{"type":"int","default":4000,"min":1,"max":200000}}',
     TRUE, 95),

    ('deepseek', 'DeepSeek', 'https://api.deepseek.com/v1',
     '{"deepseek-v3":["CHAT"], "deepseek-coder":["CHAT","CODE"]}',
     '{"temperature":{"type":"float","default":1.0,"min":0,"max":2}, "max_tokens":{"type":"int","default":2000,"min":1,"max":8192}}',
     TRUE, 90),

    ('glm', '智谱 AI (Zhipu)', 'https://open.bigmodel.cn/api/paas/v4',
     '{"glm-4v":["CHAT","VISION"], "glm-4-plus":["CHAT"]}',
     '{"temperature":{"type":"float","default":0.9,"min":0.01,"max":0.99}, "top_p":{"type":"float","default":0.7,"min":0.01,"max":0.99}}',
     TRUE, 85),

    ('aliyun', '通义千问 (DashScope)', 'https://dashscope.aliyuncs.com/compatible-mode/v1',
     '{"qwen-max":["CHAT"], "qwen-plus":["CHAT"], "qwen-turbo":["CHAT"]}',
     '{"temperature":{"type":"float","default":0.8,"min":0,"max":2}}',
     TRUE, 80);

-- ===============================================
-- 2. 初始化管理员账户 (密码: admin123)
-- 注：ID 字段由于是自增，此处不再手动指定
-- ===============================================
INSERT INTO sys_user (username, password_hash, nickname, email, role, status)
VALUES ('admin', '$2a$10$EasYxZ6ZB.YqlgDI8XnH4uuFow/KHNVnTLhXhOoBvhPTMK.FdrvEW', '系统管理员', 'admin@tolink.com', 'ADMIN', 1);

-- ===============================================
-- 3. 可选：初始化一个测试用户的 LLM 配置 (示例)
-- ===============================================
-- 假设管理员 ID 为 10000，DeepSeek 厂商 ID 为 10002
INSERT INTO llm_user_config (user_id, provider_id, provider_type, provider_name, config_name, api_key, model_name, is_default)
VALUES (10000, 10002, 'deepseek', 'DeepSeek', '我的测试配置', 'sk-xxxxxxxxxxxx', 'deepseek-v3', TRUE);