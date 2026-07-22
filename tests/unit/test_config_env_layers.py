from pathlib import Path
from src.config import Settings, _settings_env_files
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
def test_missing_local_override_keeps_shared_env_file_only(
    tmp_path: Path, monkeypatch
) -> None:
    shared_env = tmp_path / ".env.development"
    shared_env.write_text("APP_NAME=shared\n", encoding="utf-8")
    monkeypatch.setenv("TOLINK_ENV_FILE", str(shared_env))
    assert _settings_env_files() == (str(shared_env),)
