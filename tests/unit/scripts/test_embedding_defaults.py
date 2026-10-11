"""新默认配置不改变历史迁移种子或已有数据集绑定。"""

import pytest
import sqlalchemy as sa

from scripts.ops.embedding_defaults import MODEL, PROTOCOL, configure_defaults


@pytest.fixture
def connection():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    configs = sa.Table(
        "llm_model_config",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        *[
            sa.Column(name, sa.String)
            for name in (
                "scope",
                "provider_type",
                "model_name",
                "display_name",
                "capability",
                "protocol",
                "api_base_url",
                "api_key",
            )
        ],
        *[
            sa.Column(name, sa.Integer)
            for name in (
                "owner_user_id",
                "provider_id",
                "is_active",
                "snapshot_version",
            )
        ],
    )
    defaults = sa.Table(
        "llm_capability_default",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scope", sa.String),
        sa.Column("owner_user_id", sa.Integer),
        sa.Column("capability", sa.String),
        sa.Column("config_id", sa.Integer),
    )
    bindings = sa.Table(
        "dataset_parse_config",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dense_embedding_config_id", sa.Integer),
        sa.Column("sparse_embedding_config_id", sa.Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        base = dict(
            scope="SYSTEM",
            owner_user_id=0,
            provider_id=1,
            provider_type="linkrag",
            is_active=1,
            snapshot_version=1,
            api_key="synthetic-ciphertext",
            api_base_url="https://ark.test/multimodal",
        )
        conn.execute(
            configs.insert(),
            [
                dict(
                    base, id=1, model_name="BAAI/bge-m3", capability="EMBEDDING", protocol="openai"
                ),
                dict(
                    base, id=2, model_name=MODEL, capability="SPARSE_EMBEDDING", protocol=PROTOCOL
                ),
            ],
        )
        conn.execute(
            defaults.insert(),
            [
                dict(scope="SYSTEM", owner_user_id=0, capability="EMBEDDING", config_id=1),
                dict(scope="SYSTEM", owner_user_id=0, capability="SPARSE_EMBEDDING", config_id=2),
            ],
        )
        conn.execute(
            bindings.insert().values(
                id=10, dense_embedding_config_id=1, sparse_embedding_config_id=2
            )
        )
        yield conn, configs, defaults, bindings
    engine.dispose()


def test_preview_does_not_write(connection):
    conn, configs, defaults, bindings = connection
    result = configure_defaults(conn, 2)
    assert result == {"applied": False, "model": MODEL, "denseConfigId": None, "sparseConfigId": 2}
    assert conn.scalar(sa.select(sa.func.count()).select_from(configs)) == 2
    assert (
        conn.scalar(sa.select(defaults.c.config_id).where(defaults.c.capability == "EMBEDDING"))
        == 1
    )


def test_apply_is_idempotent_and_preserves_existing_configs_and_bindings(connection):
    conn, configs, defaults, bindings = connection
    original = conn.execute(sa.select(configs).order_by(configs.c.id)).all()
    first = configure_defaults(conn, 2, apply=True)
    second = configure_defaults(conn, 2, apply=True)
    assert first == second
    assert conn.scalar(sa.select(sa.func.count()).select_from(configs)) == 3
    assert (
        conn.execute(
            sa.select(configs).where(configs.c.id.in_([1, 2])).order_by(configs.c.id)
        ).all()
        == original
    )
    assert conn.execute(
        sa.select(bindings.c.dense_embedding_config_id, bindings.c.sparse_embedding_config_id)
    ).one() == (1, 2)
    dense = (
        conn.execute(sa.select(configs).where(configs.c.id == first["denseConfigId"]))
        .mappings()
        .one()
    )
    assert dense["protocol"] == PROTOCOL
    assert dense["api_key"] == "synthetic-ciphertext"
    assert (
        conn.scalar(sa.select(defaults.c.config_id).where(defaults.c.capability == "EMBEDDING"))
        == dense["id"]
    )


@pytest.mark.parametrize(
    "field,value", [("scope", "USER"), ("is_active", 0), ("protocol", "openai")]
)
def test_rejects_invalid_sparse_source(connection, field, value):
    conn, configs, defaults, bindings = connection
    conn.execute(configs.update().where(configs.c.id == 2).values(**{field: value}))
    with pytest.raises(ValueError, match="active SYSTEM"):
        configure_defaults(conn, 2, apply=True)
    assert conn.scalar(sa.select(sa.func.count()).select_from(configs)) == 2


def test_rejects_conflicting_dense_without_mutating_it(connection):
    conn, configs, defaults, bindings = connection
    conn.execute(configs.update().where(configs.c.id == 1).values(model_name=MODEL))
    with pytest.raises(ValueError, match="refusing to mutate"):
        configure_defaults(conn, 2, apply=True)
    assert conn.scalar(sa.select(configs.c.protocol).where(configs.c.id == 1)) == "openai"
    assert (
        conn.scalar(sa.select(defaults.c.config_id).where(defaults.c.capability == "EMBEDDING"))
        == 1
    )
