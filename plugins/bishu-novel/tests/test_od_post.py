from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    PLUGIN_ROOT
    / "resources"
    / "script-library"
    / "nvl"
    / "od_post"
    / "od_post.py"
)


def test_od_post_writes_only_director_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "director.json"
    source.write_text(
        json.dumps(
            {
                "guide": {"title": "第一章"},
                "hooks": [{"id": "hook-1"}],
                "debts": [{"id": "debt-1"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output_root = tmp_path / "cache" / "od"
    assert json.loads((output_root / "guide.json").read_text(encoding="utf-8")) == {
        "title": "第一章"
    }
    assert json.loads((output_root / "hooks.json").read_text(encoding="utf-8")) == [
        {"id": "hook-1"}
    ]
    assert json.loads((output_root / "debts.json").read_text(encoding="utf-8")) == [
        {"id": "debt-1"}
    ]
    assert sorted(path.name for path in output_root.iterdir()) == [
        "debts.json",
        "guide.json",
        "hooks.json",
    ]
