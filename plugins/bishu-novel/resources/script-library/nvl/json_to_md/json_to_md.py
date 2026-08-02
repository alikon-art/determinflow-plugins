#!/usr/bin/env python3
"""通用 JSON→Markdown 渲染脚本。

模式：
  tree:      递归读取目录下所有 JSON，按文件名排序，每个 JSON 渲染为一个 ## section
  character: 读取角色缓存目录下 skeleton.json + beliefs.json + *_deep.json，合并渲染
  voice:     读取 voice.json，渲染为角色声音锚 MD

用法:
  python json-to-md.py --mode tree --input-dir {book_dir}/world --output {book_dir}/meta/world_foundation.md --title "世界观基础"
  python json-to-md.py --mode character --book-dir {book_dir} --output {book_dir}/meta/character_profiles.md
  python json-to-md.py --mode voice --voice-json cache/character/voice.json --output meta/character_voice.md
"""

import argparse
import json
import os
import sys


def _h(level: int, title: str) -> str:
    return f"{'#' * level} {title}"


def _p(text: str) -> str:
    return text.rstrip() + "\n"


def _table(rows: list[list[str]], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["------"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("\n", " ") for c in row) + " |")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  tree 模式：递归渲染 JSON
# ═══════════════════════════════════════════════════════════

def render_json_to_md(data: dict, filename: str) -> str:
    """将单个 JSON 渲染为 Markdown section。递归处理嵌套对象和数组。"""
    label = filename.replace(".json", "").replace("_", " ").title()
    parts = [_h(2, label)]

    def _render(obj, indent: int = 0):
        prefix = "  " * indent
        if isinstance(obj, dict):
            for k, v in obj.items():
                key_display = k.replace("_", " ").title()
                if isinstance(v, (dict, list)):
                    parts.append(f"{prefix}- **{key_display}**：")
                    _render(v, indent + 1)
                else:
                    parts.append(f"{prefix}- **{key_display}**：{v}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, dict):
                    if i == 0:
                        # 收集所有 key 用于表头
                        keys = list(item.keys())
                        rows = []
                        for it in obj:
                            if isinstance(it, dict):
                                rows.append([str(it.get(k, "")) for k in keys])
                        if rows:
                            parts.append(_table(rows, [k.replace("_", " ").title() for k in keys]))
                        return
                    parts.append(f"{prefix}- **{i + 1}.**")
                    _render(item, indent + 1)
                else:
                    parts.append(f"{prefix}- {item}")
        else:
            parts.append(f"{prefix}{obj}")

    _render(data)
    return "\n\n".join(parts)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, strict=False)


# ═══════════════════════════════════════════════════════════
#  character 模式：角色渲染
# ═══════════════════════════════════════════════════════════

def render_character(name: str, true_name: str, aliases: list, skeleton: dict, beliefs: list, deep: dict) -> str:
    """将单个角色的所有维度渲染为 Markdown section。"""
    # 标题：name 为主，有别名时追加
    header = name
    if aliases:
        header = f"{name}（{'、'.join(aliases)}）"
    parts = [_h(2, header)]

    # essence 定调句
    essence = skeleton.get("essence", "").strip()
    if essence:
        parts.append(f"> {essence}")

    # 真名行（仅当真名与 name 不同或为空时显示）
    if true_name and true_name != name:
        parts.append(f"> 真名：{true_name}")
    elif not true_name:
        parts.append("> 真名未知")

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
    # 信念匹配：直接用 name
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


# ═══════════════════════════════════════════════════════════
#  voice 模式：角色声音锚渲染
# ═══════════════════════════════════════════════════════════

