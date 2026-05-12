import pytest

from src.evaluation.datasets.loader import MinioDataset
from src.evaluation.datasets.manifest import load_manifest


class FakeObjectStorage:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects
        self.downloads: list[tuple[str, str]] = []

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        self.downloads.append((bucket, object_key))
        try:
            return self.objects[(bucket, object_key)]
        except KeyError as exc:
            raise FileNotFoundError(f"{bucket}/{object_key}") from exc

    def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        return sorted(
            key for obj_bucket, key in self.objects
            if obj_bucket == bucket and key.startswith(prefix)
        )


def test_load_manifest_should_parse_minio_v2_schema():
    manifest = load_manifest(_manifest_yaml().encode("utf-8"), source_type="bytes")

    assert manifest.name == "parser_smoke"
    assert manifest.storage is not None
    assert manifest.storage.bucket == "test_set"
    assert manifest.samples[0].split == "test"
    assert manifest.samples[0].file_type == "pdf"


def test_load_manifest_should_reject_remote_sample_without_split():
    raw = _manifest_yaml().replace("    split: test\n", "")

    with pytest.raises(ValueError, match="split"):
        load_manifest(raw.encode("utf-8"), source_type="bytes")


def test_minio_dataset_should_download_manifest_filter_split_and_load_bytes():
    storage = FakeObjectStorage(
        {
            ("test_set", "datasets/parser_smoke/v2/manifest.yaml"): _manifest_yaml().encode("utf-8"),
            ("test_set", "datasets/parser_smoke/v2/samples/AQS.pdf"): b"%PDF-aqs",
            ("test_set", "datasets/parser_smoke/v2/ground_truth/AQS.md"): b"# AQS",
            ("test_set", "datasets/parser_smoke/v2/ground_truth/ThreadLocal.md"): b"# ThreadLocal",
        }
    )

    dataset = MinioDataset(
        dataset_name="parser_smoke",
        version="v2",
        split="test",
        object_storage=storage,
    )

    samples = list(dataset.iter_samples())

    assert dataset.name == "parser_smoke"
    assert dataset.version == "v2"
    assert dataset.sample_count == 1
    assert samples[0].sample_id == "AQS"
    assert samples[0].file_path is None
    assert samples[0].ground_truth["markdown"] == "# AQS"
    assert samples[0].load_bytes() == b"%PDF-aqs"
    assert ("test_set", "datasets/parser_smoke/v2/samples/AQS.pdf") in storage.downloads


def test_minio_dataset_should_resolve_latest_version_from_pointer():
    storage = FakeObjectStorage(
        {
            ("test_set", "datasets/parser_smoke/latest.json"): b'{"version": "v2"}',
            ("test_set", "datasets/parser_smoke/v2/manifest.yaml"): _manifest_yaml().encode("utf-8"),
            ("test_set", "datasets/parser_smoke/v2/ground_truth/AQS.md"): b"# AQS",
            ("test_set", "datasets/parser_smoke/v2/ground_truth/ThreadLocal.md"): b"# ThreadLocal",
        }
    )

    dataset = MinioDataset(
        dataset_name="parser_smoke",
        version="latest",
        split="validation",
        object_storage=storage,
    )

    samples = list(dataset.iter_samples())

    assert dataset.version == "v2"
    assert dataset.sample_count == 1
    assert samples[0].sample_id == "ThreadLocal"


def test_minio_dataset_should_discover_samples_by_same_stem():
    storage = FakeObjectStorage(
        {
            ("test_set", "datasets/multi/v1/manifest.yaml"): _discovery_manifest_yaml().encode("utf-8"),
            ("test_set", "datasets/multi/v1/test_set/pdf/AQS.pdf"): b"%PDF-aqs",
            ("test_set", "datasets/multi/v1/ground_truth/pdf/AQS.md"): b"# AQS",
        }
    )

    dataset = MinioDataset(
        dataset_name="multi_source_parser_eval",
        version="v1",
        split="test",
        object_storage=storage,
        prefix="datasets/multi",
    )

    samples = list(dataset.iter_samples())

    assert dataset.sample_count == 1
    assert samples[0].sample_id == "AQS"
    assert samples[0].file_type == "pdf"
    assert samples[0].ground_truth["markdown"] == "# AQS"
    assert samples[0].tags == ["pdf", "text_only"]
    assert samples[0].load_bytes() == b"%PDF-aqs"


def test_minio_dataset_should_reject_discovered_source_without_markdown():
    storage = FakeObjectStorage(
        {
            ("test_set", "datasets/multi/v1/manifest.yaml"): _discovery_manifest_yaml().encode("utf-8"),
            ("test_set", "datasets/multi/v1/test_set/pdf/AQS.pdf"): b"%PDF-aqs",
        }
    )

    with pytest.raises(ValueError, match="缺少同名标准 Markdown"):
        MinioDataset(
            dataset_name="multi_source_parser_eval",
            version="v1",
            split="test",
            object_storage=storage,
            prefix="datasets/multi",
        )


def _manifest_yaml() -> str:
    return """
name: parser_smoke
version: "v2"
description: "remote parser smoke"
storage:
  backend: minio
  bucket: test_set
  prefix: datasets/parser_smoke/v2
samples:
  - id: AQS
    split: test
    file:
      key: samples/AQS.pdf
      content_type: application/pdf
    file_type: pdf
    domain: Java技术文档
    language: zh
    difficulty: medium
    ground_truth:
      markdown:
        key: ground_truth/AQS.md
        content_type: text/markdown
    tags: [java, concurrency]
  - id: ThreadLocal
    split: validation
    file:
      key: samples/ThreadLocal.pdf
      content_type: application/pdf
    file_type: pdf
    domain: Java技术文档
    language: zh
    difficulty: medium
    ground_truth:
      markdown:
        key: ground_truth/ThreadLocal.md
        content_type: text/markdown
    tags: [java, concurrency]
""".strip()


def _discovery_manifest_yaml() -> str:
    return """
name: multi_source_parser_eval
version: "v1"
description: "multi source discovery"
storage:
  backend: minio
  bucket: test_set
  prefix: datasets/multi/v1
discovery:
  enabled: true
  test_set_dir: test_set
  ground_truth_dir: ground_truth
  match_strategy: same_stem
  ground_truth_extension: .md
  include_file_types: [pdf, docx, html]
defaults:
  split: test
  language: zh
sample_overrides:
  AQS:
    tags: [pdf, text_only]
""".strip()
