"""B5 companion-image contract: matching, validation, manifest and storage cleanup."""

import json
from pathlib import Path

import pytest

from src.api.management_http import BusinessError
from src.application.markdown_asset_bundle import AssetFile, materialize, preflight, scan
from src.application import document_uploads
from src.application.document_uploads import UploadJob

PNG = b"\x89PNG\r\n\x1a\n" + b"fixture-image-bytes"


def _fixture(tmp_path: Path, markdown: str, *, image_path: str = "images/a.png"):
    source = tmp_path / "guide.md"
    source.write_text(markdown, encoding="utf-8")
    image = tmp_path / "a.png"
    image.write_bytes(PNG)
    return source, AssetFile(image_path, "a.png", image, "image/png", len(PNG))


def test_full_path_materializes_java_compatible_manifest_and_rewrites(tmp_path):
    source, asset = _fixture(tmp_path, "![logo](../images/a.png)\n")
    plan = preflight(source, "guide.md", "FULL_PATH", "docs/guide.md",
                     [asset], ["images/a.png"])
    assert plan.summary["outcome"] == "READY"
    assert plan.summary["matchedCount"] == 1
    key, uploads, generated = materialize(
        plan, source, user_id=7, dataset_id=5, file_id=3, directory=tmp_path)
    assert key == "markdown-assets/v1/user-7/dataset-5/file-3/source/normalized.md"
    assert [item.object_key.rsplit("/", 1)[-1] for item in uploads] == [
        "original.md", plan.summary["issues"][0]["storedFilename"],
        "normalized.md", "manifest.json"]
    normalized = generated[0].read_text()
    assert normalized == f"![logo]({plan.summary['issues'][0]['logicalUri']})\n"
    manifest = json.loads(generated[1].read_text())
    assert (manifest["version"], manifest["userId"], manifest["datasetId"],
            manifest["fileId"], manifest["source"]["normalizedObjectKey"]) == (
                1, 7, 5, 3, key)
    assert manifest["summary"] == plan.summary


def test_shallow_mode_and_all_four_reference_syntaxes(tmp_path):
    source, asset = _fixture(tmp_path, "\n".join((
        "![a](a.png)", "![b][ref]", "[ref]: a.png",
        '<img src="a.png" alt="c">', "![[a.png|d]]",
        "```md", "![ignored](missing.png)", "```")), image_path="a.png")
    plan = preflight(source, "guide.md", "SHALLOW_BASENAME", None, [asset], [])
    assert plan.summary["matchedCount"] == 4
    assert [x.syntax for x in plan.references] == [
        "MARKDOWN", "MARKDOWN_REFERENCE", "HTML", "OBSIDIAN"]
    assert plan.summary["blockingIssues"] is False


def test_missing_asset_is_reported_for_manual_confirmation(tmp_path):
    source, _ = _fixture(tmp_path, "![x](missing.png)")
    plan = preflight(source, "guide.md", "FULL_PATH", "docs/guide.md", [], [])
    assert plan.summary["outcome"] == "ASSET_MISSING"
    assert plan.summary["blockingIssues"] is True
    assert plan.summary["missingPaths"] == ["docs/missing.png"]


@pytest.mark.parametrize("target", ["../../outside.png", "/etc/passwd", "C:\\secret.png"])
def test_unsafe_asset_reference_is_rejected(tmp_path, target):
    source, _ = _fixture(tmp_path, f"![x]({target})")
    with pytest.raises(BusinessError) as error:
        preflight(source, "guide.md", "FULL_PATH", "docs/guide.md", [], [])
    assert error.value.http_status == 400


def test_image_magic_and_declared_mime_must_match(tmp_path):
    source, asset = _fixture(tmp_path, "![x](a.png)", image_path="a.png")
    wrong = AssetFile("a.png", "a.png", asset.temp_path, "image/jpeg", asset.size)
    with pytest.raises(BusinessError) as error:
        preflight(source, "guide.md", "SHALLOW_BASENAME", None, [wrong], [])
    assert error.value.code == 30014


def test_inventory_ambiguity_and_path_collision(tmp_path):
    source, asset = _fixture(tmp_path, "![[a.png]]", image_path="images/a.png")
    plan = preflight(source, "guide.md", "FULL_PATH", "docs/guide.md", [asset],
                     ["images/a.png", "other/a.png"])
    assert plan.summary["outcome"] == "ASSET_AMBIGUOUS"
    with pytest.raises(BusinessError) as error:
        preflight(source, "guide.md", "FULL_PATH", "docs/guide.md", [asset],
                  ["images/a.png", "images/./a.png"])
    assert error.value.http_status == 400


def test_remote_and_code_images_are_not_local_references():
    assert scan("![web](https://example.invalid/a.png)\n`![code](a.png)`\n") == ()


@pytest.mark.asyncio
async def test_partial_bundle_upload_removes_every_attempted_object(monkeypatch, tmp_path):
    source, asset = _fixture(tmp_path, "![x](a.png)", image_path="a.png")
    plan = preflight(source, "guide.md", "SHALLOW_BASENAME", None, [asset], [])
    key, uploads, generated = materialize(
        plan, source, user_id=7, dataset_id=5, file_id=3, directory=tmp_path)
    attempted = []
    removed = []

    class Storage:
        def upload_path(self, _bucket, object_key, _path, _mime):
            attempted.append(object_key)
            if len(attempted) == 3:
                raise TimeoutError("storage acknowledgement lost")

        def remove_object(self, _bucket, object_key):
            removed.append(object_key)

    monkeypatch.setattr(document_uploads.StorageFactory, "get_storage", lambda: Storage())
    job = UploadJob(3, 7, 5, "guide.md", "text/markdown", source, key, False,
                    uploads, (asset.temp_path, *generated))
    with pytest.raises(TimeoutError):
        await document_uploads._process(job)
    assert removed == list(reversed(attempted))
