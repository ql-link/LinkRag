"""LINK-91：稠密 embedder 按发起用户解析的单测。

覆盖「查配置 → 解密 api_key → create_client」范式与必配缺失语义：
- 用户无默认 EMBEDDING 配置 → DenseEmbeddingConfigMissingError。
- 命中用户配置 → 用用户的 provider/解密后的 key/base_url/model 构造 embedder。
- pipeline 解析复用用户模型名，并按用户 provider/model cap batch size。
"""

from __future__ import annotations

import pytest

import src.core.splitter.factory as factory
from src.core.splitter.factory import (
    DenseEmbeddingConfigMissingError,
    aresolve_user_chunk_embedding_pipeline,
    aresolve_user_embedding_client,
)


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSessionFactory:
    def __call__(self):
        return _FakeSession()


class _FakeEmbedder:
    def __init__(self, provider_type: str = "qwen") -> None:
        self.provider_type = provider_type

    def has_capability(self, _cap):
        return True


def _patch_session_factory(monkeypatch):
    monkeypatch.setattr("src.database.get_async_session_factory", lambda: _FakeSessionFactory())


def _patch_config_reader(monkeypatch, *, config):
    class _FakeConfigReader:
        def __init__(self, db):
            self.db = db

        async def get_user_default_config_by_capability(
            self, *, user_id, capability, use_cache=True
        ):
            assert capability == "EMBEDDING"
            return config

    monkeypatch.setattr(
        "src.services.config_reader_service.ConfigReaderService",
        lambda db: _FakeConfigReader(db),
    )


def _patch_resolver_model_factory(monkeypatch, created: dict | None = None):
    """patch 统一解析模块内的 ModelFactory 与 decrypt（解析逻辑已收敛到 user_model_resolver）。"""
    import src.core.llm.user_model_resolver as umr

    class _FakeMF:
        def create_client(self, **kwargs):
            if created is not None:
                created.update(kwargs)
            return _FakeEmbedder(provider_type=kwargs["provider_type"])

    monkeypatch.setattr(umr, "ModelFactory", lambda: _FakeMF())
    monkeypatch.setattr(umr, "decrypt_api_key", lambda enc: f"decrypted:{enc}")


@pytest.mark.asyncio
async def test_resolve_user_embedding_client_missing_config_raises(monkeypatch):
    _patch_session_factory(monkeypatch)
    _patch_config_reader(monkeypatch, config=None)

    with pytest.raises(DenseEmbeddingConfigMissingError) as exc_info:
        await aresolve_user_embedding_client(user_id=7)
    assert exc_info.value.user_id == 7


@pytest.mark.asyncio
async def test_resolve_user_embedding_client_uses_user_config(monkeypatch):
    _patch_session_factory(monkeypatch)
    _patch_config_reader(
        monkeypatch,
        config={
            "provider_type": "qwen",
            "api_key": "ENC",
            "api_base_url": "https://user.example/v1",
            "model_name": "user-embed-model",
        },
    )

    created: dict = {}
    _patch_resolver_model_factory(monkeypatch, created)

    embedder, model_name = await aresolve_user_embedding_client(user_id=7)

    assert model_name == "user-embed-model"
    assert created["provider_type"] == "qwen"
    # api_key 必须是解密后的明文，而不是库里的密文
    assert created["api_key"] == "decrypted:ENC"
    assert created["api_base_url"] == "https://user.example/v1"
    assert created["model_name"] == "user-embed-model"
    assert embedder.provider_type == "qwen"


@pytest.mark.asyncio
async def test_resolve_user_chunk_embedding_pipeline_uses_user_model_and_batch_cap(monkeypatch):
    _patch_session_factory(monkeypatch)
    _patch_config_reader(
        monkeypatch,
        config={
            "provider_type": "qwen",
            "api_key": "ENC",
            "api_base_url": None,
            # DashScope text-embedding-v4 已知单次上限 10
            "model_name": "text-embedding-v4",
        },
    )

    _patch_resolver_model_factory(monkeypatch)
    # 配置一个超过 DashScope 上限的 batch size，验证 cap 生效
    monkeypatch.setattr(factory.settings, "CHUNK_INDEX_EMBED_BATCH_SIZE", 32)

    pipeline = await aresolve_user_chunk_embedding_pipeline(user_id=7)

    assert pipeline.embedding_model == "text-embedding-v4"
    assert pipeline.batch_size == 10  # 被 provider 已知上限 cap 到 10
