DEFAULT_BUCKET_COUNT = 128
DEFAULT_COLLECTION_PREFIX = "kb_bucket"
DEFAULT_QDRANT_TIMEOUT_SECONDS = 20
QDRANT_PAYLOAD_INDEX_FIELDS = ("user_id", "set_id", "doc_id")

# 写入路径对瞬时故障（502/503/504、网关抖动、连接超时）的重试：共享 Qdrant 在高
# 并发写入时偶发网关 5xx，但写操作都幂等（显式 id 的 upsert / update_vectors），
# 重试安全。指数退避：第 i 次失败后睡 BACKOFF * 2**i 秒。
DEFAULT_QDRANT_WRITE_MAX_ATTEMPTS = 3
DEFAULT_QDRANT_WRITE_BACKOFF_SECONDS = 0.5
