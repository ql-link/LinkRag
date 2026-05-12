from src.evaluation.contracts.store import EvalRun, EvalRunSummary
from src.evaluation.storage.minio_result_store import MinioResultStore


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        try:
            return self.objects[(bucket, object_key)]
        except KeyError as exc:
            raise FileNotFoundError(f"{bucket}/{object_key}") from exc

    def upload_bytes(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self.objects[(bucket, object_key)] = content


async def test_minio_result_store_should_save_run_and_indexes():
    storage = FakeObjectStorage()
    store = MinioResultStore(storage)
    run = _build_run()

    run_id = await store.save_run(run)

    assert run_id == "run-1"
    assert ("test_set", "runs/parser_smoke/run-1/run.json") in storage.objects
    assert ("test_set", "runs/by_id/run-1.json") in storage.objects
    assert ("test_set", "runs/parser_smoke/index.jsonl") in storage.objects
    assert ("test_set", "runs/index.jsonl") in storage.objects


async def test_minio_result_store_should_load_run_by_id_and_list_runs():
    storage = FakeObjectStorage()
    store = MinioResultStore(storage)
    await store.save_run(_build_run())

    loaded = await store.load_run("run-1")
    runs = await store.list_runs(dataset_name="parser_smoke", status="done")

    assert loaded is not None
    assert loaded.summary.dataset_name == "parser_smoke"
    assert [item.run_id for item in runs] == ["run-1"]


async def test_minio_result_store_should_promote_and_load_baseline():
    storage = FakeObjectStorage()
    store = MinioResultStore(storage)
    await store.save_run(_build_run())

    await store.promote_baseline("parser_smoke", "run-1")
    baseline = await store.load_baseline("parser_smoke")

    assert baseline is not None
    assert baseline.summary.run_id == "run-1"
    assert ("test_set", "baselines/parser_smoke/latest.json") in storage.objects


async def test_minio_result_store_should_upload_report():
    storage = FakeObjectStorage()
    store = MinioResultStore(storage)

    key = await store.save_report(
        dataset_name="parser_smoke",
        run_id="run-1",
        format_name="markdown",
        content=b"# report",
        content_type="text/markdown",
    )

    assert key == "reports/parser_smoke/run-1/report.md"
    assert storage.objects[("test_set", key)] == b"# report"


async def test_minio_result_store_should_upload_artifact():
    storage = FakeObjectStorage()
    store = MinioResultStore(storage)

    key = await store.save_artifact(
        dataset_name="parser_smoke",
        run_id="run-1",
        relative_path="best_top3/1_sample/parser.md",
        content=b"# parsed",
        content_type="text/markdown",
    )

    assert key == "reports/parser_smoke/run-1/artifacts/best_top3/1_sample/parser.md"
    assert storage.objects[("test_set", key)] == b"# parsed"


async def test_minio_result_store_should_upload_parsed_result():
    storage = FakeObjectStorage()
    store = MinioResultStore(storage)

    result = await store.save_parsed_result(
        dataset_name="parser_smoke",
        run_id="run-1",
        sample_id="sample-1",
        evaluable_name="parser.pdf.naive",
        markdown="# Parsed",
        metadata={"elapsed_ms": 12},
    )

    assert result["parsed_markdown_key"] == (
        "reports/parser_smoke/run-1/parsed/sample-1/parser.pdf.naive/parsed.md"
    )
    assert storage.objects[("test_set", result["parsed_markdown_key"])] == b"# Parsed"
    assert ("test_set", result["metadata_key"]) in storage.objects


def _build_run() -> EvalRun:
    return EvalRun(
        summary=EvalRunSummary(
            run_id="run-1",
            dataset_name="parser_smoke",
            pipeline_config="[]",
            created_at=1.0,
            status="done",
            sample_count=1,
            success_count=1,
        ),
        metrics=[{"metric_id": "parser.stability.success_rate", "value": 1.0, "detail": {}}],
    )
