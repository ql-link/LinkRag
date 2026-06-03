from src.config import settings
from src.services.storage.base import BaseObjectStorage
from src.services.storage.minio_storage import MinioStorage
from src.services.storage.oss_storage import OssStorage


class StorageFactory:
    """对象存储工厂。"""

    @staticmethod
    def get_storage() -> BaseObjectStorage:
        provider = settings.STORAGE_TYPE.lower()
        if provider == "minio":
            return MinioStorage()
        if provider == "oss":
            return OssStorage()
        raise ValueError(f"不支持的存储提供方: {provider}")
