"""CLI for explicit Novel API database migrations."""

from __future__ import annotations

import argparse
import asyncio
import os

import asyncpg

from .migration_runner import MigrationError, MigrationRunner
from .secret_files import SecretLoadError, read_secret


def _read_secret(name: str, *, fallback_name: str | None = None) -> str:
    try:
        value = read_secret(name)
        if value or fallback_name is None:
            return value
        return read_secret(fallback_name)
    except SecretLoadError as exc:
        raise MigrationError(str(exc)) from None


def _connection_options(family: str = "novel") -> dict:
    if family != "novel":
        raise MigrationError(f"unsupported migration family: {family}")
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "user": os.getenv("DB_USER", "postgres"),
        "password": _read_secret("DB_PASSWORD"),
        "database": os.getenv("DB_NAME", "novel_platform"),
    }


async def _run(args: argparse.Namespace) -> None:
    runner = MigrationRunner()
    connection = await asyncpg.connect(**_connection_options())
    try:
        if args.command == "adopt":
            changed = await runner.adopt(
                connection,
                "novel",
                release_revision=args.release_revision,
            )
        elif args.command == "migrate":
            changed = await runner.migrate(
                connection,
                "novel",
                release_revision=args.release_revision,
            )
        else:
            changed = await runner.verify(connection, "novel")
    finally:
        await connection.close()
    print(f"novel: {args.command} ok ({len(changed)} migrations)")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("adopt", "migrate", "verify"))
    parser.add_argument("--release-revision", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        asyncio.run(_run(args))
    except MigrationError as exc:
        print(f"migration rejected: {exc}", file=__import__("sys").stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
