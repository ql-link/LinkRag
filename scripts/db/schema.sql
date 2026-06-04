-- ===============================================
-- toLink-Rag 种子数据脚本 (seed data)
-- ===============================================
--
-- 用途：在已建表（migrations/db.sql baseline + migrations 0002~0012 全量升级）
--       的库上灌入一批贴近真实业务的初始化数据，便于本地联调 / 演示 / 集成测试。
--
-- 适配 schema：当前迁移链头（0012）。相对 migrations/db.sql baseline 的差异：
--   - dataset / document_original_file 新增 is_deleted + deleted_seq 软删列
--   - document_parsed_log 去掉 task_status/failure_reason，新增 retry_of_task_id
--   - document_post_process_pipeline 重命名为 document_parse_pipeline，
--     并新增 cleaning_*/pretokenize_*/sparse_vectorizing_* 阶段位
--   - kb_document_chunk 重构为 dense_/sparse_vector_status + lifecycle_status
--
-- 幂等：每张表先 DELETE 再 INSERT，可重复执行。显式主键均 >= 10000，
--       与各表 AUTO_INCREMENT=10000 起点对齐。
--
-- 执行：mysql -h 127.0.0.1 -P 3306 -u root -p tolink_rag_db < scripts/db/seed_data.sql
-- ===============================================

USE tolink_rag_db;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- 按外键依赖逆序清理，便于重复执行
DELETE FROM kb_document_chunk;
DELETE FROM document_parse_pipeline;
DELETE FROM document_parsed_log;
DELETE FROM document_parse_file;
DELETE FROM document_original_file;
DELETE FROM llm_usage_log;
DELETE FROM chat_message;
DELETE FROM chat_conversation;
DELETE FROM dataset;
DELETE FROM llm_user_config;
DELETE FROM llm_system_provider;
DELETE FROM sys_user;

-- ===============================================
-- 1. 系统用户 sys_user
-- ===============================================
INSERT INTO sys_user
    (id, username, password_hash, nickname, email, phone, avatar_url, role, status, last_login_at, created_at, updated_at)
VALUES
    (10001, 'admin',     '$2b$12$E1Qq7Xj8m0nKpVtq3w5bUu9Zl2QyB6cR4sD8fG1hJ3kL5mN7oP9q', '超级管理员', 'admin@tolink.ai',       '13800000001', 'https://oss.tolink.ai/avatar/admin.png',   'ADMIN', 1, '2026-05-31 09:12:33', '2026-04-01 10:00:00', '2026-05-31 09:12:33'),
    (10002, 'zhangwei',  '$2b$12$7sH2kLpQ9mNvR4tYuB6cXeJ1oZ3aD5fG8hK0lM2nP4qS6tU8wY0a', '张伟',     'zhangwei@example.com',  '13800000002', 'https://oss.tolink.ai/avatar/10002.png',   'USER',  1, '2026-05-31 08:45:10', '2026-04-03 14:22:00', '2026-05-31 08:45:10'),
    (10003, 'lifang',    '$2b$12$3aD5fG8hK0lM2nP4qS6tU.7sH2kLpQ9mNvR4tYuB6cXeJ1oZ3aD5', '李芳',     'lifang@example.com',    '13800000003', 'https://oss.tolink.ai/avatar/10003.png',   'USER',  1, '2026-05-30 19:03:51', '2026-04-08 09:15:00', '2026-05-30 19:03:51'),
    (10004, 'wangqiang', '$2b$12$9mNvR4tYuB6cXeJ1oZ3aD.5fG8hK0lM2nP4qS6tU8wY0a7sH2kLpQ', '王强',     'wangqiang@example.com', '13800000004', NULL,                                        'USER',  0, NULL,                  '2026-05-12 11:40:00', '2026-05-20 16:30:00');


-- ===============================================
-- 2. LLM 系统级厂商配置 llm_system_provider
-- ===============================================
-- provider_type 取值与 src/core/llm/factory.py 注册键严格对齐：
--   openai / anthropic / glm / deepseek / qwen
-- supported_capabilities 为 List[str]，
--   能力标签集合：CHAT / EMBEDDING / RERANK / VISION / OCR / TOOL_CALLING
-- api_base_url 取各 Provider 实现的 DEFAULT_API_BASE。
-- user_id=0 的 llm_user_config 记录承载系统预设配置。
-- ===============================================
INSERT INTO llm_system_provider
    (id, provider_type, provider_name, api_base_url, supported_capabilities, config_schema, is_active, priority, created_at, updated_at)
