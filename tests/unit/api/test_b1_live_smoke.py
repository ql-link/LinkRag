"""The live fixture runner must not create Dev data without Python auth readiness."""

from scripts.acceptance import b1_live_smoke


def test_auth_preflight_blocks_registration_before_dev_write(monkeypatch, capsys):
    monkeypatch.setattr(
        b1_live_smoke.settings,
        "DATABASE_URL",
        "mysql+aiomysql://fixture@100.86.10.52/tolink_rag_dev",
    )
    monkeypatch.setattr(b1_live_smoke.settings, "APP_ENV", "development")
    monkeypatch.setattr(
        "sys.argv",
        [
            "b1_live_smoke.py",
            "--java-url",
            "http://java.test",
            "--python-url",
            "http://python.test",
        ],
    )
    calls = []

    def fake_curl(base_url, method, path, **kwargs):
        calls.append((base_url, method, path))
        return 503, {"code": 503, "message": "管理端认证尚未配置", "data": None}

    monkeypatch.setattr(b1_live_smoke, "_curl", fake_curl)
    assert b1_live_smoke.main() == 2
    assert calls == [("http://python.test", "GET", "/api/v1/user/profile")]
    assert "auth_preflight=BLOCKED" in capsys.readouterr().out
