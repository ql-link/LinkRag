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


-- 4. 对话表
CREATE TABLE IF NOT EXISTS chat_conversation (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '对话唯一标识',
    user_id         BIGINT UNSIGNED NOT NULL COMMENT '所属用户 ID',
    last_config_id  BIGINT UNSIGNED COMMENT '最后使用的 LLM 配置 ID',
    last_model_name VARCHAR(128)    COMMENT '最后使用的模型名快照',
    title           VARCHAR(255)    COMMENT '对话标题',
    is_pinned       BOOLEAN         DEFAULT FALSE COMMENT '是否置顶',
    is_deleted      BOOLEAN         DEFAULT FALSE COMMENT '软删除标记',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_user_active_list (user_id, is_deleted, is_pinned, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '对话表';

-- 5. 对话消息表
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

-- 6. LLM 调用用量日志表
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

-- 7. 原始文档上传记录表
CREATE TABLE IF NOT EXISTS document_original_file (
    id                    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '原始文件主键ID',
    conversation_id       BIGINT UNSIGNED NOT NULL COMMENT '所属对话ID',
    user_id               BIGINT UNSIGNED NOT NULL COMMENT '上传用户ID',
    original_filename     VARCHAR(255)    NOT NULL COMMENT '用户上传时的原始文件名',
    file_suffix           VARCHAR(32)     NOT NULL COMMENT '标准化小写文件后缀: md/pdf/docx/txt/html',
    file_size             BIGINT UNSIGNED NOT NULL COMMENT '原始文件大小，单位字节',
    content_type          VARCHAR(128)    DEFAULT NULL COMMENT '上传请求中的Content-Type',
    file_sha256           CHAR(64)        DEFAULT NULL COMMENT '原文件SHA256',
    storage_provider      VARCHAR(32)     NOT NULL DEFAULT 'minio' COMMENT '存储提供方: minio/oss',
    bucket_name           VARCHAR(128)    NOT NULL COMMENT '原始文件所在bucket',
    object_key            VARCHAR(512)    NOT NULL COMMENT '原始文件对象Key',
    file_url              VARCHAR(1024)   DEFAULT NULL COMMENT '内部访问URL，可选',
    upload_status         VARCHAR(20)     NOT NULL DEFAULT 'uploading' COMMENT '上传状态: uploading/success/failed',
    upload_failure_reason VARCHAR(512)    DEFAULT NULL COMMENT '上传失败原因',
    is_deleted            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删除标记: 0-未删除, 1-已删除',
    created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',

    KEY idx_conversation_deleted_created (conversation_id, is_deleted, created_at),
    KEY idx_user_deleted_created (user_id, is_deleted, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '原始文档上传记录表';

-- 8. 文档解析任务执行记录表
CREATE TABLE IF NOT EXISTS document_parse_task (
    id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '解析任务主键ID',
    task_id           VARCHAR(36)     NOT NULL COMMENT '解析任务唯一标识(UUID)',
    original_file_id  BIGINT UNSIGNED NOT NULL COMMENT '关联原始文件ID，对应 document_original_file.id',
    file_type         VARCHAR(32)     NOT NULL COMMENT '文件真实格式: md/pdf/docx/txt/html',
    status            VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT '状态: pending/processing/success/failed',
    md_bucket         VARCHAR(128)    DEFAULT NULL COMMENT 'Markdown文件bucket',
    md_object_key     VARCHAR(512)    DEFAULT NULL COMMENT 'Markdown文件对象Key',
    md_storage_status VARCHAR(24)     NOT NULL DEFAULT 'pending' COMMENT 'Markdown存储状态: pending/success/failed',
    page_count        INT             DEFAULT NULL COMMENT '解析出的总页数/大致长度指标',
    error_message     VARCHAR(512)    DEFAULT NULL COMMENT '失败原因',
    time_cost_ms      INT             DEFAULT NULL COMMENT '解析耗时(毫秒)',
    created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '任务创建时间',
    updated_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '任务更新时间',

    UNIQUE KEY uk_task_id (task_id),
    KEY idx_original_file_status (original_file_id, status),
    KEY idx_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '文档解析任务执行记录表';

-- 设置所有表的自增起始值为 10000 (MySQL 8.0 推荐显式指定方式)
ALTER TABLE sys_user AUTO_INCREMENT = 10000;
ALTER TABLE llm_system_provider AUTO_INCREMENT = 10000;
ALTER TABLE llm_user_config AUTO_INCREMENT = 10000;
ALTER TABLE chat_conversation AUTO_INCREMENT = 10000;
ALTER TABLE chat_message AUTO_INCREMENT = 10000;
ALTER TABLE llm_usage_log AUTO_INCREMENT = 10000;
ALTER TABLE document_original_file AUTO_INCREMENT = 10000;
ALTER TABLE document_parse_task AUTO_INCREMENT = 10000;