VALUES
    -- 10001 OpenAI：对话(含视觉/工具) + 文本向量化
    (10001, 'openai', 'OpenAI', 'https://api.openai.com/v1',
        JSON_ARRAY('CHAT','VISION','TOOL_CALLING','EMBEDDING'),
        JSON_OBJECT(
            'api_key',      JSON_OBJECT('type','string', 'required', TRUE,  'label','API Key'),
            'api_base_url', JSON_OBJECT('type','string', 'required', FALSE, 'default','https://api.openai.com/v1'),
            'temperature',  JSON_OBJECT('type','number', 'default', 0.7, 'min', 0, 'max', 2),
            'max_tokens',   JSON_OBJECT('type','integer','default', 4096),
            'top_p',        JSON_OBJECT('type','number', 'default', 1.0),
            'dimensions',   JSON_OBJECT('type','integer','required', FALSE, 'note','仅 EMBEDDING 模型生效'),
            'timeout_ms',   JSON_OBJECT('type','integer','default', 60000)
        ),
        TRUE, 85, '2026-04-01 10:00:00', '2026-04-01 10:00:00'),

    -- 10002 Anthropic Claude：对话(含视觉/工具)，无官方 embedding
    (10002, 'anthropic', 'Anthropic Claude', 'https://api.anthropic.com/v1',
        JSON_ARRAY('CHAT','VISION','TOOL_CALLING'),
        JSON_OBJECT(
            'api_key',      JSON_OBJECT('type','string', 'required', TRUE,  'label','API Key'),
            'api_base_url', JSON_OBJECT('type','string', 'required', FALSE, 'default','https://api.anthropic.com/v1'),
            'temperature',  JSON_OBJECT('type','number', 'default', 1.0, 'min', 0, 'max', 1),
            'max_tokens',   JSON_OBJECT('type','integer','default', 8192),
            'top_p',        JSON_OBJECT('type','number', 'default', 1.0),
            'timeout_ms',   JSON_OBJECT('type','integer','default', 90000)
        ),
        TRUE, 80, '2026-04-01 10:00:00', '2026-04-01 10:00:00'),

    -- 10003 智谱 GLM：对话 + 多模态(视觉/OCR) + 向量化
    (10003, 'glm', '智谱 GLM', 'https://open.bigmodel.cn/api/paas/v1',
        JSON_ARRAY('CHAT','TOOL_CALLING','VISION','OCR','EMBEDDING'),
        JSON_OBJECT(
            'api_key',      JSON_OBJECT('type','string', 'required', TRUE,  'label','API Key'),
            'api_base_url', JSON_OBJECT('type','string', 'required', FALSE, 'default','https://open.bigmodel.cn/api/paas/v1'),
            'temperature',  JSON_OBJECT('type','number', 'default', 0.6, 'min', 0, 'max', 1),
            'max_tokens',   JSON_OBJECT('type','integer','default', 4096),
            'dimensions',   JSON_OBJECT('type','integer','default', 2048, 'note','embedding-3 维度'),
            'timeout_ms',   JSON_OBJECT('type','integer','default', 60000)
        ),
        TRUE, 70, '2026-04-02 11:30:00', '2026-04-02 11:30:00'),

    -- 10004 DeepSeek：对话(含推理)，OpenAI 兼容协议
    (10004, 'deepseek', 'DeepSeek', 'https://api.deepseek.com/v1',
        JSON_ARRAY('CHAT','TOOL_CALLING'),
        JSON_OBJECT(
            'api_key',      JSON_OBJECT('type','string', 'required', TRUE,  'label','API Key'),
            'api_base_url', JSON_OBJECT('type','string', 'required', FALSE, 'default','https://api.deepseek.com/v1'),
            'temperature',  JSON_OBJECT('type','number', 'default', 0.5, 'min', 0, 'max', 2),
            'max_tokens',   JSON_OBJECT('type','integer','default', 4096),
            'timeout_ms',   JSON_OBJECT('type','integer','default', 60000)
        ),
        TRUE, 60, '2026-04-05 09:00:00', '2026-04-05 09:00:00'),

    -- 10005 Qwen（通义千问）：系统默认 provider，覆盖 对话/视觉/OCR/重排/向量化 全能力
    (10005, 'qwen', '通义千问 Qwen', 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        JSON_ARRAY('CHAT','TOOL_CALLING','VISION','OCR','RERANK','EMBEDDING'),
        JSON_OBJECT(
            'api_key',      JSON_OBJECT('type','string', 'required', TRUE,  'label','DashScope API Key'),
            'api_base_url', JSON_OBJECT('type','string', 'required', FALSE, 'default','https://dashscope.aliyuncs.com/compatible-mode/v1'),
            'temperature',  JSON_OBJECT('type','number', 'default', 0.7, 'min', 0, 'max', 2),
            'max_tokens',   JSON_OBJECT('type','integer','default', 4096),
            'top_p',        JSON_OBJECT('type','number', 'default', 0.8),
            'dimensions',   JSON_OBJECT('type','integer','default', 1024, 'note','text-embedding-v4 维度'),
            'timeout_ms',   JSON_OBJECT('type','integer','default', 60000)
        ),
        TRUE, 95, '2026-04-01 10:00:00', '2026-04-01 10:00:00'),

    -- 10006 OpenAI 兼容自建网关：演示一条 is_active=FALSE 的停用厂商
    (10006, 'openai', 'OpenAI 兼容网关(停用)', 'https://llm-gateway.internal.example.com/v1',
        JSON_ARRAY('CHAT','TOOL_CALLING','EMBEDDING'),
        JSON_OBJECT(
            'api_key',      JSON_OBJECT('type','string', 'required', TRUE),
            'api_base_url', JSON_OBJECT('type','string', 'required', TRUE),
            'temperature',  JSON_OBJECT('type','number', 'default', 0.7),
            'timeout_ms',   JSON_OBJECT('type','integer','default', 120000)
        ),
        FALSE, 30, '2026-05-06 14:00:00', '2026-05-18 09:20:00');

