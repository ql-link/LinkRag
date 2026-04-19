class FileDownloader:
    """对象存储下载兼容包装器"""

    @staticmethod
    def download(bucket: str, object_key: str) -> bytes:
        from src.services.storage.factory import StorageFactory

        storage = StorageFactory.get_storage()
        return storage.download_bytes(bucket, object_key)
