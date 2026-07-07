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

# 全文字段名：coarse / fine 两个字段各自建 BM25F 索引，字段权重在查询时通过
# bm25f(k1, b, {coarse=coarse_boost, fine=1}) 给，对齐 ES multi_match 的双字段召回。
FIELD_COARSE = "coarse"
FIELD_FINE = "fine"

# 建表 DDL 用到的公共选项：
# - morphology='none'：文本已经过 RagFlowTokenizer 预分词、空格拼接，不需要 Manticore
#   自己的词干化/形态还原，避免二次处理打乱预分词结果。
# - index_field_lengths='1'：bm25f() 需要按字段长度做长度归一，必须显式开启。
# - charset_table='non_cjk, chinese'：默认字符集表不认中文字符，会把中文词当分隔符
#   丢弃（实测：不加这个配置，中文内容基本等于没索引）。
TABLE_DDL_OPTIONS = "morphology='none' index_field_lengths='1' charset_table='non_cjk, chinese'"
