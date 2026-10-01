from pathlib import Path

from src.config import Settings, _settings_env_files


def test_default_mq_vendor_is_rabbitmq(tmp_path: Path, monkeypatch) -> None:
    missing_env = tmp_path / ".env.missing"
    monkeypatch.setenv("TOLINK_ENV_FILE", str(missing_env))
    monkeypatch.delenv("MQ_VENDOR", raising=False)

    configured = Settings(_env_file=_settings_env_files())

    assert configured.MQ_VENDOR == "rabbitmq"


def test_local_env_file_overrides_shared_env_file(tmp_path: Path, monkeypatch) -> None:
    shared_env = tmp_path / ".env.development"
    local_env = tmp_path / ".env.development.local"
    shared_env.write_text("APP_NAME=shared\nDB_PASSWORD=\n", encoding="utf-8")
    local_env.write_text("DB_PASSWORD=local-secret\n", encoding="utf-8")
    monkeypatch.setenv("TOLINK_ENV_FILE", str(shared_env))
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    env_files = _settings_env_files()
    configured = Settings(_env_file=env_files)
    assert env_files == (str(shared_env), str(local_env))
    assert configured.APP_NAME == "shared"
    assert configured.DB_PASSWORD == "local-secret"


def test_missing_local_override_keeps_shared_env_file_only(tmp_path: Path, monkeypatch) -> None:
    shared_env = tmp_path / ".env.development"
    shared_env.write_text("APP_NAME=shared\n", encoding="utf-8")
    monkeypatch.setenv("TOLINK_ENV_FILE", str(shared_env))
    assert _settings_env_files() == (str(shared_env),)


def test_file_timezone_boundary_requires_explicit_offset(monkeypatch):
    from datetime import datetime

    import pytest
    from pydantic import ValidationError

    monkeypatch.delenv("FILE_DB_BEIJING_SINCE", raising=False)
    assert Settings(_env_file=None, FILE_DB_BEIJING_SINCE="").FILE_DB_BEIJING_SINCE is None
    assert Settings(
        _env_file=None, FILE_DB_BEIJING_SINCE="2026-10-01T06:12:48Z"
    ).FILE_DB_BEIJING_SINCE == datetime(2026, 10, 1, 14, 12, 48)
    with pytest.raises(ValidationError, match="FILE_DB_BEIJING_SINCE"):
        Settings(_env_file=None, FILE_DB_BEIJING_SINCE="2026-10-01T14:12:48")
