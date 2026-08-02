from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PLUGIN_ROOT / "resources/script-library/nvl"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script_name", ["json_to_db", "db_sync"])
def test_database_scripts_read_password_file(
    script_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "db-password"
    password_file.write_text("workflow-database-secret\n", encoding="utf-8")
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setenv("DB_PASSWORD_FILE", str(password_file))
    module = _load_module(
        SCRIPT_ROOT / script_name / f"{script_name}.py",
        f"test_{script_name}",
    )
    captured: dict[str, object] = {}
    connection = object()

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(module.psycopg2, "connect", fake_connect)

    assert module.get_conn() is connection
    assert captured["password"] == "workflow-database-secret"  # pragma: allowlist secret


def test_inline_password_precedes_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_file = tmp_path / "missing"
    monkeypatch.setenv("DB_PASSWORD", "inline-secret")
    monkeypatch.setenv("DB_PASSWORD_FILE", str(missing_file))
    helper = _load_module(SCRIPT_ROOT / "_secret_files.py", "workflow_secrets")

    assert helper.read_secret("DB_PASSWORD") == "inline-secret"


def test_password_file_rejects_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.write_text("must-not-be-read\n", encoding="utf-8")
    link = tmp_path / "db-password"
    link.symlink_to(target)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setenv("DB_PASSWORD_FILE", str(link))
    helper = _load_module(SCRIPT_ROOT / "_secret_files.py", "unsafe_secrets")

    with pytest.raises(helper.SecretLoadError, match="unreadable"):
        helper.read_secret("DB_PASSWORD")