def render_voice_char(char: dict) -> str:
    """将单个角色的声线 JSON 渲染为 Markdown section。"""
    name = char.get("name", "未知")
    parts = [_h(2, name)]

    vp = char.get("voice_positioning", "")
    if vp:
        parts.append(_h(3, "核心声音定位"))
        parts.append(_p(vp))

    sf = char.get("syntax_fingerprint", {})
    if sf:
        parts.append(_h(3, "句法指纹"))
        if sf.get("sentence_preference"):
            parts.append(f"- 长短句偏好：{sf['sentence_preference']}")
        catchphrases = sf.get("catchphrases", [])
        if catchphrases:
            parts.append(f"- 口头禅：{'、'.join(catchphrases)}")
        if sf.get("pause_habit"):
            parts.append(f"- 停顿习惯：{sf['pause_habit']}")
        if sf.get("dominant_sentence_type"):
            parts.append(f"- 常用句式：{sf['dominant_sentence_type']}")

    cb = char.get("cognitive_bias", "")
    if cb:
        parts.append(_h(3, "认知偏差"))
        parts.append(_p(cb))

    fs = char.get("forbidden_speech", [])
    if fs:
        parts.append(_h(3, "禁止说的话"))
        for item in fs:
            parts.append(f"- {item}")

    ep = char.get("emotion_patterns", {})
    if ep:
        parts.append(_h(3, "情绪表达模式"))
        if ep.get("anger"):
            parts.append(f"- 愤怒时：{ep['anger']}")
        if ep.get("nervous"):
            parts.append(f"- 紧张时：{ep['nervous']}")
        if ep.get("lying"):
            parts.append(f"- 撒谎时：{ep['lying']}")

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="通用 JSON→Markdown 渲染")
    parser.add_argument("--mode", required=True, choices=["tree", "character", "voice"])
    parser.add_argument("--input-dir", default="", help="JSON 文件目录（tree 模式）")
    parser.add_argument("--book-dir", default="", help="书籍根目录（character 模式）")
    parser.add_argument("--voice-json", default="", help="voice.json 路径（voice 模式）")
    parser.add_argument("--output", required=True, help="输出 Markdown 文件路径")
    parser.add_argument("--title", default="角色档案", help="一级标题")
    args = parser.parse_args()

    sections = []

    if args.mode == "tree":
        input_dir = args.input_dir
        if not os.path.isdir(input_dir):
            print(f"[json-to-md] 错误：目录不存在 {input_dir}", file=sys.stderr)
            sys.exit(1)

        json_files = sorted(f for f in os.listdir(input_dir) if f.endswith(".json"))
        if not json_files:
            print(f"[json-to-md] 错误：{input_dir} 中没有 JSON 文件", file=sys.stderr)
            sys.exit(1)

        for fname in json_files:
            fpath = os.path.join(input_dir, fname)
            try:
                data = load_json(fpath)
                sections.append(render_json_to_md(data, fname))
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"[json-to-md] 跳过 {fname}: {e}", file=sys.stderr)

    elif args.mode == "character":
        cache_dir = os.path.join(args.book_dir, "cache", "character")
        skeleton_path = os.path.join(cache_dir, "skeleton.json")
        beliefs_path = os.path.join(cache_dir, "beliefs.json")

        if not os.path.exists(skeleton_path):
            print(f"[json-to-md] 错误：skeleton.json 不存在 ({skeleton_path})", file=sys.stderr)
            sys.exit(1)

        skeleton_data = load_json(skeleton_path)
        characters = skeleton_data.get("characters", [])
        if not characters:
            print("[json-to-md] 错误：skeleton.json 中无 characters", file=sys.stderr)
            sys.exit(1)

        beliefs = []
        if os.path.exists(beliefs_path):
            beliefs = load_json(beliefs_path).get("beliefs", [])

        for char in characters:
            name = char.get("name", "")
            true_name = char.get("true_name", "")
            aliases = char.get("aliases", [])
            if not name:
                print(f"[json-to-md] 警告：角色缺少 name 字段，跳过", file=sys.stderr)
                continue
            deep_path = os.path.join(cache_dir, f"{name}_deep.json")
            deep = {}
            if os.path.exists(deep_path):
                deep = load_json(deep_path)
            else:
                print(f"[json-to-md] 警告：{name}_deep.json 不存在，深层维度留空", file=sys.stderr)
            sections.append(render_character(name, true_name, aliases, char, beliefs, deep))

    elif args.mode == "voice":
        voice_path = args.voice_json
        if not os.path.exists(voice_path):
            print(f"[json-to-md] 错误：voice.json 不存在 ({voice_path})", file=sys.stderr)
            sys.exit(1)

        voice_data = load_json(voice_path)
        characters = voice_data.get("characters", [])
        if not characters:
            # Agent 偶发输出空 characters 时不要阻断整条角色管线。
            # 使用同目录 skeleton.json 生成最小声音锚，后续人工或再生可覆盖。
            skeleton_path = os.path.join(os.path.dirname(voice_path), "skeleton.json")
            if os.path.exists(skeleton_path):
                skeleton = load_json(skeleton_path).get("characters", [])
                characters = [
                    {
                        "name": c.get("name", "未知"),
                        "voice_positioning": "待补充",
                        "syntax_fingerprint": {
                            "sentence_preference": "待补充",
                            "catchphrases": [],
                            "pause_habit": "待补充",
                            "dominant_sentence_type": "待补充",
                        },
                        "cognitive_bias": "待补充",
                        "forbidden_speech": [],
                        "emotion_patterns": {
                            "anger": "待补充",
                            "nervous": "待补充",
                            "lying": "待补充",
                        },
                    }
                    for c in skeleton
                    if c.get("name")
                ]
                print("[json-to-md] 警告：voice.json 中无 characters，已用 skeleton.json 生成最小声音锚", file=sys.stderr)
            if not characters:
                print("[json-to-md] 错误：voice.json 中无 characters，且无法从 skeleton.json 兜底", file=sys.stderr)
                sys.exit(1)

        for char in characters:
            sections.append(render_voice_char(char))

    if not sections:
        print("[json-to-md] 错误：没有成功渲染任何内容", file=sys.stderr)
        sys.exit(1)

    output = f"# {args.title}\n\n" + "\n\n---\n\n".join(sections) + "\n"
    output = output.replace('——', '，')

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"[json-to-md] 已生成：{args.output}，共 {len(sections)} 个 section", file=sys.stderr)


if __name__ == "__main__":
    main()
