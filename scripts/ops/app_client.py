"""接入应用凭证运维 CLI。

用法（在部署容器或已配置数据库环境变量的 shell 中执行）::

    python scripts/ops/app_client.py create linkresume --dense-config-id 10001 \\
        --sparse-config-id 10002 --description "Link Resume"
    python scripts/ops/app_client.py rotate-secret linkresume
    python scripts/ops/app_client.py disable linkresume
    python scripts/ops/app_client.py enable linkresume

``create`` / ``rotate-secret`` 仅在 stdout 输出一次 ``Authorization`` 凭证
``<client_id>.<secret>``，数据库只保存 bcrypt 哈希。轮换或停用后，各进程内的凭证缓存
最长 60 秒后失效。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.application import app_identity  # noqa: E402


async def _run(args: argparse.Namespace) -> None:
    if args.command == "create":
        client_id, secret = await app_identity.create_app_client(
            args.app_code,
            dense_config_id=args.dense_config_id,
            sparse_config_id=args.sparse_config_id,
            description=args.description,
        )
    elif args.command == "rotate-secret":
        client_id, secret = await app_identity.rotate_app_secret(args.app_code)
    else:
        status = "DISABLED" if args.command == "disable" else "ACTIVE"
        await app_identity.set_app_status(args.app_code, status)
        print(f"{args.app_code}: {status}")
        return
    print("Store this credential now; it will not be shown again:")
    print(f"{client_id}.{secret}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("app_code")
    create.add_argument("--dense-config-id", type=int, required=True)
    create.add_argument("--sparse-config-id", type=int, required=True)
    create.add_argument("--description")
    for name in ("rotate-secret", "disable", "enable"):
        sub.add_parser(name).add_argument("app_code")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
