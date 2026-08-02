from __future__ import annotations

import json
import tomllib
from pathlib import Path

from ai_company_plugin_bishu_novel.backend.novel.schemas import (
    GenerateChapterRequest,
)


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WORKFLOWS = {
    "build",
    "character",
    "mvp",
    "outline",
    "polish",
    "post-hoc",
    "story-plan",
}
EXPECTED_SCRIPT_LIBRARIES = {
    "ai_detect",
    "cm_post",
    "db_sync",
    "json_to_db",
    "json_to_md",
    "no_post",
    "od_post",
    "parse_intent",
    "polish_post",
    "se_post",
    "si_post",
    "trimmer_post",
    "vo_post",
    "we_post",
}
UNSUPPORTED_SCHEMA_KEYS = {"additionalProperties", "minLength", "writeOnly"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_keys(schema: dict) -> set[str]:
    keys = set(schema)
    for child in schema.get("properties", {}).values():
        keys.update(_schema_keys(child))
    return keys


def test_manifest_and_settings_contract() -> None:
    manifest = tomllib.loads(
        (PLUGIN_ROOT / "extension.toml").read_text(encoding="utf-8")
    )
    assert manifest["extension"]["id"] == "bishu-novel"
    assert manifest["extension"]["version"] == "0.1.0"
    assert manifest["extension"]["backend"] == (
        "ai_company_plugin_bishu_novel.backend.extension:create_extension"
    )
    assert manifest["resource_namespace"]["prefix"] == "bishu-novel"
    assert set(manifest["resources"]) == {
        "agents",
        "prompts",
        "workflows",
        "script_libraries",
    }

    schema = _json(PLUGIN_ROOT / "settings.schema.json")
    assert schema["type"] == "object"
    assert {
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "AI_DETECT_GATEWAY_URL",
    } <= set(schema["properties"])
    assert not (_schema_keys(schema) & UNSUPPORTED_SCHEMA_KEYS)
    assert schema["properties"]["DB_PASSWORD"]["format"] == "password"
    assert "default" not in schema["properties"]["DB_PASSWORD"]
    assert "default" not in schema["properties"]["ENGINE_SIGN_KEYS"]


def test_resource_graph_contains_only_referenced_production_resources() -> None:
    resources = PLUGIN_ROOT / "resources"
    agents = _json(resources / "agents.json")["agents"]
    prompts = _json(resources / "prompts.json")["agents"]
    definitions = sorted((resources / "workflows").glob("*/definition.json"))

    assert {path.parent.name for path in definitions} == EXPECTED_WORKFLOWS
    assert len(agents) == 33
    assert set(prompts) == set(agents)

    referenced_agents: set[str] = set()
    referenced_libraries: set[str] = set()
    for definition_path in definitions:
        definition = _json(definition_path)
        assert definition["workflow_id"] == definition_path.parent.name
        assert definition["version"] == 1
        if definition["workflow_id"] == "mvp":
            assert not definition.get("execution_schemes")
        for node in definition.get("nodes", []):
            if node.get("node_type") == "agent":
                referenced_agents.add(node["agent_type"])
            params = node.get("node_params", {})
            if (
                node.get("node_type") == "script"
                and params.get("script_source") == "library"
            ):
                assert params["script_group"] == "nvl"
                referenced_libraries.add(params["script_name"])

    assert referenced_agents == set(agents)
    assert referenced_libraries == EXPECTED_SCRIPT_LIBRARIES
    library_root = resources / "script-library" / "nvl"
    assert {
        path.name
        for path in library_root.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    } == EXPECTED_SCRIPT_LIBRARIES


def test_chapter_api_exposes_only_production_controls() -> None:
    debug_fields = {
        "execution_mode",
        "execution_scheme_id",
        "selected_node_ids",
        "disabled_node_ids",
    }
    assert not (set(GenerateChapterRequest.model_fields) & debug_fields)


def test_public_package_has_no_private_pipeline_markers() -> None:
    forbidden = {
        "-".join(("nov" + "el", "tear" + "down")),
        "-".join(("hind" + "sight", "mem" + "ory")),
        "".join(("field_", "rewrite")),
        "".join(("pattern_", "usage_", "receipt")),
        "".join(("tear" + "down_", "pat" + "tern")),
        "拆" + "书",
    }
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file() or path.suffix in {".pyc", ".pyo"}:
            continue
        try:
            content = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for marker in forbidden:
            assert marker not in content, f"private marker in {path}"

    resources = PLUGIN_ROOT / "resources"
    assert not (PLUGIN_ROOT / "integration").exists()
    assert not (resources / "skills.json").exists()
    assert not (resources / "rules.json").exists()
    assert not (resources / "preset-phrases.json").exists()


def test_example_secrets_are_empty() -> None:
    values = {}
    for raw_line in (PLUGIN_ROOT / ".env.example").read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value

    assert values["DB_PASSWORD"] == ""
    assert values["ENGINE_SIGN_KEYS"] == ""
