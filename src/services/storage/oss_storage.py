from src.services.storage.base import BaseObjectStorage


class OssStorage(BaseObjectStorage):
    """OSS 适配器占位实现。"""

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        raise NotImplementedError("OSS 存储适配器尚未实现")

    def upload_bytes(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        raise NotImplementedError("OSS 存储适配器尚未实现")

    def build_object_url(self, bucket: str, object_key: str) -> str:
        raise NotImplementedError("OSS 存储适配器尚未实现")
