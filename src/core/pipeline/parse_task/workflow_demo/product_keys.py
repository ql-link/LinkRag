"""Product keys used by the parse-task workflow demo."""

SOURCE = "parse.source"
MARKDOWN = "parse.markdown"
CHUNKS = "parse.chunks"
# Qdrant point 已按 payload 建好（dense/sparse 解耦的前置）：dense 与 sparse 各自
# update_vectors 独立写入，依赖此产物保证 point 已存在、且不并发建点相互覆盖。
POINTS_READY = "parse.points_ready"
DENSE_VECTORS = "parse.dense_vectors"
TOKENS = "parse.tokens"
ES_INDEX = "parse.es_index"
SPARSE_VECTORS = "parse.sparse_vectors"