-- ===============================================
-- 3. 用户级 LLM 配置 llm_user_config
--    api_key 为加密后密文（演示用占位 Fernet 风格 token）
--    user_id=0 为系统预设配置：可切换、可使用，不由 Python 对外展示明文细节。
-- ===============================================
INSERT INTO llm_user_config
    (id, user_id, provider_id, provider_type, provider_name, config_name, api_key, custom_api_base_url,
     model_name, priority, is_active, is_default, timeout_ms, max_retries, stream_enabled, capability, extra_config, created_at, updated_at)
VALUES
    -- 系统预设：未设置个人默认配置时兜底使用
    (10000, 0, 10005, 'qwen', '通义千问 Qwen', '系统预设对话',
        'gAAAAABm1cQ8system-chat-preset-encrypted-key-placeholder', NULL,
        'qwen3.5-flash', 100, TRUE, TRUE, 60000, 3, TRUE, 'CHAT',
        JSON_OBJECT('temperature', 0.7, 'top_p', 0.8), '2026-06-04 10:00:00', '2026-06-04 10:00:00'),

    (10007, 0, 10005, 'qwen', '通义千问 Qwen', '系统预设向量化',
        'gAAAAABm1cQ8system-embedding-preset-encrypted-key-placeholder', NULL,
        'text-embedding-v4', 100, TRUE, TRUE, 30000, 3, FALSE, 'EMBEDDING',
        JSON_OBJECT('dimensions', 1024), '2026-06-04 10:00:00', '2026-06-04 10:00:00'),

    -- 张伟：OpenAI 对话（默认）+ OpenAI 向量化（默认）
    (10001, 10002, 10001, 'openai', 'OpenAI', '我的GPT-4o对话',
        'gAAAAABm1cQ8xJ3kL5mN7oP9qZl2QyB6cR4sD8fG1hJ3kL5mN7oP9q-encrypted-key-01', NULL,
        'gpt-4o', 90, TRUE, TRUE, 60000, 3, TRUE, 'CHAT',
        JSON_OBJECT('temperature', 0.7, 'top_p', 1.0), '2026-04-03 15:00:00', '2026-05-28 10:11:00'),

    (10002, 10002, 10001, 'openai', 'OpenAI', 'OpenAI向量化',
        'gAAAAABm1cQ8aD5fG8hK0lM2nP4qS6tU8wY0a7sH2kLpQ9mNvR4tYuB-encrypted-key-02', NULL,
        'text-embedding-3-small', 90, TRUE, TRUE, 30000, 3, FALSE, 'EMBEDDING',
        JSON_OBJECT('dimensions', 1536), '2026-04-03 15:05:00', '2026-04-03 15:05:00'),

    -- 张伟：Claude 对话（备用，非默认）
    (10003, 10002, 10002, 'claude', 'Anthropic Claude', 'Claude兜底',
        'gAAAAABm1cQ8nP4qS6tU8wY0a7sH2kLpQ9mNvR4tYuB6cXeJ1oZ3aD-encrypted-key-03', NULL,
        'claude-sonnet-4-6', 70, TRUE, FALSE, 90000, 2, TRUE, 'CHAT',
        JSON_OBJECT('temperature', 1.0), '2026-04-10 09:20:00', '2026-04-10 09:20:00'),

    -- 李芳：GLM 对话（默认）+ GLM 向量化（默认）
    (10004, 10003, 10003, 'glm', '智谱 GLM', '智谱GLM对话',
        'gAAAAABm1cQ8tYuB6cXeJ1oZ3aD5fG8hK0lM2nP4qS6tU8wY0a7sH2-encrypted-key-04', NULL,
        'glm-4-plus', 80, TRUE, TRUE, 60000, 3, TRUE, 'CHAT',
        JSON_OBJECT('temperature', 0.6), '2026-04-08 10:00:00', '2026-05-29 14:00:00'),

    (10005, 10003, 10003, 'glm', '智谱 GLM', '智谱向量化',
        'gAAAAABm1cQ8cXeJ1oZ3aD5fG8hK0lM2nP4qS6tU8wY0a7sH2kLpQ9-encrypted-key-05', NULL,
        'embedding-3', 80, TRUE, TRUE, 30000, 3, FALSE, 'EMBEDDING',
        JSON_OBJECT('dimensions', 2048), '2026-04-08 10:05:00', '2026-04-08 10:05:00'),

    -- 李芳：DeepSeek 自建网关对话（默认未启用）
    (10006, 10003, 10004, 'deepseek', 'DeepSeek', 'DeepSeek私有网关',
        'gAAAAABm1cQ8B6cXeJ1oZ3aD5fG8hK0lM2nP4qS6tU8wY0a7sH2kLp-encrypted-key-06',
        'https://llm-gateway.internal.lifang.com/v1',
        'deepseek-chat', 50, FALSE, FALSE, 60000, 3, TRUE, 'CHAT',
        JSON_OBJECT('temperature', 0.5), '2026-05-01 16:00:00', '2026-05-15 09:30:00');

