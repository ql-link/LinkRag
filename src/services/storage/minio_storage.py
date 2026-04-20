from io import BytesIO
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

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=object_key)
        return response["Body"].read()

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
