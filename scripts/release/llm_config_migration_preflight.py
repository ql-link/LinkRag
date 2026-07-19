#!/usr/bin/env python3
"""LLM 配置干净切换发布门禁。

该 wrapper 只在维护锁、旧 writer、旧消息与 seed 密文全部通过后
生成短期授权。任一证据失败时不会启动 Alembic 子进程。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REQUIRED_CAPABILITIES = {
    "CHAT",
    "EMBEDDING",
    "SPARSE_EMBEDDING",
    "VISION",
    "RERANK",
    "ASR",
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _ciphertext_map(value: dict[str, Any]) -> dict[str, str]:
    raw = value.get("ciphertexts", value)
    if not isinstance(raw, dict):
        raise ValueError("ciphertexts must be an object")
    result: dict[str, str] = {}
    for capability, item in raw.items():
        ciphertext = item.get("ciphertext") if isinstance(item, dict) else item
        if isinstance(ciphertext, str) and ciphertext.strip():
            result[str(capability).upper()] = ciphertext.strip()
    return result


def validate_evidence(
    evidence: dict[str, Any],
    *,
    manifest_count: int,
    ciphertexts: dict[str, str],
) -> str | None:
    """返回第一个固定阻断原因，全部通过返回 ``None``。"""
    if evidence.get("maintenance_lock") != "HELD":
        return "MAINTENANCE_LOCK_REQUIRED"
    if int(evidence.get("legacy_llm_writer_count", -1)) != 0:
        return "LEGACY_WRITER_STILL_RUNNING"
    if int(evidence.get("legacy_llm_message_lag", -1)) != 0:
        return "LEGACY_MESSAGE_NOT_DRAINED"
    if int(evidence.get("seed_ciphertext_count", -1)) != manifest_count:
        return "SEED_CIPHERTEXT_INCOMPLETE"
    evidence_caps = {str(item).upper() for item in evidence.get("seed_capability_set", [])}
    if evidence_caps != REQUIRED_CAPABILITIES:
        return "SEED_CAPABILITY_INCOMPLETE"
    if set(ciphertexts) != REQUIRED_CAPABILITIES:
        return "SEED_CIPHERTEXT_INCOMPLETE"
    return None


def _validate_ciphertexts(ciphertexts: dict[str, str]) -> None:
    forbidden = ("CHANGE_ME", "demo-encrypted-key")
    for capability, ciphertext in ciphertexts.items():
        if not ciphertext or any(marker.lower() in ciphertext.lower() for marker in forbidden):
            raise ValueError(f"invalid ciphertext for capability {capability}")

    # 发布环境必须能用正式加密器解开；异常中不包含密文或明文。
    from src.core.llm.encryption import decrypt_api_key

    for capability, ciphertext in ciphertexts.items():
        try:
            plaintext = decrypt_api_key(ciphertext)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"ciphertext cannot be decrypted for {capability}") from exc
        if not plaintext:
            raise ValueError(f"ciphertext decrypts to empty value for {capability}")


def _sign_authorization(payload: dict[str, Any], secret: str) -> dict[str, Any]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    return {**payload, "signature": signature}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--ciphertexts", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("llm_seed_manifest.json"))
    parser.add_argument("--authorization-file", type=Path, required=True)
    parser.add_argument("--authorization-ttl-seconds", type=int, default=600)
    parser.add_argument("--run-migration", action="store_true")
    args = parser.parse_args(argv)

    try:
        evidence = _load_json(args.evidence)
        manifest = _load_json(args.manifest)
        ciphertexts = _ciphertext_map(_load_json(args.ciphertexts))
        reason = validate_evidence(
            evidence,
            manifest_count=len(manifest.get("system_configs", [])),
            ciphertexts=ciphertexts,
        )
        if reason is not None:
            print(json.dumps({"status": "BLOCKED", "reason": reason}))
            return 2
        _validate_ciphertexts(ciphertexts)
        auth_secret = os.environ.get("TOLINK_LLM_MIGRATION_AUTH_SECRET", "")
        if len(auth_secret) < 32:
            raise ValueError("TOLINK_LLM_MIGRATION_AUTH_SECRET must contain at least 32 characters")
        now = int(time.time())
        payload = {
            "schemaVersion": 1,
            "revision": "0036",
            "issuedAt": now,
            "expiresAt": now + args.authorization_ttl_seconds,
            "nonce": secrets.token_hex(16),
            "evidenceSha256": hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
        }
        authorization = _sign_authorization(payload, auth_secret)
        args.authorization_file.write_text(
            json.dumps(authorization, sort_keys=True), encoding="utf-8"
        )
        os.chmod(args.authorization_file, 0o600)
        if args.run_migration:
            env = os.environ.copy()
            env["TOLINK_LLM_MIGRATION_AUTH_FILE"] = str(args.authorization_file)
            env["TOLINK_LLM_SEED_CIPHERTEXT_FILE"] = str(args.ciphertexts)
            completed = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                check=False,
                env=env,
            )
            return completed.returncode
        print(json.dumps({"status": "AUTHORIZED", "expiresAt": payload["expiresAt"]}))
        return 0
    except Exception as exc:  # noqa: BLE001
        # 只输出异常类型，防止上游库把密文/明文带进 message。
        print(
            json.dumps(
                {"status": "BLOCKED", "reason": "PREFLIGHT_VALIDATION_FAILED", "error": type(exc).__name__}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
