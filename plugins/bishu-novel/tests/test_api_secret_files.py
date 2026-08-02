from __future__ import annotations

from pathlib import Path

import pytest

from ai_company_plugin_bishu_novel.backend.secret_files import (
    SecretLoadError,
    read_secret,
)


def test_read_secret_uses_file_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "db-password"
    password_file.write_text("bishu-novel-secret\n", encoding="utf-8")
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setenv("DB_PASSWORD_FILE", str(password_file))

    assert read_secret("DB_PASSWORD") == "bishu-novel-secret"


def test_read_secret_prefers_inline_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DB_PASSWORD", "inline-secret")
    monkeypatch.setenv("DB_PASSWORD_FILE", str(tmp_path / "missing"))

    assert read_secret("DB_PASSWORD") == "inline-secret"


def test_read_secret_rejects_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.write_text("must-not-be-read\n", encoding="utf-8")
    link = tmp_path / "db-password"
    link.symlink_to(target)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setenv("DB_PASSWORD_FILE", str(link))

    with pytest.raises(SecretLoadError, match="unreadable"):
        read_secret("DB_PASSWORD")
