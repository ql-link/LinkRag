from pathlib import Path

from src.services.storage.base import BaseObjectStorage


class OssStorage(BaseObjectStorage):
    """OSS 适配器占位实现。

    本次治理保持"协议对齐 + 占位实现"：所有方法签名与 ``BaseObjectStorage`` 保持一致，
    但实际访问 OSS 的 SDK 调用由生产侧后续独立改造接入；调用任一方法会抛
    ``NotImplementedError`` 防止误用。
    """

    def download_to_path(self, bucket: str, object_key: str, dst: Path) -> None:
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