-- ===============================================
-- 4. 数据集 dataset（含软删列）
-- ===============================================
INSERT INTO dataset
    (id, user_id, name, description, status, is_deleted, deleted_seq, created_at, updated_at)
VALUES
    (10001, 10002, '产品技术文档库', '内部产品手册、架构设计与 API 文档的统一知识库',     'ACTIVE',  0, 0, '2026-04-04 09:00:00', '2026-05-30 18:20:00'),
    (10002, 10002, '客服话术知识库', '一线客服常见问题与标准应答话术',                   'ACTIVE',  0, 0, '2026-04-20 11:00:00', '2026-05-29 17:45:00'),
    (10003, 10003, '法律合同库',     '采购、销售与劳动合同模板及条款解读',               'ACTIVE',  0, 0, '2026-04-09 10:30:00', '2026-05-28 15:10:00'),
    -- 一条软删数据集：deleted_seq = 自身 id，支持删后同名重建
    (10004, 10003, '废弃测试库',     '早期导入的测试数据，已逻辑删除',                   'ARCHIVED', 1, 10004, '2026-04-15 14:00:00', '2026-05-10 10:00:00');

-- ===============================================
-- 5. 对话 chat_conversation
-- ===============================================
INSERT INTO chat_conversation
    (id, user_id, dataset_id, last_config_id, last_model_name, title, is_pinned, created_at, updated_at)
VALUES
    (10001, 10002, 10001, 10001, 'gpt-4o',     '如何配置向量化模型',     TRUE,  '2026-05-20 09:00:00', '2026-05-20 09:18:00'),
    (10002, 10002, 10001, 10001, 'gpt-4o',     '解析失败重试机制说明',   FALSE, '2026-05-25 14:30:00', '2026-05-25 14:42:00'),
    (10003, 10003, 10003, 10004, 'glm-4-plus', '劳动合同试用期条款',     FALSE, '2026-05-28 10:00:00', '2026-05-28 10:09:00');

-- ===============================================
-- 6. 对话消息 chat_message
-- ===============================================
INSERT INTO chat_message
    (id, conversation_id, config_id, model_name, role, content, token_count, created_at)
VALUES
    (10001, 10001, NULL,  NULL,     'system',    '你是产品技术文档库的智能助手，请基于检索到的文档片段回答用户问题，并标注来源。', 38, '2026-05-20 09:00:00'),
    (10002, 10001, 10001, 'gpt-4o', 'user',      '我想给知识库换一个向量化模型，应该怎么配置？',                                   21, '2026-05-20 09:00:30'),
    (10003, 10001, 10001, 'gpt-4o', 'assistant', '在「用户 LLM 配置」中新增一条 capability=EMBEDDING 的配置，并设为默认即可。系统会在下次解析入库时使用新的向量模型；已索引的历史 chunk 需要重新触发解析才会用新模型重算向量。', 96, '2026-05-20 09:01:10'),
    (10004, 10001, 10001, 'gpt-4o', 'user',      '已有的 chunk 会自动重算吗？',                                                    14, '2026-05-20 09:17:00'),
    (10005, 10001, 10001, 'gpt-4o', 'assistant', '不会自动重算。需要对相关原文件触发一次手动重试解析（manual_retry），流水线会重新走分片→向量化→ES 入库，使用当前默认的 EMBEDDING 配置。', 72, '2026-05-20 09:18:00'),

    (10006, 10002, 10001, 'gpt-4o', 'user',      '解析任务失败后是怎么重试的？',                                                   16, '2026-05-25 14:30:00'),
    (10007, 10002, 10001, 'gpt-4o', 'assistant', '解析失败会在 document_parse_pipeline 记录 failed_stage 与 recover_from_stage，用户手动重试时会新建一条 parsed_log（retry_of_task_id 指向上一轮 task_id），并通过 superseded_by_task_id 做 CAS 占用，避免并发重复重试。', 118, '2026-05-25 14:42:00'),

    (10008, 10003, 10004, 'glm-4-plus', 'user',      '帮我看下这份劳动合同的试用期约定是否合规。',                                  19, '2026-05-28 10:00:00'),
    (10009, 10003, 10004, 'glm-4-plus', 'assistant', '根据检索到的条款：三年期固定合同对应试用期不得超过六个月。当前合同写的是「试用期三个月」，在法定上限内，合规。建议补充试用期工资不低于转正工资 80% 的约定。', 88, '2026-05-28 10:09:00');

