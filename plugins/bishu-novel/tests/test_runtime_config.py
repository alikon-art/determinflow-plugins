from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from ai_company_plugin_bishu_novel.backend import config, extension
from ai_company_plugin_bishu_novel.backend.novel import db


def test_backend_config_prefers_runtime_settings_over_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENGINE_SIGN_ENABLED", "false")
    monkeypatch.setenv("ENGINE_SIGN_MODE", "observe")
    monkeypatch.setenv("ENGINE_SIGN_KEYS", "environment:environment-secret")
    monkeypatch.setenv("ENGINE_SIGN_CLOCK_SKEW_SECONDS", "10")
    monkeypatch.setenv("ENGINE_SIGN_NONCE_TTL_SECONDS", "20")

    config.configure({
        "ENGINE_SIGN_ENABLED": True,
        "ENGINE_SIGN_MODE": "enforce",
        "ENGINE_SIGN_KEYS": f"runtime:{'r' * 32}",
        "ENGINE_SIGN_CLOCK_SKEW_SECONDS": 120,
        "ENGINE_SIGN_NONCE_TTL_SECONDS": 180,
    })

    assert config.ENGINE_SIGN_ENABLED is True
    assert config.ENGINE_SIGN_MODE == "enforce"
    assert config.get_engine_signing_keys() == {"runtime": "r" * 32}
    assert config.ENGINE_SIGN_CLOCK_SKEW_SECONDS == 120
    assert config.ENGINE_SIGN_NONCE_TTL_SECONDS == 180


def test_backend_config_uses_environment_as_fallback(monkeypatch) -> None:
    monkeypatch.setenv("ENGINE_SIGN_ENABLED", "true")
    monkeypatch.setenv("ENGINE_SIGN_MODE", "enforce")
    monkeypatch.setenv("ENGINE_SIGN_KEYS", f"environment:{'e' * 32}")
    monkeypatch.setenv("ENGINE_SIGN_CLOCK_SKEW_SECONDS", "240")
    monkeypatch.delenv("ENGINE_SIGN_NONCE_TTL_SECONDS", raising=False)

    config.configure({})

    assert config.ENGINE_SIGN_ENABLED is True
    assert config.ENGINE_SIGN_MODE == "enforce"
    assert config.get_engine_signing_keys() == {"environment": "e" * 32}
    assert config.ENGINE_SIGN_CLOCK_SKEW_SECONDS == 240
    assert config.ENGINE_SIGN_NONCE_TTL_SECONDS == 300


def test_backend_config_uses_signing_keys_file_as_fallback(
    monkeypatch,
    tmp_path,
) -> None:
    signing_keys_file = tmp_path / "engine-sign-keys"
    signing_keys_file.write_text(
        f"file-key:{'f' * 32}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENGINE_SIGN_ENABLED", "true")
    monkeypatch.setenv("ENGINE_SIGN_MODE", "enforce")
    monkeypatch.delenv("ENGINE_SIGN_KEYS", raising=False)
    monkeypatch.setenv("ENGINE_SIGN_KEYS_FILE", str(signing_keys_file))

    config.configure({})
    config.validate_engine_signing_config()

    assert config.get_engine_signing_keys() == {"file-key": "f" * 32}


