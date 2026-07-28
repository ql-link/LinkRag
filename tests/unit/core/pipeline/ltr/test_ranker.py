from pathlib import Path

import pytest

from src.config import PROJECT_ROOT
from src.core.pipeline.ltr import load_lambda_mart_ranker

MODEL_DIR = Path(PROJECT_ROOT) / "models" / "ltr" / "candidate-difference-v3-20260728-final33"


def test_versioned_bundle_loads_and_passes_contract_vectors():
    ranker = load_lambda_mart_ranker(MODEL_DIR)

    assert ranker.model_version == "candidate-difference-v3-20260728-final33"
    assert ranker.manifest["alias_enabled"] is False
    assert ranker.manifest["feature_version"] == "candidate_difference_v3"


def test_tampered_manifest_is_rejected(tmp_path):
    target = tmp_path / "model"
    target.mkdir()
    for source in MODEL_DIR.iterdir():
        (target / source.name).write_bytes(source.read_bytes())
    manifest = target / "manifest.json"
    manifest.write_text(manifest.read_text().replace("candidate_difference_v3", "bad", 1))

    with pytest.raises(ValueError, match="feature version mismatch"):
        load_lambda_mart_ranker(target)
