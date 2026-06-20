"""MinioStorage.remove_prefix 单测（LINK-55）。

绕过 __init__（避免真实 boto3 / settings），注入 fake S3 client，验证：
- 空前缀拒绝（不触达 client，返回 0）；
- 前缀下无对象 → no-op（不调 delete_objects，返回 0）；
- 多对象跨页分批删除（单批上限 1000）。
"""

from src.services.storage.minio_storage import MinioStorage


class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, *, Bucket, Prefix):  # noqa: N803 (boto3 kwargs 命名)
        self.bucket = Bucket
        self.prefix = Prefix
        return iter(self._pages)


class _FakeS3Client:
    def __init__(self, pages, errors_on_call=None):
        self._paginator = _FakePaginator(pages)
        self.delete_calls = []
        # errors_on_call: 第 N 次 delete_objects 调用返回的 Errors（模拟逐键失败）
        self._errors_on_call = errors_on_call or {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self._paginator

    def delete_objects(self, *, Bucket, Delete):  # noqa: N803
        idx = len(self.delete_calls)
        self.delete_calls.append((Bucket, [o["Key"] for o in Delete["Objects"]]))
        errors = self._errors_on_call.get(idx, [])
        deleted = [o for o in Delete["Objects"] if o not in errors]
        return {"Deleted": deleted, "Errors": errors}


def _storage_with(pages):
    storage = MinioStorage.__new__(MinioStorage)  # 跳过 __init__
    storage._client = _FakeS3Client(pages)
    return storage


def test_empty_prefix_is_rejected_noop():
    storage = _storage_with([{"Contents": [{"Key": "x"}]}])
    assert storage.remove_prefix("b", "") == 0
    assert storage._client.delete_calls == []


def test_no_objects_is_noop():
    storage = _storage_with([{}])  # 无 Contents
    assert storage.remove_prefix("b", "parsed/u/d/task/") == 0
    assert storage._client.delete_calls == []


def test_deletes_all_objects_under_prefix():
    pages = [
        {"Contents": [{"Key": "parsed/u/d/task/a.md"}, {"Key": "parsed/u/d/task/image/a/1.png"}]},
        {"Contents": [{"Key": "parsed/u/d/task/image/a/2.png"}]},
    ]
    storage = _storage_with(pages)
    deleted = storage.remove_prefix("b", "parsed/u/d/task/")
    assert deleted == 3
    all_deleted = [k for _, keys in storage._client.delete_calls for k in keys]
    assert set(all_deleted) == {
        "parsed/u/d/task/a.md",
        "parsed/u/d/task/image/a/1.png",
        "parsed/u/d/task/image/a/2.png",
    }


def test_partial_delete_errors_raise_not_silent():
    # S3 delete_objects 逐键失败放在 Errors（不抛）；remove_prefix 必须抛出，
    # 避免编排误判 OSS 已清干净继续删 DB 账本，导致失败对象永久泄漏。
    import pytest

    pages = [{"Contents": [{"Key": "parsed/u/d/Y/M/D/task/a.png"}, {"Key": "parsed/u/d/Y/M/D/task/b.png"}]}]
    storage = MinioStorage.__new__(MinioStorage)
    storage._client = _FakeS3Client(
        pages,
        errors_on_call={0: [{"Key": "parsed/u/d/Y/M/D/task/b.png", "Code": "AccessDenied"}]},
    )
    with pytest.raises(OSError):
        storage.remove_prefix("b", "parsed/u/d/Y/M/D/task/")


def test_batches_at_1000():
    keys = [{"Key": f"parsed/u/d/task/{i}.png"} for i in range(1500)]
    storage = _storage_with([{"Contents": keys}])
    deleted = storage.remove_prefix("b", "parsed/u/d/task/")
    assert deleted == 1500
    # 1500 → 两批（1000 + 500）
    assert [len(keys) for _, keys in storage._client.delete_calls] == [1000, 500]