-- ===============================================
-- 7. LLM 调用用量日志 llm_usage_log
-- ===============================================
INSERT INTO llm_usage_log
    (id, user_id, config_id, provider_type, model_name, prompt_tokens, completion_tokens, total_tokens,
     latency_ms, status, error_message, fallback_config_id, conversation_id, created_at)
VALUES
    (10001, 10002, 10001, 'openai', 'gpt-4o',     157, 96, 253, 1840, 'success', NULL, NULL, 10001, '2026-05-20 09:01:10'),
    (10002, 10002, 10001, 'openai', 'gpt-4o',     203, 72, 275, 1620, 'success', NULL, NULL, 10001, '2026-05-20 09:18:00'),
    (10003, 10002, 10001, 'openai', 'gpt-4o',     188, 118, 306, 2210, 'success', NULL, NULL, 10002, '2026-05-25 14:42:00'),
    -- 一条触发 fallback 的记录：主配置超时，回落到 Claude 兜底
    (10004, 10002, 10003, 'claude', 'claude-sonnet-4-6', 188, 0, 188, 90000, 'failed', 'Upstream request timeout after 90000ms', 10001, 10002, '2026-05-25 14:40:30'),
    (10005, 10003, 10004, 'glm',    'glm-4-plus', 142, 88, 230, 1370, 'success', NULL, NULL, 10003, '2026-05-28 10:09:00');

-- ===============================================
-- 8. 原始文档上传 document_original_file（含软删列）
-- ===============================================
INSERT INTO document_original_file
    (id, dataset_id, user_id, original_filename, file_suffix, file_size, content_type,
     bucket_name, object_key, file_url, upload_status, is_upload_success, failure_reason,
     is_deleted, deleted_seq, created_at, updated_at)
VALUES
    (10001, 10001, 10002, '产品架构设计v2.md', 'md', 48213,
        'text/markdown', 'rag-raw', 'raw/10002/10001/产品架构设计v2.md',
        'http://minio:9000/rag-raw/raw/10002/10001/产品架构设计v2.md', 'success', 1, NULL,
        0, 0, '2026-04-04 09:30:00', '2026-04-04 09:31:20'),

    (10002, 10001, 10002, 'OpenAPI接口规范.pdf', 'pdf', 1284560,
        'application/pdf', 'rag-raw', 'raw/10002/10001/OpenAPI接口规范.pdf',
        'http://minio:9000/rag-raw/raw/10002/10001/OpenAPI接口规范.pdf', 'success', 1, NULL,
        0, 0, '2026-04-04 09:35:00', '2026-04-04 09:37:05'),

    (10003, 10002, 10002, '客服常见问题FAQ.docx', 'docx', 96400,
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'rag-raw',
        'raw/10002/10002/客服常见问题FAQ.docx',
        'http://minio:9000/rag-raw/raw/10002/10002/客服常见问题FAQ.docx', 'success', 1, NULL,
        0, 0, '2026-04-20 11:20:00', '2026-04-20 11:21:10'),

    (10004, 10003, 10003, '劳动合同模板2026.docx', 'docx', 73820,
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'rag-raw',
        'raw/10003/10003/劳动合同模板2026.docx',
        'http://minio:9000/rag-raw/raw/10003/10003/劳动合同模板2026.docx', 'success', 1, NULL,
        0, 0, '2026-04-09 11:00:00', '2026-04-09 11:01:30'),

    -- 一条上传失败的记录
    (10005, 10003, 10003, '扫描件合同.pdf', 'pdf', 0,
        'application/pdf', 'rag-raw', NULL, NULL, 'failed', 0, '客户端中断上传，OSS 未收到完整对象',
        0, 0, '2026-05-02 16:10:00', '2026-05-02 16:10:45'),

    -- 一条软删的原文件：deleted_seq = 自身 id
    (10006, 10004, 10003, '废弃测试文档.txt', 'txt', 1024,
        'text/plain', 'rag-raw', 'raw/10003/10004/废弃测试文档.txt',
        'http://minio:9000/rag-raw/raw/10003/10004/废弃测试文档.txt', 'success', 1, NULL,
        1, 10006, '2026-04-15 14:30:00', '2026-05-10 10:00:00');

-- ===============================================
-- 9. 文件解析表 document_parse_file
-- ===============================================
INSERT INTO document_parse_file
    (id, document_original_file_id, dataset_id, user_id, latest_parse_task_id, original_filename, parse_count, created_at, updated_at)
VALUES
    (10001, 10001, 10001, 10002, 'a1b2c3d4-1111-4a1b-8c2d-0e1f2a3b4c01', '产品架构设计v2.md',    1, '2026-04-04 09:31:30', '2026-04-04 09:32:10'),
    (10002, 10002, 10001, 10002, 'a1b2c3d4-2222-4a1b-8c2d-0e1f2a3b4c02', 'OpenAPI接口规范.pdf',  1, '2026-04-04 09:37:10', '2026-04-04 09:39:40'),
    (10003, 10003, 10002, 10002, 'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c04', '客服常见问题FAQ.docx', 2, '2026-04-20 11:21:20', '2026-05-25 14:50:00'),
    (10004, 10004, 10003, 10003, 'a1b2c3d4-4444-4a1b-8c2d-0e1f2a3b4c05', '劳动合同模板2026.docx', 1, '2026-04-09 11:01:40', '2026-04-09 11:03:20');

