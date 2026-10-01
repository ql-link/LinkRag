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
    def get_storage(
        *, request_timeout_seconds: float | None = None, max_attempts: int | None = None
    ) -> BaseObjectStorage:
        StorageFactory.validate_provider()
        if request_timeout_seconds is None and max_attempts is None:
            return MinioStorage()
        return MinioStorage(
            request_timeout_seconds=request_timeout_seconds, max_attempts=max_attempts
        )
