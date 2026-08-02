#!/usr/bin/env python3
"""校验 story_plan.json 的三层冰山结构完整性"""

import json
import sys
import os


REQUIRED_FIELDS = {
    "surface": [
        "expanded_premise",
        "core_conflict",
        "reader_promise",
        "tone_reference",
        "target_readers",
        "commercial_tags",
    ],
    "engine": [
        "protagonist_trap",
        "conflict_engine",
        "conflict_layers",
        "mystery_box",
        "progression_loop",
        "dual_story",
    ],
    "payoff": [
        "tension_archetypes",
        "payoff_grammar",
        "emotional_rhythm",
        "growth_path",
        "ending_flavor",
    ],
}

SUBFIELDS = {
    "engine.conflict_layers": ["external", "internal", "relational"],
    "engine.dual_story": ["foreground", "background"],
}

# 越界检测：不应出现的模式
BOUNDARY_VIOLATIONS = [
    (r"第\s*\d+\s*章", "章节号（越界：故事规划不应分配章节级兑现）"),
    (r"(前十章|三十章内|五十章内|前\d+章)", "章节范围（越界：卷纲负责章节分配）"),
]


def check_boundary(field_name: str, value: str) -> list[str]:
    """检测字段内容是否越界"""
    violations = []
    import re
    for pattern, desc in BOUNDARY_VIOLATIONS:
        if re.search(pattern, str(value)):
            violations.append(f"BOUNDARY VIOLATION: {field_name} 包含 '{desc}'")
    return violations


def main():
    plan_path = "story_plan.json"
    if not os.path.exists(plan_path):
        print(f"ERROR: {plan_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    errors = []
    warnings = []

    # 校验三层主字段
    for layer, fields in REQUIRED_FIELDS.items():
        layer_data = plan.get(layer)
        if not isinstance(layer_data, dict):
            errors.append(f"MISSING LAYER: '{layer}' not found or not an object")
            continue
        for field in fields:
            if field not in layer_data:
                errors.append(f"MISSING FIELD: {layer}.{field}")
            elif not layer_data[field]:
                errors.append(f"EMPTY FIELD: {layer}.{field}")
            else:
                # 越界检测（仅字符串字段）
                if isinstance(layer_data[field], str):
                    warnings.extend(check_boundary(f"{layer}.{field}", layer_data[field]))
                # 数组字段越界检测
                elif isinstance(layer_data[field], list):
                    for i, item in enumerate(layer_data[field]):
                        if isinstance(item, str):
                            warnings.extend(check_boundary(f"{layer}.{field}[{i}]", item))

    # 校验子字段
    for path, subfields in SUBFIELDS.items():
        layer, field = path.split(".")
        layer_data = plan.get(layer, {})
        obj = layer_data.get(field, {})
        if not isinstance(obj, dict):
            errors.append(f"MISSING SUB-OBJECT: {path}")
            continue
        for sf in subfields:
            if sf not in obj:
                errors.append(f"MISSING SUBFIELD: {path}.{sf}")
            elif not obj[sf]:
                errors.append(f"EMPTY SUBFIELD: {path}.{sf}")
            else:
                if isinstance(obj[sf], str):
                    warnings.extend(check_boundary(path, obj[sf]))

    # 校验 constraints
    constraints = plan.get("constraints")
    if not isinstance(constraints, list):
        errors.append("MISSING: 'constraints' not found or not an array")
    elif len(constraints) < 3:
        errors.append(f"TOO FEW CONSTRAINTS: {len(constraints)} (expected 3-8)")

    # 校验 issues（可选字段，但有就必须格式正确）
    issues = plan.get("issues")
    if issues is not None:
        if not isinstance(issues, list):
            errors.append("INVALID: 'issues' must be an array")
        else:
            for i, issue in enumerate(issues):
                if not isinstance(issue, dict):
                    errors.append(f"INVALID issues[{i}]: must be an object")
                    continue
                if issue.get("type") not in ("conflict", "missing_info"):
                    errors.append(f"INVALID issues[{i}].type: must be 'conflict' or 'missing_info'")
                if not issue.get("field"):
                    errors.append(f"MISSING issues[{i}].field")
                if not issue.get("message"):
                    errors.append(f"MISSING issues[{i}].message")

    # 输出 warning
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}", file=sys.stderr)
        print(f"\n{len(errors)} validation errors total", file=sys.stderr)
        sys.exit(1)

    # 生成摘要
    surface = plan["surface"]
    engine = plan["engine"]
    payoff = plan["payoff"]
    tags = ", ".join(surface.get("commercial_tags", []))

    summary_parts = [
        f"故事宏观规划校验通过 ✓",
        f"核心冲突: {surface['core_conflict'][:100]}",
        f"叙事气质: {surface['tone_reference'][:80]}",
        f"商业标签: {tags}",
        f"张力类型: {len(payoff.get('tension_archetypes', []))}种",
        f"爆点类型: {len(payoff.get('payoff_grammar', []))}种",
        f"约束规则: {len(plan.get('constraints', []))}条",
        f"issues: {len(plan.get('issues', []))}项",
    ]
    summary = " | ".join(summary_parts)

    print(f"<WF_VAR>plan_summary:{summary}</WF_VAR>")
    print(f"<script_out>{summary}</script_out>")


if __name__ == "__main__":
    main()