-- ===============================================
-- 10. 文件解析产物快照 document_parsed_log
--     （含一条 retry_of_task_id 串联的重试链）
-- ===============================================
INSERT INTO document_parsed_log
    (id, task_id, document_original_file_id, document_parse_file_id, trigger_mode,
     parsed_filename, parsed_bucket_name, parsed_object_key, parsed_file_url,
     parsed_at, parse_started_at, parse_finished_at, parse_duration_ms, retry_of_task_id, created_at, updated_at)
VALUES
    (10001, 'a1b2c3d4-1111-4a1b-8c2d-0e1f2a3b4c01', 10001, 10001, 'upload_auto',
        '产品架构设计v2.md', 'rag-parsed', 'parsed/10002/10001/产品架构设计v2.md',
        'http://minio:9000/rag-parsed/parsed/10002/10001/产品架构设计v2.md',
        '2026-04-04 09:32:05', '2026-04-04 09:31:35', '2026-04-04 09:32:05', 30210, NULL,
        '2026-04-04 09:31:30', '2026-04-04 09:32:10'),

    (10002, 'a1b2c3d4-2222-4a1b-8c2d-0e1f2a3b4c02', 10002, 10002, 'upload_auto',
        'OpenAPI接口规范.md', 'rag-parsed', 'parsed/10002/10001/OpenAPI接口规范.md',
        'http://minio:9000/rag-parsed/parsed/10002/10001/OpenAPI接口规范.md',
        '2026-04-04 09:39:30', '2026-04-04 09:37:15', '2026-04-04 09:39:30', 135200, NULL,
        '2026-04-04 09:37:10', '2026-04-04 09:39:40'),

    -- 客服FAQ：第一轮自动解析失败（产物为空）
    (10003, 'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c03', 10003, 10003, 'upload_auto',
        NULL, NULL, NULL, NULL,
        NULL, '2026-04-20 11:21:25', '2026-04-20 11:21:40', 15300, NULL,
        '2026-04-20 11:21:20', '2026-04-20 11:21:40'),

    -- 客服FAQ：手动重试成功，retry_of_task_id 指向上一轮 task_id
    (10004, 'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c04', 10003, 10003, 'manual_retry',
        '客服常见问题FAQ.md', 'rag-parsed', 'parsed/10002/10002/客服常见问题FAQ.md',
        'http://minio:9000/rag-parsed/parsed/10002/10002/客服常见问题FAQ.md',
        '2026-05-25 14:49:50', '2026-05-25 14:49:20', '2026-05-25 14:49:50', 29800,
        'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c03',
        '2026-05-25 14:49:10', '2026-05-25 14:50:00'),

    (10005, 'a1b2c3d4-4444-4a1b-8c2d-0e1f2a3b4c05', 10004, 10004, 'upload_auto',
        '劳动合同模板2026.md', 'rag-parsed', 'parsed/10003/10003/劳动合同模板2026.md',
        'http://minio:9000/rag-parsed/parsed/10003/10003/劳动合同模板2026.md',
        '2026-04-09 11:03:10', '2026-04-09 11:01:45', '2026-04-09 11:03:10', 85100, NULL,
        '2026-04-09 11:01:40', '2026-04-09 11:03:20');

-- ===============================================
-- 11. 文件解析流程状态 document_parse_pipeline
--     6 阶段：cleaning / chunking / vectorizing / pretokenize / es_indexing / sparse_vectorizing
-- ===============================================
INSERT INTO document_parse_pipeline
    (id, document_parsed_log_id, task_id, document_original_file_id, document_parse_file_id,
     pipeline_status, cleaning_status, chunking_status, vectorizing_status, pretokenize_status,
     es_indexing_status, sparse_vectorizing_status,
     failed_stage, recover_from_stage, failure_reason,
     cleaning_duration_ms, chunking_duration_ms, vectorizing_duration_ms, pretokenize_duration_ms,
     es_indexing_duration_ms, sparse_vectorizing_duration_ms, total_duration_ms,
     superseded_by_task_id, started_at, finished_at, created_at, updated_at)
