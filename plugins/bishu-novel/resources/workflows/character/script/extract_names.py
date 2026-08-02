#!/usr/bin/env python3
"""从 skeleton JSON 中提取角色名列表，产出 list 变量供循环网关使用。

用法:
    python extract_names.py --file cache/character/skeleton.json

产出:
    <WF_VAR>character_names:["张三","李四","王五"]</WF_VAR>
"""

import argparse
import json
import re
import sys


def _extract_json(raw: str) -> str:
    text = raw.strip()
    if not text:
        return text
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, count=1)
    text = re.sub(r'\n?```\s*$', '', text, count=1)
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u00ab', '"').replace('\u00bb', '"')
    text = text.replace('\u201e', '"').replace('\u201a', "'")
    text = text.replace('\uff02', '"')
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text.strip()


def _drop_obvious_orphan_lines(text: str) -> str:
    """Drop lines that are clearly not JSON tokens.

    LLM output occasionally contains a dangling fragment like:
        寻者",
    inside an object.  It is better to drop that line and keep the rest of the
    valid structure than to fail the whole character pipeline.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if stripped[0] in '{[}]':
            kept.append(line)
            continue
        if stripped.startswith('"') and ':' in stripped:
            kept.append(line)
            continue
        if stripped.startswith('"') and stripped.rstrip(',').endswith('"'):
            kept.append(line)
            continue
        # Any other line is likely an orphan natural-language fragment.
    return "\n".join(kept)


def _load_json_tolerant(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    text = _extract_json(raw)
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        repaired = _drop_obvious_orphan_lines(text)
        repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)
        data = json.loads(repaired, strict=False)
        # Persist the repaired JSON so downstream nodes read valid JSON too.
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("[extract_names] 已修复 skeleton JSON 中的孤立文本行", file=sys.stderr)
        return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="skeleton JSON 文件路径")
    args = parser.parse_args()

    try:
        data = _load_json_tolerant(args.file)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    names = [c["name"] for c in data.get("characters", []) if c.get("name")]

    if not names:
        print("[extract_names] 错误：未找到角色名", file=sys.stderr)
        sys.exit(1)

    # 输出 list 变量（双引号 JSON 数组）
    names_json = json.dumps(names, ensure_ascii=False)
    print(f"<WF_VAR>character_names:{names_json}</WF_VAR>")
    print(f"<script_out>已提取 {len(names)} 个角色: {', '.join(names)}</script_out>")


if __name__ == "__main__":
    main()
