#!/usr/bin/env python3
"""保存角色维度 JSON 到书籍缓存目录。

用法:
    python save_character_dim.py --book-dir /path/to/book --dim-name skeleton --json '{"characters": [...]}'

产出:
    文件: {book_dir}/cache/character/{dim_name}.json
    <WF_VAR>{dim_name}_summary: 摘要文本</WF_VAR>
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
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, count=1)
    text = re.sub(r'\n?```\s*$', '', text, count=1)

    # 弯曲/智能引号 → ASCII 直引号
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u00ab', '"').replace('\u00bb', '"')
    text = text.replace('\u201e', '"').replace('\u201a', "'")
    text = text.replace('\uff02', '"')

    # 尾随逗号修复
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    return text.strip()


def generate_summary(data: dict, dim_name: str) -> str:
    """根据维度名提取关键摘要，控制在 150 字以内。"""
    if dim_name == "skeleton":
        chars = data.get("characters", [])
        names = [c.get("name", "") for c in chars[:5]]
        return f"角色阵容: {', '.join(names)}，共 {len(chars)} 人"
    elif dim_name == "beliefs":
        beliefs = data.get("beliefs", [])
        summary_parts = [f"{b.get('character', '')}: {b.get('core_belief', '')[:30]}" for b in beliefs[:3]]
        return "信念生态: " + "; ".join(summary_parts)
    elif dim_name.endswith("_deep"):
        name = dim_name.replace("_deep", "")
        desire = data.get("core_desire", {}).get("surface_goal", "")
        trauma = data.get("key_trauma", {}).get("wound", "")
        contradiction = data.get("internal_contradiction", {}).get("conflicting_elements", "")
        return f"{name} — 欲望: {desire[:40]}；创伤: {trauma[:30]}；矛盾: {contradiction[:30]}"
    return "摘要生成失败"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-dir", required=True, help="书籍根目录")
    parser.add_argument("--dim-name", required=True, help="维度名，如 skeleton / beliefs / 张三_deep")
    parser.add_argument("--json", required=True, help="维度 JSON 字符串")
    args = parser.parse_args()

    # 解析 JSON
    try:
        data = json.loads(_extract_json(args.json), strict=False)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 确保缓存目录存在
    cache_dir = os.path.join(args.book_dir, "cache", "character")
    os.makedirs(cache_dir, exist_ok=True)

    # 写入文件
    filepath = os.path.join(cache_dir, f"{args.dim_name}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[save_character_dim] 已保存: {filepath}", file=sys.stderr)

    # 生成摘要并产出变量
    summary = generate_summary(data, args.dim_name)
    print(f"<WF_VAR>{args.dim_name}_summary:{summary}</WF_VAR>")


if __name__ == "__main__":
    main()
