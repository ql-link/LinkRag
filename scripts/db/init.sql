-- ===============================================
-- toLink-Rag 数据库完整表结构快照
-- ===============================================
-- 本文件是「migrations/db.sql (0001 baseline) + 全部 Alembic migration」叠加后的
-- 当前表结构快照，仅用于人/工具查阅与代码评审参考。
-- ⚠️ 不是部署入口：
--   - 冷启动以 migrations/db.sql 为准（已 stamp 为 0001 baseline）；
--   - schema 演进的唯一权威源是 src/models/**.py + migrations/versions/*.py；
--   - 修改字段必须先改 ORM 模型并新增 migration，再同步本文件。
-- 同步时机：每条会改动表结构的 migration 落库时一并更新本文件。
-- 末次同步：migration 0016_20260609_add_user_feedback_table
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
    is_active       BOOLEAN        NOT NULL DEFAULT TRUE COMMENT '是否启用',
    priority        INT            NOT NULL DEFAULT 50 COMMENT '厂商优先级（1-100）',
    created_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_provider_type (provider_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT 'LLM 系统级厂商配置表';

-- 2.1 厂商模型能力目录表
CREATE TABLE IF NOT EXISTS llm_provider_model (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    provider_id     BIGINT UNSIGNED NOT NULL COMMENT '关联 llm_system_provider.id',
    model_name      VARCHAR(128)    NOT NULL COMMENT '模型名',
    capability      VARCHAR(32)     NOT NULL COMMENT '单能力；一模型多能力=多行',
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE COMMENT '该模型能力是否上架',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_provider_model_cap (provider_id, model_name, capability),
    INDEX idx_provider_cap (provider_id, capability)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '厂商模型能力目录表';

-- 2.2 系统预设表
CREATE TABLE IF NOT EXISTS llm_system_preset (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    provider_id     BIGINT UNSIGNED NOT NULL COMMENT '关联 llm_system_provider.id',
    model_name      VARCHAR(128)    NOT NULL COMMENT '模型名',
    capability      VARCHAR(32)     NOT NULL COMMENT '能力标识',
    api_key         VARCHAR(512)    NOT NULL COMMENT '平台 Key（加密）',
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE COMMENT '是否对新用户下发',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_preset_provider_model_cap (provider_id, model_name, capability)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '系统预设表';

-- 3. 用户级 LLM 配置表（下游唯一生效源）
CREATE TABLE IF NOT EXISTS llm_user_config (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '配置唯一标识',
    user_id             BIGINT UNSIGNED NOT NULL COMMENT '用户 ID',
    provider_id         BIGINT UNSIGNED NOT NULL COMMENT '关联 SystemProvider ID',
    provider_type       VARCHAR(32)     NOT NULL COMMENT '厂商类型快照，下游路由 SDK',
    api_key             VARCHAR(512)    NOT NULL COMMENT '厂商级 API Key（加密存储）',
    api_base_url        VARCHAR(512)    COMMENT '实际生效地址：用户自定义或厂商默认',
    model_name          VARCHAR(128)    NOT NULL COMMENT '具体模型名',
    capability          VARCHAR(32)     NOT NULL DEFAULT 'CHAT' COMMENT '专用能力标识：CHAT/EMBEDDING/RERANK/OCR 等',
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE COMMENT '模型启停 + 生效过滤',
    is_default          BOOLEAN         NOT NULL DEFAULT FALSE COMMENT '该能力是否生效（单用户单能力唯一）',
    is_system_preset    BOOLEAN         NOT NULL DEFAULT FALSE COMMENT '系统预设行（只读）',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_user_provider_model_capability (user_id, provider_id, model_name, capability, is_system_preset),
    INDEX idx_user_active_default (user_id, is_active, is_default),
    INDEX idx_user_provider_cap (user_id, provider_type, capability)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '用户级 LLM 配置表';

-- 4. 数据集表
CREATE TABLE IF NOT EXISTS dataset (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '数据集唯一标识',
    user_id         BIGINT UNSIGNED NOT NULL COMMENT '所属用户 ID',
    name            VARCHAR(128)    NOT NULL COMMENT '数据集名称',
    description     VARCHAR(512)    DEFAULT NULL COMMENT '数据集描述',
    status          VARCHAR(16)     NOT NULL DEFAULT 'ACTIVE' COMMENT '数据集状态',
    is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE COMMENT '逻辑删除标记（软删保留数据集）',
    deleted_seq     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '删除判别列：活行=0、软删=自身id；纳入唯一键支持删后同名重建',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_dataset_user_name_seq (user_id, name, deleted_seq),
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

    UNIQUE KEY uk_conversation_user_dataset_title (user_id, dataset_id, title),
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
    is_deleted                 BOOLEAN NOT NULL DEFAULT FALSE COMMENT '逻辑删除标记（软删保留原文件，不删 OSS）',
    deleted_seq                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '删除判别列：活行=0、软删=自身id；纳入唯一键支持删后同名重传',
    created_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_dof_name_suffix_seq (dataset_id, user_id, original_filename, file_suffix, deleted_seq),
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

-- 10. 文件解析产物快照表
-- 经 migration 0007 把 task_status / failure_reason 下沉到 document_parse_pipeline
-- 经 migration 0009 新增 retry_of_task_id 用于重试链路审计反查。
CREATE TABLE IF NOT EXISTS document_parsed_log (
    id                         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '解析任务记录主键',
    task_id                    VARCHAR(36) NOT NULL COMMENT '解析任务业务唯一标识(UUID)',
    document_original_file_id  BIGINT UNSIGNED NOT NULL COMMENT '原文件主键，对应 document_original_file.id',
    document_parse_file_id     BIGINT UNSIGNED DEFAULT NULL COMMENT '文件解析表主键，对应 document_parse_file.id',
    trigger_mode               VARCHAR(20) NOT NULL COMMENT '触发方式: upload_auto/manual_retry',
    parsed_filename            VARCHAR(255) DEFAULT NULL COMMENT '解析后文件名',
    parsed_bucket_name         VARCHAR(64) DEFAULT NULL COMMENT '解析结果文件桶名',
    parsed_object_key          VARCHAR(512) DEFAULT NULL COMMENT '解析结果文件对象Key',
    parsed_file_url            VARCHAR(1024) DEFAULT NULL COMMENT '解析结果文件内部定位地址',
    parsed_at                  DATETIME DEFAULT NULL COMMENT '解析时间',
    parse_started_at           DATETIME DEFAULT NULL COMMENT 'Python开始解析时间',
    parse_finished_at          DATETIME DEFAULT NULL COMMENT 'Python结束解析时间',
    parse_duration_ms          BIGINT DEFAULT NULL COMMENT '解析耗时，单位毫秒',
    retry_of_task_id           VARCHAR(36) DEFAULT NULL COMMENT '重试链路上一个 task_id；首次解析为 NULL',
    created_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_parse_task_id (task_id),
    INDEX idx_parsed_log_original_file (document_original_file_id, updated_at),
    INDEX idx_parsed_log_parse_file (document_parse_file_id, updated_at),
    INDEX idx_parsed_log_retry_of (retry_of_task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=10000 COMMENT '文件解析产物快照表';

-- 11. 文件解析流程状态表
-- 经 migration 0002/0003 新增 pretokenize_status / pretokenize_duration_ms；
-- 0007 重命名表（post_process → parse pipeline），新增 cleaning_status /
-- cleaning_duration_ms（先前的"解析+上传"语义下沉为"文档清洗"阶段），
-- 删除 chunk_count / retry_count / last_retry_at / idx_post_pipeline_retry；
-- 0009 新增 sparse_vectorizing_* 与 superseded_by_task_id。
CREATE TABLE IF NOT EXISTS document_parse_pipeline (
    id                          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '解析流程主键',
    document_parsed_log_id      BIGINT UNSIGNED NOT NULL COMMENT '解析日志主键，对应 document_parsed_log.id',
    task_id                     VARCHAR(36) NOT NULL COMMENT '解析任务业务唯一标识，对应 document_parsed_log.task_id',
    document_original_file_id   BIGINT UNSIGNED NOT NULL COMMENT '原文件主键，对应 document_original_file.id',
    document_parse_file_id      BIGINT UNSIGNED DEFAULT NULL COMMENT '文件解析表主键，对应 document_parse_file.id',
    pipeline_status             VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '流程状态: PENDING/PROCESSING/SUCCESS/FAILED',
    cleaning_status             VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '文档清洗（解析+上传）阶段状态: PENDING/SUCCESS/FAILED',
    chunking_status             VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '分片状态: PENDING/SUCCESS/FAILED',
    vectorizing_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '向量化状态: PENDING/SUCCESS/FAILED',
    pretokenize_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '预分词状态: PENDING/SUCCESS/FAILED',
    es_indexing_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'ES入库状态: PENDING/SUCCESS/FAILED',
    sparse_vectorizing_status   VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '稀疏向量阶段状态: PENDING/PROCESSING/SUCCESS/FAILED',
    failed_stage                VARCHAR(20) DEFAULT NULL COMMENT '失败阶段: CLEANING/CHUNKING/VECTORIZING/PRETOKENIZE/ES_INDEXING/SPARSE_VECTORIZING',
    recover_from_stage          VARCHAR(20) DEFAULT NULL COMMENT '下次恢复阶段: CLEANING/CHUNKING/VECTORIZING/PRETOKENIZE/ES_INDEXING/SPARSE_VECTORIZING',
    failure_reason              VARCHAR(512) DEFAULT NULL COMMENT '最近一次失败原因摘要',
    cleaning_duration_ms        BIGINT DEFAULT NULL COMMENT '文档清洗阶段耗时，单位毫秒',
    chunking_duration_ms        BIGINT DEFAULT NULL COMMENT '分片耗时，单位毫秒',
    vectorizing_duration_ms     BIGINT DEFAULT NULL COMMENT '向量化耗时，单位毫秒',
    pretokenize_duration_ms     BIGINT DEFAULT NULL COMMENT '预分词耗时，单位毫秒',
    es_indexing_duration_ms     BIGINT DEFAULT NULL COMMENT 'ES入库耗时，单位毫秒',
    sparse_vectorizing_duration_ms BIGINT DEFAULT NULL COMMENT '稀疏向量阶段耗时，单位毫秒',
    total_duration_ms           BIGINT DEFAULT NULL COMMENT '流程总耗时，单位毫秒',
    superseded_by_task_id       VARCHAR(36) DEFAULT NULL COMMENT '被哪个新 task_id 接班（重试 CAS 第 2 层目标列）',
    started_at                  DATETIME DEFAULT NULL COMMENT '流程开始时间',
    finished_at                 DATETIME DEFAULT NULL COMMENT '流程结束时间',
    created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_parse_pipeline_parsed_log (document_parsed_log_id),
    KEY idx_parse_pipeline_task_id (task_id),
    KEY idx_parse_pipeline_parse_file (document_parse_file_id, updated_at),
    KEY idx_parse_pipeline_status (pipeline_status, updated_at),
    KEY idx_parse_pipeline_superseded (superseded_by_task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci AUTO_INCREMENT=10000 COMMENT '文件解析流程状态表';

-- 12. 博客文章表
CREATE TABLE IF NOT EXISTS blog_post (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '博客文章唯一标识',
    title               VARCHAR(255)    NOT NULL COMMENT '文章标题',
    slug                VARCHAR(255)    NOT NULL COMMENT '公开访问标识',
    summary             VARCHAR(1000)   DEFAULT NULL COMMENT '文章摘要',
    content_object_key  VARCHAR(512)    DEFAULT NULL COMMENT 'Markdown 正文私有对象 Key',
    cover_asset_id      BIGINT UNSIGNED DEFAULT NULL COMMENT '封面资源 ID，对应 blog_asset.id',
    status              VARCHAR(20)     NOT NULL DEFAULT 'DRAFT' COMMENT '状态：DRAFT/PUBLISHED',
    published_at        DATETIME        DEFAULT NULL COMMENT '首次发布时间',
    created_by          BIGINT UNSIGNED NOT NULL COMMENT '创建管理员用户 ID，仅用于审计',
    is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE COMMENT '逻辑删除标记',
    deleted_seq         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '删除判别列：活行=0，软删后置为自身 ID',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_blog_post_slug_seq (slug, deleted_seq),
    KEY idx_blog_post_public_list (status, published_at, id),
    KEY idx_blog_post_admin_list (is_deleted, updated_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci AUTO_INCREMENT=10000 COMMENT '博客文章表';

-- 13. 博客文章资源表
CREATE TABLE IF NOT EXISTS blog_asset (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '博客资源唯一标识',
    post_id             BIGINT UNSIGNED NOT NULL COMMENT '所属博客文章 ID',
    asset_type          VARCHAR(20)     NOT NULL COMMENT '资源类型：COVER/CONTENT_IMAGE',
    original_filename   VARCHAR(255)    NOT NULL COMMENT '上传时的原始文件名',
    content_type        VARCHAR(128)    NOT NULL COMMENT '文件 MIME 类型',
    file_size           BIGINT UNSIGNED NOT NULL COMMENT '文件大小，单位字节',
    object_key          VARCHAR(512)    NOT NULL COMMENT 'MinIO 对象 Key',
    public_url          VARCHAR(1024)   NOT NULL COMMENT '资源公开访问 URL',
    created_by          BIGINT UNSIGNED NOT NULL COMMENT '上传管理员用户 ID',
    is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE COMMENT '逻辑删除标记',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_blog_asset_object_key (object_key),
    KEY idx_blog_asset_post_type (post_id, asset_type, is_deleted, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci AUTO_INCREMENT=10000 COMMENT '博客文章资源表';

-- 14. 匿名用户反馈表
CREATE TABLE IF NOT EXISTS user_feedback (
    id                    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '反馈 ID',
    type                  VARCHAR(32)     NOT NULL DEFAULT 'OTHER' COMMENT '反馈类型：BUG=问题反馈，FEATURE=功能建议，EXPERIENCE=体验反馈，OTHER=其他',
    title                 VARCHAR(128)    NOT NULL COMMENT '反馈标题',
    content               TEXT            NOT NULL COMMENT '反馈详细内容',
    attachment_object_key VARCHAR(512)    DEFAULT NULL COMMENT '附件 MinIO object_key，例如 feedback/2026/06/09/a.png',
    status                VARCHAR(32)     NOT NULL DEFAULT 'PENDING' COMMENT '处理状态：PENDING=待处理，PROCESSING=处理中，RESOLVED=已解决，CLOSED=已关闭',
    priority              TINYINT         NOT NULL DEFAULT 3 COMMENT '处理优先级：1=高，2=中，3=低',
    admin_id              BIGINT UNSIGNED DEFAULT NULL COMMENT '处理该反馈的管理员用户 ID',
    admin_reply           TEXT            DEFAULT NULL COMMENT '管理员处理回复或处理结论',
    processed_at          DATETIME        DEFAULT NULL COMMENT '管理员处理完成或最后一次处理该反馈的时间',
    created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '反馈提交时间',
    updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '反馈更新时间',

    KEY idx_feedback_created (created_at),
    KEY idx_feedback_status_priority (status, priority, created_at),
    KEY idx_feedback_type_created (type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci AUTO_INCREMENT=10000 COMMENT '匿名用户反馈表';

-- 15. 文档 Chunk 真值记录表
-- 经 migration 0004 引入稀疏向量字段；0005 把 status/error_msg/retry_count/last_retry_at/embedding_model
--   重命名为 dense_vector_*，并删除冗余的 vector_status / vector_error_msg 与对应索引；
-- 0006 删除 dense/sparse 的 retry_count/last_retry_at/error_msg 与 es_error_msg
--   (重试治理与失败原因归 document_post_process_pipeline)；
-- 0008 收敛 dense/sparse 状态为 PENDING/SUCCESS/FAILED，删除 sparse_vector_nonzero_count，
--   并按实际查询路径重构索引；
-- 0010 新增 lifecycle_status 与生命周期查询索引。
--   (重试治理与失败原因归 document_parse_pipeline)。
CREATE TABLE IF NOT EXISTS kb_document_chunk (
    id                          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '物理主键ID',
    chunk_id                    VARCHAR(128) NOT NULL COMMENT 'Chunk业务唯一键，对应Qdrant Point ID',
    doc_id                      BIGINT UNSIGNED NOT NULL COMMENT '文档ID',
    set_id                      BIGINT UNSIGNED NOT NULL COMMENT '知识集ID',
    user_id                     BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
    bucket_id                   INT DEFAULT NULL COMMENT '路由后的Qdrant物理桶编号',
    content                     TEXT NOT NULL COMMENT 'splitter最终产出的可检索Chunk原文',
    content_hash                VARCHAR(64) NOT NULL COMMENT '基于最终Chunk内容计算的SHA-256哈希',
    chunk_type                  VARCHAR(32) NOT NULL DEFAULT 'text' COMMENT '分片类型: paragraph/image/table/code_block/heading/mixed/text',
    start_line                  INT DEFAULT NULL COMMENT 'Chunk在源文档中的起始行号',
    end_line                    INT DEFAULT NULL COMMENT 'Chunk在源文档中的结束行号',
    chunk_index                 INT DEFAULT NULL COMMENT '当前Chunk在文档内的顺序编号',
    dense_vector_status         VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT '稠密向量状态: PENDING/SUCCESS/FAILED',
    dense_vector_model          VARCHAR(128) DEFAULT NULL COMMENT '实际使用的稠密向量模型名称',
    sparse_vector_status        VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT '稀疏向量状态: PENDING/SUCCESS/FAILED',
    sparse_vector_model         VARCHAR(128) DEFAULT NULL COMMENT '实际使用的稀疏向量模型名称',
    es_status                   VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT 'ES索引状态: PENDING/SUCCESS/FAILED',
    lifecycle_status            VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' COMMENT 'Chunk业务生命周期状态: ACTIVE=业务有效，可参与解析/索引/检索; REMOVED=已从业务视图移除，不再参与解析/索引/检索，外部索引清理由异步任务处理',
    create_time                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    update_time                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',

    UNIQUE KEY uk_chunk_id (chunk_id),
    KEY idx_user_set (user_id, set_id),
    KEY idx_doc_dense_status (doc_id, dense_vector_status),
    KEY idx_doc_sparse_status (doc_id, sparse_vector_status),
    KEY idx_doc_es_status (doc_id, es_status),
    KEY idx_doc_lifecycle_status (doc_id, lifecycle_status),
    KEY idx_lifecycle_update_time (lifecycle_status, update_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci AUTO_INCREMENT=10000 COMMENT '文档Chunk真值记录表';

-- 自增起始值统一为 10000
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
ALTER TABLE document_parse_pipeline AUTO_INCREMENT = 10000;
ALTER TABLE blog_post AUTO_INCREMENT = 10000;
ALTER TABLE blog_asset AUTO_INCREMENT = 10000;
ALTER TABLE user_feedback AUTO_INCREMENT = 10000;
ALTER TABLE kb_document_chunk AUTO_INCREMENT = 10000;
