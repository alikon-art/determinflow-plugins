#!/usr/bin/env python3
"""上下文裁剪后处理：读减法列表 + 原始数据 → 裁剪 → 输出。

用法:
  # 世界裁剪
  python trimmer_post.py --world-json cache/sync/world.json \
      --subtract cache/trimmer/subtract.json \
      --output cache/trimmer/trimmed_world.json

  # 世界 + 角色裁剪
  python trimmer_post.py --world-json cache/sync/world.json \
      --characters-json cache/sync/characters.json \
      --subtract cache/trimmer/subtract.json \
      --output cache/trimmer/trimmed_world.json \
      --output-characters cache/trimmer/trimmed_characters.json
"""

import argparse
import json
import os


def deep_copy(obj):
    return json.loads(json.dumps(obj))


def trim_world(world, subtract):
    """世界裁剪：按 subtract 中的维度→字段列表删二级字段。"""
    trimmed = deep_copy(world)
    removed = 0
    for dim, fields in subtract.items():
        if dim == "characters":
            continue  # 角色裁剪单独处理
        if dim in trimmed and isinstance(trimmed[dim], dict):
            for field in fields:
                if field in trimmed[dim]:
                    del trimmed[dim][field]
                    removed += 1
    return trimmed, removed


def trim_characters(characters, subtract):
    """角色裁剪：按 subtract.characters 中的名字列表移除角色。"""
    names_to_remove = set(subtract.get("characters", []))
    if not names_to_remove:
        return characters, 0

    chars_list = characters.get("characters", [])
    kept = [c for c in chars_list if c.get("name") not in names_to_remove]
    removed = len(chars_list) - len(kept)
    return {"characters": kept}, removed


def main():
    parser = argparse.ArgumentParser(description="上下文裁剪后处理")
    parser.add_argument("--world-json", default=None, help="原始 world.json（6 维度合并）")
    parser.add_argument("--characters-json", default=None, help="原始角色 JSON")
    parser.add_argument("--subtract", required=True, help="trimmer 产出的减法列表 JSON")
    parser.add_argument("--output", default=None, help="世界裁剪后输出路径")
    parser.add_argument("--output-characters", default=None, help="角色裁剪后输出路径")
    args = parser.parse_args()

    with open(args.subtract, "r", encoding="utf-8") as f:
        subtract = json.load(f)

    # 世界裁剪
    if args.world_json and args.output:
        with open(args.world_json, "r", encoding="utf-8") as f:
            world = json.load(f)
        trimmed_world, w_removed = trim_world(world, subtract)

        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(trimmed_world, f, ensure_ascii=False, indent=2)

        def count_fields(d):
            return sum(len(v) if isinstance(v, dict) else 1 for v in d.values() if v is not None)

        print(f"[OK] world: {args.world_json} → {args.output} "
              f"({count_fields(world)}→{count_fields(trimmed_world)} fields, removed {w_removed})")

    # 角色裁剪
    if args.characters_json and args.output_characters:
        if not os.path.exists(args.characters_json):
            print(f"[SKIP] characters_json not found: {args.characters_json}（sync_down 未产出，跳过角色裁剪）")
        else:
            with open(args.characters_json, "r", encoding="utf-8") as f:
                characters = json.load(f)
            trimmed_chars, c_removed = trim_characters(characters, subtract)

            os.makedirs(os.path.dirname(args.output_characters) or ".", exist_ok=True)
            with open(args.output_characters, "w", encoding="utf-8") as f:
                json.dump(trimmed_chars, f, ensure_ascii=False, indent=2)

            orig_count = len(characters.get("characters", []))
            final_count = len(trimmed_chars.get("characters", []))
            print(f"[OK] characters: {args.characters_json} → {args.output_characters} "
                  f"({orig_count}→{final_count} characters, removed {c_removed})")

    if not (args.output or args.output_characters):
        print("[ERROR] 至少需要 --output 或 --output-characters 之一", flush=True)
        exit(1)


if __name__ == "__main__":
    main()
