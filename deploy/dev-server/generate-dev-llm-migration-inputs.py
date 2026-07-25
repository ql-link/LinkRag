#!/usr/bin/env python3
"""Generate dev-only inputs required by the irreversible LLM config migration."""

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
        raise SystemExit("usage: generate-dev-llm-migration-inputs.py OUTPUT_DIR")
    if not os.environ.get("API_KEY_ENCRYPTION_SECRET"):
        raise RuntimeError("API_KEY_ENCRYPTION_SECRET is required")

    output_dir = Path(sys.argv[1])
    output_dir.mkdir(parents=True, exist_ok=True)
    ciphertexts = {
        capability: encrypt_api_key(f"dev-only-{capability.lower()}")
        for capability in CAPABILITIES
    }
    path = output_dir / "ciphertexts.json"
    path.write_text(json.dumps({"ciphertexts": ciphertexts}), encoding="utf-8")
    path.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
