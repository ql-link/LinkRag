from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.client import Config

from src.config import settings
from src.services.storage.base import BaseObjectStorage


class MinioStorage(BaseObjectStorage):
    """基于 S3 兼容接口的 MinIO 存储实现。"""

    def __init__(self) -> None:
        endpoint = settings.MINIO_ENDPOINT
        access_key = settings.MINIO_ACCESS_KEY
        secret_key = settings.MINIO_SECRET_KEY
        use_ssl = settings.MINIO_USE_SSL
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            endpoint_url = endpoint
        else:
            scheme = "https" if use_ssl else "http"
            endpoint_url = f"{scheme}://{endpoint}"

        self._endpoint_url = endpoint_url.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            use_ssl=use_ssl,
            config=Config(signature_version="s3v4"),
        )

    def download_to_path(self, bucket: str, object_key: str, dst: Path) -> None:
        """boto3 ``download_fileobj`` 分块写盘（默认 8MB chunk），整个调用栈不持有整对象 bytes。

        - 失败时 ``dst`` 可能是半成品文件，调用方负责 finally 清理。
        - 磁盘满（``OSError`` errno=ENOSPC）让 SDK / 系统调用直接抛出，由 pipeline 分类为
          ``TEMP_DISK_FULL``。
        - 对象 404 / 网络异常抛 botocore 异常，由 pipeline 分类为 ``SOURCE_FILE_NOT_FOUND``。
        """
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as fp:
            self._client.download_fileobj(Bucket=bucket, Key=object_key, Fileobj=fp)

    def upload_bytes(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self._client.upload_fileobj(
            BytesIO(content),
            bucket,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )

    def build_object_url(self, bucket: str, object_key: str) -> str:
        escaped_key = "/".join(quote(part) for part in object_key.split("/"))
        return f"{self._endpoint_url}/{bucket}/{escaped_key}"
