#!/usr/bin/env python3
"""story_plan.json → story_plan.md + style_profile.json → style_profile.md"""

import json
import sys
import os


def render_section(title: str, content: str | list | dict) -> str:
    """渲染一个节为 markdown"""
    lines = [f"## {title}", ""]
    if isinstance(content, str):
        lines.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                for k, v in item.items():
                    lines.append(f"- **{k}**: {v}")
                lines.append("")
            else:
                lines.append(f"- {item}")
    elif isinstance(content, dict):
        for k, v in content.items():
            if isinstance(v, str):
                lines.append(f"### {k}\n\n{v}")
            elif isinstance(v, list):
                lines.append(f"### {k}")
                for item in v:
                    lines.append(f"- {item}")
                lines.append("")
    lines.append("")
    return "\n".join(lines)


def main():
    json_path = "cache/story_plan/story_plan.json"
    md_path = "meta/story_plan.md"

    if not os.path.exists(json_path):
        print(f"ERROR: {json_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        plan = json.load(f)

    lines = [
        "# 故事引擎",
        "",
        "> 三层冰山结构：显性层（读者感受）→ 引擎层（驱动力）→ 兑现层（兑现规律）",
        "",
        "---",
        "",
        "# 一、显性层 Surface",
        "",
        f"## 扩展前提\n\n{plan['surface'].get('expanded_premise', '')}",
        "",
        f"## 核心冲突\n\n{plan['surface'].get('core_conflict', '')}",
        "",
        f"## 读者承诺\n\n{plan['surface'].get('reader_promise', '')}",
        "",
        f"## 叙事气质\n\n{plan['surface'].get('tone_reference', '')}",
        "",
        f"## 目标读者\n\n{plan['surface'].get('target_readers', '')}",
        "",
    ]

    tags = plan['surface'].get('commercial_tags', [])
    tags_str = ", ".join(tags) if tags else "—"
    lines += [f"## 商业标签\n\n{tags_str}", ""]

    lines += [
        "---",
        "",
        "# 二、引擎层 Engine",
        "",
        f"## 主角困境\n\n{plan['engine'].get('protagonist_trap', '')}",
        "",
        f"## 冲突引擎\n\n{plan['engine'].get('conflict_engine', '')}",
        "",
    ]

    cl = plan['engine'].get('conflict_layers', {})
    lines += [
        "## 冲突层",
        "",
        f"### 外部\n\n{cl.get('external', '')}",
        "",
        f"### 内在\n\n{cl.get('internal', '')}",
        "",
        f"### 关系\n\n{cl.get('relational', '')}",
        "",
        f"## 核心悬谜\n\n{plan['engine'].get('mystery_box', '')}",
        "",
        f"## 推进循环\n\n{plan['engine'].get('progression_loop', '')}",
        "",
    ]

    ds = plan['engine'].get('dual_story', {})
    lines += [
        "## 前后台双层",
        "",
        f"### 前台\n\n{ds.get('foreground', '')}",
        "",
        f"### 后台\n\n{ds.get('background', '')}",
        "",
        "---",
        "",
        "# 三、兑现层 Payoff",
        "",
    ]

    ta = plan['payoff'].get('tension_archetypes', [])
    lines.append("## 张力类型")
    for i, t in enumerate(ta, 1):
        lines.append(f"{i}. {t}")
    lines.append("")

    pg = plan['payoff'].get('payoff_grammar', [])
    lines.append("## 爆点语法")
    for i, p in enumerate(pg, 1):
        lines.append(f"{i}. {p}")
    lines.append("")

    lines += [
        f"## 情绪律动\n\n{plan['payoff'].get('emotional_rhythm', '')}",
        "",
        f"## 成长路径\n\n{plan['payoff'].get('growth_path', '')}",
        "",
        f"## 结局余味\n\n{plan['payoff'].get('ending_flavor', '')}",
        "",
        "---",
        "",
        "# 四、叙事约束",
        "",
    ]

    constraints = plan.get('constraints', [])
    for i, c in enumerate(constraints, 1):
        lines.append(f"{i}. {c}")
    lines.append("")

    issues = plan.get('issues', [])
    if issues:
        lines += [
            "---",
            "",
            "# 五、标记问题",
            "",
        ]
        for i, iss in enumerate(issues, 1):
            lines.append(f"{i}. **[{iss.get('type', '')}]** `{iss.get('field', '')}`: {iss.get('message', '')}")
        lines.append("")

    content = "\n".join(lines)

    os.makedirs(os.path.dirname(md_path) or ".", exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

    summary = f"story_plan.md 转换完成 ✓ | {len(plan['surface'].get('commercial_tags', []))}标签 | {len(plan.get('constraints', []))}条约束"
    print(f"<WF_VAR>plan_summary:{summary}</WF_VAR>")
    print(f"<script_out>{summary}</script_out>")


def render_style_profile(json_path: str, md_path: str) -> str:
    """style_profile.json → style_profile.md"""
    if not os.path.exists(json_path):
        print(f"WARN: {json_path} not found, skipping style_profile.md", file=sys.stderr)
        return ""

    with open(json_path, encoding="utf-8") as f:
        sp = json.load(f)

    lines = ["# 风格宪法", "", "---", ""]

    tone = sp.get("tone", "")
    if tone:
        lines += ["## 1. 基调定位", "", tone, ""]

    refs = sp.get("references", [])
    if refs:
        lines += ["## 2. 风格锚定", ""]
        for r in refs:
            work = r.get("work", "")
            tags = r.get("tags", "")
            header = f"### {work}" + (f"（{tags}）" if tags else "")
            lines.append(header)
            if r.get("learn"):
                lines.append(f"- **学什么**：{r['learn']}")
            if r.get("apply"):
                lines.append(f"- **怎么用**：{r['apply']}")
            lines.append("")

    persona = sp.get("narrative_persona", "")
    if persona:
        lines += ["## 3. 叙事人格", "", persona, ""]

    commandments = sp.get("commandments", [])
    if commandments:
        lines += ["## 4. 文风戒律", ""]
        for c in commandments:
            lines.append(f"- {c}")
        lines.append("")

    notes = sp.get("genre_notes", "")
    if notes:
        lines += ["## 5. 题材笔法", "", notes, ""]

    content = "\n".join(lines)

    os.makedirs(os.path.dirname(md_path) or ".", exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

    return f"style_profile.md ✓ | {len(refs)}参考 | {len(commandments)}戒律"


def main():
    # story_plan.json → story_plan.md
    sp_json = "cache/story_plan/story_plan.json"
    sp_md = "meta/story_plan.md"

    if not os.path.exists(sp_json):
        print(f"ERROR: {sp_json} not found", file=sys.stderr)
        sys.exit(1)

    with open(sp_json, encoding="utf-8") as f:
        plan = json.load(f)

    lines = [
        "# 故事引擎",
        "",
        "> 三层冰山结构：显性层（读者感受）→ 引擎层（驱动力）→ 兑现层（兑现规律）",
        "",
        "---",
        "",
        "# 一、显性层 Surface",
        "",
        f"## 扩展前提\n\n{plan['surface'].get('expanded_premise', '')}",
        "",
        f"## 核心冲突\n\n{plan['surface'].get('core_conflict', '')}",
        "",
        f"## 读者承诺\n\n{plan['surface'].get('reader_promise', '')}",
        "",
        f"## 叙事气质\n\n{plan['surface'].get('tone_reference', '')}",
        "",
        f"## 目标读者\n\n{plan['surface'].get('target_readers', '')}",
        "",
    ]

    tags = plan['surface'].get('commercial_tags', [])
    tags_str = ", ".join(tags) if tags else "—"
    lines += [f"## 商业标签\n\n{tags_str}", ""]

    lines += [
        "---",
        "",
        "# 二、引擎层 Engine",
        "",
        f"## 主角困境\n\n{plan['engine'].get('protagonist_trap', '')}",
        "",
        f"## 冲突引擎\n\n{plan['engine'].get('conflict_engine', '')}",
        "",
    ]

    cl = plan['engine'].get('conflict_layers', {})
    lines += [
        "## 冲突层",
        "",
        f"### 外部\n\n{cl.get('external', '')}",
        "",
        f"### 内在\n\n{cl.get('internal', '')}",
        "",
        f"### 关系\n\n{cl.get('relational', '')}",
        "",
        f"## 核心悬谜\n\n{plan['engine'].get('mystery_box', '')}",
        "",
        f"## 推进循环\n\n{plan['engine'].get('progression_loop', '')}",
        "",
    ]

    ds = plan['engine'].get('dual_story', {})
    lines += [
        "## 前后台双层",
        "",
        f"### 前台\n\n{ds.get('foreground', '')}",
        "",
        f"### 后台\n\n{ds.get('background', '')}",
        "",
        "---",
        "",
        "# 三、兑现层 Payoff",
        "",
    ]

    ta = plan['payoff'].get('tension_archetypes', [])
    lines.append("## 张力类型")
    for i, t in enumerate(ta, 1):
        lines.append(f"{i}. {t}")
    lines.append("")

    pg = plan['payoff'].get('payoff_grammar', [])
    lines.append("## 爆点语法")
    for i, p in enumerate(pg, 1):
        lines.append(f"{i}. {p}")
    lines.append("")

    lines += [
        f"## 情绪律动\n\n{plan['payoff'].get('emotional_rhythm', '')}",
        "",
        f"## 成长路径\n\n{plan['payoff'].get('growth_path', '')}",
        "",
        f"## 结局余味\n\n{plan['payoff'].get('ending_flavor', '')}",
        "",
        "---",
        "",
        "# 四、叙事约束",
        "",
    ]

    constraints = plan.get('constraints', [])
    for i, c in enumerate(constraints, 1):
        lines.append(f"{i}. {c}")
    lines.append("")

    issues = plan.get('issues', [])
    if issues:
        lines += [
            "---",
            "",
            "# 五、标记问题",
            "",
        ]
        for i, iss in enumerate(issues, 1):
            lines.append(f"{i}. **[{iss.get('type', '')}]** `{iss.get('field', '')}`: {iss.get('message', '')}")
        lines.append("")

    content = "\n".join(lines)

    os.makedirs(os.path.dirname(sp_md) or ".", exist_ok=True)
    with open(sp_md, "w", encoding="utf-8") as f:
        f.write(content)

    story_plan_summary = f"story_plan.md ✓ | {len(plan['surface'].get('commercial_tags', []))}标签 | {len(plan.get('constraints', []))}条约束"

    # style_profile.json → style_profile.md
    sf_json = "cache/story_plan/style_profile.json"
    sf_md = "meta/style_profile.md"
    style_summary = render_style_profile(sf_json, sf_md)

    summary = story_plan_summary
    if style_summary:
        summary += f" | {style_summary}"

    print(f"<WF_VAR>plan_summary:{summary}</WF_VAR>")
    print(f"<script_out>{summary}</script_out>")


if __name__ == "__main__":
    main()
