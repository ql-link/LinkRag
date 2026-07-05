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
        public_endpoint = settings.MINIO_PUBLIC_ENDPOINT or endpoint_url
        self._public_endpoint_url = public_endpoint.rstrip("/")
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
        return f"{self._public_endpoint_url}/{bucket}/{escaped_key}"

    def remove_prefix(self, bucket: str, prefix: str) -> int:
        """列举前缀下全部对象并分批删除（S3 ``delete_objects`` 单批上限 1000）。

        前缀为空直接拒绝（返回 0），避免误删整桶；前缀下无对象时 ``list_objects_v2``
        返回空 ``Contents``，循环自然 no-op。删除失败（网络 / 超时）由 botocore 抛出，
        交删除编排归类为暂时性失败重试。
        """
        if not prefix:
            return 0

        paginator = self._client.get_paginator("list_objects_v2")
        deleted = 0
        batch: list[dict[str, str]] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                batch.append({"Key": obj["Key"]})
                if len(batch) == 1000:
                    deleted += self._delete_batch(bucket, batch)
                    batch = []
        if batch:
            deleted += self._delete_batch(bucket, batch)
        return deleted

    def _delete_batch(self, bucket: str, batch: list[dict[str, str]]) -> int:
        """删一批对象并校验逐键结果。

        S3 ``delete_objects`` 对逐键失败**不抛异常**，而是放在响应的 ``Errors`` 里。
        若静默吞掉，删除编排会误以为 OSS 已清干净并继续删 DB 账本，导致失败对象永久泄漏。
        故此处显式校验：有 ``Errors`` 即抛，交编排归类为暂时性失败重试。返回实际删除数。
        """
        resp = self._client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
        errors = resp.get("Errors") or []
        if errors:
            sample = errors[0]
            raise OSError(
                f"delete_objects 部分失败 bucket={bucket}: {len(errors)}/{len(batch)} 个对象未删, "
                f"示例 key={sample.get('Key')} code={sample.get('Code')} msg={sample.get('Message')}"
            )
        return len(resp.get("Deleted") or [])
