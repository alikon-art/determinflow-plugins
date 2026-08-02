#!/usr/bin/env python3
"""将角色缓存 JSON 拼接为 character_profiles.md。

用法:
    python merge_characters.py --book-dir /path/to/book --output /path/to/character_profiles.md

产出:
    拼接后的 character_profiles.md
"""

import argparse
import json
import os
import sys


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, strict=False)


def _h(level: int, title: str) -> str:
    return f"{'#' * level} {title}"


def _p(text: str) -> str:
    return text.rstrip() + "\n"


def _table(rows: list[list[str]], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["------"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("\n", " ") for c in row) + " |")
    return "\n".join(lines)


def render_character(name: str, skeleton: dict, beliefs: list, deep: dict) -> str:
    """将单个角色的所有维度渲染为 Markdown section。"""
    parts = [_h(2, name)]

    # ── A 层：世界烙印 ──
    sk = skeleton
    parts.append(_h(3, "世界烙印"))
    wp = sk.get("world_position", {})
    wa = sk.get("world_anchor", {})

    parts.append(_h(4, "世界位置"))
    parts.append(f"- 出身阶层：{wp.get('origin_class', '—')}")
    parts.append(f"- 所属势力：{wp.get('affiliation', '—')}")
    parts.append(f"- 社会身份：{wp.get('social_role', '—')}")
    parts.append(f"- 对核心冲突的站位：{wp.get('stance_on_core_conflict', '—')}")

    parts.append(_h(4, "世界观锚点"))
    parts.append(f"- 体现的规则：{wa.get('embodies_rule', '—')}")
    parts.append(f"- 被塑造的规则：{wa.get('shaped_by_rule', '—')}")
    parts.append(f"- 可能挑战的规则：{wa.get('may_challenge_rule', '—')}")

    # ── B 层：内在构造 ──
    parts.append(_h(3, "内在构造"))
    b = next((b for b in beliefs if b.get("character") == name), {})
    parts.append(_h(4, "核心信念"))
    parts.append(f"- 信念：{b.get('core_belief', '—')}")
    parts.append(f"- 来源：{b.get('belief_source', '—')}")
    parts.append(f"- 作者视角：{b.get('author_perspective', '—')}")

    cd = deep.get("core_desire", {})
    parts.append(_h(4, "核心欲望"))
    parts.append(f"- 表层目标：{cd.get('surface_goal', '—')}")
    parts.append(f"- 深层欲望：{cd.get('deep_desire', '—')}")

    df = deep.get("deep_fear", {})
    parts.append(_h(4, "深层恐惧"))
    parts.append(f"- 恐惧：{df.get('fear', '—')}")
    parts.append(f"- 来源：{df.get('source', '—')}")

    sec = deep.get("secret", {})
    parts.append(_h(4, "秘密"))
    parts.append(f"- 内容：{sec.get('content', '—')}")
    who_knows = sec.get("who_knows", [])
    who_should = sec.get("who_doesnt_know_but_should", [])
    parts.append(f"- 谁知道：{', '.join(who_knows) if who_knows else '无人'}")
    parts.append(f"- 谁不知道但该知道：{', '.join(who_should) if who_should else '—'}")
    parts.append(f"- 暴露后果：{sec.get('exposure_consequence', '—')}")

    bl = deep.get("bottom_line", {})
    parts.append(_h(4, "不可触碰的底线"))
    parts.append(f"- 触犯条件：{bl.get('condition', '—')}")
    parts.append(f"- 来源：{bl.get('source', '—')}")
    parts.append(f"- 反应：{bl.get('reaction_when_crossed', '—')}")

    # ── C 层：创伤与矛盾 ──
    parts.append(_h(3, "创伤与矛盾"))
    kt = deep.get("key_trauma", {})
    parts.append(_h(4, "关键创伤"))
    parts.append(f"- 伤口：{kt.get('wound', '—')}")
    parts.append(f"- 触发条件：{kt.get('trigger', '—')}")
    parts.append(f"- 应激反应：{kt.get('stress_response', '—')}")
    parts.append(f"- 行为影响：{kt.get('impact_on_behavior', '—')}")

    ic = deep.get("internal_contradiction", {})
    parts.append(_h(4, "内在矛盾"))
    parts.append(f"- 冲突元素：{ic.get('conflicting_elements', '—')}")
    parts.append(f"- 来源：{ic.get('source', '—')}")
    parts.append(f"- 可能走向：{ic.get('possible_direction', '—')}")

    # ── D 层：人际与弧线 ──
    parts.append(_h(3, "人际与弧线"))
    rels = sk.get("relationships", [])
    if rels:
        parts.append(_h(4, "关系网络"))
        rows = []
        for r in rels:
            rows.append([
                r.get("target", ""),
                r.get("nature", ""),
                r.get("meaning_to_character", ""),
                r.get("hidden_tension", ""),
                r.get("default_attitude", ""),
            ])
        parts.append(_table(rows, ["对象", "关系", "意义", "隐藏张力", "默认态度"]))

    ap = deep.get("arc_potential", {})
    parts.append(_h(4, "弧线潜能"))
    parts.append(f"- 成长方向：{ap.get('growth_direction', '—')}")
    parts.append(f"- 堕落方向：{ap.get('corruption_direction', '—')}")
    parts.append(f"- 关键抉择：{ap.get('key_choice', '—')}")

    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="合并角色缓存 JSON 为 character_profiles.md")
    parser.add_argument("--book-dir", required=True, help="书籍根目录（含 cache/character/ 子目录）")
    parser.add_argument("--output", required=True, help="输出 Markdown 文件路径")
    args = parser.parse_args()

    cache_dir = os.path.join(args.book_dir, "cache", "character")

    # 1. 读取骨架
    skeleton_path = os.path.join(cache_dir, "skeleton.json")
    if not os.path.exists(skeleton_path):
        print(f"[merge_characters] 错误：skeleton.json 不存在 ({skeleton_path})", file=sys.stderr)
        sys.exit(1)
    skeleton_data = load_json(skeleton_path)
    characters = skeleton_data.get("characters", [])
    if not characters:
        print("[merge_characters] 错误：skeleton.json 中无 characters", file=sys.stderr)
        sys.exit(1)

    # 2. 读取信念
    beliefs_path = os.path.join(cache_dir, "beliefs.json")
    beliefs = []
    if os.path.exists(beliefs_path):
        beliefs = load_json(beliefs_path).get("beliefs", [])

    # 3. 逐个角色渲染
    sections = []
    for char in characters:
        name = char.get("name", "")
        if not name:
            continue

        # 读取该角色的深层维度
        deep_path = os.path.join(cache_dir, f"{name}_deep.json")
        deep = {}
        if os.path.exists(deep_path):
            deep = load_json(deep_path)
        else:
            print(f"[merge_characters] 警告：{name}_deep.json 不存在，深层维度留空", file=sys.stderr)

        sections.append(render_character(name, char, beliefs, deep))

    if not sections:
        print("[merge_characters] 错误：没有成功渲染任何角色", file=sys.stderr)
        sys.exit(1)

    output = "# 角色设定\n\n" + "\n\n---\n\n".join(sections) + "\n"

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"[merge_characters] 已生成：{args.output}，共 {len(sections)} 个角色", file=sys.stderr)


if __name__ == "__main__":
    main()
