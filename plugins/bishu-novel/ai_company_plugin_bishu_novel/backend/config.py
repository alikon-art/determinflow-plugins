"""Runtime configuration owned by the Novel API extension."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from .secret_files import read_secret

logger = logging.getLogger(__name__)


ENGINE_SIGN_ENABLED = False
ENGINE_SIGN_MODE = "observe"
ENGINE_SIGN_KEYS = ""
ENGINE_SIGN_CLOCK_SKEW_SECONDS = 300
ENGINE_SIGN_NONCE_TTL_SECONDS = 360


def _setting(
    settings: Mapping[str, object],
    name: str,
    default: object,
) -> object:
    if name in settings:
        return settings[name]
    return os.getenv(name, default)


def _boolean(name: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise RuntimeError(f"{name} 必须是 boolean")


def _integer(name: str, value: object) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"{name} 必须是 integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise RuntimeError(f"{name} 必须是 integer") from exc
    raise RuntimeError(f"{name} 必须是 integer")


def _string(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{name} 必须是 string")
    return value


def configure(settings: Mapping[str, object] | None = None) -> None:
    """Apply owner-scoped plugin settings, using environment variables as fallback."""
    if settings is None:
        settings = {}
    if not isinstance(settings, Mapping):
        raise RuntimeError("plugin_config 必须是 object")

    enabled = _boolean(
        "ENGINE_SIGN_ENABLED",
        _setting(settings, "ENGINE_SIGN_ENABLED", False),
    )
    mode = _string(
        "ENGINE_SIGN_MODE",
        _setting(settings, "ENGINE_SIGN_MODE", "observe"),
    )
    keys = _string(
        "ENGINE_SIGN_KEYS",
        settings["ENGINE_SIGN_KEYS"]
        if "ENGINE_SIGN_KEYS" in settings
        else read_secret("ENGINE_SIGN_KEYS"),
    )
    clock_skew = _integer(
        "ENGINE_SIGN_CLOCK_SKEW_SECONDS",
        _setting(settings, "ENGINE_SIGN_CLOCK_SKEW_SECONDS", 300),
    )
    nonce_ttl = _integer(
        "ENGINE_SIGN_NONCE_TTL_SECONDS",
        _setting(
            settings,
            "ENGINE_SIGN_NONCE_TTL_SECONDS",
            clock_skew + 60,
        ),
    )

    global ENGINE_SIGN_ENABLED
    global ENGINE_SIGN_MODE
    global ENGINE_SIGN_KEYS
    global ENGINE_SIGN_CLOCK_SKEW_SECONDS
    global ENGINE_SIGN_NONCE_TTL_SECONDS
    ENGINE_SIGN_ENABLED = enabled
    ENGINE_SIGN_MODE = mode
    ENGINE_SIGN_KEYS = keys
    ENGINE_SIGN_CLOCK_SKEW_SECONDS = clock_skew
    ENGINE_SIGN_NONCE_TTL_SECONDS = nonce_ttl


def get_engine_signing_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for pair in ENGINE_SIGN_KEYS.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        key_id, secret = pair.split(":", 1)
        if key_id.strip() and secret.strip():
            keys[key_id.strip()] = secret.strip()
    return keys


def validate_engine_signing_config() -> None:
    if not ENGINE_SIGN_ENABLED:
        return
    if ENGINE_SIGN_MODE not in {"observe", "enforce"}:
        raise RuntimeError(f"ENGINE_SIGN_MODE 必须是 observe 或 enforce，当前: {ENGINE_SIGN_MODE}")

    raw_pairs = [pair.strip() for pair in ENGINE_SIGN_KEYS.split(",")]
    if not raw_pairs or any(not pair or ":" not in pair for pair in raw_pairs):
        raise RuntimeError("ENGINE_SIGN_ENABLED=true 但 ENGINE_SIGN_KEYS 格式无效")

    keys = get_engine_signing_keys()
    if len(keys) != len(raw_pairs):
        raise RuntimeError("ENGINE_SIGN_KEYS 包含空值或重复 key id")
    if ENGINE_SIGN_MODE == "enforce":
        weak_key_ids = [
            key_id
            for key_id, secret in keys.items()
            if len(secret.encode("utf-8")) < 32
        ]
        if weak_key_ids:
            raise RuntimeError(
                "ENGINE_SIGN_MODE=enforce 要求每个 HMAC 密钥至少 32 bytes: "
                + ", ".join(sorted(weak_key_ids))
            )
    logger.info("Novel API 签名验证已启用: mode=%s", ENGINE_SIGN_MODE)
