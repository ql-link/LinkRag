"""Curl six B2 uploads against Dev MinIO and remove only created test objects."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urljoin

from sqlalchemy.engine import make_url

from src.config import settings
from src.services.storage.factory import StorageFactory


def _request(
    base_url: str, biz_type: str, file: Path, filename: str, mime: str
) -> tuple[int, dict]:
    command = [
        "curl",
        "--noproxy",
        "*",
        "--silent",
        "--show-error",
        "--max-time",
        "20",
        "--request",
        "POST",
        "--write-out",
        "\n%{http_code}",
        "--form",
        f"file=@{file};filename={filename};type={mime}",
        f"{base_url.rstrip('/')}/api/v1/oss-files/{biz_type}",
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"curl transport failed for {biz_type}")
    body, status = result.stdout.rsplit("\n", 1)
    return int(status), json.loads(body)


def _get(url: str) -> tuple[int, bytes, str]:
    command = [
        "curl",
        "--noproxy",
        "*",
        "--silent",
        "--show-error",
        "--max-time",
        "12",
        "--output",
        "-",
        "--write-out",
        "\n%{http_code}\n%{content_type}",
        url,
    ]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise RuntimeError("public URL transport failed")
    body, status, content_type = result.stdout.rsplit(b"\n", 2)
    return int(status), body, content_type.decode(errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-url", required=True)
    args = parser.parse_args()
    db = make_url(settings.DATABASE_URL or "")
    if (
        settings.APP_ENV != "development"
        or db.database != "tolink_rag_dev"
        or db.host != "100.86.10.52"
        or settings.STORAGE_TYPE != "minio"
    ):
        raise RuntimeError("probe accepts only named Dev MySQL and MinIO")
    if (
        not settings.B2_GENERIC_UPLOAD_ENABLED
        or settings.B3_CONTROL_WRITES_ENABLED
        or settings.B4_DATASET_WRITES_ENABLED
        or settings.B5_FILE_WRITES_ENABLED
        or settings.B5_DELETE_WRITES_ENABLED
    ):
        raise RuntimeError("only B2 generic upload may be enabled")
    public_base = (settings.MINIO_PUBLIC_BASE_URL or "").rstrip("/")
    if not public_base:
        raise RuntimeError("public base URL is required to derive cleanup keys")
    storage = StorageFactory.get_storage()
    created: list[tuple[str, str]] = []
    failures = 0
    cases = [
        ("avatar", "probe.png", "image/png", settings.MINIO_PUBLIC_BUCKET, True),
        ("providerIcon", "probe.png", "image/png", settings.MINIO_PUBLIC_BUCKET, True),
        ("chatImage", "probe.png", "image/png", settings.MINIO_PUBLIC_BUCKET, True),
        ("document", "probe.md", "text/markdown", settings.MINIO_RAW_BUCKET, False),
        ("cert", "probe.pem", "application/octet-stream", settings.MINIO_PRIVATE_BUCKET, False),
        ("feedback", "probe.txt", "text/plain", settings.MINIO_PUBLIC_BUCKET, True),
    ]
    try:
        with TemporaryDirectory(prefix="b2-upload-probe-") as directory:
            file = Path(directory) / "source"
            for biz_type, filename, mime, bucket, public in cases:
                content = f"b2-probe-{biz_type}".encode()
                file.write_bytes(content)
                status, response = _request(args.python_url, biz_type, file, filename, mime)
                if status != 200 or response.get("code") != 200:
                    failures += 1
                    print(f"{biz_type}: FAIL http={status} code={response.get('code')}")
                    continue
                result = response["data"]
                if public:
                    if not result.startswith(public_base + "/"):
                        raise RuntimeError("public URL does not match configured cleanup base")
                    key = unquote(result[len(public_base) + 1 :])
                else:
                    key = result
                if not key.startswith(biz_type + "/"):
                    raise RuntimeError("server object key violates fixture cleanup prefix")
                created.append((bucket, key))
                downloaded = Path(directory) / f"{biz_type}.download"
                storage.download_to_path(bucket, key, downloaded)
                okay = downloaded.read_bytes() == content
                public_status = None
                if public:
                    try:
                        public_url = urljoin(args.python_url.rstrip("/") + "/", result)
                        public_status, public_bytes, actual_mime = _get(public_url)
                        expected_mime = "text/plain" if biz_type == "feedback" else "image/png"
                        okay = (
                            okay
                            and public_status == 200
                            and public_bytes == content
                            and actual_mime.startswith(expected_mime)
                        )
                    except RuntimeError:
                        okay = False
                else:
                    anonymous_url = urljoin(
                        args.python_url.rstrip("/") + "/",
                        f"/api/v1/oss-files/public/{key}",
                    )
                    anonymous_status, _, _ = _get(anonymous_url)
                    okay = okay and anonymous_status == 404
                failures += not okay
                detail = f" public_http={public_status}" if public else ""
                print(f"{biz_type}: {'PASS' if okay else 'FAIL'} upload_and_read{detail}")
            for label, kind, filename, content, expected in (
                ("empty", "avatar", "probe.png", b"", 40001),
                ("suffix", "avatar", "probe.exe", b"x", 40001),
                ("unknown", "unknown", "probe.png", b"x", 40001),
                ("size_over", "avatar", "probe.png", b"x" * (5 * 1024 * 1024 + 1), 40001),
            ):
                file.write_bytes(content)
                status, response = _request(
                    args.python_url, kind, file, filename, "application/octet-stream"
                )
                okay = status == 400 and response.get("code") == expected
                failures += not okay
                print(
                    f"{label}: {'PASS' if okay else 'FAIL'} http={status} code={response.get('code')}"
                )
    finally:
        for bucket, key in created:
            storage.remove_object(bucket, key)
        print(f"cleanup_objects={len(created)}")
    print(f"result failed={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
