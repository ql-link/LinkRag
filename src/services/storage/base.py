from abc import ABC, abstractmethod


class BaseObjectStorage(ABC):
    """对象存储抽象接口。"""

    @abstractmethod
    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        """下载对象内容。"""

    @abstractmethod
    def upload_bytes(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        """上传对象内容。"""

    @abstractmethod
    def build_object_url(self, bucket: str, object_key: str) -> str:
        """构造对象访问 URL。"""
