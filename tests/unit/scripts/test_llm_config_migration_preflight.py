"""破坏性 0036 的发布 preflight 必须 fail closed。"""

from __future__ import annotations

import json

import pytest

from scripts.release import llm_config_migration_preflight as preflight


CAPABILITIES = [
    "CHAT",
    "EMBEDDING",
    "SPARSE_EMBEDDING",
    "VISION",
    "RERANK",
    "ASR",
]


def _valid_evidence():
    return {
        "maintenance_lock": "HELD",
        "legacy_llm_writer_count": 0,
        "legacy_llm_message_lag": 0,
        "seed_ciphertext_count": 6,
        "seed_capability_set": CAPABILITIES,
    }


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("maintenance_lock", "ABSENT", "MAINTENANCE_LOCK_REQUIRED"),
        ("legacy_llm_writer_count", 1, "LEGACY_WRITER_STILL_RUNNING"),
        ("legacy_llm_message_lag", 1, "LEGACY_MESSAGE_NOT_DRAINED"),
        ("seed_ciphertext_count", 5, "SEED_CIPHERTEXT_INCOMPLETE"),
        ("seed_capability_set", CAPABILITIES[:-1], "SEED_CAPABILITY_INCOMPLETE"),
    ],
)
def test_invalid_evidence_blocks_before_authorization_and_alembic(
    tmp_path, monkeypatch, capsys, field, value, reason
):
    evidence = _valid_evidence()
    evidence[field] = value
    evidence_path = tmp_path / "evidence.json"
    ciphertext_path = tmp_path / "ciphertexts.json"
    auth_path = tmp_path / "authorization.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    ciphertext_path.write_text(
        json.dumps({"ciphertexts": {cap: "opaque" for cap in CAPABILITIES}}),
        encoding="utf-8",
    )
    called = []
    monkeypatch.setattr(preflight.subprocess, "run", lambda *a, **k: called.append((a, k)))

    exit_code = preflight.main(
        [
            "--evidence",
            str(evidence_path),
            "--ciphertexts",
            str(ciphertext_path),
            "--authorization-file",
            str(auth_path),
            "--run-migration",
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {"status": "BLOCKED", "reason": reason}
    assert not auth_path.exists()
    assert called == []