VALUES
    -- 全链路成功
    (10001, 10001, 'a1b2c3d4-1111-4a1b-8c2d-0e1f2a3b4c01', 10001, 10001,
        'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS',
        NULL, NULL, NULL,
        30210, 1820, 4300, 760, 980, 1240, 39310,
        NULL, '2026-04-04 09:31:35', '2026-04-04 09:32:55', '2026-04-04 09:31:30', '2026-04-04 09:32:55'),

    (10002, 10002, 'a1b2c3d4-2222-4a1b-8c2d-0e1f2a3b4c02', 10002, 10002,
        'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS',
        NULL, NULL, NULL,
        135200, 4100, 9800, 1530, 2100, 2680, 155410,
        NULL, '2026-04-04 09:37:15', '2026-04-04 09:40:30', '2026-04-04 09:37:10', '2026-04-04 09:40:30'),

    -- 第一轮 cleaning 阶段失败，被重试任务接班（superseded_by_task_id 指向重试 task_id）
    (10003, 10003, 'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c03', 10003, 10003,
        'FAILED', 'FAILED', 'PENDING', 'PENDING', 'PENDING', 'PENDING', 'PENDING',
        'CLEANING', 'CLEANING', 'docx 转换中断：嵌入对象解析异常 (unzip EOF)',
        15300, NULL, NULL, NULL, NULL, NULL, 15300,
        'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c04', '2026-04-20 11:21:25', '2026-04-20 11:21:40', '2026-04-20 11:21:20', '2026-05-25 14:49:10'),

    -- 重试任务：全链路成功
    (10004, 10004, 'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c04', 10003, 10003,
        'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS',
        NULL, NULL, NULL,
        29800, 1450, 3900, 680, 870, 1100, 37800,
        NULL, '2026-04-20 11:21:20', '2026-05-25 14:50:10', '2026-05-25 14:49:10', '2026-05-25 14:50:10'),

    -- 进行中：sparse 阶段尚未完成
    (10005, 10005, 'a1b2c3d4-4444-4a1b-8c2d-0e1f2a3b4c05', 10004, 10004,
        'PROCESSING', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'PROCESSING',
        NULL, NULL, NULL,
        85100, 2300, 6100, 1020, 1340, NULL, NULL,
        NULL, '2026-04-09 11:01:45', NULL, '2026-04-09 11:01:40', '2026-04-09 11:03:25');

-- ===============================================
-- 12. 文档 Chunk 真值记录 kb_document_chunk
--     dense/sparse/es 三类索引状态 + lifecycle_status 业务生命周期
-- ===============================================
INSERT INTO kb_document_chunk
    (id, chunk_id, doc_id, set_id, user_id, bucket_id, content, content_hash, chunk_type,
     start_line, end_line, chunk_index,
     dense_vector_status, dense_vector_model, sparse_vector_status, sparse_vector_model, es_status,
     lifecycle_status, create_time, update_time)
