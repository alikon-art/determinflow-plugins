from __future__ import annotations

import tomllib
from pathlib import Path

from src.extension_host.lifecycle import load_extension_lifecycle
from src.extension_host.manifest import parse_extension_manifest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_resource_only_manifest_is_portable() -> None:
    manifest = tomllib.loads(
        (PLUGIN_ROOT / "extension.toml").read_text(encoding="utf-8")
    )
    extension = manifest["extension"]
    assert extension["id"] == "bishu-novel"
    assert extension["version"] == "0.3.0"
    assert manifest["resource_namespace"]["prefix"] == "bishu-novel"
    assert "backend" not in extension
    assert extension["dependencies"] == []
    assert "settings" not in manifest
    assert "installation" not in manifest
    assert "lifecycle" not in manifest


def test_manifest_matches_core_resource_only_contract() -> None:
    manifest_path = PLUGIN_ROOT / "extension.toml"

    parsed = parse_extension_manifest(manifest_path)
    lifecycle = load_extension_lifecycle(manifest_path)

    assert parsed.extension_id == "bishu-novel"
    assert parsed.version == "0.3.0"
    assert parsed.backend == ""
    assert lifecycle is None


def test_old_monorepo_imports_and_platform_deployment_assets_are_absent() -> None:
    legacy_import = ".".join(("extensions", "novel_api"))
    legacy_path = "/".join(("extensions", "novel_api"))
    for path in PLUGIN_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        content = path.read_text(encoding="utf-8")
        assert legacy_import not in content
        assert legacy_path not in content

    assert not (PLUGIN_ROOT / "ai_company_plugin_bishu_novel").exists()
    assert not (PLUGIN_ROOT / "resources" / "migrations").exists()
    assert not (PLUGIN_ROOT / "settings.schema.json").exists()
    assert not (PLUGIN_ROOT / "requirements.txt").exists()
    assert not (PLUGIN_ROOT / "pyproject.toml").exists()
    assert not (PLUGIN_ROOT / "compose.yml").exists()
    assert not (PLUGIN_ROOT / "compose.prod.yml").exists()
    assert not (PLUGIN_ROOT / "deploy.sh").exists()
    assert not (PLUGIN_ROOT / "nginx").exists()
