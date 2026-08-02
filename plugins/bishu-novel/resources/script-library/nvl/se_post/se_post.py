#!/usr/bin/env python3
"""SE 后处理：se_output.json → storyboard.md（四维度意图卡片）"""

import argparse, json, os


def render_field(value, max_len=60):
    """渲染单个字段，截断标注。"""
    s = str(value)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def main():
    parser = argparse.ArgumentParser(description="SE JSON → storyboard.md 渲染")
    parser.add_argument("--input", required=True, help="SE 的 JSON 输出")
    parser.add_argument("--output", required=True, help="渲染后的 MD 路径")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    sb = data.get("storyboard", {})
    plot = sb.get("plot", {})
    char = sb.get("character", {})
    narr = sb.get("narrative", {})
    style = sb.get("style", {})

    # 从输出路径提取章节号
    chapter = os.path.basename(os.path.dirname(args.output)) or "?"

    lines = []
    lines.append(f"# 第{chapter}章 · 意图卡片")
    lines.append("")

    # ── 一、剧情导演 ──
    lines.append("## 一、剧情导演")
    lines.append("")
    lines.append(f"**本章目标**")
    lines.append(render_field(plot.get("chapter_goal", "无")))
    lines.append("")
    lines.append(f"**核心冲突**")
    lines.append(render_field(plot.get("core_conflict", "无")))
    lines.append("")
    lines.append(f"**关键推进**")
    for beat in plot.get("key_beats", []):
        lines.append(f"- {render_field(beat)}")
    lines.append("")
    lines.append(f"**悬念设计**")
    lines.append(render_field(plot.get("suspense", "无")))
    lines.append("")
    hi = plot.get("hook_intent", "无")
    if hi and hi != "无":
        lines.append(f"**伏笔意图**")
        lines.append(render_field(hi))
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 二、人物导演 ──
    lines.append("## 二、人物导演")
    lines.append("")
    rel_moves = char.get("relationship_moves", [])
    if rel_moves:
        lines.append("**关系推进**")
        for rm in rel_moves:
            pair = rm.get("pair", "?→?")
            change = rm.get("change", "")
            trigger = rm.get("trigger", "")
            lines.append(f"- {pair}：{render_field(change)}。触发感：{render_field(trigger, 30)}")
        lines.append("")
    imps = char.get("impressions", [])
    if imps:
        lines.append("**印象锚点**")
        for im in imps:
            name = im.get("name", "?")
            side = im.get("side", "")
            lines.append(f"- {name}：{render_field(side, 50)}")
        lines.append("")
    arcs = char.get("emotion_arcs", [])
    if arcs:
        lines.append("**情感走向**")
        for ea in arcs:
            name = ea.get("name", "?")
            frm = ea.get("from", "")
            mid = ea.get("mid", "")
            to = ea.get("to", "")
            trig = ea.get("trigger", "")
            lines.append(f"- {name}：从{frm}→{mid}→{to}。触发点：{render_field(trig, 30)}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 三、叙事导演 ──
    lines.append("## 三、叙事导演")
    lines.append("")
    lines.append(f"**推荐技巧**")
    lines.append(render_field(narr.get("technique", "无"), 40))
    lines.append("")
    lines.append(f"**原因**")
    lines.append(render_field(narr.get("reason", "无")))
    lines.append("")
    gaps = narr.get("info_gaps", [])
    if gaps:
        lines.append("**信息差设计**")
        for g in gaps:
            desc = g.get("description", "")
            dur = g.get("duration", "")
            lines.append(f"- {render_field(desc)}")
            lines.append(f"- 持续：{dur}")
            res = g.get("resolve_ids", [])
            if res:
                lines.append(f"- 本章兑现的信息黑洞：{', '.join(map(str, res))}")
            dfr = g.get("defer_ids", [])
            if dfr:
                lines.append(f"- 留给后续的：{', '.join(map(str, dfr))}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 四、风格导演 ──
    lines.append("## 四、风格导演")
    lines.append("")
    lines.append(f"**本章节奏**")
    lines.append(render_field(style.get("rhythm", "无"), 40))
    lines.append("")
    lines.append(f"**对白/描写侧重**")
    lines.append(render_field(style.get("dialogue_action", "无"), 30))
    lines.append("")
    lines.append(f"**氛围调性**")
    lines.append(render_field(style.get("atmosphere", "无"), 50))
    lines.append("")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] {args.input} → {args.output}")


if __name__ == "__main__":
    main()
