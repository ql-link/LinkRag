-- ===============================================
-- LLM 模型短展示名回填脚本
-- ===============================================
-- 用途：为 llm_provider_model / llm_system_preset 填充 display_name。
-- 说明：真实调用模型 ID 仍使用 model_name，display_name 只用于前端展示。
-- ===============================================

SET NAMES utf8mb4;

-- 全厂商模型展示名回填；真实调用仍使用 model_name。
DROP TEMPORARY TABLE IF EXISTS tmp_llm_model_display_names;

CREATE TEMPORARY TABLE tmp_llm_model_display_names AS
SELECT
    id,
    CASE
        WHEN model_name = 'qwen3-asr-flash' THEN 'Qwen ASR Flash'
        WHEN model_name = 'deepseek-ai/DeepSeek-V4-Flash' THEN 'DeepSeek V4 Flash'
        WHEN model_name = 'Qwen/Qwen3.6-27B' THEN 'Qwen 3.6 27B'
        WHEN model_name = 'bge-m3' THEN 'BGE-M3'
        WHEN model_name = 'doubao-seed-2-0-pro-260215' THEN 'Doubao Seed 2.0 Pro'
        WHEN model_name = 'BAAI/bge-m3' THEN 'BGE-M3'
        WHEN model_name = 'BAAI/bge-reranker-v2-m3' THEN 'BGE Reranker M3'
        WHEN model_name = 'doubao-embedding-vision-251215' AND capability = 'SPARSE_EMBEDDING' THEN 'Doubao Sparse'
        WHEN model_name = 'doubao-embedding-vision-251215' THEN 'Doubao Vision Embedding'
        WHEN clean_name REGEXP '^chatgpt ' THEN CONCAT('ChatGPT ', REGEXP_REPLACE(clean_name, '^chatgpt ', ''))
        WHEN clean_name REGEXP '^gpt ' THEN CONCAT('GPT ', REGEXP_REPLACE(clean_name, '^gpt ', ''))
        WHEN clean_name REGEXP '^qwen' THEN CONCAT('Qwen ', REGEXP_REPLACE(clean_name, '^qwen ?', ''))
        WHEN clean_name REGEXP '^claude' THEN CONCAT('Claude ', REGEXP_REPLACE(clean_name, '^claude ?', ''))
        WHEN clean_name REGEXP '^gemini' THEN CONCAT('Gemini ', REGEXP_REPLACE(clean_name, '^gemini ?', ''))
        WHEN clean_name REGEXP '^deepseek' THEN CONCAT('DeepSeek ', REGEXP_REPLACE(clean_name, '^deepseek ?', ''))
        WHEN clean_name REGEXP '^glm' THEN CONCAT('GLM ', REGEXP_REPLACE(clean_name, '^glm ?', ''))
        WHEN clean_name REGEXP '^kimi' THEN CONCAT('Kimi ', REGEXP_REPLACE(clean_name, '^kimi ?', ''))
        WHEN clean_name REGEXP '^moonshot kimi' THEN CONCAT('Kimi ', REGEXP_REPLACE(clean_name, '^moonshot kimi ?', ''))
        WHEN clean_name REGEXP '^grok' THEN CONCAT('Grok ', REGEXP_REPLACE(clean_name, '^grok ?', ''))
        WHEN clean_name REGEXP '^jina' THEN CONCAT('Jina ', REGEXP_REPLACE(clean_name, '^jina ?', ''))
        WHEN clean_name REGEXP '^doubao' THEN CONCAT('Doubao ', REGEXP_REPLACE(clean_name, '^doubao ?', ''))
        WHEN clean_name REGEXP '^mimo' THEN CONCAT('MiMo ', REGEXP_REPLACE(clean_name, '^mimo ?', ''))
        WHEN clean_name REGEXP '^hunyuan' THEN CONCAT('Hunyuan ', REGEXP_REPLACE(clean_name, '^hunyuan ?', ''))
        WHEN clean_name REGEXP '^baichuan' THEN CONCAT('Baichuan ', REGEXP_REPLACE(clean_name, '^baichuan ?', ''))
        WHEN clean_name REGEXP '^ernie' THEN CONCAT('ERNIE ', REGEXP_REPLACE(clean_name, '^ernie ?', ''))
        WHEN clean_name REGEXP '^whisper' THEN CONCAT('Whisper ', REGEXP_REPLACE(clean_name, '^whisper ?', ''))
        WHEN clean_name REGEXP '^llama' THEN CONCAT('Llama ', REGEXP_REPLACE(clean_name, '^llama ?', ''))
        WHEN clean_name REGEXP '^mistral' THEN CONCAT('Mistral ', REGEXP_REPLACE(clean_name, '^mistral ?', ''))
        WHEN clean_name REGEXP '^mixtral' THEN CONCAT('Mixtral ', REGEXP_REPLACE(clean_name, '^mixtral ?', ''))
        WHEN clean_name REGEXP '^text embedding' THEN CONCAT('Text Embedding ', REGEXP_REPLACE(clean_name, '^text embedding ?', ''))
        WHEN clean_name REGEXP '^embedding ' THEN CONCAT('Embedding ', REGEXP_REPLACE(clean_name, '^embedding ', ''))
        WHEN clean_name REGEXP '^gte rerank' THEN CONCAT('GTE Rerank ', REGEXP_REPLACE(clean_name, '^gte rerank ?', ''))
        WHEN clean_name REGEXP '^bge ' THEN CONCAT('BGE ', REGEXP_REPLACE(clean_name, '^bge ', ''))
        WHEN clean_name REGEXP '^o[0-9]' THEN TRIM(CONCAT(UPPER(SUBSTRING(clean_name, 1, 2)), ' ', REGEXP_REPLACE(clean_name, '^o[0-9] ?', '')))
        ELSE clean_name
    END AS display_name
