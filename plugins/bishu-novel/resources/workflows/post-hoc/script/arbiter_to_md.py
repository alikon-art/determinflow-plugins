#!/usr/bin/env python3
"""后验文件映射脚本。

1. 将 cache/arbiter/ 下的裁决 JSON 渲染为可读 Markdown 放到章节目录下
2. 将 cache/observer/diff_character.json 复制到章节目录下

用法:
  python arbiter-to-md.py --chapter-number 0001
"""

import argparse
import json
import os
import shutil
import sys


def _h(level: int, title: str) -> str:
    return f"{'#' * level} {title}"


def _p(text: str) -> str:
    return text.rstrip() + "\n"


def render_world(json_path: str, chapter: str) -> str:
    """渲染 diff_world_resolved.json → diff_world_resolved.md"""
    if not os.path.exists(json_path):
        print(f"[arbiter-to-md] 跳过：{json_path} 不存在", file=sys.stderr)
        return ""

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    lines = [
        _h(1, f"世界事实裁决 — 第{chapter}章"),
        "",
    ]

    if not entries:
        lines.append("本章未引入任何新地点、新势力、规则变更、世界级物品或世界事实冲突。")
        lines.append("")
        lines.append("（diff_world.json 所有字段均为空数组）")
        return "\n".join(lines) + "\n"

    # 按 verdict 分组
    groups = {"adopt": [], "pending": [], "conflict": []}
    for e in entries:
        groups.get(e["verdict"], []).append(e["fact"])

    for key, label in [("adopt", "已采纳"), ("pending", "待确认"), ("conflict", "冲突·需人工")]:
        if groups[key]:
            lines.append(_h(2, label))
            for fact in groups[key]:
                lines.append(f"- {fact}")
            lines.append("")

    return "\n".join(lines) + "\n"


def render_story(json_path: str, chapter: str) -> str:
    """渲染 diff_story_confirmed.json → diff_story_confirmed.md"""
    if not os.path.exists(json_path):
        print(f"[arbiter-to-md] 跳过：{json_path} 不存在", file=sys.stderr)
        return ""

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    lines = [
        _h(1, f"故事差异确认 — 第{chapter}章"),
        "",
    ]

    # 已落地
    landed = data.get("landed", [])
    lines.append(_h(2, "已落地"))
    if landed:
        for item in landed:
            lines.append(f"✓ {item['planned']} — {item.get('evidence', '')}")
    else:
        lines.append("（无）")
    lines.append("")

    # 未落地
    missed = data.get("missed", [])
    lines.append(_h(2, "未落地"))
    if missed:
        for item in missed:
            lines.append(f"✗ {item['planned']}")
            if item.get("note"):
                lines.append(f"  {item['note']}")
    else:
        lines.append("（无）")
    lines.append("")

    # 偏离
    deviated = data.get("deviated", [])
    lines.append(_h(2, "偏离"))
    if deviated:
        for item in deviated:
            judgment = item.get("judgment", "")
            lines.append(f"↻ 导演计划「{item['planned']}」→ 正文：{item['actual']}")
            lines.append(f"  判断：{judgment}。{item.get('reason', '')}")
    else:
        lines.append("（无）")
    lines.append("")

    # 计划外
    unplanned = data.get("unplanned", [])
    lines.append(_h(2, "计划外叙事"))
    if unplanned:
        for item in unplanned:
            lines.append(f"? {item['event']}")
            if item.get("suggestion"):
                lines.append(f"  {item['suggestion']}")
    else:
        lines.append("（无）")
    lines.append("")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="后验裁决器 JSON → Markdown 映射")
    parser.add_argument("--chapter-number", required=True, help="章节号（如 0001）")
    args = parser.parse_args()

    chapter = args.chapter_number

    # 映射
    written = 0
    for name, render_fn in [
        ("diff_world_resolved", render_world),
        ("diff_story_confirmed", render_story),
    ]:
        json_path = f"cache/arbiter/{name}.json"
        md_path = f"story/{chapter}/{name}.md"

        content = render_fn(json_path, chapter)
        if not content:
            continue

        os.makedirs(os.path.dirname(md_path) or ".", exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)
        written += 1

    # 复制 diff_character.json 到章节目录
    src = "cache/observer/diff_character.json"
    dst = f"story/{chapter}/diff_character.json"
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copy2(src, dst)
        print(f"[arbiter-to-md] 已复制 diff_character.json → story/{chapter}/", file=sys.stderr)
    else:
        print(f"[arbiter-to-md] 跳过：{src} 不存在", file=sys.stderr)

    print(f"[arbiter-to-md] 已生成 {written} 个 Markdown 文件 → story/{chapter}/", file=sys.stderr)


if __name__ == "__main__":
    main()
