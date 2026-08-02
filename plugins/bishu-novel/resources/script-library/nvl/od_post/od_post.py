#!/usr/bin/env python3
"""Split the novel-director output into deterministic downstream artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层必须是对象")
    return data


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()

    data = _read_json(args.input)
    guide = data.get("guide", {})
    hooks = data.get("hooks", [])
    debts = data.get("debts", [])
    if not isinstance(guide, dict):
        raise ValueError("guide 必须是对象")
    if not isinstance(hooks, list):
        raise ValueError("hooks 必须是数组")
    if not isinstance(debts, list):
        raise ValueError("debts 必须是数组")

    output_root = Path("cache/od")
    _write_json(output_root / "guide.json", guide)
    _write_json(output_root / "hooks.json", hooks)
    _write_json(output_root / "debts.json", debts)
    print(
        "[OK] guide.json + hooks.json "
        f"({len(hooks)}条) + debts.json ({len(debts)}条) → cache/od/"
    )


if __name__ == "__main__":
    main()
