#!/usr/bin/env python3
"""DB ↔ 文件同步脚本。通用 JSON→MD 渲染器 + DB 读写。

用法:
  # sync_down: DB → MD 文件
  python db_sync.py --book-id <UUID> --templates world,character

  # sync_up: cache/JSON → DB
  python db_sync.py --book-id <UUID> --chapter <N> --direction up

  # 纯渲染: JSON 文件 → MD 文件（不连 DB）
  python db_sync.py --book-id <UUID> --render cache/we/world_state.json --output story/0001/world_state.md
"""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _secret_files import read_secret  # noqa: E402


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "novel_platform"),
        user=os.getenv("DB_USER", "postgres"),
        password=read_secret("DB_PASSWORD"),
    )


def _workflow_source_detail(workflow_id: str | None, suffix: str) -> str:
    if not workflow_id:
        raise ValueError("写入 revision 时必须传入 workflow_id")
    return f"{workflow_id}:{suffix}"


# ═══════════════════════════════════════════════════════════
#  通用 JSON → MD 渲染器（唯一渲染入口）
# ═══════════════════════════════════════════════════════════

def render_json(data, depth: int = 1, field_order: list[str] | None = None) -> str:
    """通用递归 JSON → MD。覆盖所有非特殊渲染需求。

    - dict: 每个 key → heading，value 递归
    - str/int/float: 原样段落
    - list[str]: 有序号列表
    - list[dict]: ≤5 列且平均格宽≤30 → 表格；否则逐条展开
    - None: 跳过
    - field_order: 可选字段排序列表，未列出的字段追加在末尾（字母序）

    depth: 1=#, 2=##, ...
    """
    if data is None:
        return ""

    parts = []
    hdr = "#" * depth

    if isinstance(data, dict):
        # 字段排序
        if field_order:
            ordered = [k for k in field_order if k in data]
            rest = sorted(k for k in data if k not in field_order)
            keys = ordered + rest
        else:
            keys = sorted(data.keys())
        for key in keys:
            val = data[key]
            if val is None:
                continue
            parts.append(f"{hdr} {key.replace('_', ' ').title()}")
            rendered = render_json(val, depth + 1)
            if rendered:
                parts.append(rendered)
            else:
                parts.append("")
    elif isinstance(data, list):
        if not data:
            return ""
        if all(isinstance(item, str) for item in data):
            for i, item in enumerate(data, 1):
                parts.append(f"{i}. {item}")
        elif all(isinstance(item, dict) for item in data):
            all_keys = []
            for item in data:
                for k in item:
                    if k not in all_keys:
                        all_keys.append(k)
            avg_w = sum(
                len(str(item.get(k, "")))
                for item in data for k in all_keys
            ) / max(len(data) * len(all_keys), 1)
            if len(all_keys) <= 5 and avg_w <= 30:
                parts.append("| " + " | ".join(
                    k.replace("_", " ").title() for k in all_keys
                ) + " |")
                parts.append("|" + "|".join(["------"] * len(all_keys)) + "|")
                for item in data:
                    parts.append("| " + " | ".join(
                        str(item.get(k, "")).replace("\n", " ")
                        for k in all_keys
                    ) + " |")
            else:
                for i, item in enumerate(data, 1):
                    parts.append(f"{hdr}# {i}")
                    parts.append("")
                    rendered = render_json(item, depth + 2)
                    if rendered:
                        parts.append(rendered)
        else:
            for i, item in enumerate(data, 1):
                parts.append(f"{i}. {render_json(item, depth + 1).strip()}")
    elif isinstance(data, (str, int, float)):
        text = str(data).strip()
        if text and text not in ("None", ""):
            parts.append(text)
    elif isinstance(data, bool):
        parts.append(str(data))

    return "\n".join(parts)


def clean(text: str) -> str:
    return text.replace("——", "，")


# ═══════════════════════════════════════════════════════════
#  sync_down 渲染函数（DB 查询 + 通用渲染）
# ═══════════════════════════════════════════════════════════

