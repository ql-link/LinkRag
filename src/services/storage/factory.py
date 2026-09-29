from src.config import settings
from src.services.storage.base import BaseObjectStorage
from src.services.storage.minio_storage import MinioStorage


class StorageFactory:
    """对象存储工厂。"""

    @staticmethod
    def validate_provider() -> None:
        provider = settings.STORAGE_TYPE.lower()
        if provider == "oss":
            raise NotImplementedError("OSS 存储适配器尚未实现，不能用于运行环境")
        if provider != "minio":
            raise ValueError(f"不支持的存储提供方: {provider}")

    @staticmethod
    def get_storage() -> BaseObjectStorage:
        StorageFactory.validate_provider()
        return MinioStorage()
