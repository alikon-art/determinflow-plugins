from __future__ import annotations

import importlib
import json
import tomllib
from pathlib import Path

from src.extension_host.lifecycle import load_extension_lifecycle
from src.extension_host.manifest import parse_extension_manifest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MIGRATIONS = {
    "20260601_novel_api_baseline.sql",
    "20260609_product_schema.sql",
    "20260613_book_scale_params.sql",
    "20260613_book_soft_delete.sql",
    "20260720_novel_runtime_schema.sql",
}
UNSUPPORTED_SCHEMA_KEYS = {"additionalProperties", "minLength", "writeOnly"}


def _schema_keys(schema: dict) -> set[str]:
    keys = set(schema)
    for child in schema.get("properties", {}).values():
        keys.update(_schema_keys(child))
    return keys


def test_manifest_backend_and_settings_are_portable() -> None:
    manifest = tomllib.loads(
        (PLUGIN_ROOT / "extension.toml").read_text(encoding="utf-8")
    )
    extension = manifest["extension"]
    assert extension["id"] == "bishu-novel"
    assert extension["version"] == "0.1.0"
    assert manifest["resource_namespace"]["prefix"] == "bishu-novel"
    assert (
        extension["backend"]
        == "ai_company_plugin_bishu_novel.backend.extension:create_extension"
    )
    assert extension["dependencies"] == []
    assert manifest["settings"]["schema"] == "settings.schema.json"
    assert manifest["installation"]["requirements"] == "requirements.txt"
    assert (PLUGIN_ROOT / manifest["installation"]["requirements"]).is_file()
    lifecycle = manifest["lifecycle"]
    expected_module = (
        "ai_company_plugin_bishu_novel.backend.migrations_cli"
    )
    assert lifecycle["migrate_command"] == [
        "${PYTHON}",
        "-m",
        expected_module,
        "migrate",
        "--release-revision",
        "${PLUGIN_REVISION}",
    ]
    assert lifecycle["verify_command"] == [
        "${PYTHON}",
        "-m",
        expected_module,
        "verify",
        "--release-revision",
        "${PLUGIN_REVISION}",
    ]
    assert lifecycle["working_directory"] == "."
    assert lifecycle["timeout_seconds"] == 300

    schema = json.loads(
        (PLUGIN_ROOT / "settings.schema.json").read_text(encoding="utf-8")
    )
    assert schema["type"] == "object"
    assert {
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "AI_DETECT_GATEWAY_URL",
        "ENGINE_SIGN_ENABLED",
        "ENGINE_SIGN_MODE",
        "ENGINE_SIGN_KEYS",
        "ENGINE_SIGN_CLOCK_SKEW_SECONDS",
        "ENGINE_SIGN_NONCE_TTL_SECONDS",
    } <= set(schema["properties"])
    assert not (_schema_keys(schema) & UNSUPPORTED_SCHEMA_KEYS)
    assert schema["properties"]["DB_PASSWORD"]["format"] == "password"
    assert schema["properties"]["ENGINE_SIGN_KEYS"]["format"] == "password"


def test_manifest_lifecycle_matches_core_contract() -> None:
    manifest_path = PLUGIN_ROOT / "extension.toml"

    parsed = parse_extension_manifest(manifest_path)
    lifecycle = load_extension_lifecycle(manifest_path)

    assert parsed.extension_id == "bishu-novel"
    assert parsed.version == "0.1.0"
    assert lifecycle is not None
    assert lifecycle.migrate_command[-2:] == (
        "--release-revision",
        "${PLUGIN_REVISION}",
    )
    assert lifecycle.migrate_command[3] == "migrate"
    assert lifecycle.verify_command[3] == "verify"
    assert lifecycle.timeout_seconds == 300


def test_package_imports_from_an_arbitrary_checkout() -> None:
    module = importlib.import_module(
        "ai_company_plugin_bishu_novel.backend.extension"
    )
    extension = module.create_extension()
    assert extension.manifest.extension_id == "bishu-novel"


def test_only_declared_migrations_are_owned() -> None:
    migration_root = PLUGIN_ROOT / "resources" / "migrations"
    assert {path.name for path in migration_root.glob("*.sql")} == EXPECTED_MIGRATIONS


def test_old_monorepo_imports_and_platform_deployment_assets_are_absent() -> None:
    legacy_import = ".".join(("extensions", "novel_api"))
    legacy_path = "/".join(("extensions", "novel_api"))
    for path in PLUGIN_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        content = path.read_text(encoding="utf-8")
        assert legacy_import not in content
        assert legacy_path not in content

    assert not (PLUGIN_ROOT / "compose.yml").exists()
    assert not (PLUGIN_ROOT / "compose.prod.yml").exists()
    assert not (PLUGIN_ROOT / "deploy.sh").exists()
    assert not (PLUGIN_ROOT / "nginx").exists()
