#!/usr/bin/env python3
"""将六个世界观维度 JSON 拼接为单一 Markdown 文档。

用法:
    python merge_world.py --book-dir /path/to/book --output /path/to/world_foundation.md

产出:
    拼接后的 world_foundation.md
"""

import argparse
import json
import os
import sys


DIMENSIONS = [
    "core_laws",
    "space_time",
    "society",
    "history_culture",
    "existence",
    "information",
]


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, strict=False)


def _h(level: int, title: str) -> str:
    """Markdown heading."""
    return f"{'#' * level} {title}"


def _table(rows: list[list[str]], headers: list[str]) -> str:
    """Render a markdown table."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["------"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("\n", " ") for c in row) + " |")
    return "\n".join(lines)


def _p(text: str) -> str:
    """Ensure text ends with newline."""
    return text.rstrip() + "\n"


# ── Per-dimension renderers ──────────────────────────────────────────

def render_core_laws(data: dict) -> str:
    inner = data.get("core_laws", data)
    parts = [_h(2, "一、核心法则")]

    ps = inner.get("power_system", "")
    if ps:
        parts.append(_h(3, "力量体系"))
        parts.append(_p(ps))

    axioms = inner.get("axioms", [])
    if axioms:
        parts.append(_h(3, "底层公理"))
        rows = []
        for a in axioms:
            rows.append([
                f"**{a.get('name', '')}**",
                a.get("statement", ""),
                a.get("cost", ""),
                a.get("boundary", ""),
                a.get("enforcement", ""),
            ])
        parts.append(_table(rows, ["公理", "陈述", "代价", "边界", "执行"]))

    taboos = inner.get("taboos", [])
    if taboos:
        parts.append(_h(3, "绝对禁忌"))
        for t in taboos:
            parts.append(f"- {t}")

    pm = inner.get("power_manifestation", "")
    if pm:
        parts.append(_h(3, "力量显现"))
        parts.append(_p(pm))

    return "\n\n".join(parts)


def render_space_time(data: dict) -> str:
    inner = data.get("space_time", data)
    parts = [_h(2, "二、时空地理")]

    wl = inner.get("world_layout", "")
    if wl:
        parts.append(_h(3, "世界格局"))
        parts.append(_p(wl))

    locs = inner.get("key_locations", [])
    if locs:
        parts.append(_h(3, "关键地点"))
        rows = []
        for l in locs:
            rows.append([
                l.get("name", ""),
                l.get("terrain", ""),
                l.get("feature", ""),
                l.get("risk", ""),
                l.get("controlling_force", ""),
            ])
        parts.append(_table(rows, ["地点", "地形", "特征", "风险", "控制方"]))

    eco = inner.get("ecology", "")
    if eco:
        parts.append(_h(3, "生态资源"))
        parts.append(_p(eco))

    era = inner.get("era", "")
    if era:
        parts.append(_h(3, "时代背景"))
        parts.append(_p(era))

    et = inner.get("environment_texture", "")
    if et:
        parts.append(_h(3, "空间体感"))
        parts.append(_p(et))

    return "\n\n".join(parts)


def render_society(data: dict) -> str:
    inner = data.get("society", data)
    parts = [_h(2, "三、社会权力")]

    races = inner.get("races", [])
    if races:
        parts.append(_h(3, "种族"))
        rows = []
        for r in races:
            rows.append([
                r.get("name", ""),
                r.get("traits", ""),
                r.get("population", ""),
                r.get("social_status", ""),
            ])
        parts.append(_table(rows, ["种族", "特征", "人口", "社会地位"]))

    cs = inner.get("class_structure", "")
    if cs:
        parts.append(_h(3, "阶层结构"))
        parts.append(_p(cs))

    ps = inner.get("political_system", "")
    if ps:
        parts.append(_h(3, "政治体制"))
        parts.append(_p(ps))

    forces = inner.get("forces", [])
    if forces:
        parts.append(_h(3, "势力"))
        for f in forces:
            goals = "；".join(f.get("goals", []))
            methods = "；".join(f.get("methods", []))
            parts.append(
                _table(
                    [[
                        f.get("name", ""),
                        f.get("type", ""),
                        f.get("base_of_power", ""),
                        goals,
                        methods,
                    ]],
                    ["势力", "类型", "权力基础", "目标", "手段"],
                )
            )

    fr = inner.get("force_relations", [])
    if fr:
        parts.append(_h(3, "势力关系"))
        rows = []
        for r in fr:
            rows.append([
                r.get("source", ""),
                r.get("relation", ""),
                r.get("target", ""),
                r.get("tension_point", ""),
            ])
        parts.append(_table(rows, ["来源", "关系", "目标", "矛盾点"]))

    pv = inner.get("power_visibility", "")
    if pv:
        parts.append(_h(3, "权力的感知"))
        parts.append(_p(pv))

    return "\n\n".join(parts)


def render_history_culture(data: dict) -> str:
    inner = data.get("history_culture", data)
    parts = [_h(2, "四、历史文化")]

    events = inner.get("major_events", [])
    if events:
        parts.append(_h(3, "关键历史事件"))
        rows = []
        for e in events:
            rows.append([
                e.get("event", ""),
                e.get("era", ""),
                e.get("lasting_impact", ""),
            ])
        parts.append(_table(rows, ["事件", "时代", "持续性影响"]))

    religions = inner.get("religions", [])
    if religions:
        parts.append(_h(3, "宗教"))
        rows = []
        for r in religions:
            rows.append([
                r.get("name", ""),
                r.get("core_belief", ""),
                r.get("follower_scope", ""),
            ])
        parts.append(_table(rows, ["宗教", "核心信仰", "信众范围"]))

    customs = inner.get("customs", "")
    if customs:
        parts.append(_h(3, "风俗"))
        parts.append(_p(customs))

    economy = inner.get("economy", "")
    if economy:
        parts.append(_h(3, "经济"))
        parts.append(_p(economy))

    ds = inner.get("daily_slice", "")
    if ds:
        parts.append(_h(3, "底层日常"))
        parts.append(_p(ds))

    return "\n\n".join(parts)


def render_existence(data: dict) -> str:
    inner = data.get("existence", data)
    parts = [_h(2, "五、存在基础")]

    for field, title in [
        ("calendar", "历法"),
        ("lifespan", "寿命"),
        ("death", "死亡"),
        ("disease_and_birth", "疾病与繁衍"),
    ]:
        val = inner.get(field, "")
        if val:
            parts.append(_h(3, title))
            parts.append(_p(val))

    return "\n\n".join(parts)


def render_information(data: dict) -> str:
    inner = data.get("information", data)
    parts = [_h(2, "六、信息传播")]

    for field, title in [
        ("info_speed", "信息速度"),
        ("knowledge_medium", "知识载体"),
        ("info_barriers", "信息壁垒"),
        ("rumor_and_truth", "谣言与真相"),
    ]:
        val = inner.get(field, "")
        if val:
            parts.append(_h(3, title))
            parts.append(_p(val))

    return "\n\n".join(parts)


RENDERERS = {
    "core_laws": render_core_laws,
    "space_time": render_space_time,
    "society": render_society,
    "history_culture": render_history_culture,
    "existence": render_existence,
    "information": render_information,
}


def main():
    parser = argparse.ArgumentParser(description="合并世界观 JSON 为 Markdown")
    parser.add_argument("--book-dir", required=True, help="书籍根目录（含 world/ 子目录）")
    parser.add_argument("--output", required=True, help="输出 Markdown 文件路径")
    args = parser.parse_args()

    world_dir = os.path.join(args.book_dir, "world")
    sections = []

    for dim in DIMENSIONS:
        path = os.path.join(world_dir, f"{dim}.json")
        if not os.path.exists(path):
            print(f"[merge_world] 跳过：{path} 不存在", file=sys.stderr)
            continue
        try:
            data = load_json(path)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"[merge_world] 错误：无法读取 {path}：{e}", file=sys.stderr)
            continue

        renderer = RENDERERS.get(dim)
        if renderer:
            sections.append(renderer(data))

    if not sections:
        print("[merge_world] 错误：没有成功加载任何维度", file=sys.stderr)
        sys.exit(1)

    output = "# 世界观基础\n\n" + "\n\n---\n\n".join(sections) + "\n"

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"[merge_world] 已生成：{args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
