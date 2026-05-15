-- ===============================================
-- toLink-Service 数据库初始化脚本 (自增 ID 版)
-- ===============================================

CREATE DATABASE IF NOT EXISTS tolink_rag_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE tolink_rag_db;

-- 1. 系统用户表
CREATE TABLE IF NOT EXISTS sys_user (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '用户唯一标识',
    username        VARCHAR(64)    NOT NULL COMMENT '登录账号',
    password_hash   VARCHAR(255)   NOT NULL COMMENT '加密后的密码',
    nickname        VARCHAR(64)    COMMENT '用户昵称',
    email           VARCHAR(128)   COMMENT '邮箱地址',
    phone           VARCHAR(20)    COMMENT '手机号',
    avatar_url      VARCHAR(512)   COMMENT '头像地址',
    role            ENUM('ADMIN', 'USER') NOT NULL DEFAULT 'USER' COMMENT '角色: ADMIN/USER',
    status          TINYINT        NOT NULL DEFAULT 1 COMMENT '状态: 1-正常, 0-禁用',
    last_login_at   DATETIME       COMMENT '最后登录时间',
    created_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_username (username),
    UNIQUE KEY uk_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '系统用户表';

-- 2. LLM 系统级厂商配置表
CREATE TABLE IF NOT EXISTS llm_system_provider (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '厂商唯一标识',
    provider_type   VARCHAR(32)    NOT NULL COMMENT '厂商类型：openai/claude/glm/deepseek',
    provider_name   VARCHAR(64)    NOT NULL COMMENT '厂商展示名称，如 "OpenAI"',
    api_base_url    VARCHAR(512)   NOT NULL COMMENT '官方默认 API 地址',
    supported_models JSON           COMMENT '支持模型与能力映射',
    config_schema   JSON           COMMENT '配置参数 Schema',
    is_active       BOOLEAN        NOT NULL DEFAULT TRUE COMMENT '是否启用',
    priority        INT            NOT NULL DEFAULT 50 COMMENT '厂商优先级（1-100）',
    created_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_provider_type (provider_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT 'LLM 系统级厂商配置表';

-- 3. 用户级 LLM 配置表
CREATE TABLE IF NOT EXISTS llm_user_config (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '配置唯一标识',
    user_id             BIGINT UNSIGNED NOT NULL COMMENT '用户 ID',
    provider_id         BIGINT UNSIGNED NOT NULL COMMENT '关联 SystemProvider ID',
    provider_type       VARCHAR(32)     NOT NULL COMMENT '厂商类型快照',
    provider_name       VARCHAR(64)     NOT NULL COMMENT '厂商名称快照',
    config_name         VARCHAR(64)     NOT NULL COMMENT '用户自定义配置名称',
    api_key             VARCHAR(512)    NOT NULL COMMENT 'API Key（加密存储）',
    custom_api_base_url VARCHAR(512)    COMMENT '自定义 API 地址',
    model_name          VARCHAR(128)    NOT NULL COMMENT '具体模型名',
    priority            INT             NOT NULL DEFAULT 50 COMMENT '优先级 1-100',
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE COMMENT '是否启用',
    is_default          BOOLEAN         NOT NULL DEFAULT FALSE COMMENT '是否为默认配置',
    timeout_ms          INT             DEFAULT 60000 COMMENT '超时时间(毫秒)',
    max_retries         INT             DEFAULT 3 COMMENT '最大重试次数',
    stream_enabled      BOOLEAN         DEFAULT TRUE COMMENT '是否支持流式输出',
    capability          VARCHAR(32)     NOT NULL DEFAULT 'CHAT' COMMENT '🆕专用能力标识：CHAT/EMBEDDING/RERANK/OCR',
    extra_config        JSON            COMMENT '扩展配置',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_user_provider_model (user_id, provider_id, model_name),
    INDEX idx_user_active_default (user_id, is_active, is_default),
    INDEX idx_user_provider_cap (user_id, provider_type, capability) -- 🆕 新增：支撑按能力快速切换的查询索引
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '用户级 LLM 配置表';


-- 4. 数据集表
CREATE TABLE IF NOT EXISTS dataset (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '数据集唯一标识',
    user_id         BIGINT UNSIGNED NOT NULL COMMENT '所属用户 ID',
    name            VARCHAR(128)    NOT NULL COMMENT '数据集名称',
    description     VARCHAR(512)    DEFAULT NULL COMMENT '数据集描述',
    status          VARCHAR(16)     NOT NULL DEFAULT 'ACTIVE' COMMENT '数据集状态',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_dataset_user_name (user_id, name),
    INDEX idx_dataset_user_updated (user_id, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '数据集表';

-- 5. 对话表
CREATE TABLE IF NOT EXISTS chat_conversation (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '对话唯一标识',
    user_id         BIGINT UNSIGNED NOT NULL COMMENT '所属用户 ID',
    dataset_id      BIGINT UNSIGNED NOT NULL COMMENT '所属数据集 ID',
    last_config_id  BIGINT UNSIGNED COMMENT '最后使用的 LLM 配置 ID',
    last_model_name VARCHAR(128)    COMMENT '最后使用的模型名快照',
    title           VARCHAR(255)    COMMENT '对话标题',
    is_pinned       BOOLEAN         DEFAULT FALSE COMMENT '是否置顶',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_chat_conversation_user_pinned_updated (user_id, is_pinned, updated_at),
    INDEX idx_chat_conversation_dataset_updated (dataset_id, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '对话表';

-- 6. 对话消息表
CREATE TABLE IF NOT EXISTS chat_message (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '消息唯一标识',
    conversation_id     BIGINT UNSIGNED NOT NULL COMMENT '所属对话 ID',
    config_id           BIGINT UNSIGNED COMMENT '产生该消息所使用的 LLM 配置 ID',
    model_name          VARCHAR(128)    COMMENT '模型名快照',
    role                VARCHAR(16)     NOT NULL COMMENT '角色：user/assistant/system',
    content             MEDIUMTEXT      NOT NULL COMMENT '消息内容',
    token_count         INT             DEFAULT 0 COMMENT '该条消息消耗的 Token 数',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_conversation_created (conversation_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '对话消息表';

-- 7. LLM 调用用量日志表
CREATE TABLE IF NOT EXISTS llm_usage_log (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '记录唯一标识',
    user_id             BIGINT UNSIGNED NOT NULL COMMENT '用户 ID',
    config_id           BIGINT UNSIGNED NOT NULL COMMENT '用户配置 ID',
    provider_type       VARCHAR(32)     NOT NULL COMMENT '厂商类型',
    model_name          VARCHAR(128)    NOT NULL COMMENT '模型名称',
    prompt_tokens       INT             NOT NULL COMMENT '输入 Token 数',
    completion_tokens   INT             NOT NULL COMMENT '输出 Token 数',
    total_tokens        INT             NOT NULL COMMENT '总 Token 数',
    latency_ms          INT             COMMENT '响应延迟(毫秒)',
    status              VARCHAR(16)     NOT NULL COMMENT '调用状态：success/failed/partial',
    error_message       VARCHAR(512)    COMMENT '错误信息',
    fallback_config_id  BIGINT UNSIGNED COMMENT '触发 Fallback 时记录原配置 ID',
    conversation_id     BIGINT UNSIGNED COMMENT '关联对话 ID',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_user_date (user_id, created_at),
    INDEX idx_config_date (config_id, created_at),
    INDEX idx_conversation_id (conversation_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT 'LLM 调用用量日志表';

-- 8. 原始文档上传表
CREATE TABLE IF NOT EXISTS document_original_file (
    id                         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '原始文档唯一标识',
    dataset_id                 BIGINT UNSIGNED NOT NULL COMMENT '所属数据集ID，对应 dataset.id',
    user_id                    BIGINT UNSIGNED NOT NULL COMMENT '上传用户ID',
    original_filename          VARCHAR(255) NOT NULL COMMENT '用户上传时的原始文件名',
    file_suffix                VARCHAR(32) NOT NULL COMMENT '标准化小写文件后缀',
    file_size                  BIGINT UNSIGNED NOT NULL COMMENT '原始文件大小，单位字节',
    content_type               VARCHAR(128) DEFAULT NULL COMMENT '上传请求中的 Content-Type',
    bucket_name                VARCHAR(64) NOT NULL DEFAULT 'rag-raw' COMMENT '原文件私有存储桶',
    object_key                 VARCHAR(512) DEFAULT NULL COMMENT '私有OSS对象Key',
    file_url                   VARCHAR(1024) DEFAULT NULL COMMENT 'Python/RAG内部下载URL，不含服务间鉴权Token',
    upload_status              VARCHAR(20) NOT NULL DEFAULT 'uploading' COMMENT '上传状态: uploading/success/failed',
    is_upload_success          TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否上传成功',
    failure_reason             VARCHAR(512) DEFAULT NULL COMMENT '上传失败原因',
    created_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_dataset_user_name_suffix (dataset_id, user_id, original_filename, file_suffix),
    INDEX idx_document_original_dataset_created (dataset_id, created_at),
    INDEX idx_document_original_user_created (user_id, created_at),
    INDEX idx_document_original_upload_status (upload_status, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '知识库原始文档上传记录表';

-- 9. 文件解析表
CREATE TABLE IF NOT EXISTS document_parse_file (
    id                         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '文件解析表主键',
    document_original_file_id  BIGINT UNSIGNED NOT NULL COMMENT '原文件主键，对应 document_original_file.id',
    dataset_id                 BIGINT UNSIGNED NOT NULL COMMENT '所属数据集ID',
    user_id                    BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
    latest_parse_task_id       VARCHAR(36) DEFAULT NULL COMMENT 'Java最新触发解析任务业务ID，对应 document_parsed_log.task_id',
    original_filename          VARCHAR(255) NOT NULL COMMENT '原文件名快照',
    parse_count                INT NOT NULL DEFAULT 0 COMMENT '累计解析次数',
    created_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_parse_task_original_file (document_original_file_id),
    INDEX idx_parse_task_dataset_user (dataset_id, user_id, updated_at),
    INDEX idx_parse_task_latest_task (latest_parse_task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '文件解析表';

-- 10. 文件解析日志表
CREATE TABLE IF NOT EXISTS document_parsed_log (
    id                         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '解析任务记录主键',
    task_id                    VARCHAR(36) NOT NULL COMMENT '解析任务业务唯一标识(UUID)',
    document_original_file_id  BIGINT UNSIGNED NOT NULL COMMENT '原文件主键，对应 document_original_file.id',
    document_parse_file_id     BIGINT UNSIGNED DEFAULT NULL COMMENT '文件解析表主键，对应 document_parse_file.id',
    trigger_mode               VARCHAR(20) NOT NULL COMMENT '触发方式: upload_auto/manual_retry',
    task_status                VARCHAR(16) NOT NULL DEFAULT 'created' COMMENT '任务状态: created/success/failed',
    failure_reason             VARCHAR(512) DEFAULT NULL COMMENT '解析失败原因',
    parsed_filename            VARCHAR(255) DEFAULT NULL COMMENT '解析后文件名',
    parsed_bucket_name         VARCHAR(64) DEFAULT NULL COMMENT '解析结果文件桶名',
    parsed_object_key          VARCHAR(512) DEFAULT NULL COMMENT '解析结果文件对象Key',
    parsed_file_url            VARCHAR(1024) DEFAULT NULL COMMENT '解析结果文件内部定位地址',
    parsed_at                  DATETIME DEFAULT NULL COMMENT '解析时间',
    parse_started_at           DATETIME DEFAULT NULL COMMENT 'Python开始解析时间',
    parse_finished_at          DATETIME DEFAULT NULL COMMENT 'Python结束解析时间',
    parse_duration_ms          BIGINT DEFAULT NULL COMMENT '解析耗时，单位毫秒',
    created_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_parse_task_id (task_id),
    INDEX idx_parsed_log_original_status (document_original_file_id, task_status, updated_at),
    INDEX idx_parsed_log_parse_task_status (document_parse_file_id, task_status, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '文件解析任务日志表';

-- 11. 文件级解析后处理流程状态表
CREATE TABLE IF NOT EXISTS document_post_process_pipeline (
    id                         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '解析后处理流程主键',
    document_parsed_log_id      BIGINT UNSIGNED NOT NULL COMMENT '解析日志主键，对应 document_parsed_log.id',
    task_id                    VARCHAR(36) NOT NULL COMMENT '解析任务业务唯一标识，对应 document_parsed_log.task_id',
    document_original_file_id   BIGINT UNSIGNED NOT NULL COMMENT '原文件主键，对应 document_original_file.id',
    document_parse_file_id      BIGINT UNSIGNED DEFAULT NULL COMMENT '文件解析表主键，对应 document_parse_file.id',

    pipeline_status             VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '流程状态: PENDING/PROCESSING/SUCCESS/FAILED',
    chunking_status             VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '分片状态: PENDING/SUCCESS/FAILED',
    vectorizing_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '向量化状态: PENDING/SUCCESS/FAILED',
    es_indexing_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'ES入库状态: PENDING/SUCCESS/FAILED',

    failed_stage                VARCHAR(20) DEFAULT NULL COMMENT '失败阶段: CHUNKING/VECTORIZING/ES_INDEXING',
    recover_from_stage          VARCHAR(20) DEFAULT NULL COMMENT '下次恢复阶段: CHUNKING/VECTORIZING/ES_INDEXING',
    failure_reason              VARCHAR(512) DEFAULT NULL COMMENT '最近一次失败原因摘要',

    chunk_count                 INT NOT NULL DEFAULT 0 COMMENT '本次分片数量',
    retry_count                 INT NOT NULL DEFAULT 0 COMMENT '已重试次数',
    last_retry_at               DATETIME DEFAULT NULL COMMENT '最近一次重试时间',

    chunking_duration_ms        BIGINT DEFAULT NULL COMMENT '分片耗时，单位毫秒',
    vectorizing_duration_ms     BIGINT DEFAULT NULL COMMENT '向量化耗时，单位毫秒',
    es_indexing_duration_ms     BIGINT DEFAULT NULL COMMENT 'ES入库耗时，单位毫秒',
    total_duration_ms           BIGINT DEFAULT NULL COMMENT '后处理流程总耗时，单位毫秒',

    started_at                  DATETIME DEFAULT NULL COMMENT '后处理开始时间',
    finished_at                 DATETIME DEFAULT NULL COMMENT '后处理结束时间',
    created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_post_pipeline_parsed_log (document_parsed_log_id),
    KEY idx_post_pipeline_task_id (task_id),
    KEY idx_post_pipeline_parse_file (document_parse_file_id, updated_at),
    KEY idx_post_pipeline_status (pipeline_status, updated_at),
    KEY idx_post_pipeline_retry (pipeline_status, recover_from_stage, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci AUTO_INCREMENT=10000 COMMENT '文件级解析后处理流程状态表';

-- 12. 文档 Chunk 真值记录表
CREATE TABLE IF NOT EXISTS kb_document_chunk (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '物理主键ID',
    chunk_id        VARCHAR(128) NOT NULL COMMENT 'Chunk业务唯一键，对应Qdrant Point ID',
    doc_id          BIGINT UNSIGNED NOT NULL COMMENT '文档ID',
    set_id          BIGINT UNSIGNED NOT NULL COMMENT '知识集ID',
    user_id         BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
    bucket_id       INT DEFAULT NULL COMMENT '路由后的Qdrant物理桶编号',
    content         TEXT NOT NULL COMMENT 'splitter最终产出的可检索Chunk原文',
    content_hash    VARCHAR(64) NOT NULL COMMENT '基于最终Chunk内容计算的SHA-256哈希',
    chunk_type      VARCHAR(32) NOT NULL DEFAULT 'text' COMMENT '分片类型: paragraph/image/table/code_block/heading/mixed/text',
    start_line      INT DEFAULT NULL COMMENT 'Chunk在源文档中的起始行号',
    end_line        INT DEFAULT NULL COMMENT 'Chunk在源文档中的结束行号',
    chunk_index     INT DEFAULT NULL COMMENT '当前Chunk在文档内的顺序编号',
    status          VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT '生命周期状态: PENDING/INDEXING/INDEXED/FAILED/DELETING/DELETED/DELETE_FAILED',
    error_msg       VARCHAR(512) DEFAULT NULL COMMENT '最近一次写入或补偿失败原因',
    retry_count     INT NOT NULL DEFAULT 0 COMMENT '已执行的补偿重试次数',
    last_retry_at   DATETIME DEFAULT NULL COMMENT '最近一次补偿重试时间',
    embedding_model VARCHAR(128) DEFAULT NULL COMMENT '实际使用的embedding模型名称',
    vector_status   VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT '向量化状态: PENDING/SUCCESS/FAILED',
    vector_error_msg VARCHAR(512) DEFAULT NULL COMMENT '向量化失败原因',
    es_status       VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT 'ES索引状态: PENDING/SUCCESS/FAILED',
    es_error_msg    VARCHAR(512) DEFAULT NULL COMMENT 'ES索引失败原因',
    create_time     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    update_time     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',

    UNIQUE KEY uk_chunk_id (chunk_id),
    KEY idx_user_set (user_id, set_id),
    KEY idx_bucket_status (bucket_id, status),
    KEY idx_bucket_vector_status (bucket_id, vector_status),
    KEY idx_doc_id (doc_id),
    KEY idx_chunk_type (chunk_type),
    KEY idx_content_hash (content_hash),
    KEY idx_bucket_es_status (bucket_id, es_status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci AUTO_INCREMENT=10000 COMMENT '文档Chunk真值记录表';

-- 设置所有表的自增起始值为 10000 (MySQL 8.0 推荐显式指定方式)
ALTER TABLE sys_user AUTO_INCREMENT = 10000;
ALTER TABLE llm_system_provider AUTO_INCREMENT = 10000;
ALTER TABLE llm_user_config AUTO_INCREMENT = 10000;
ALTER TABLE dataset AUTO_INCREMENT = 10000;
ALTER TABLE chat_conversation AUTO_INCREMENT = 10000;
ALTER TABLE chat_message AUTO_INCREMENT = 10000;
ALTER TABLE llm_usage_log AUTO_INCREMENT = 10000;
ALTER TABLE document_original_file AUTO_INCREMENT = 10000;
ALTER TABLE document_parse_file AUTO_INCREMENT = 10000;
ALTER TABLE document_parsed_log AUTO_INCREMENT = 10000;
ALTER TABLE document_post_process_pipeline AUTO_INCREMENT = 10000;
ALTER TABLE knowledge_file_config AUTO_INCREMENT = 10000;
ALTER TABLE kb_document_chunk AUTO_INCREMENT = 10000;
