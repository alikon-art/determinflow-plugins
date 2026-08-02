#!/usr/bin/env python3
"""保存世界观维度 JSON 到书籍目录，并产出摘要变量。

用法:
    python save_dimension.py --book-dir /path/to/book --dim-name core_laws --json '{"core_laws": {...}}'

产出:
    <WF_VAR>{dim_name}_summary:摘要文本</WF_VAR>
"""

import argparse
import json
import os
import re
import sys


def _extract_json(raw: str) -> str:
    """从可能包裹在 ```json...``` markdown 代码块中的字符串提取纯 JSON。"""
    text = raw.strip()
    if not text:
        return text
    # 去除开头的 ```json 或 ``` 标记
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, count=1)
    # 去除结尾的 ``` 标记
    text = re.sub(r'\n?```\s*$', '', text, count=1)

    # ── LLM 生成 JSON 的常见病修复 ──

    # 1. 弯曲/智能引号 → ASCII 直引号
    text = text.replace('\u201c', '"').replace('\u201d', '"')   # " " → "
    text = text.replace('\u2018', "'").replace('\u2019', "'")   # ' ' → '
    text = text.replace('\u00ab', '"').replace('\u00bb', '"')   # « » → "
    text = text.replace('\u201e', '"').replace('\u201a', "'")   # „ ‚

    # 2. 中文引号 → ASCII 直引号（LLM 混用中英文标点时出现）
    text = text.replace('\uff02', '"')   # ＂（全角双引号）→ "

    # 3. 尾随逗号：删除 ] 或 } 前的最后一个逗号
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    return text.strip()


def generate_summary(data: dict, dim_name: str) -> str:
    """根据维度名提取关键摘要，控制在 150 字以内。"""
    inner = list(data.values())[0] if data else {}

    if dim_name == "core_laws":
        ps = inner.get("power_system", "")
        axioms = inner.get("axioms", [])
        axiom_names = [a.get("name", "") for a in axioms[:3]]
        return f"力量体系: {ps[:80]}；公理: {', '.join(axiom_names)}" if axiom_names else f"力量体系: {ps[:120]}"

    elif dim_name == "space_time":
        layout = inner.get("world_layout", "")
        era = inner.get("era", "")
        locs = inner.get("key_locations", [])
        loc_names = [l.get("name", "") for l in locs[:3]]
        locs_str = f"；地点: {', '.join(loc_names)}" if loc_names else ""
        return f"格局: {layout[:60]}；时代: {era[:40]}{locs_str}"

    elif dim_name == "society":
        races = inner.get("races", [])
        race_names = [r.get("name", "") for r in races[:3]]
        forces = inner.get("forces", [])
        force_names = [f.get("name", "") for f in forces[:3]]
        return f"种族: {', '.join(race_names) or '人类'}；势力: {', '.join(force_names)}"

    elif dim_name == "history_culture":
        events = inner.get("major_events", [])
        event_strs = [e.get("event", "") for e in events[:2]]
        economy = inner.get("economy", "")
        return f"关键事件: {'; '.join(event_strs)}；经济: {economy[:60]}"

    elif dim_name == "existence":
        lifespan = inner.get("lifespan", "")
        death = inner.get("death", "")
        return f"寿命: {lifespan[:60]}；死亡: {death[:60]}"

    elif dim_name == "information":
        speed = inner.get("info_speed", "")
        barriers = inner.get("info_barriers", "")
        return f"信息速度: {speed[:60]}；壁垒: {barriers[:60]}"

    return "摘要生成失败"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-dir", required=True, help="书籍根目录")
    parser.add_argument("--dim-name", required=True, help="维度名，如 core_laws")
    parser.add_argument("--json", required=True, help="维度 JSON 字符串")
    args = parser.parse_args()

    # 解析 JSON（先剥离可能的 markdown 代码块包裹）
    try:
        data = json.loads(_extract_json(args.json), strict=False)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 确保目录存在
    world_dir = os.path.join(args.book_dir, "world")
    os.makedirs(world_dir, exist_ok=True)

    # 写入文件
    filepath = os.path.join(world_dir, f"{args.dim_name}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[save_dimension] 已保存: {filepath}", file=sys.stderr)

    # 生成摘要并产出变量
    summary = generate_summary(data, args.dim_name)
    print(f"<WF_VAR>{args.dim_name}_summary:{summary}</WF_VAR>")


if __name__ == "__main__":
    main()
