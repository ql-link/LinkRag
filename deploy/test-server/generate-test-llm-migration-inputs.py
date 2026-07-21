#!/usr/bin/env python3
"""Generate test-only inputs required by the irreversible LLM config migration."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from src.core.llm.encryption import encrypt_api_key

CAPABILITIES = (
    "CHAT",
    "EMBEDDING",
    "SPARSE_EMBEDDING",
    "VISION",
    "RERANK",
    "ASR",
)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate-test-llm-migration-inputs.py OUTPUT_DIR")
    if not os.environ.get("API_KEY_ENCRYPTION_SECRET"):
        raise RuntimeError("API_KEY_ENCRYPTION_SECRET is required")

    output_dir = Path(sys.argv[1])
    output_dir.mkdir(parents=True, exist_ok=True)
    ciphertexts = {
        capability: encrypt_api_key(f"test-only-{capability.lower()}")
        for capability in CAPABILITIES
    }
    evidence = {
        "maintenance_lock": "HELD",
        "legacy_llm_writer_count": 0,
        "legacy_llm_message_lag": 0,
        "seed_ciphertext_count": len(CAPABILITIES),
        "seed_capability_set": list(CAPABILITIES),
    }
    for name, payload in (
        ("ciphertexts.json", {"ciphertexts": ciphertexts}),
        ("evidence.json", evidence),
    ):
        path = output_dir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
