"""Database pool helpers for the novel production API."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

import asyncpg

from ..secret_files import read_secret


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str


_db_pool: asyncpg.Pool | None = None
_db_pool_loop: asyncio.AbstractEventLoop | None = None
_database_settings: DatabaseSettings | None = None


def _setting(
    settings: Mapping[str, object],
    name: str,
    default: object,
) -> object:
    if name in settings:
        return settings[name]
    return os.getenv(name, default)


def _string(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{name} 必须是 string")
    return value


def configure(settings: Mapping[str, object] | None = None) -> None:
    """Apply owner-scoped database settings with environment fallback."""
    if settings is None:
        settings = {}
    if not isinstance(settings, Mapping):
        raise RuntimeError("plugin_config 必须是 object")
    port_value = _setting(settings, "DB_PORT", 5432)
    if isinstance(port_value, bool):
        raise RuntimeError("DB_PORT 必须是 integer")
    if isinstance(port_value, int):
        port = port_value
    elif isinstance(port_value, str):
        try:
            port = int(port_value)
        except ValueError as exc:
            raise RuntimeError("DB_PORT 必须是 integer") from exc
    else:
        raise RuntimeError("DB_PORT 必须是 integer")

    global _database_settings
    _database_settings = DatabaseSettings(
        host=_string("DB_HOST", _setting(settings, "DB_HOST", "127.0.0.1")),
        port=port,
        user=_string("DB_USER", _setting(settings, "DB_USER", "postgres")),
        password=_string(
            "DB_PASSWORD",
            settings["DB_PASSWORD"]
            if "DB_PASSWORD" in settings
            else read_secret("DB_PASSWORD"),
        ),
        database=_string(
            "DB_NAME",
            _setting(settings, "DB_NAME", "novel_platform"),
        ),
    )


def _current_settings() -> DatabaseSettings:
    if _database_settings is None:
        configure({})
    assert _database_settings is not None
    return _database_settings


async def get_pool() -> asyncpg.Pool:
    global _db_pool, _db_pool_loop
    current_loop = asyncio.get_running_loop()
    if _db_pool is None or _db_pool_loop is not current_loop:
        settings = _current_settings()
        _db_pool = await asyncpg.create_pool(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.database,
            min_size=2,
            max_size=10,
        )
        _db_pool_loop = current_loop
    return _db_pool


async def close_pool() -> None:
    global _db_pool, _db_pool_loop
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
        _db_pool_loop = None
