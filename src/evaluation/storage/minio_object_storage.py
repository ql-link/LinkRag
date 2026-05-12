# -*- coding: utf-8 -*-
"""Evaluation-specific MinIO object storage client."""
from __future__ import annotations

from io import BytesIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from src.evaluation.config import EvalConfig, eval_config


class MinioEvaluationObjectStorage:
    """Small S3-compatible client scoped to evaluation configuration."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        use_ssl: bool = False,
    ) -> None:
        if endpoint.startswith(("http://", "https://")):
            endpoint_url = endpoint
        else:
            scheme = "https" if use_ssl else "http"
            endpoint_url = f"{scheme}://{endpoint}"

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            use_ssl=use_ssl,
            config=Config(signature_version="s3v4"),
        )

    @classmethod
    def from_config(
        cls,
        config: EvalConfig | None = None,
    ) -> "MinioEvaluationObjectStorage":
        cfg = config or eval_config
        return cls(
            endpoint=cfg.EVAL_MINIO_ENDPOINT,
            access_key=cfg.EVAL_MINIO_ACCESS_KEY,
            secret_key=cfg.EVAL_MINIO_SECRET_KEY,
            use_ssl=cfg.EVAL_MINIO_USE_SSL,
        )

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=bucket, Key=object_key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(f"MinIO object not found: {bucket}/{object_key}") from exc
            raise
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

    def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        """List object keys under a prefix.

        Evaluation datasets use MinIO as a versioned directory tree. Discovery
        mode needs a stable, sorted key list so same input objects produce the
        same sample ordering across runs.
        """
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix.strip("/")):
            for item in page.get("Contents", []):
                key = item.get("Key")
                if key:
                    keys.append(str(key))
        return sorted(keys)
