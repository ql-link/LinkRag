"""预览或设置豆包联合编码的 SYSTEM 默认配置；不修改已有 Dataset 绑定。

部署后在目标环境执行，默认只读预览，写入须明确 --apply。
0036 的历史种子保持固定，新安装和已有环境均使用此独立配置入口。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MODEL = "doubao-embedding-vision-251215"
PROTOCOL = "doubao_vision"


def configure_defaults(connection, sparse_config_id: int, *, apply: bool = False) -> dict:
    """复用目标库中的豆包密文；仅新增 dense 配置并更新 SYSTEM 默认指针。"""
    configs = sa.Table("llm_model_config", sa.MetaData(), autoload_with=connection)
    defaults = sa.Table("llm_capability_default", sa.MetaData(), autoload_with=connection)
    sparse = (
        connection.execute(sa.select(configs).where(configs.c.id == sparse_config_id))
        .mappings()
        .one_or_none()
    )
    if sparse is None or not (
        sparse["scope"] == "SYSTEM"
        and sparse["owner_user_id"] == 0
        and sparse["capability"] == "SPARSE_EMBEDDING"
        and sparse["is_active"]
        and sparse["model_name"] == MODEL
        and sparse["protocol"] == PROTOCOL
        and sparse["api_base_url"]
        and sparse["api_key"]
    ):
        raise ValueError("source must be an active SYSTEM doubao_vision sparse config")
    dense = (
        connection.execute(
            sa.select(configs).where(
                configs.c.scope == "SYSTEM",
                configs.c.owner_user_id == 0,
                configs.c.provider_id == sparse["provider_id"],
                configs.c.model_name == MODEL,
                configs.c.capability == "EMBEDDING",
            )
        )
        .mappings()
        .one_or_none()
    )
    if dense is not None:
        keys_match = dense["api_key"] == sparse["api_key"]
        if not keys_match:
            from src.core.llm.encryption import decrypt_api_key

            keys_match = decrypt_api_key(dense["api_key"]) == decrypt_api_key(sparse["api_key"])
        if not (
            dense["is_active"]
            and dense["protocol"] == PROTOCOL
            and dense["api_base_url"] == sparse["api_base_url"]
            and keys_match
        ):
            raise ValueError("existing dense config differs; refusing to mutate bound config")
    dense_id = int(dense["id"]) if dense is not None else None
    if apply:
        if dense_id is None:
            result = connection.execute(
                configs.insert().values(
                    scope="SYSTEM",
                    owner_user_id=0,
                    provider_id=sparse["provider_id"],
                    provider_type=sparse["provider_type"],
                    model_name=MODEL,
                    display_name="Doubao Dense",
                    capability="EMBEDDING",
                    protocol=PROTOCOL,
                    api_base_url=sparse["api_base_url"],
                    api_key=sparse["api_key"],
                    is_active=True,
                    snapshot_version=1,
                )
            )
            dense_id = int(result.inserted_primary_key[0])
        for capability, config_id in (
            ("EMBEDDING", dense_id),
            ("SPARSE_EMBEDDING", sparse_config_id),
        ):
            predicate = sa.and_(
                defaults.c.scope == "SYSTEM",
                defaults.c.owner_user_id == 0,
                defaults.c.capability == capability,
            )
            existing = connection.execute(
                sa.select(defaults.c.id).where(predicate)
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(
                    defaults.insert().values(
                        scope="SYSTEM",
                        owner_user_id=0,
                        capability=capability,
                        config_id=config_id,
                    )
                )
            else:
                connection.execute(defaults.update().where(predicate).values(config_id=config_id))
    # 不输出端点、密文、密钥或任何用户数据。
    return {
        "applied": apply,
        "model": MODEL,
        "denseConfigId": dense_id,
        "sparseConfigId": sparse_config_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sparse-config-id", type=int, required=True)
    parser.add_argument("--expected-app-env", choices=("development", "production"), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from src.config import settings

    if settings.APP_ENV != args.expected_app_env:
        parser.error("APP_ENV does not match the requested target")
    engine = sa.create_engine(settings.DATABASE_URL)
    try:
        with engine.begin() as connection:
            print(
                json.dumps(configure_defaults(connection, args.sparse_config_id, apply=args.apply))
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
