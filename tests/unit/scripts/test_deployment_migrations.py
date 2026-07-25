"""部署链路必须在切换应用镜像前使用对应环境配置执行 Alembic。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_production_jenkins_migrates_before_deploy_with_production_env() -> None:
    source = (ROOT / "Jenkinsfile").read_text(encoding="utf-8")

    migration_stage = source.index("stage('Migrate Database')")
    deploy_stage = source.index("stage('Deploy')")

    assert migration_stage < deploy_stage
    assert '--env-file "$RAG_ENV_FILE"' in source
    assert '--env-file "$RAG_SECRET_ENV_FILE"' in source
    assert "python scripts/release/run_alembic.py" in source
    assert "--expected-app-env production" in source
    assert "--expected-port 3306" in source
    assert "--expected-database tolink_rag_db" in source


def test_dev_deploy_migrates_with_development_env() -> None:
    source = (ROOT / "deploy/test-server/build-component-on-primary.sh").read_text(encoding="utf-8")

    migration = source.index("python scripts/release/run_alembic.py")
    deploy = source.index(
        'docker compose --env-file .env.test --profile apps up -d "$compose_service"'
    )

    assert migration < deploy
    assert '--env-file "$test_root/config/rag/.env.development"' in source
    assert '--env-file "$test_root/config/rag/.env.development.local"' in source
    assert "--expected-app-env development" in source
    assert "--expected-port 13306" in source
    assert "--expected-database tolink_rag_test" in source
    assert "--seed-ciphertext-file /run/llm-migration/ciphertexts.json" in source
    assert "-e TOLINK_LLM_SEED_CIPHERTEXT_FILE=" not in source