FROM (
    SELECT
        id,
        provider_type,
        model_name,
        capability,
        TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(
                REGEXP_REPLACE(raw_name, ' [0-9]{4} [0-9]{2} [0-9]{2}$', ''),
                ' [0-9]{8}$', ''
            ),
            ' [0-9]{2} [0-9]{2}$', ''
        )) AS clean_name
    FROM (
        SELECT
            pm.id,
            sp.provider_type,
            pm.model_name,
            pm.capability,
            TRIM(REGEXP_REPLACE(
                REPLACE(REPLACE(REPLACE(LOWER(SUBSTRING_INDEX(pm.model_name, '/', -1)), '_', ' '), '-', ' '), ':', ' '),
                ' +', ' '
            )) AS raw_name
        FROM llm_provider_model pm
        JOIN llm_system_provider sp ON sp.id = pm.provider_id
    ) raw_models
) normalized_models;

UPDATE tmp_llm_model_display_names
SET display_name = TRIM(REGEXP_REPLACE(display_name, ' +', ' '));

UPDATE tmp_llm_model_display_names
SET display_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   display_name,
                   ' flash', ' Flash'),
                   ' pro', ' Pro'),
                   ' mini', ' Mini'),
                   ' nano', ' Nano'),
                   ' turbo', ' Turbo'),
                   ' latest', ' Latest'),
                   ' preview', ' Preview'),
                   ' embedding', ' Embedding'),
                   ' embeddings', ' Embeddings'),
                   ' reranker', ' Reranker'),
                   ' sonnet', ' Sonnet'),
                   ' opus', ' Opus'),
                   ' haiku', ' Haiku'),
                   ' thinking', ' Thinking'),
                   ' instruct', ' Instruct'),
                   ' vision', ' Vision'),
                   ' chat', ' Chat'),
                   ' large', ' Large'),
                   ' small', ' Small'),
                   ' max', ' Max');

UPDATE tmp_llm_model_display_names
SET display_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   display_name,
                   ' asr', ' ASR'),
                   ' vl', ' VL'),
                   ' r1', ' R1'),
                   ' r2', ' R2'),
                   ' k2', ' K2'),
                   ' v1', ' V1'),
                   ' v2', ' V2'),
                   ' v3', ' V3'),
                   ' v4', ' V4'),
                   ' v5', ' V5');

UPDATE tmp_llm_model_display_names
SET display_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   display_name,
                   ' plus', ' Plus'),
                   ' long', ' Long'),
                   ' coder', ' Coder'),
                   ' reasoner', ' Reasoner'),
                   ' distill', ' Distill'),
                   ' base', ' Base'),
                   ' multilingual', ' Multilingual'),
                   ' maverick', ' Maverick'),
                   ' air', ' Air'),
                   ' seed', ' Seed');

UPDATE tmp_llm_model_display_names
SET display_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                   display_name,
                   ' rerank', ' Rerank'),
                   ' clip', ' CLIP'),
                   ' beta', ' Beta'),
                   ' instruct', ' Instruct'),
                   ' a3b', ' A3B');

UPDATE tmp_llm_model_display_names
SET display_name = LEFT(display_name, 64);

UPDATE llm_provider_model pm
JOIN tmp_llm_model_display_names d ON d.id = pm.id
SET pm.display_name = d.display_name,
    pm.updated_at = CURRENT_TIMESTAMP
WHERE d.display_name IS NOT NULL
  AND d.display_name <> '';

UPDATE llm_system_preset p
JOIN llm_provider_model pm
  ON pm.provider_id = p.provider_id
 AND pm.model_name = p.model_name
 AND pm.capability = p.capability
SET p.display_name = pm.display_name,
    p.updated_at = CURRENT_TIMESTAMP
WHERE pm.display_name IS NOT NULL
  AND pm.display_name <> '';

DROP TEMPORARY TABLE IF EXISTS tmp_llm_model_display_names;