def test_backend_config_prefers_environment_signing_keys_over_file(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("ENGINE_SIGN_KEYS", f"environment:{'e' * 32}")
    monkeypatch.setenv(
        "ENGINE_SIGN_KEYS_FILE",
        str(tmp_path / "missing-signing-keys"),
    )

    config.configure({})

    assert config.get_engine_signing_keys() == {"environment": "e" * 32}


def test_database_helper_prefers_runtime_settings_over_environment(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakePool:
        async def close(self) -> None:
            return None

    async def fake_create_pool(**kwargs):
        captured.update(kwargs)
        return FakePool()

    monkeypatch.setenv("DB_HOST", "environment-host")
    monkeypatch.setenv("DB_PORT", "15432")
    monkeypatch.setenv("DB_NAME", "environment-db")
    monkeypatch.setenv("DB_USER", "environment-user")
    monkeypatch.setenv("DB_PASSWORD", "environment-password")
    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)

    db.configure({
        "DB_HOST": "runtime-host",
        "DB_PORT": 25432,
        "DB_NAME": "runtime-db",
        "DB_USER": "runtime-user",
        "DB_PASSWORD": "runtime-password",  # pragma: allowlist secret
    })
    asyncio.run(db.get_pool())
    asyncio.run(db.close_pool())

    assert "runtime-password" not in repr(db._current_settings())
    assert captured == {
        "host": "runtime-host",
        "port": 25432,
        "database": "runtime-db",
        "user": "runtime-user",
        "password": "runtime-password",  # pragma: allowlist secret
        "min_size": 2,
        "max_size": 10,
    }


def test_database_helper_uses_environment_as_fallback(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePool:
        async def close(self) -> None:
            return None

    async def fake_create_pool(**kwargs):
        captured.update(kwargs)
        return FakePool()

    monkeypatch.setenv("DB_HOST", "environment-host")
    monkeypatch.setenv("DB_PORT", "15432")
    monkeypatch.setenv("DB_NAME", "environment-db")
    monkeypatch.setenv("DB_USER", "environment-user")
    monkeypatch.setenv("DB_PASSWORD", "environment-password")
    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)

    db.configure({})
    asyncio.run(db.get_pool())
    asyncio.run(db.close_pool())

    assert captured == {
        "host": "environment-host",
        "port": 15432,
        "database": "environment-db",
        "user": "environment-user",
        "password": "environment-password",  # pragma: allowlist secret
        "min_size": 2,
        "max_size": 10,
    }


def test_database_helper_uses_password_file_as_fallback(
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}
    password_file = tmp_path / "db-password"
    password_file.write_text("file-password\n", encoding="utf-8")

    class FakePool:
        async def close(self) -> None:
            return None

    async def fake_create_pool(**kwargs):
        captured.update(kwargs)
        return FakePool()

    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setenv("DB_PASSWORD_FILE", str(password_file))
    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)

    db.configure({})
    asyncio.run(db.get_pool())
    asyncio.run(db.close_pool())

    assert captured["password"] == "file-password"  # pragma: allowlist secret


def test_extension_start_wires_owner_plugin_config(monkeypatch) -> None:
    plugin_config = {
        "DB_HOST": "runtime-host",
        "ENGINE_SIGN_ENABLED": False,
    }
    configured: list[tuple[str, object]] = []

    monkeypatch.setattr(
        extension.backend_config,
        "configure",
        lambda settings: configured.append(("backend", settings)),
    )
    monkeypatch.setattr(
        extension.database,
        "configure",
        lambda settings: configured.append(("database", settings)),
    )
    monkeypatch.setattr(
        extension.backend_config,
        "validate_engine_signing_config",
        lambda: None,
    )
    monkeypatch.setattr(
        extension,
        "configure_resource_resolver",
        lambda resolver: configured.append(("resource_resolver", resolver)),
    )

    async def cleanup_zombie_jobs() -> None:
        return None

    monkeypatch.setattr(
        extension.job_service,
        "cleanup_zombie_jobs",
        cleanup_zombie_jobs,
    )

    def resolver(*_args, **_kwargs):
        return "resolved-resource"

    runtime = SimpleNamespace(
        workflow_runtime=object(),
        resolve_resource=resolver,
        get_service=lambda name, default=None: (
            plugin_config if name == "plugin_config" else default
        ),
    )

    asyncio.run(extension.BishuNovelExtension().start(runtime))

    assert configured == [
        ("backend", plugin_config),
        ("database", plugin_config),
        ("resource_resolver", resolver),
    ]


def test_extension_rejects_core_without_public_resource_resolver() -> None:
    runtime = SimpleNamespace(get_service=lambda _name, default=None: default)

    with pytest.raises(
        RuntimeError,
        match=r"CoreRuntime\.resolve_resource",
    ):
        extension._require_resource_resolver(runtime)


def test_runtime_secret_is_not_logged(caplog) -> None:
    secret = "do-not-log-this-secret-value-1234"  # pragma: allowlist secret
    caplog.set_level(logging.INFO)

    config.configure({
        "ENGINE_SIGN_ENABLED": True,
        "ENGINE_SIGN_MODE": "enforce",
        "ENGINE_SIGN_KEYS": f"runtime:{secret}",
    })
    config.validate_engine_signing_config()

    assert secret not in caplog.text


def test_database_start_failure_does_not_log_runtime_secret(
    monkeypatch,
    caplog,
) -> None:
    secret = "database-secret-that-must-not-appear"  # pragma: allowlist secret

    async def cleanup_zombie_jobs() -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(
        extension.job_service,
        "cleanup_zombie_jobs",
        cleanup_zombie_jobs,
    )
    caplog.set_level(logging.WARNING)
    runtime = SimpleNamespace(
        workflow_runtime=object(),
        resolve_resource=lambda *_args, **_kwargs: "resolved-resource",
        get_service=lambda name, default=None: (
            {
                "DB_PASSWORD": secret,
                "ENGINE_SIGN_ENABLED": False,
            }
            if name == "plugin_config"
            else default
        ),
    )

    with pytest.raises(RuntimeError, match="Novel 数据库不可用: RuntimeError"):
        asyncio.run(extension.BishuNovelExtension().start(runtime))

    assert secret not in caplog.text
