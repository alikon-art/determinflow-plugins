#!/usr/bin/env python3
"""Manage Bishu's file-only workspace archive.

The current workflow workspace is the single source of truth. This helper only
validates, combines, renders, and indexes files below that workspace; it never
opens a database or creates an external identifier.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


WORLD_DIMENSIONS = (
    "core_laws",
    "space_time",
    "society",
    "history_culture",
    "existence",
    "information",
)
INDEX_PATHS = {
    "hooks": "archive/hooks.json",
    "debts": "archive/debts.json",
}


def _workspace_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"只允许工作区内相对路径: {raw_path}")
    workspace = Path.cwd().resolve()
    resolved = (workspace / path).resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"路径不能离开工作区: {raw_path}")
    return resolved


def _split_paths(raw_paths: str) -> list[str]:
    return [item.strip() for item in raw_paths.split(",") if item.strip()]


def _read_json(raw_path: str) -> Any:
    path = _workspace_path(raw_path)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(raw_path: str, value: Any) -> None:
    path = _workspace_path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_text(raw_path: str, value: str) -> None:
    path = _workspace_path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _require_files(raw_paths: str) -> None:
    missing = []
    empty = []
    for raw_path in _split_paths(raw_paths):
        path = _workspace_path(raw_path)
        if not path.is_file():
            missing.append(raw_path)
        elif path.stat().st_size == 0:
            empty.append(raw_path)
    if missing:
        raise FileNotFoundError("缺少本地存档文件: " + ", ".join(missing))
    if empty:
        raise ValueError("本地存档文件为空: " + ", ".join(empty))


def _normalize_chapter(raw_chapter: str) -> str:
    if not re.fullmatch(r"\d{1,6}", raw_chapter):
        raise ValueError("章节号必须是 1-6 位数字")
    return f"{int(raw_chapter):04d}"


def _ensure_indexes() -> None:
    for raw_path in INDEX_PATHS.values():
        path = _workspace_path(raw_path)
        if not path.exists():
            _write_json(raw_path, [])


def _merge_index(index_name: str, source_path: str) -> int:
    if not source_path:
        return 0
    source = _read_json(source_path)
    if not isinstance(source, list):
        raise ValueError(f"{source_path} 必须是数组")

    target_path = INDEX_PATHS[index_name]
    current = _read_json(target_path)
    if not isinstance(current, list):
        raise ValueError(f"{target_path} 必须是数组")

    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in current + source:
        if not isinstance(item, dict):
            raise ValueError(f"{index_name} 条目必须是对象")
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise ValueError(f"{index_name} 条目缺少 id")
        if item_id not in by_id:
            order.append(item_id)
        by_id[item_id] = {**by_id.get(item_id, {}), **item}

    _write_json(target_path, [by_id[item_id] for item_id in order])
    return len(source)


def _build_world_cache() -> None:
    combined: dict[str, Any] = {}
    missing = []
    for dimension in WORLD_DIMENSIONS:
        raw_path = f"world/{dimension}.json"
        path = _workspace_path(raw_path)
        if not path.is_file():
            missing.append(raw_path)
            continue
        data = _read_json(raw_path)
        combined[dimension] = (
            data.get(dimension, data) if isinstance(data, dict) else data
        )
    if missing:
        raise FileNotFoundError("世界观存档不完整: " + ", ".join(missing))
    _write_json("cache/sync/world.json", combined)


def _named_items(value: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    items = value.get(key, [])
    if not isinstance(items, list):
        return {}
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("character") or "").strip()
        if name:
            result[name] = item
    return result


def _build_character_cache() -> None:
    skeleton = _read_json("cache/character/skeleton.json")
    if not isinstance(skeleton, dict) or not isinstance(
        skeleton.get("characters"), list
    ):
        raise ValueError("cache/character/skeleton.json 缺少 characters 数组")

    beliefs_path = _workspace_path("cache/character/beliefs.json")
    voice_path = _workspace_path("cache/character/voice.json")
    beliefs = (
        _named_items(_read_json("cache/character/beliefs.json"), "beliefs")
        if beliefs_path.is_file()
        else {}
    )
    voices = (
        _named_items(_read_json("cache/character/voice.json"), "characters")
        if voice_path.is_file()
        else {}
    )

    characters = []
    for base in skeleton["characters"]:
        if not isinstance(base, dict):
            continue
        name = str(base.get("name", "")).strip()
        if not name:
            continue
        deep_path = _workspace_path(f"cache/character/{name}_deep.json")
        deep = _read_json(f"cache/character/{name}_deep.json") if deep_path.is_file() else {}
        characters.append(
            {
                **base,
                "belief": beliefs.get(name, {}),
                "deep": deep,
                "voice": voices.get(name, {}),
            }
        )
    if not characters:
        raise ValueError("角色本地存档中没有有效角色")
    _write_json("cache/sync/characters.json", {"characters": characters})


def _render_near_term_context() -> None:
    source_path = _workspace_path("cache/no/near_term.json")
    if source_path.is_file():
        data = _read_json("cache/no/near_term.json")
        chapters = data.get("chapters", []) if isinstance(data, dict) else []
        lines = ["# 近期大纲（世界引擎摘录）", ""]
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            lines.extend(
                [
                    f"## 第{chapter.get('number', '?')}章 · {chapter.get('title', '')}",
                    f"- 情节摘要：{chapter.get('summary', '')}",
                    f"- 世界时间推进：{chapter.get('time_advance', '')}",
                    "",
                ]
            )
        _write_text("cache/sync/near_term_we.md", "\n".join(lines))
        return

    outline_path = _workspace_path("outline/near_term_outline.md")
    if outline_path.is_file():
        _write_text(
            "cache/sync/near_term_we.md",
            outline_path.read_text(encoding="utf-8"),
        )


def _title(raw_path: str) -> str:
    stem = Path(raw_path).stem.replace("_", " ")
    return stem.strip().title() or "存档"


def _render_scalar(value: Any) -> str:
    if value is None or value == "":
        return "（空）"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _render_value(value: Any, level: int = 2) -> list[str]:
    lines: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            label = str(key).replace("_", " ")
            if isinstance(child, (dict, list)):
                lines.extend([f"{'#' * min(level, 6)} {label}", ""])
                lines.extend(_render_value(child, level + 1))
            else:
                lines.append(f"- {label}：{_render_scalar(child)}")
        return lines
    if isinstance(value, list):
        if not value:
            return ["（无）"]
        for index, child in enumerate(value, start=1):
            if isinstance(child, dict):
                label = child.get("name") or child.get("title") or child.get("id")
                lines.extend(
                    [
                        f"{'#' * min(level, 6)} {label or f'条目 {index}'}",
                        "",
                    ]
                )
                lines.extend(_render_value(child, level + 1))
            else:
                lines.append(f"- {_render_scalar(child)}")
        return lines
    return [_render_scalar(value)]


def _render_document(raw_path: str, value: Any) -> str:
    if Path(raw_path).name == "body.json" and isinstance(value, dict):
        return str(value.get("body", "")).rstrip() + "\n"
    lines = [f"# {_title(raw_path)}", ""]
    lines.extend(_render_value(value))
    return "\n".join(lines).rstrip() + "\n"


def _render_files(inputs: str, outputs: str) -> int:
    input_paths = _split_paths(inputs)
    output_paths = _split_paths(outputs)
    if len(input_paths) != len(output_paths):
        raise ValueError("--inputs 与 --outputs 数量必须一致")
    for input_path, output_path in zip(input_paths, output_paths, strict=True):
        data = _read_json(input_path)
        _write_text(output_path, _render_document(input_path, data))
    return len(input_paths)


def _render_indexes() -> None:
    _render_files(
        "archive/hooks.json,archive/debts.json",
        "meta/hooks.md,meta/debts.md",
    )


def _prepare(args: argparse.Namespace) -> None:
    if args.require:
        _require_files(args.require)
    _ensure_indexes()
    _render_indexes()
    if args.context:
        _build_world_cache()
        _build_character_cache()
        _render_near_term_context()


def _checkpoint(args: argparse.Namespace) -> None:
    if args.files:
        _require_files(args.files)
    changed = False
    if args.merge_hooks:
        _ensure_indexes()
        _merge_index("hooks", args.merge_hooks)
        changed = True
    if args.merge_debts:
        _ensure_indexes()
        _merge_index("debts", args.merge_debts)
        changed = True
    if changed:
        _render_indexes()


def _post_hoc(args: argparse.Namespace) -> None:
    chapter = _normalize_chapter(args.chapter)
    arbiter = _read_json("cache/arbiter/arb_output.json")
    observer = _read_json("cache/observer/obs_output.json")
    if not isinstance(arbiter, dict) or not isinstance(observer, dict):
        raise ValueError("后验输出必须是 JSON 对象")

    _write_json(
        f"story/{chapter}/diff_world_resolved.json",
        arbiter.get("world_rulings", {"entries": []}),
    )
    _write_json(
        f"story/{chapter}/diff_story_confirmed.json",
        arbiter.get(
            "story_confirmed",
            {"landed": [], "missed": [], "deviated": [], "unplanned": []},
        ),
    )
    _write_json(
        f"story/{chapter}/diff_character.json",
        observer.get("character_diff", {}),
    )

    _ensure_indexes()
    _write_json("archive/post_hoc_hooks.json", arbiter.get("new_hooks", []))
    _write_json("archive/post_hoc_debts.json", arbiter.get("new_debts", []))
    _merge_index("hooks", "archive/post_hoc_hooks.json")
    _merge_index("debts", "archive/post_hoc_debts.json")
    _render_indexes()


def _render(args: argparse.Namespace) -> None:
    _render_files(args.inputs, args.outputs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="笔枢纯本地存档工具")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="检查并准备本地工作区")
    prepare.add_argument("--require", default="", help="必须存在的相对文件，逗号分隔")
    prepare.add_argument("--context", action="store_true", help="构建章节生产上下文")
    prepare.set_defaults(handler=_prepare)

    checkpoint = commands.add_parser("checkpoint", help="校验并索引阶段产物")
    checkpoint.add_argument(
        "--files",
        default="",
        help="必须存在的相对文件，逗号分隔",
    )
    checkpoint.add_argument("--merge-hooks", default="", help="要合并的伏笔 JSON")
    checkpoint.add_argument("--merge-debts", default="", help="要合并的债务 JSON")
    checkpoint.set_defaults(handler=_checkpoint)

    render = commands.add_parser("render", help="将本地 JSON 渲染为 Markdown")
    render.add_argument("--inputs", required=True, help="输入 JSON，逗号分隔")
    render.add_argument("--outputs", required=True, help="输出 Markdown，逗号分隔")
    render.set_defaults(handler=_render)

    post_hoc = commands.add_parser("post-hoc", help="归档章节后验结果")
    post_hoc.add_argument("--chapter", required=True, help="章节号")
    post_hoc.set_defaults(handler=_post_hoc)
    return parser


def main() -> None:
    args = _parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
