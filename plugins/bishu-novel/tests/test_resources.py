from __future__ import annotations

import json
import tomllib
from pathlib import Path

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
    "json_to_md",
    "local_archive",
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


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_is_resource_only() -> None:
    manifest = tomllib.loads(
        (PLUGIN_ROOT / "extension.toml").read_text(encoding="utf-8")
    )
    assert manifest["extension"]["id"] == "bishu-novel"
    assert manifest["extension"]["version"] == "0.2.0"
    assert "backend" not in manifest["extension"]
    assert "installation" not in manifest
    assert "lifecycle" not in manifest
    assert "settings" not in manifest
    assert manifest["resource_namespace"]["prefix"] == "bishu-novel"
    assert set(manifest["resources"]) == {
        "agents",
        "prompts",
        "workflows",
        "script_libraries",
    }


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
        assert definition["version"] == 2
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


def test_workflows_do_not_require_database_or_book_ids() -> None:
    for definition_path in (
        PLUGIN_ROOT / "resources" / "workflows"
    ).glob("*/definition.json"):
        content = definition_path.read_text(encoding="utf-8").lower()
        assert "book_id" not in content
        assert "uuid" not in content
        assert "db_sync" not in content
        assert "json_to_db" not in content


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