VALUES
    -- 文档 10001（产品架构设计v2.md）的 3 个 chunk，全部成功
    (10001, 'a1b2c3d4-1111-4a1b-8c2d-0e1f2a3b4c01_0', 10001, 10001, 10002, 3,
        '# 系统总体架构\n\ntoLink-Rag 采用分层架构：API 网关层负责鉴权与路由，核心业务层承载文档解析、分块与向量化，存储层由 MySQL（元数据）、Qdrant（向量）与 Elasticsearch（全文）组成。',
        'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9', 'heading',
        1, 6, 0,
        'SUCCESS', 'text-embedding-3-small', 'SUCCESS', 'bge-m3-sparse', 'SUCCESS',
        'ACTIVE', '2026-04-04 09:32:10', '2026-04-04 09:32:55'),

    (10002, 'a1b2c3d4-1111-4a1b-8c2d-0e1f2a3b4c01_1', 10001, 10001, 10002, 3,
        '## 解析流水线\n\n文档上传后由 MQ 触发解析任务，流水线依次执行：文档清洗 → 分块 → 稠密向量化 → 预分词 → ES 入库 → 稀疏向量化，整体状态由 document_parse_pipeline 单表权威维护。',
        'c1a5298f939e87e8f962a5edfc206918b6a8c44e21a1f4f4d3b8e9a0c7d5e6f2', 'paragraph',
        8, 12, 1,
        'SUCCESS', 'text-embedding-3-small', 'SUCCESS', 'bge-m3-sparse', 'SUCCESS',
        'ACTIVE', '2026-04-04 09:32:12', '2026-04-04 09:32:55'),

    (10003, 'a1b2c3d4-1111-4a1b-8c2d-0e1f2a3b4c01_2', 10001, 10001, 10002, 3,
        '## 检索召回\n\n查询阶段并行执行稠密向量召回与稀疏向量召回，再通过 RRF 融合排序，最终交由 Reranker 精排返回 TopK。',
        'd2e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6', 'paragraph',
        14, 18, 2,
        'SUCCESS', 'text-embedding-3-small', 'SUCCESS', 'bge-m3-sparse', 'SUCCESS',
        'ACTIVE', '2026-04-04 09:32:14', '2026-04-04 09:32:55'),

    -- 文档 10002（OpenAPI接口规范）含一个表格 chunk
    (10004, 'a1b2c3d4-2222-4a1b-8c2d-0e1f2a3b4c02_0', 10002, 10001, 10002, 7,
        '## POST /v1/datasets/{id}/documents\n\n上传文档接口，支持 multipart/form-data，单文件上限 50MB，返回 document_original_file_id。',
        'e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4', 'heading',
        1, 4, 0,
        'SUCCESS', 'text-embedding-3-small', 'SUCCESS', 'bge-m3-sparse', 'SUCCESS',
        'ACTIVE', '2026-04-04 09:39:40', '2026-04-04 09:40:30'),

    (10005, 'a1b2c3d4-2222-4a1b-8c2d-0e1f2a3b4c02_1', 10002, 10001, 10002, 7,
        '| 参数 | 类型 | 必填 | 说明 |\n| --- | --- | --- | --- |\n| file | binary | 是 | 待上传文件 |\n| parse_now | bool | 否 | 是否立即触发解析，默认 true |',
        'f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5', 'table',
        6, 10, 1,
        'SUCCESS', 'text-embedding-3-small', 'SUCCESS', 'bge-m3-sparse', 'SUCCESS',
        'ACTIVE', '2026-04-04 09:39:42', '2026-04-04 09:40:30'),

    -- 文档 10003（客服FAQ，重试成功后入库）2 个 chunk
    (10006, 'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c04_0', 10003, 10002, 10002, 5,
        '### 如何重置密码？\n\n登录页点击「忘记密码」，输入注册邮箱后系统将发送重置链接，链接有效期 30 分钟。',
        'a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6', 'paragraph',
        1, 3, 0,
        'SUCCESS', 'text-embedding-3-small', 'SUCCESS', 'bge-m3-sparse', 'SUCCESS',
        'ACTIVE', '2026-05-25 14:50:00', '2026-05-25 14:50:10'),

    (10007, 'a1b2c3d4-3333-4a1b-8c2d-0e1f2a3b4c04_1', 10003, 10002, 10002, 5,
        '### 订单多久发货？\n\n现货商品 24 小时内发货，预售商品以商品详情页标注的发货时间为准。',
        'b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7', 'paragraph',
        5, 7, 1,
        'SUCCESS', 'text-embedding-3-small', 'SUCCESS', 'bge-m3-sparse', 'SUCCESS',
        'ACTIVE', '2026-05-25 14:50:02', '2026-05-25 14:50:10'),

    -- 文档 10004（劳动合同，进行中）：dense/es 成功，sparse 仍 PENDING
    (10008, 'a1b2c3d4-4444-4a1b-8c2d-0e1f2a3b4c05_0', 10004, 10003, 10003, 2,
        '第三条 试用期\n\n甲乙双方约定试用期三个月，自 ____ 年 __ 月 __ 日起至 ____ 年 __ 月 __ 日止。试用期工资不低于本岗位转正工资的百分之八十。',
        'c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8', 'paragraph',
        12, 16, 0,
        'SUCCESS', 'embedding-3', 'PENDING', NULL, 'SUCCESS',
        'ACTIVE', '2026-04-09 11:03:20', '2026-04-09 11:03:25'),

    (10009, 'a1b2c3d4-4444-4a1b-8c2d-0e1f2a3b4c05_1', 10004, 10003, 10003, 2,
        '第四条 劳动报酬\n\n乙方月工资为人民币 ____ 元，甲方于每月 15 日前以货币形式足额支付上一自然月工资。',
        'd8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9', 'paragraph',
        18, 21, 1,
        'SUCCESS', 'embedding-3', 'PENDING', NULL, 'SUCCESS',
        'ACTIVE', '2026-04-09 11:03:22', '2026-04-09 11:03:25'),

    -- 一个已被业务移除的 chunk（lifecycle REMOVED），等待异步清理外部索引
    (10010, 'a1b2c3d4-4444-4a1b-8c2d-0e1f2a3b4c05_2', 10004, 10003, 10003, 2,
        '附则\n\n本合同一式两份，甲乙双方各执一份，自双方签字盖章之日起生效。',
        'e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0', 'paragraph',
        23, 25, 2,
        'SUCCESS', 'embedding-3', 'SUCCESS', 'bge-m3-sparse', 'SUCCESS',
        'REMOVED', '2026-04-09 11:03:24', '2026-05-28 15:10:00');

SET FOREIGN_KEY_CHECKS = 1;

-- ===============================================
-- 种子数据汇总
--   sys_user                : 4  (1 ADMIN + 3 USER，含 1 禁用)
--   llm_system_provider     : 4  (openai / claude / glm / deepseek)
--   llm_user_config         : 6  (CHAT / EMBEDDING，含默认与兜底)
--   dataset                 : 4  (含 1 软删)
--   chat_conversation       : 3
--   chat_message            : 9
--   llm_usage_log           : 5  (含 1 fallback 失败)
--   document_original_file  : 6  (含 1 上传失败 + 1 软删)
--   document_parse_file     : 4
--   document_parsed_log     : 5  (含 1 失败 + 1 重试链)
--   document_parse_pipeline : 5  (成功 / 失败被接班 / 进行中)
--   kb_document_chunk       : 10 (含 sparse PENDING 与 1 个 REMOVED)
-- ===============================================
