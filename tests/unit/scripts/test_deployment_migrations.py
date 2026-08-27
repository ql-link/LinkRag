"""部署链路必须在切换应用镜像前使用对应环境配置执行 Alembic。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read_env(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
        for key, value in [line.split("=", 1)]
    }


def test_production_jenkins_delegates_migration_and_deploy_to_cloud() -> None:
    jenkinsfile = (ROOT / "Jenkinsfile").read_text(encoding="utf-8")
    cloud_script = (ROOT / "deploy/scripts/build-production-on-cloud.sh").read_text(
        encoding="utf-8"
    )

    package_stage = jenkinsfile.index("stage('Package Commit')")
    deploy_stage = jenkinsfile.index("stage('Deploy Production on Cloud')")
    migration = cloud_script.index("python scripts/release/run_alembic.py")
    cutover = cloud_script.index('cutover_started="true"')

    assert package_stage < deploy_stage
    assert "git archive --format=tar.gz" in jenkinsfile
    assert "deploy/scripts/build-production-on-cloud.sh" in jenkinsfile
    assert 'CLOUD_HOST = \'100.77.31.79\'' in jenkinsfile

    assert migration < cutover
    assert '--env-file "${candidate_base_env}"' in cloud_script
    assert '--env-file "${secret_env}"' in cloud_script
    assert "--expected-app-env production" in cloud_script
    assert "--expected-host tolink-mysql" in cloud_script
    assert "--expected-port 3306" in cloud_script
    assert "--expected-database tolink_rag_db" in cloud_script
    assert 'compose_project="linkrag-production"' in cloud_script
    assert "up -d --no-deps tolink-rag" in cloud_script
    assert 'curl -fsS "http://127.0.0.1:${http_port}/ready"' in cloud_script
    assert "rollback_old_application" in cloud_script


def test_dev_deploy_migrates_with_development_env() -> None:
    source = (ROOT / "deploy/dev-server/build-component-on-primary.sh").read_text(encoding="utf-8")

    migration = source.index("python scripts/release/run_alembic.py")
    deploy = source.index(
        'docker compose --env-file .env.dev --profile apps up -d "$compose_service"'
    )

    assert migration < deploy
    assert '--env-file "$dev_root/config/rag/.env.development"' in source
    assert '--env-file "$dev_root/config/rag/.env.development.local"' in source
    assert "--expected-app-env development" in source
    assert "--expected-host tolink-dev-mysql" in source
    assert "--expected-port 3306" in source
    assert "--expected-database tolink_rag_dev" in source
    assert "--seed-ciphertext-file /run/llm-migration/ciphertexts.json" in source
    assert "-e TOLINK_LLM_SEED_CIPHERTEXT_FILE=" not in source


def test_dev_base_config_targets_isolated_dev_resources() -> None:
    env = _read_env(ROOT / ".env.development")

    assert env["APP_ENV"] == "development"
    assert env["LOG_SERVICE_NAME"] == "tolink-rag-dev"
    assert env["DB_NAME"] == "tolink_rag_dev"
    assert env["CHUNK_INDEX_COLLECTION_NAME"] == "tolink_dev_chunks"
    assert env["MANTICORE_BM25_TABLE_PREFIX"] == "dev_bm25_ds_v2"
    assert env["MINIO_RAW_BUCKET"] == "tolink-dev-raw"
    assert env["MINIO_PRIVATE_BUCKET"] == "tolink-dev-docs"