def _query_one(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()


def _render_world_md(data: dict) -> str:
    """纯渲染：6 维度 dict → world MD"""
    dims = {
        "core_laws": "核心法则", "space_time": "时空地理",
        "society": "社会权力", "history_culture": "历史文化",
        "existence": "存在基础", "information": "信息传播",
    }
    sections = []
    for col, label in dims.items():
        dim_data = data.get(col)
        sections.append(
            f"## {label}\n\n{render_json(dim_data, 3)}" if dim_data
            else f"## {label}\n\n> 暂无数据"
        )
    return "# 世界观基础\n\n" + "\n\n---\n\n".join(sections) + "\n"


def render_world(book_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT core_laws, space_time, society, history_culture, existence, information "
        "FROM world WHERE book_id = %s", (book_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        print(f"[db_sync] 错误：book {book_id} 的 world 表无数据", file=sys.stderr)
        sys.exit(1)

    # Dump 原始 6 维度 JSON 供 trimmer 使用
    raw = {}
    for col in ["core_laws", "space_time", "society", "history_culture", "existence", "information"]:
        if row[col] is not None:
            raw[col] = row[col]
    os.makedirs("cache/sync", exist_ok=True)
    with open("cache/sync/world.json", "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)

    return _render_world_md(raw)


def _render_character_md(rows: list[dict]) -> str:
    """纯渲染：character 行列表 → character MD"""
    sections = []
    for row in rows:
        name = row["name"]
        role = row.get("role") or ""
        gender = row.get("gender") or ""
        age = row.get("age") or ""
        aliases = row.get("aliases") or []

        # 标题：名字 + 叙事定位 | 性别年龄 | 别名
        header = name
        tags = []
        if role:
            tags.append(role)
        if gender and age:
            tags.append(f"{gender}，{age}")
        elif gender:
            tags.append(gender)
        elif age:
            tags.append(age)
        if aliases:
            tags.append("、".join(aliases))
        if tags:
            header = f"{name}（{' | '.join(tags)}）"

        parts = [f"## {header}", ""]
        wp = row.get("world_position") or {}
        if wp:
            parts.append("### 世界烙印")
            parts.append("")
            parts.append(render_json(wp, 4))

        extras = row.get("extras") or {}
        wa = extras.get("world_anchor", {})
        if wa:
            parts.append("### 世界观锚点")
            parts.append("")
            parts.append(render_json(wa, 4))

        beliefs = row.get("beliefs") or {}
        sd = row.get("surface_goal", "")
        dd = row.get("deep_desire", "")
        df = row.get("deep_fear") or {}
        secret = row.get("secrets") or {}
        bl = row.get("bottom_line") or {}
        inner = {}
        if beliefs: inner["核心信念"] = beliefs
        if sd: inner["表层目标"] = sd
        if dd: inner["深层欲望"] = dd
        if df: inner["深层恐惧"] = df
        if secret: inner["秘密"] = secret
        if bl: inner["不可触碰的底线"] = bl
        if inner:
            parts.append("### 内在构造")
            parts.append("")
            parts.append(render_json(inner, 4))

        traumas = row.get("traumas") or {}
        contradictions = row.get("contradictions") or {}
        tc = {}
        if traumas: tc["关键创伤"] = traumas
        if contradictions: tc["内在矛盾"] = contradictions
        if tc:
            parts.append("### 创伤与矛盾")
            parts.append("")
            parts.append(render_json(tc, 4))

        rels = extras.get("relationships", [])
        ap = row.get("arc_description") or {}
        ia = {}
        if rels: ia["关系网络"] = rels
        if ap: ia["弧线潜能"] = ap
        if ia:
            parts.append("### 人际与弧线")
            parts.append("")
            parts.append(render_json(ia, 4))

        sections.append("\n".join(parts))

    return "# 角色档案\n\n" + "\n\n---\n\n".join(sections) + "\n"


def render_character(book_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT name, role, gender, age, aliases, world_position, extras, beliefs, "
        "surface_goal, deep_desire, deep_fear, secrets, bottom_line, "
        "traumas, contradictions, arc_description "
        "FROM character WHERE book_id = %s ORDER BY created_at", (book_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        print(f"[db_sync] 错误：book {book_id} 的 character 表无数据", file=sys.stderr)
        sys.exit(1)
    return _render_character_md(rows)


def render_character_json(book_id: str) -> str:
    """输出角色全量 JSON，供 Trimmer 消费后裁剪再渲染给写手。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT name, role, gender, age, aliases, world_position, extras, beliefs, "
        "surface_goal, deep_desire, deep_fear, secrets, bottom_line, "
        "traumas, contradictions, arc_description "
        "FROM character WHERE book_id = %s ORDER BY created_at", (book_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        print(f"[db_sync] 错误：book {book_id} 的 character 表无数据", file=sys.stderr)
        sys.exit(1)
    # RealDictCursor 返回的 jsonb 字段已经是 Python dict，直接序列化
    import json
    return json.dumps({"characters": list(rows)}, ensure_ascii=False, indent=2)


def _render_voice_md(rows: list[dict]) -> str:
    """纯渲染：voice 行列表 → voice MD"""
    sections = []
    for row in rows:
        name = row["name"]
        voice = row["voice"] or {}
        parts = [f"## {name}", "", render_json(voice, 3, VOICE_FIELD_ORDER)]
        sections.append("\n".join(parts))
    return "# 角色声音锚\n\n" + "\n\n---\n\n".join(sections) + "\n"


def render_voice(book_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT name, voice FROM character WHERE book_id = %s AND voice IS NOT NULL ORDER BY created_at",
        (book_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        print(f"[db_sync] 错误：book {book_id} 无角色声线数据", file=sys.stderr)
        sys.exit(1)
    return _render_voice_md(rows)


def _render_style_md(data: dict) -> str:
    """纯渲染：style_profile dict → style MD"""
    return "# 风格档案\n\n" + render_json(data, 2, STYLE_FIELD_ORDER) + "\n"


def render_style(book_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT style_profile FROM book WHERE id = %s", (book_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or not row["style_profile"]:
        print(f"[db_sync] 错误：book {book_id} 无 style_profile 数据", file=sys.stderr)
        sys.exit(1)
    return _render_style_md(row["style_profile"])


def _render_story_plan_md(data: dict) -> str:
    """纯渲染：story_plan dict → story plan MD。三层冰山各有 essence 定调句。"""
    parts = ["# 故事规划"]
    layer_titles = {"surface": "显性层", "engine": "引擎层", "payoff": "兑现层"}
    for key in ("surface", "engine", "payoff"):
        layer = data.get(key, {})
        if not layer:
            continue
        title = layer_titles.get(key, key)
        parts.append(f"## {title}")
        essence = layer.get("essence", "").strip()
        if essence:
            parts.append(f"> {essence}")
        # 渲染剩余字段（排除 essence）
        rest = {k: v for k, v in layer.items() if k != "essence"}
        if rest:
            parts.append(render_json(rest, 3, STORY_PLAN_FIELD_ORDER))
    # 渲染 constraints 和 issues
    for key in ("constraints", "issues"):
        val = data.get(key)
        if val:
            parts.append(f"## {key}")
            parts.append(render_json(val, 3, STORY_PLAN_FIELD_ORDER))
    return "\n\n".join(parts) + "\n"


def render_story_plan(book_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT story_plan FROM book WHERE id = %s", (book_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or not row["story_plan"]:
        print(f"[db_sync] 错误：book {book_id} 无 story_plan 数据", file=sys.stderr)
        sys.exit(1)
    return _render_story_plan_md(row["story_plan"])


# ═══════════════════════════════════════════════════════════
#  特殊渲染（hooks/debts 状态分区、outline 追加逻辑）
# ═══════════════════════════════════════════════════════════

HOOK_STATUS_TITLES = {
    "open": "未激活", "progressing": "进行中",
    "near_payoff": "即将回收", "resolved": "已完成",
}


def _render_hooks_md(rows: list[dict]) -> str:
    """纯渲染：list[dict] → hooks MD（兼容 DB 的 item_id 和 JSON 的 id 字段）"""
    sections = {"open": [], "progressing": [], "near_payoff": [], "resolved": []}
    for r in rows:
        s = r.get("status", "open")
        if s in sections:
            sections[s].append(r)

    parts = ["# 伏笔列表"]
    for status, items in sections.items():
        if not items:
            continue
        parts.extend([f"## {HOOK_STATUS_TITLES[status]}（{len(items)} 条）", ""])
        parts.append("| ID | 描述 | 首次出现 | 预期回收 | 最近推进 | 回收 | 来源 |")
        parts.append("|----|------|---------|---------|---------|------|------|")
        for h in items:
            parts.append(
                f"| {h.get('id', h.get('item_id', '?'))} | {h.get('description', '——')} | "
                f"{h.get('chapter_created', '?')} | {h.get('expected_payoff', '——')} | "
                f"{h.get('last_advanced') or '——'} | {h.get('chapter_resolved') or '——'} | "
                f"{h.get('source', '大纲导演')} |"
            )
        parts.append("")
    return clean("\n".join(parts))


def render_hooks(book_id: str) -> str | None:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT item_id, description, status, chapter_created, chapter_resolved, "
        "expected_payoff, last_advanced, source "
        "FROM hook WHERE book_id = %s ORDER BY item_id", (book_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return None
    return _render_hooks_md(rows)


def _render_debts_md(rows: list[dict]) -> str:
    """纯渲染：list[dict] → debts MD（兼容 DB 和 JSON 的字段名差异）"""
    sections = {"open": [], "resolved": []}
    for r in rows:
        s = r.get("status", "open")
        if s in sections:
            sections[s].append(r)

    parts = ["# 叙事债务"]
    for status, items in sections.items():
        if not items:
            continue
        title = "未清算" if status == "open" else "已清算"
        parts.extend([f"## {title}（{len(items)} 条）", ""])
        parts.append("| ID | 描述 | 债务人 | 债权人 | 产生章 | 预期回收 | 清算章 | 来源 |")
        parts.append("|----|------|--------|--------|--------|---------|--------|------|")
        for d in items:
            parts.append(
                f"| {d.get('id', d.get('item_id', '?'))} | {d.get('description', '——')} | "
                f"{d.get('from', d.get('from_char', '——'))} | {d.get('to', d.get('to_char', '——'))} | "
                f"{d.get('chapter_created', '?')} | {d.get('expected_payoff', '——')} | "
                f"{d.get('chapter_resolved') or '——'} | {d.get('source', '大纲导演')} |"
            )
        parts.append("")
    return clean("\n".join(parts))


def render_debts(book_id: str) -> str | None:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT item_id, description, status, chapter_created, chapter_resolved, "
        "expected_payoff, last_advanced, source, from_char, to_char "
        "FROM debt WHERE book_id = %s ORDER BY item_id", (book_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return None
    return _render_debts_md(rows)


# ═══════════════════════════════════════════════════════════
#  Outline 渲染（特殊：多卷拼接 / 追加覆盖逻辑）
# ═══════════════════════════════════════════════════════════

def _render_volume_outline_md(rows: list[dict]) -> str:
    """纯渲染：outline 行列表 → volume outline MD"""
    parts = ["# 卷大纲"]
    for row in rows:
        data = row["content"] if isinstance(row["content"], dict) else json.loads(row["content"])
        parts.append(_render_single_volume(data))
    return "\n\n".join(parts) + "\n"


def render_volume_outline(book_id: str) -> str | None:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT volume_number, content FROM outline "
        "WHERE book_id = %s AND type = 'volume' ORDER BY volume_number",
        (book_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return None
    return clean(_render_volume_outline_md(rows))


def _render_single_volume(data: dict) -> str:
    vn = data.get("volume_number", "?")
    title = data.get("title", "?")
    cr = data.get("chapter_range", {})
    start, end = cr.get("start", "?"), cr.get("end", "?")
    lines = [
        f"## 卷{vn} · {title}（第{start}-{end}章）", "",
        f"### 本卷定位", data.get("positioning", "——"),
    ]
    acts = data.get("acts", {})
    if acts:
        labels = [("establish", "第一幕·建立"), ("confront", "第二幕·对抗"), ("resolve", "第三幕·收束")]
        lines.extend(["", "### 三幕功能标注"])
        for key, label in labels:
            a = acts.get(key, {})
            if a:
                lines.append(f"- **{label}**（约{a.get('chapters', '?')}）：{a.get('content', '——')}")

    c = data.get("conflicts", {})
    lines.extend(["", "### 核心冲突",
        f"- **外部**：{c.get('external', '——')}",
        f"- **内部**：{c.get('internal', '——')}",
        f"- **底层**：{c.get('underlying', '——')}"])

    nodes = data.get("nodes", [])
    if nodes:
        lines.extend(["", "### 本卷关键节点"])
        for n in nodes:
            lines.append(f"- 节点{n.get('id', '?')}：{n.get('description', '——')} → 代价/后果：{n.get('consequence', '——')}")

    chars = data.get("characters", [])
    if chars:
        lines.extend(["", "### 本卷出场角色"])
        for ch in chars:
            lines.append(f"- **{ch.get('name', '?')}**：{ch.get('identity', '——')}")
            lines.append(f"  - 叙事功能：{ch.get('narrative_function', '——')}")

    ending = data.get("ending", {})
    lines.extend(["", "### 卷末落点", "本卷结束时：",
        f"- 角色状态：{ending.get('character_state', '——')}",
        f"- 悬念遗留：{ending.get('suspense', '——')}",
        f"- 情绪余韵：{ending.get('emotional_aftertaste', '——')}"])
    st = data.get("style_tone", "")
    if st:
        lines.extend(["", "### 风格基调", st])
    return "\n".join(lines)


def render_near_term(book_id: str) -> str | None:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT content FROM outline WHERE book_id = %s AND type = 'near_term' "
        "ORDER BY volume_number DESC LIMIT 1", (book_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    data = row["content"] if isinstance(row["content"], dict) else json.loads(row["content"])
    return clean(_render_near_term_md(data))


def _render_near_term_md(data: dict) -> str:
    cr = data.get("chapter_range") or {}
    chapters = data.get("chapters", [])
    # 如果 chapter_range 为空，从 chapters 数组推断
    start = cr.get("start") or (chapters[0].get("number") if chapters else "?")
    end = cr.get("end") or (chapters[-1].get("number") if chapters else "?")
    arc = data.get("arc_name", "")
    lines = [f"# 近期大纲（第{start}-{end}章）"]
    if arc:
        lines.extend(["", f"## 当前弧线 · {arc}"])
    for ch in data.get("chapters", []):
        n = ch.get("number", "?")
        title = ch.get("title", "")
        lines.extend([
            "", f"### 第{n}章 · {title}",
            f"- **情节摘要**：{ch.get('summary', '——')}",
            f"- **节奏**：{ch.get('rhythm', '——')}",
            f"- **世界时间推进**：{ch.get('time_advance', '?')}",
        ])
    char_arcs = data.get("character_arcs", [])
    if char_arcs:
        lines.extend(["", "## 角色弧线"])
        for ca in char_arcs:
            lines.append(f"- **{ca.get('name', '?')}**：{ca.get('from', '?')} → {ca.get('to', '?')} → {ca.get('change', '?')}")
    dp = data.get("decision_points", [])
    if dp:
        lines.extend(["", "## 关键决策点"])
        for d in dp:
            lines.append(f"- 第{d.get('chapter', '?')}章：{d.get('character', '?')}面临{d.get('choice', '?')}，将影响{d.get('impact', '?')}")
    return "\n".join(lines) + "\n"


def _render_near_term_we_md(data: dict) -> str:
    """近纲裁剪版：只保留章节摘要+时间推进，供世界状态机消费。"""
    cr = data.get("chapter_range") or {}
    chapters = data.get("chapters", [])
    start = cr.get("start") or (chapters[0].get("number") if chapters else "?")
    end = cr.get("end") or (chapters[-1].get("number") if chapters else "?")
    arc = data.get("arc_name", "")
    lines = [f"# 近期大纲 · 世界引擎用（第{start}-{end}章）"]
    if arc:
        lines.extend(["", f"## 当前弧线 · {arc}"])
    for ch in data.get("chapters", []):
        n = ch.get("number", "?")
        title = ch.get("title", "")
        lines.extend([
            "", f"### 第{n}章 · {title}",
            f"- **情节摘要**：{ch.get('summary', '——')}",
            f"- **世界时间推进**：{ch.get('time_advance', '?')}",
        ])
    return "\n".join(lines) + "\n"


def render_near_term_we(book_id: str) -> str | None:
    """世界引擎用近纲：章节摘要+时间推进，无角色弧线/关键决策点。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT content FROM outline WHERE book_id = %s AND type = 'near_term' "
        "ORDER BY volume_number DESC LIMIT 1", (book_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    data = row["content"] if isinstance(row["content"], dict) else json.loads(row["content"])
    return clean(_render_near_term_we_md(data))


# ═══════════════════════════════════════════════════════════
#  上一章 / 本章 渲染（从 chapter 表）
# ═══════════════════════════════════════════════════════════

def _chapter_json(book_id, chapter, column) -> dict | None:
    """读 chapter 表某列的 JSON，chapter=0 返回 None。"""
    if not chapter:
        return None
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        f"SELECT {column} FROM chapter WHERE book_id = %s AND chapter_number = %s",
        (book_id, chapter),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or not row[column]:
        return None
    return row[column] if isinstance(row[column], (dict, list)) else json.loads(row[column])


def _render_prev_ws(data, ch):
    return f"# 世界状态 · 第{ch}章\n\n" + render_json(data, 2, WORLD_STATE_FIELD_ORDER)


def _render_prev_we(data, ch):
    return f"# 世界事件 · 第{ch}章\n\n" + render_json(data, 2, WORLD_EVENTS_FIELD_ORDER)


def _render_prev_cs(data, ch):
    return render_character_state_md(data, ch)


def _render_minor(data, ch):
    """渲染次要角色注册表为表格（字段 schema 由 CM 固定，12 字段）。"""
    if not isinstance(data, list) or not data:
        return f"# 次要角色注册表 · 第{ch}章\n\n(无数据)\n"

    header = "| 角色 | 状态 | 出场 | 身份 | 标签 | 与主角 | 约束 |"
    sep    = "|------|------|------|------|------|--------|------|"

    status_text = {"alive": "存活", "dead": "死亡", "departed": "离场", "unknown": "未知"}
    rows = []
    for m in data:
        name = m.get("name", "?")
        status = status_text.get(m.get("status", ""), "?")

        # 出场：首次 -> 最后（合并两列）
        fa = m.get("first_appearance", {})
        la = m.get("last_appearance", {})
        if isinstance(fa, dict) and isinstance(la, dict):
            f_str = f"Ch.{fa.get('chapter','?')} {fa.get('scene','?')}"
            l_str = f"Ch.{la.get('chapter','?')} {la.get('note','?')}"
            appear = f"{f_str} -> {l_str}" if f_str != l_str else f_str
        else:
            appear = str(fa) if fa else "-"

        role = m.get("story_role", "-")
        tags = ", ".join(m.get("key_tags", [])) if m.get("key_tags") else "-"
        rel  = m.get("relation_to_protagonist", "-")

        # 约束：回归约束 + 死因 + 待兑现
        constraints = []
        if m.get("return_constraints"):
            constraints.append(m['return_constraints'])
        if m.get("death_detail"):
            constraints.append(m['death_detail'])
        if m.get("pending_promises"):
            constraints.append(m['pending_promises'])
        c_str = "；".join(constraints) if constraints else "-"

        rows.append(f"| {name} | {status} | {appear} | {role} | {tags} | {rel} | {c_str} |")

    return clean(f"# 次要角色注册表 · 第{ch}章\n\n{header}\n{sep}\n" + "\n".join(rows) + "\n")


def _render_diff_world(data, ch):
    """后验·世界事实裁决 → MD"""
    if not data:
        return f"# 世界事实裁决 · 第{ch}章\n\n(无数据)\n"
    if isinstance(data, dict):
        data = data.get("entries", [])
    lines = [f"# 世界事实裁决 · 第{ch}章", ""]
    icon = {"adopt": "[通过]", "pending": "[待定]", "conflict": "[冲突]"}
    for e in data:
        lines.append(f"- {icon.get(e.get('verdict',''), '')} {e.get('fact', '?')}")
    return clean("\n".join(lines)) + "\n"


def _render_diff_story(data, ch):
    """后验·故事差异确认 → MD"""
    if not data:
        return f"# 故事差异确认 · 第{ch}章\n\n(无数据)\n"
    lines = [f"# 故事差异确认 · 第{ch}章", ""]
    labels = {"landed": "已落地", "missed": "未落地", "deviated": "偏离", "unplanned": "计划外"}
    for section in ["landed", "missed", "deviated", "unplanned"]:
        items = data.get(section, []) if isinstance(data, dict) else []
        if not items:
            continue
        lines.append(f"## {labels.get(section, section)}")
        for it in items:
            if section == "landed":
                lines.append(f"- {it.get('planned', '?')} — {it.get('evidence', '')}")
            elif section == "missed":
                lines.append(f"- {it.get('planned', '?')} — {it.get('note', '')}")
            elif section == "deviated":
                lines.append(f"- 计划：{it.get('planned', '?')} → 实际：{it.get('actual', '?')} [{it.get('judgment', '')}]")
            elif section == "unplanned":
                lines.append(f"- {it.get('event', '?')} — {it.get('suggestion', '')}")
        lines.append("")
    return clean("\n".join(lines)) + "\n"


def _render_diff_char(data, ch):
    """后验·角色差异 → 紧凑 Markdown（省 token）。"""
    if not data or not isinstance(data, dict):
        return f"# 角色差异 · 第{ch}章\n\n(无数据)\n"
    lines = [f"# 角色差异 · 第{ch}章", ""]
    sections = [
        ("new_characters", "新角色", ["name", "role", "evidence", "note"]),
        ("relationship_changes", "关系变化", ["pair", "change", "evidence", "current_state"]),
        ("state_changes", "状态变化", ["character", "field", "from", "to", "evidence"]),
        ("character_items", "角色物品", ["character", "item", "action", "evidence", "note"]),
        ("lifecycle_anomalies", "生命周期异常", ["character", "status", "anomaly", "evidence"]),
    ]
    for key, title, cols in sections:
        items = data.get(key, [])
        if not items:
            continue
        lines.append(f"## {title}")
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join(["------"] * len(cols)) + "|")
        for it in items:
            row = [str(it.get(c, "-")) for c in cols]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    return clean("\n".join(lines)) + "\n"


def _render_guide(data, ch):
    return f"# 单章指导 · 第{ch}章\n\n" + render_json(data, 2, GUIDE_FIELD_ORDER)


# ── 单章指导字段顺序 ──
GUIDE_FIELD_ORDER = [
    "title", "positioning",
    "anchors",  # sub-keys handled by render_json
    "moral_dilemma", "tension_level", "dialogue_ratio", "target_word_count",
    "plot_points", "world_time_advance",
    "info_boundary", "info_voids",
    "hook_ops_summary", "debt_ops_summary",
]

# ── 风格档案字段顺序 ──
STYLE_FIELD_ORDER = [
    "tone",             # 这本书是什么
    "narrative_persona", # 谁在讲
    "references",        # 参考坐标系
    "genre_notes",       # 题材笔法
    "commandments",      # 文风戒律
]

# ── 故事规划字段顺序 ──
STORY_PLAN_FIELD_ORDER = [
    "surface",    # 读者感知层（premise/core_conflict/tone_reference...）
    "engine",     # 引擎层（conflict_engine/progression_loop...）
    "payoff",     # 回收层（tension_archetypes/emotional_rhythm...）
    "constraints", # 硬约束
    "issues",     # 已知问题
]

# ── 世界状态字段顺序 ──
WORLD_STATE_FIELD_ORDER = [
    "world_time",          # 当前世界时间
    "time_advanced_days",  # 本章推进天数
    "forces",              # 势力动态
    "undercurrents",       # 暗线运行
]

# ── 世界事件字段顺序 ──
WORLD_EVENTS_FIELD_ORDER = [
    "world_time",
    "time_advanced_days",
    "on_camera_events",     # 镜头内事件
    "off_camera_events",    # 镜头外事件
    "undercurrent_progress", # 暗线推进
    "power_shift",          # 势力格局变化
]

# ── 角色声音锚字段顺序 ──
VOICE_FIELD_ORDER = [
    "voice_positioning",   # 核心声音定位
    "syntax_fingerprint",  # 句法指纹
    "cognitive_bias",      # 认知偏差
    "emotion_patterns",    # 情绪模式
    "forbidden_speech",    # 禁止说的话
]


# ═══════════════════════════════════════════════════════════
#  角色状态专用渲染（平铺格式，不用通用递归）
# ═══════════════════════════════════════════════════════════

def render_character_state_md(data, chapter) -> str:
    """角色状态专用渲染。平铺格式，深层 JSON 不会产生 ###### 标题。"""
    lines = [f"# 长线角色状态 · 第{chapter}章"]
    for cs in (data if isinstance(data, list) else [data]):
        name = cs.get("name", "未知")
        lines.extend(["", f"## {name}", ""])

        ident = cs.get("identity", {})
        if ident:
            lines.extend([
                "### 身份锚",
                f"- 核心标签：{_v(ident, 'core_tags')}",
                f"- 反差细节：{_v(ident, 'contrast_detail')}",
                f"- 说话风格：{_v(ident, 'speech_style')}",
            ])

        drives = cs.get("drives", {})
        if drives:
            lines.extend(["", "### 本质驱动力",
                f"- 核心欲望：{_v(drives, 'core_desire')}",
                f"- 深层恐惧：{_v(drives, 'deep_fear')}",
                f"- 秘密：{_v(drives, 'secret')}",
                f"- 不可触碰的底线：{_v(drives, 'bottom_line')}",
            ])

        scars = cs.get("scars", [])
        if scars:
            lines.extend(["", "### 创伤层（Scars）",
                "| 伤疤ID | 触发事件 | 触发章 | 心理影响 | 触发词 | 原始强度 | 当前强度 | 状态 |",
                "|--------|---------|--------|---------|--------|---------|---------|------|"])
            for s in scars:
                tw = ", ".join(s.get("trigger_words", [])) or "——"
                lines.append(
                    f"| {s.get('id', '?')} | {_v(s, 'trigger_event')} | {s.get('trigger_chapter', '?')} "
                    f"| {_v(s, 'psychological_impact')} | {tw} | {_v(s, 'original_intensity')} "
                    f"| {_v(s, 'current_intensity')} | {_v(s, 'status')} |")
            lines.append("")

        motivs = cs.get("motivations", [])
        if motivs:
            lines.extend(["", "### 驱动层（Motivations）",
                "| 执念ID | 描述 | 来源事件 | 来源章 | 优先级 | 状态 |",
                "|--------|------|---------|--------|--------|------|"])
            for m in motivs:
                lines.append(
                    f"| {m.get('id', '?')} | {_v(m, 'description')} | {_v(m, 'source_event')} "
                    f"| {m.get('source_chapter', '?')} | {m.get('priority', '?')} | {_v(m, 'status')} |")
            lines.append("")

        rels = cs.get("relationships", [])
        if rels:
            lines.extend(["", "### 关系层",
                "| 关系对象 | 信任 | 冲突 | 亲密 | 依赖 | 表面关系 | 隐藏张力 | 最近变化章 |",
                "|---------|------|------|------|------|---------|---------|-----------|"])
            for r in rels:
                lines.append(
                    f"| {r.get('target', '?')} | {r.get('trust', 0)} | {r.get('conflict', 0)} "
                    f"| {r.get('intimacy', 0)} | {r.get('dependency', 0)} | {_v(r, 'surface_relation')} "
                    f"| {_v(r, 'hidden_tension')} | {r.get('last_change_chapter', '?')} |")
            lines.append("")

        snap = cs.get("snapshot", {})
        if snap:
            lines.extend(["", "### 状态快照",
                f"- 当前位置：{_v(snap, 'location')}",
                f"- 身体状况：{_v(snap, 'physical_state')}",
                f"- 社交处境：{_v(snap, 'social_situation')}",
                f"- 当前目标：{_v(snap, 'current_goal')}",
                f"- 当前限制：{_v(snap, 'current_constraints')}",
                f"- 情绪基调：{_v(snap, 'emotional_baseline')}",
                f"- 持有物：{_v(snap, 'possessions')}",
            ])

        pov = cs.get("pov_firewall", {})
        if pov:
            rc = pov.get("revealed_chapter", "?")
            lines.extend(["", "### POV 防火墙",
                f"- 公开信息：{_v(pov, 'public_info')}",
                f"- 隐藏信息：{_v(pov, 'hidden_info')} — 揭示章：{rc}",
            ])

    return clean("\n".join(lines))


def _v(obj, key, default="——"):
    """取值，空则返回 default"""
    v = obj.get(key, "")
    return v if v else default


PREV_TEMPLATES = {
    "prev_ws": ("world_state", _render_prev_ws, "world_state.md"),
    "prev_we": ("world_events", _render_prev_we, "world_events.md"),
    "prev_cs": ("character_state", _render_prev_cs, "character_state_long.md"),
    "prev_cm": ("character_minor", _render_minor, "character_minor.md"),
    "prev_diff_world": ("world_rulings", _render_diff_world, "diff_world_resolved.md"),
    "prev_diff_story": ("story_confirmed", _render_diff_story, "diff_story_confirmed.md"),
    "prev_diff_char": ("character_diff", _render_diff_char, "diff_character.md"),
}

CURR_TEMPLATES = {
    "guide": ("guide", _render_guide, "single_chapter_guide.md"),
    "cs": ("character_state", _render_prev_cs, "character_state_long.md"),
    "cm": ("character_minor", _render_minor, "character_minor.md"),
    "cur_diff_world": ("world_rulings", _render_diff_world, "diff_world_resolved.md"),
    "cur_diff_story": ("story_confirmed", _render_diff_story, "diff_story_confirmed.md"),
    "cur_diff_char": ("character_diff", _render_diff_char, "diff_character.md"),
}

TEMPLATES = {
    "world": ("meta/world_foundation.md", render_world),
    "character": ("meta/character_profiles.md", render_character),
    "character_json": ("cache/sync/characters.json", render_character_json),
    "voice": ("meta/character_voice.md", render_voice),
    "style": ("meta/style_profile.md", render_style),
    "story_plan": ("meta/story_plan.md", render_story_plan),
    "volume": ("outline/volume_outline.md", render_volume_outline),
    "near_term": ("outline/near_term_outline.md", render_near_term),
    "near_term_we": ("cache/sync/near_term_we.md", render_near_term_we),
    "hooks": ("meta/hooks.md", render_hooks),
    "debts": ("meta/debts.md", render_debts),
    "polish_body": ("story/{chapter}/chapter.md", None),  # 路径含 {chapter}，特殊处理
}


def _render_body_text(data, ch):
    """body 列已是纯文本，直接返回。"""
    return data if data else ""


def render_polish_body(book_id: str, chapter: int) -> str:
    """拉取当前 chapter 正文。polish_record 已废弃，正文真相源为 chapter.body。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT body FROM chapter WHERE book_id = %s AND chapter_number = %s",
        (book_id, chapter),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return (row["body"] if row and row["body"] else "")


# ═══════════════════════════════════════════════════════════
#  sync_up（cache/JSON → DB）
# ═══════════════════════════════════════════════════════════

def _optional(path: str):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _json_hash(data) -> str:
    import hashlib
    payload = json.dumps(data if data is not None else {}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _revision_key_chapter(chapter: int, field: str) -> str:
    return f"{chapter:04d}:{field}"


def _get_chapter_field(cur, book_id, chapter, field):
    cur.execute(
        f"SELECT {field} FROM chapter WHERE book_id = %s AND chapter_number = %s",
        (book_id, chapter),
    )
    row = cur.fetchone()
    if not row:
        return {} if field != "body" else {"body": ""}
    value = row[field]
    if field == "body":
        return {"body": value or ""}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value or {}


def _get_outline_content(cur, book_id, outline_type, volume_number):
    cur.execute(
        "SELECT content FROM outline WHERE book_id = %s AND type = %s AND volume_number = %s",
        (book_id, outline_type, volume_number),
    )
    row = cur.fetchone()
    if not row:
        return {}
    value = row["content"]
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value or {}


def _get_current_version(cur, book_id, resource_type, resource_key):
    cur.execute(
        "SELECT current_version FROM novel_resource_state WHERE book_id = %s AND resource_type = %s AND resource_key = %s",
        (book_id, resource_type, resource_key),
    )
    row = cur.fetchone()
    return int(row["current_version"]) if row else 0


def _insert_revision(cur, book_id, resource_type, resource_key, before, after, source, source_detail=None,
                     workflow_id=None, workflow_task_id=None, metadata=None):
    version = _get_current_version(cur, book_id, resource_type, resource_key) + 1
    before_hash = _json_hash(before)
    after_hash = _json_hash(after)
    changed = before_hash != after_hash
    diff_stats = {"change_ratio": 1 if changed else 0}
    edit_intensity = "rewrite" if changed else "none"
    cur.execute("""
        INSERT INTO novel_resource_revision (
            book_id, resource_type, resource_key, version, base_version, edit_mode,
            source, source_detail, edit_intensity, diff_stats,
            workflow_id, workflow_task_id,
            before_content, after_content, diff, metadata
        ) VALUES (%s,%s,%s,%s,%s,'replace',%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)
        RETURNING id
    """, (
        book_id, resource_type, resource_key, version, version - 1,
        source, source_detail, edit_intensity, json.dumps(diff_stats, ensure_ascii=False),
        workflow_id, workflow_task_id,
        json.dumps(before if before is not None else {}, ensure_ascii=False),
        json.dumps(after if after is not None else {}, ensure_ascii=False),
        json.dumps({"before_hash": before_hash, "after_hash": after_hash}, ensure_ascii=False),
        json.dumps(metadata or {}, ensure_ascii=False),
    ))
    revision_id = cur.fetchone()["id"]
    cur.execute("""
        INSERT INTO novel_resource_state (book_id, resource_type, resource_key, current_version, current_revision_id, content_hash)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (book_id, resource_type, resource_key) DO UPDATE SET
            current_version = EXCLUDED.current_version,
            current_revision_id = EXCLUDED.current_revision_id,
            content_hash = EXCLUDED.content_hash,
            updated_at = now()
    """, (book_id, resource_type, resource_key, version, revision_id, after_hash))
    return revision_id, version


def _upsert_chapter(cur, book_id, chapter, **cols):
    cur.execute(
        "SELECT id FROM chapter WHERE book_id = %s AND chapter_number = %s",
        (book_id, chapter),
    )
    if cur.fetchone():
        if cols:
            set_clause = ", ".join(f"{k} = %s" for k in cols)
            cur.execute(
                f"UPDATE chapter SET {set_clause}, updated_at = now() "
                "WHERE book_id = %s AND chapter_number = %s",
                list(cols.values()) + [book_id, chapter],
            )
        action = "UPDATE"
    else:
        fields = ["book_id", "chapter_number"] + list(cols.keys())
        vals = [book_id, chapter] + list(cols.values())
        cur.execute(
            f"INSERT INTO chapter ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})",
            vals,
        )
        action = "INSERT"
    cur.connection.commit()
    return action


def sync_up(book_id: str, chapter: int, partial: str = "all", workflow_id: str | None = None, workflow_task_id: str | None = None):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if partial in ("all", "we"):
        cols = {}
        for key, path in [("world_state", "cache/we/world_state.json"),
                          ("world_events", "cache/we/world_events.json")]:
            data = _optional(path)
            if data:
                before = _get_chapter_field(cur, book_id, chapter, key)
                _insert_revision(
                    cur, book_id, "chapter", _revision_key_chapter(chapter, key),
                    before, data, "workflow",
                    _workflow_source_detail(workflow_id, f"we:{key}"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )
                cols[key] = json.dumps(data, ensure_ascii=False)
        if cols:
            action = _upsert_chapter(cur, book_id, chapter, **cols)
            print(f"[OK] chapter {chapter} {action} (WE)")
            # Also write a combined "world" revision to keep version aligned with the API
            # (GET/PUT /chapters/{N}/world use resource_key "{chapter}:world")
            ws_data = _optional("cache/we/world_state.json")
            we_data = _optional("cache/we/world_events.json")
            if ws_data or we_data:
                before = {
                    "world_state": _get_chapter_field(cur, book_id, chapter, "world_state"),
                    "world_events": _get_chapter_field(cur, book_id, chapter, "world_events"),
                }
                after = {
                    "world_state": ws_data or before["world_state"],
                    "world_events": we_data or before["world_events"],
                }
                _insert_revision(
                    cur, book_id, "chapter", _revision_key_chapter(chapter, "world"),
                    before, after, "workflow",
                    _workflow_source_detail(workflow_id, "we:world"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )

    if partial in ("all", "od"):
        od_guide = _optional("cache/od/guide.json")
        od_hooks = _optional("cache/od/hooks.json")
        od_debts = _optional("cache/od/debts.json")
        if od_guide:
            before = _get_chapter_field(cur, book_id, chapter, "guide")
            _insert_revision(
                cur, book_id, "chapter", _revision_key_chapter(chapter, "guide"),
                before, od_guide, "workflow",
                _workflow_source_detail(workflow_id, "od:guide"),
                workflow_id=workflow_id, workflow_task_id=workflow_task_id,
            )
            _upsert_chapter(cur, book_id, chapter,
                           guide=json.dumps(od_guide, ensure_ascii=False))
            print(f"[OK] chapter {chapter} UPDATE (guide)")
        if od_hooks:
            for h in od_hooks:
                cur.execute("""
                    INSERT INTO hook (book_id, item_id, description, status, chapter_created,
                        chapter_resolved, expected_payoff, last_advanced, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (book_id, item_id) DO UPDATE SET
                        description=EXCLUDED.description, status=EXCLUDED.status,
                        chapter_resolved=EXCLUDED.chapter_resolved,
                        expected_payoff=EXCLUDED.expected_payoff,
                        last_advanced=EXCLUDED.last_advanced, source=EXCLUDED.source,
                        updated_at=now()
                """, (book_id, h.get("id"), h.get("description"), h.get("status", "open"),
                      h.get("chapter_created"), h.get("chapter_resolved"),
                      h.get("expected_payoff"), h.get("last_advanced"),
                      h.get("source", "大纲导演")))
            conn.commit()
            print(f"[OK] hooks {len(od_hooks)} 条 UPSERT")
        if od_debts:
            for d in od_debts:
                cur.execute("""
                    INSERT INTO debt (book_id, item_id, description, status, chapter_created,
                        chapter_resolved, expected_payoff, last_advanced, source, from_char, to_char)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (book_id, item_id) DO UPDATE SET
                        description=EXCLUDED.description, status=EXCLUDED.status,
                        chapter_resolved=EXCLUDED.chapter_resolved,
                        expected_payoff=EXCLUDED.expected_payoff,
                        last_advanced=EXCLUDED.last_advanced, source=EXCLUDED.source,
                        from_char=EXCLUDED.from_char, to_char=EXCLUDED.to_char, updated_at=now()
                """, (book_id, d.get("id"), d.get("description"), d.get("status", "open"),
                      d.get("chapter_created"), d.get("chapter_resolved"),
                      d.get("expected_payoff"), d.get("last_advanced"),
                      d.get("source", "大纲导演"), d.get("from"), d.get("to")))
            conn.commit()
            print(f"[OK] debts {len(od_debts)} 条 UPSERT")

    if partial in ("all", "cm"):
        cm_states = _optional("cache/cm/character_states.json")
        cm_minor  = _optional("cache/cm/minor_characters.json")
        if cm_states or cm_minor:
            cols = {}
            if cm_states:
                before = _get_chapter_field(cur, book_id, chapter, "character_state")
                _insert_revision(
                    cur, book_id, "chapter", _revision_key_chapter(chapter, "character_state"),
                    before, cm_states, "workflow",
                    _workflow_source_detail(workflow_id, "cm:character_state"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )
                cols["character_state"] = json.dumps(cm_states, ensure_ascii=False)
            if cm_minor:
                before = _get_chapter_field(cur, book_id, chapter, "character_minor")
                _insert_revision(
                    cur, book_id, "chapter", _revision_key_chapter(chapter, "character_minor"),
                    before, cm_minor, "workflow",
                    _workflow_source_detail(workflow_id, "cm:character_minor"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )
                cols["character_minor"] = json.dumps(cm_minor, ensure_ascii=False)
            _upsert_chapter(cur, book_id, chapter, **cols)
            print(f"[OK] chapter {chapter} UPDATE (CM)")

    if partial in ("all", "vo"):
        vo_data = _optional("cache/vo/volume.json")
        if vo_data:
            vo_vn = vo_data.get("volume_number", 0)
            cur.execute(
                "SELECT id FROM outline WHERE book_id = %s AND type = 'volume' AND volume_number = %s",
                (book_id, vo_vn),
            )
            if cur.fetchone():
                before = _get_outline_content(cur, book_id, "volume", vo_vn)
                _insert_revision(
                    cur, book_id, "outline", f"volume:{vo_vn}",
                    before, vo_data, "workflow",
                    _workflow_source_detail(workflow_id, "vo:volume"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )
                cur.execute(
                    "UPDATE outline SET chapter_start=%s, chapter_end=%s, content=%s::jsonb, updated_at=now() "
                    "WHERE book_id=%s AND type='volume' AND volume_number=%s",
                    (vo_data.get("chapter_range", {}).get("start"),
                     vo_data.get("chapter_range", {}).get("end"),
                     json.dumps(vo_data, ensure_ascii=False), book_id, vo_vn),
                )
                conn.commit()
                print(f"[OK] outline volume {vo_vn} UPDATE")
            else:
                _insert_revision(
                    cur, book_id, "outline", f"volume:{vo_vn}",
                    {}, vo_data, "workflow",
                    _workflow_source_detail(workflow_id, "vo:volume"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )
                cur.execute(
                    "INSERT INTO outline (book_id, type, volume_number, chapter_start, chapter_end, content) "
                    "VALUES (%s, 'volume', %s, %s, %s, %s::jsonb)",
                    (book_id, vo_vn,
                     vo_data.get("chapter_range", {}).get("start"),
                     vo_data.get("chapter_range", {}).get("end"),
                     json.dumps(vo_data, ensure_ascii=False)),
                )
                conn.commit()
                print(f"[OK] outline volume {vo_vn} INSERT")

    if partial in ("all", "si"):
        si_body = _optional("cache/si/body.json")
        se_data = _optional("cache/se/se_output.json")
        cols = {}
        if si_body:
            body_text = si_body.get("body", "")
            cols["body"] = body_text
            cols["word_count"] = len(body_text)
            # 从近纲取章节标题
            cur.execute(
                "SELECT content FROM outline WHERE book_id = %s AND type = 'near_term' "
                "ORDER BY volume_number DESC LIMIT 1",
                (book_id,),
            )
            nt_row = cur.fetchone()
            if nt_row and nt_row.get("content"):
                nt_chapters = nt_row["content"].get("chapters", []) if isinstance(nt_row["content"], dict) else []
                for ch in nt_chapters:
                    if ch.get("number") == chapter:
                        cols["title"] = ch.get("title")
                        break
        if se_data:
            cols["storyboard"] = json.dumps(se_data, ensure_ascii=False)
        if cols:
            if si_body:
                before = _get_chapter_field(cur, book_id, chapter, "body")
                after = {"body": si_body.get("body", "") if isinstance(si_body, dict) else str(si_body)}
                _insert_revision(
                    cur, book_id, "chapter", _revision_key_chapter(chapter, "body"),
                    before, after, "workflow",
                    _workflow_source_detail(workflow_id, "si:body"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )
            if se_data:
                before = _get_chapter_field(cur, book_id, chapter, "storyboard")
                _insert_revision(
                    cur, book_id, "chapter", _revision_key_chapter(chapter, "storyboard"),
                    before, se_data, "workflow",
                    _workflow_source_detail(workflow_id, "si:storyboard"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )
            _upsert_chapter(cur, book_id, chapter, **cols)
            print(f"[OK] chapter {chapter} UPDATE (SI)")

    if partial in ("all", "no"):
        no_data = _optional("cache/no/near_term.json")
        if no_data:
            no_vn = no_data.get("volume_number", 0)
            cr = no_data.get("chapter_range", {}) or {}
            new_chapters = no_data.get("chapters", [])
            cur.execute(
                "SELECT content FROM outline WHERE book_id = %s AND type = 'near_term' AND volume_number = %s",
                (book_id, no_vn),
            )
            row = cur.fetchone()
            if row:
                old_data = row["content"] if isinstance(row["content"], dict) else json.loads(row["content"])
                old_chapters = old_data.get("chapters", [])
                old_numbers = {ch.get("number") for ch in old_chapters}
                added = 0
                for ch in new_chapters:
                    if ch.get("number") not in old_numbers:
                        old_chapters.append(ch)
                        added += 1
                if added:
                    before = row["content"] if isinstance(row["content"], dict) else json.loads(row["content"])
                    old_data["chapters"] = old_chapters
                    _insert_revision(
                        cur, book_id, "outline", f"near_term:{no_vn}",
                        before, old_data, "workflow",
                        _workflow_source_detail(workflow_id, "no:near_term"),
                        workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                    )
                    cur.execute(
                        "UPDATE outline SET content = %s::jsonb, updated_at = now() "
                        "WHERE book_id = %s AND type = 'near_term' AND volume_number = %s",
                        (json.dumps(old_data, ensure_ascii=False), book_id, no_vn),
                    )
                    print(f"[OK] outline near_term 合并 +{added} 章")
                else:
                    print(f"[OK] outline near_term 无新增章，跳过")
            else:
                _insert_revision(
                    cur, book_id, "outline", f"near_term:{no_vn}",
                    {}, no_data, "workflow",
                    _workflow_source_detail(workflow_id, "no:near_term"),
                    workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                )
                cur.execute(
                    "INSERT INTO outline (book_id, type, volume_number, chapter_start, chapter_end, content) "
                    "VALUES (%s, 'near_term', %s, %s, %s, %s::jsonb)",
                    (book_id, no_vn, cr.get("start"), cr.get("end"),
                     json.dumps(no_data, ensure_ascii=False)),
                )
                print(f"[OK] outline near_term INSERT")
            conn.commit()

    if partial in ("all", "ph"):
        arb = _optional("cache/arbiter/arb_output.json")
        obs = _optional("cache/observer/obs_output.json")
        if arb or obs:
            cols = {}
            if arb:
                if arb.get("world_rulings"):
                    cols["world_rulings"] = json.dumps(arb["world_rulings"], ensure_ascii=False)
                    print(f"  world_rulings: {len(arb['world_rulings'].get('entries',[]))} entries")
                if arb.get("story_confirmed"):
                    sc = arb["story_confirmed"]
                    cols["story_confirmed"] = json.dumps(sc, ensure_ascii=False)
                    print(f"  story_confirmed: landed={len(sc.get('landed',[]))} missed={len(sc.get('missed',[]))} deviated={len(sc.get('deviated',[]))} unplanned={len(sc.get('unplanned',[]))}")
            if obs:
                cd = obs.get("character_diff")
                if cd:
                    cols["character_diff"] = json.dumps(cd, ensure_ascii=False)
                    nc = len(cd.get("new_characters", []))
                    rc = len(cd.get("relationship_changes", []))
                    sc = len(cd.get("state_changes", []))
                    print(f"  character_diff: new_chars={nc} rel_changes={rc} state_changes={sc}")
            if cols:
                for field, value in cols.items():
                    before = _get_chapter_field(cur, book_id, chapter, field)
                    after = json.loads(value) if isinstance(value, str) else value
                    _insert_revision(
                        cur, book_id, "chapter", _revision_key_chapter(chapter, field),
                        before, after, "workflow",
                        _workflow_source_detail(workflow_id, f"ph:{field}"),
                        workflow_id=workflow_id, workflow_task_id=workflow_task_id,
                    )
                _upsert_chapter(cur, book_id, chapter, **cols)
                print(f"[OK] chapter {chapter} UPDATE (PH)")
            # hooks/debts
            for h in arb.get("new_hooks", []):
                hid = h.get("id")
                if not hid:
                    print(f"[WARN] hook 缺 id，跳过: {h.get('description', '?')[:50]}", file=sys.stderr)
                    continue
                cur.execute("""
                    INSERT INTO hook (book_id, item_id, description, status, chapter_created,
                        expected_payoff, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (book_id, item_id) DO UPDATE SET
                        description=EXCLUDED.description, status=EXCLUDED.status,
                        expected_payoff=EXCLUDED.expected_payoff, source=EXCLUDED.source,
                        updated_at=now()
                """, (book_id, hid, h.get("description"), h.get("status", "open"),
                      h.get("chapter_created"), h.get("expected_payoff"), h.get("source", "后验")))
            if arb.get("new_hooks"):
                conn.commit()
                print(f"[OK] hooks +{len(arb['new_hooks'])} (后验)")
            for d in arb.get("new_debts", []):
                did = d.get("id")
                if not did:
                    print(f"[WARN] debt 缺 id，跳过: {d.get('description', '?')[:50]}", file=sys.stderr)
                    continue
                cur.execute("""
                    INSERT INTO debt (book_id, item_id, description, status, chapter_created,
                        expected_payoff, source, from_char, to_char)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (book_id, item_id) DO UPDATE SET
                        description=EXCLUDED.description, status=EXCLUDED.status,
                        expected_payoff=EXCLUDED.expected_payoff, source=EXCLUDED.source,
                        from_char=EXCLUDED.from_char, to_char=EXCLUDED.to_char,
                        updated_at=now()
                """, (book_id, did, d.get("description"), d.get("status", "open"),
                      d.get("chapter_created"), d.get("expected_payoff"), d.get("source", "后验"),
                      d.get("from"), d.get("to")))
            if arb.get("new_debts"):
                conn.commit()
                print(f"[OK] debts +{len(arb['new_debts'])} (后验)")

    cur.close()
    conn.close()
    print("[OK] sync_up 完成")


def sync_polish(book_id: str, chapter: int, workflow_id: str | None = None, workflow_task_id: str | None = None):
    """润色落库：PP 终稿 + SC 自审 → revision + chapter.body。"""
    body_file = "cache/pp/body.json"
    critique_file = "cache/sc/critique.json"

    if not os.path.exists(body_file):
        print(f"[db_sync] polish 跳过：{body_file} 不存在", file=sys.stderr)
        return

    with open(body_file, "r", encoding="utf-8") as f:
        pp_data = json.load(f)
    body = pp_data.get("body", "") if isinstance(pp_data, dict) else str(pp_data)
    critique = _optional(critique_file)

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT body FROM chapter WHERE book_id = %s AND chapter_number = %s",
        (book_id, chapter),
    )
    row = cur.fetchone()
    before = {"body": row["body"] if row and row["body"] else ""}
    after = {"body": body}
    _insert_revision(
        cur, book_id, "chapter", _revision_key_chapter(chapter, "body"),
        before, after, "polish",
        _workflow_source_detail(workflow_id, "professional_polisher"),
        workflow_id=workflow_id, workflow_task_id=workflow_task_id,
        metadata={"critique": critique or {}}
    )
    _upsert_chapter(cur, book_id, chapter, body=body, word_count=len(body), status="completed")
    conn.commit()
    cur.close()
    conn.close()
    print(f"[OK] polish revision + chapter.body UPDATE (ch.{chapter}, {len(body)} chars)")


# ═══════════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="DB ↔ 文件同步 + JSON→MD 渲染")
    parser.add_argument("--book-id", required=True, help="书 UUID")
    parser.add_argument("--chapter", type=int, help="章节号")
    parser.add_argument("--prev-chapter", type=int, default=0, help="上一章节号")
    parser.add_argument("--templates", default="world", help="模板名，逗号分隔")
    parser.add_argument("--direction", default="down", choices=["down", "up", "polish"], help="down=DB→文件, up=文件→DB, polish=润色终稿入库")
    parser.add_argument("--partial", default="all",
                       choices=["all", "we", "od", "cm", "si", "vo", "no", "ph"], help="部分落库模式")
    parser.add_argument("--render", default="", help="纯渲染模式：输入 JSON 文件路径，逗号分隔多文件")
    parser.add_argument("--output", default="", help="纯渲染模式的输出 MD 路径，逗号分隔（与 --render 一一对应）")
    parser.add_argument("--workflow-id", default=None, help="内部 workflow_id，可由工作流脚本参数传入")
    parser.add_argument("--workflow-task-id", default=None, help="内部 workflow task_id，可由工作流脚本参数传入")
    args = parser.parse_args()

    if not args.render and args.direction in ("up", "polish") and not args.workflow_id:
        parser.error("--direction up/polish 必须传入 --workflow-id")

    # ── 纯渲染模式 ──
    if args.render:
        renders = [r.strip() for r in args.render.split(",") if r.strip()]
        outputs = [o.strip() for o in args.output.split(",") if o.strip()] if args.output else []
        for i, rpath in enumerate(renders):
            if not os.path.exists(rpath):
                print(f"[db_sync] 跳过：{rpath} 不存在", file=sys.stderr)
                continue
            with open(rpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if i < len(outputs):
                out = outputs[i]
            else:
                out = rpath.replace(".json", ".md")
            # 角色状态专用渲染
            if "character_states" in rpath and isinstance(data, list):
                md = render_character_state_md(data, args.chapter or 0)
            # 次要角色库（list 类型）
            elif "minor_characters" in rpath and isinstance(data, list):
                md = _render_minor(data, args.chapter or 0)
            # guide 使用字段顺序
            elif "guide.json" in rpath and isinstance(data, dict):
                md = render_json(data, 2, GUIDE_FIELD_ORDER)
            # 世界状态
            elif "world_state" in rpath and "world_events" not in rpath and isinstance(data, dict):
                md = render_json(data, 2, WORLD_STATE_FIELD_ORDER)
            # 世界事件
            elif "world_events" in rpath and isinstance(data, dict):
                md = render_json(data, 2, WORLD_EVENTS_FIELD_ORDER)
            # 世界观（6 维度 dict）
            elif "world.json" in rpath and isinstance(data, dict):
                md = _render_world_md(data)
            # 角色档案（list[dict] 或 {"characters": [...]}）
            elif "character" in rpath and "voice" not in rpath:
                if isinstance(data, list):
                    md = _render_character_md(data)
                elif isinstance(data, dict) and "characters" in data:
                    md = _render_character_md(data["characters"])
                else:
                    md = render_json(data, 2)
            # 角色声线（list[dict]）
            elif "voice" in rpath and isinstance(data, list):
                md = _render_voice_md(data)
            # 风格档案（dict）
            elif "style" in rpath and isinstance(data, dict):
                md = _render_style_md(data)
            # 故事引擎（dict）
            elif "story_plan" in rpath and isinstance(data, dict):
                md = _render_story_plan_md(data)
            # 伏笔列表（list[dict]，按状态分区表格）
            elif "hooks" in rpath and isinstance(data, list):
                md = _render_hooks_md(data)
            # 叙事债务（list[dict]，按状态分区表格）
            elif "debts" in rpath and isinstance(data, list):
                md = _render_debts_md(data)
            # 卷大纲（list[dict]）
            elif "volume" in rpath and isinstance(data, list):
                md = _render_volume_outline_md(data)
            # 近纲（dict）
            elif "near_term_we" in rpath and isinstance(data, dict):
                md = _render_near_term_we_md(data)
            elif "near_term" in rpath and isinstance(data, dict):
                md = _render_near_term_md(data)
            else:
                md = render_json(data, 2)
            md = clean(md)
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(md)
            size_kb = len(md.encode("utf-8")) / 1024
            print(f"  [OK] {rpath} → {out} ({size_kb:.1f} KB)")
        return

    # ── polish ──
    if args.direction == "polish":
        if not args.chapter:
            print("[db_sync] --direction polish 需要 --chapter", file=sys.stderr)
            sys.exit(1)
        sync_polish(args.book_id, args.chapter, args.workflow_id, args.workflow_task_id)
        return

    # ── sync_up ──
    if args.direction == "up":
        if not args.chapter and args.partial not in ("vo", "no"):
            print("[db_sync] --direction up 需要 --chapter（vo/no 模式除外）", file=sys.stderr)
            sys.exit(1)
        sync_up(args.book_id, args.chapter or 0, args.partial, args.workflow_id, args.workflow_task_id)
        return

    # ── sync_down ──
    templates = [t.strip() for t in args.templates.split(",") if t.strip()]
    all_templates = list(TEMPLATES) + list(PREV_TEMPLATES) + list(CURR_TEMPLATES)
    for t in templates:
        if t not in TEMPLATES and t not in PREV_TEMPLATES and t not in CURR_TEMPLATES:
            print(f"[db_sync] 未知模板: {t}，可选: {', '.join(all_templates)}", file=sys.stderr)
            sys.exit(1)

    conn = get_conn()
    print("[OK] 已连接数据库")
    cur = conn.cursor()
    cur.execute("SELECT id FROM book WHERE id = %s", (args.book_id,))
    if not cur.fetchone():
        print(f"[db_sync] 错误：book {args.book_id} 不存在", file=sys.stderr)
        sys.exit(1)
    cur.close()
    conn.close()

    for t in templates:
        if t in PREV_TEMPLATES:
            column, render_fn, filename = PREV_TEMPLATES[t]
            data = _chapter_json(args.book_id, args.prev_chapter, column)
            if data is None:
                content = None
            else:
                content = render_fn(data, args.prev_chapter)
            outpath = f"story/{args.prev_chapter:04d}/{filename}"
        elif t in CURR_TEMPLATES:
            column, render_fn, filename = CURR_TEMPLATES[t]
            data = _chapter_json(args.book_id, args.chapter or 0, column)
            if data is None:
                content = None
            else:
                content = render_fn(data, args.chapter or 0)
            outpath = f"story/{(args.chapter or 0):04d}/{filename}"
        else:
            outpath, render_fn = TEMPLATES[t]
            if t == "polish_body":
                # 特殊模板：根据章节号拉取当前正文
                content = render_polish_body(args.book_id, args.chapter or 0)
                outpath = outpath.replace("{chapter}", f"{(args.chapter or 0):04d}")
            else:
                content = render_fn(args.book_id)

        if content is None:
            print(f"  └─ [SKIP] {t}（无数据）")
            continue
        if not t.endswith("_json"):
            content = content.replace("——", "，")
        os.makedirs(os.path.dirname(outpath) or ".", exist_ok=True)
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(content)
        size_kb = len(content.encode("utf-8")) / 1024
        print(f"  └─ [OK] {t} → {outpath} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
