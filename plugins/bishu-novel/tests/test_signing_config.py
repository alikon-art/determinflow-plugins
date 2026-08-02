import pytest

from ai_company_plugin_bishu_novel.backend import config


def test_enforce_signing_requires_256_bit_secret(monkeypatch) -> None:
    monkeypatch.setattr(config, "ENGINE_SIGN_ENABLED", True)
    monkeypatch.setattr(config, "ENGINE_SIGN_MODE", "enforce")
    monkeypatch.setattr(config, "ENGINE_SIGN_KEYS", "portal:too-short")

    with pytest.raises(RuntimeError, match="至少 32 bytes"):
        config.validate_engine_signing_config()


def test_enforce_signing_accepts_strong_unique_secrets(monkeypatch) -> None:
    monkeypatch.setattr(config, "ENGINE_SIGN_ENABLED", True)
    monkeypatch.setattr(config, "ENGINE_SIGN_MODE", "enforce")
    monkeypatch.setattr(
        config,
        "ENGINE_SIGN_KEYS",
        f"current:{'a' * 32},previous:{'b' * 32}",
    )

    config.validate_engine_signing_config()


def test_signing_rejects_duplicate_key_ids(monkeypatch) -> None:
    monkeypatch.setattr(config, "ENGINE_SIGN_ENABLED", True)
    monkeypatch.setattr(config, "ENGINE_SIGN_MODE", "enforce")
    monkeypatch.setattr(
        config,
        "ENGINE_SIGN_KEYS",
        f"duplicate:{'a' * 32},duplicate:{'b' * 32}",
    )

    with pytest.raises(RuntimeError, match="重复 key id"):
        config.validate_engine_signing_config()
