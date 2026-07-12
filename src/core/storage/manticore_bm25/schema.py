"""Manticore BM25 后端的命名常量与表结构 DDL。

与 ES / Qdrant 两个既有后端的关键差异：BM25 按 ``dataset_id`` 物理建表（一个
dataset 一张 Manticore RT 表），不走 Qdrant 那套按 user 哈希分桶（``BucketRouter``）
或 ES 单一全局 index 的模式——IDF 与 avgdl 天然只统计这个 dataset 自己的语料，
不需要额外的 tenant filter 把统计口径圈起来。
"""

from __future__ import annotations

# payload 属性字段名（与 ES / Qdrant 后端对齐，便于跨后端代码复用同一套语义）。
ATTR_CHUNK_ID = "chunk_id"
ATTR_DOC_ID = "doc_id"
ATTR_USER_ID = "user_id"
ATTR_CHUNK_TYPE = "chunk_type"

# 生产基线只索引 coarse 字段。实测表明，将 coarse/fine 直接合并进
# Manticore BM25F 与 ES best_fields / Qdrant 独立字段统计并不等价，会显著损害
# 中文排序。fine 后续应作为独立召回路融合，不再共享一个 BM25F 分数。
FIELD_COARSE = "coarse"

# 显式固定 IDF 语义。Manticore 历史默认 normalized/tfidf_normalized 会惩罚
# 高频词，且分数会随查询词数漂移。该组合是本项目对齐现有 ES/Qdrant
# 评测基线的必要选项。
IDF_FLAGS = "plain,tfidf_unnormalized"

# 建表 DDL 用到的公共选项：
# - morphology='none'：文本已经过 RagFlowTokenizer 预分词、空格拼接，不需要 Manticore
#   自己的词干化/形态还原，避免二次处理打乱预分词结果。
# - index_field_lengths='1'：bm25a() 需要按字段长度做长度归一，必须显式开启。
# - charset_table='non_cjk, chinese'：默认字符集表不认中文字符，会把中文词当分隔符
#   丢弃（实测：不加这个配置，中文内容基本等于没索引）。
TABLE_DDL_OPTIONS = "morphology='none' index_field_lengths='1' charset_table='non_cjk, chinese'"
