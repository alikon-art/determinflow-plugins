#!/usr/bin/env python3
"""
通用 JSON → 数据库写入脚本

用法: python3 json_to_db.py --book-id <UUID> --action <action> [options]

操作模式:
  upsert-world               批量写入/更新 world 表的 6 个维度
  upsert-world-dimension     写入/更新 world 表的单个维度
  upsert-character-skeleton  写入角色骨架（DELETE 旧行 + INSERT 新行）
  upsert-character-beliefs   更新角色信念列
  upsert-character-deep      更新单个角色的深层维度列
  upsert-character-voice     更新角色声线列
  upsert-characters          批量合并写入角色（旧版，已由上述四个 action 替代）
  upsert-story-plan          写入 story_plan
  upsert-style-profile       写入 style_profile
  upsert-book                写入 story_plan + style_profile（旧接口，保留兼容）

环境变量:
  DB_HOST     (默认 127.0.0.1)
  DB_PORT     (默认 5432)
  DB_NAME     (默认 novel_platform)
  DB_USER     (默认 postgres)
  DB_PASSWORD (必填)
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, RealDictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _secret_files import read_secret  # noqa: E402


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "novel_platform"),
        user=os.environ.get("DB_USER", "postgres"),
        password=read_secret("DB_PASSWORD"),
    )


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dumps(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def content_hash(value):
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def workflow_source_detail(workflow_id, suffix):
    if not workflow_id:
        raise ValueError("写入 revision 时必须传入 workflow_id")
    return f"{workflow_id}:{suffix}"


def get_current_version(cur, book_id, resource_type, resource_key):
    cur.execute(
        "SELECT current_version FROM novel_resource_state WHERE book_id=%s AND resource_type=%s AND resource_key=%s",
        (book_id, resource_type, resource_key),
    )
    row = cur.fetchone()
    return int(row["current_version"]) if row else 0


def insert_revision(cur, book_id, resource_type, resource_key, before, after, source, source_detail=None,
                    workflow_id=None, workflow_task_id=None, metadata=None):
    version = get_current_version(cur, book_id, resource_type, resource_key) + 1
    before_hash = content_hash(before)
    after_hash = content_hash(after)
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
        source, source_detail, edit_intensity, dumps(diff_stats),
        workflow_id, workflow_task_id,
        dumps(before), dumps(after), dumps({"before_hash": before_hash, "after_hash": after_hash}),
        dumps(metadata or {}),
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


def as_plain(value):
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


# ══════════════════════════════════════════════
# upsert-world: 批量写入 6 个世界观维度
# ══════════════════════════════════════════════

WORLD_DIMENSIONS = [
    "core_laws",
    "space_time",
    "society",
    "history_culture",
    "existence",
    "information",
]

DIM_TO_COL = {d: d for d in WORLD_DIMENSIONS}


def upsert_world(book_id, file_map, workflow_id=None, workflow_task_id=None, source_detail=None):
    """file_map: {dimension_name: file_path}"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 检查 book 是否存在
    cur.execute("SELECT id FROM book WHERE id = %s", (book_id,))
    if not cur.fetchone():
        print(f"[ERROR] book {book_id} 不存在，请先创建书", file=sys.stderr)
        sys.exit(1)

    # 检查 world 行是否存在，并读取 before
    cur.execute("SELECT id, core_laws, space_time, society, history_culture, existence, information FROM world WHERE book_id = %s", (book_id,))
    existing = cur.fetchone()

    loaded = {}
    for dim in WORLD_DIMENSIONS:
        if dim in file_map:
            data = load_json(file_map[dim])
            if isinstance(data, dict) and dim in data:
                data = data[dim]
            loaded[dim] = data

    if existing:
        # UPDATE 已存在的列
        set_clauses = []
        values = []
        for dim in WORLD_DIMENSIONS:
            if dim in loaded:
                set_clauses.append(f"{dim} = %s")
                values.append(Json(loaded[dim]))
        if not set_clauses:
            print("[SKIP] 无文件可更新")
            return

        values.append(book_id)
        sql = f"UPDATE world SET {', '.join(set_clauses)}, updated_at = now() WHERE book_id = %s"
        cur.execute(sql, values)
        print(f"[UPDATE] world 表更新了 {len(set_clauses)} 个维度: {', '.join(file_map.keys())}")
    else:
        # INSERT 新行
        columns = ["book_id"] + [dim for dim in WORLD_DIMENSIONS if dim in loaded]
        placeholders = ["%s"] * len(columns)
        values = [book_id]
        for dim in WORLD_DIMENSIONS:
            if dim in loaded:
                values.append(Json(loaded[dim]))

        sql = f"INSERT INTO world ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        cur.execute(sql, values)
        print(f"[INSERT] world 表新增 {len(file_map)} 个维度: {', '.join(file_map.keys())}")

    for dim, after in loaded.items():
        before = as_plain(existing[dim]) if existing else {}
        insert_revision(
            cur, book_id, "world", dim, before, after, "workflow",
            source_detail
            or workflow_source_detail(workflow_id, "json_to_db:upsert-world"),
            workflow_id=workflow_id,
            workflow_task_id=workflow_task_id,
        )

    conn.commit()
    cur.close()
    conn.close()


def upsert_world_dimension(book_id, dimension, file_path, workflow_id=None, workflow_task_id=None, source_detail=None):
    """写入/更新 world 表单个维度，并同步 revision/state。"""
    if dimension not in WORLD_DIMENSIONS:
        print(f"[ERROR] 未知世界观维度: {dimension}", file=sys.stderr)
        sys.exit(1)
    if not file_path:
        print("[ERROR] upsert-world-dimension 需要一个 JSON 文件路径", file=sys.stderr)
        sys.exit(1)

    data = load_json(file_path)
    if isinstance(data, dict) and dimension in data:
        data = data[dimension]

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id FROM book WHERE id = %s", (book_id,))
    if not cur.fetchone():
        print(f"[ERROR] book {book_id} 不存在，请先创建书", file=sys.stderr)
        sys.exit(1)

    cur.execute(
        "SELECT id, core_laws, space_time, society, history_culture, existence, information FROM world WHERE book_id = %s",
        (book_id,),
    )
    existing = cur.fetchone()
    before = as_plain(existing[dimension]) if existing else {}

    if existing:
        cur.execute(f"UPDATE world SET {dimension} = %s, updated_at = now() WHERE book_id = %s", (Json(data), book_id))
        print(f"[UPDATE] world.{dimension} 已更新")
    else:
        cur.execute(
            f"INSERT INTO world (book_id, {dimension}) VALUES (%s, %s)",
            (book_id, Json(data)),
        )
        print(f"[INSERT] world.{dimension} 已创建")

    insert_revision(
        cur, book_id, "world", dimension, before, data, "workflow",
        source_detail
        or workflow_source_detail(
            workflow_id,
            f"json_to_db:upsert-world-dimension:{dimension}",
        ),
        workflow_id=workflow_id,
        workflow_task_id=workflow_task_id,
        metadata={"dimension": dimension, "content_available": True},
    )

    conn.commit()
    cur.close()
    conn.close()


# ══════════════════════════════════════════════
# upsert-characters: 合并写入 character 表
# ══════════════════════════════════════════════

def upsert_characters(book_id, skeleton_path, beliefs_path, deep_dir, voice_path=None,
                      workflow_id=None, workflow_task_id=None, source_detail=None):
    """从 skeleton.json + beliefs.json + {name}_deep.json + voice.json 合并写入 character 表。

    deep_dir: 存放 {name}_deep.json 的目录
    voice_path: voice.json 文件路径（可选）
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 检查 book 是否存在
    cur.execute("SELECT id FROM book WHERE id = %s", (book_id,))
    if not cur.fetchone():
        print(f"[ERROR] book {book_id} 不存在", file=sys.stderr)
        sys.exit(1)

    # 加载数据源
    skeleton = load_json(skeleton_path)
    beliefs_list = load_json(beliefs_path).get("beliefs", [])
    beliefs_map = {b["character"]: b for b in beliefs_list}

    voice_map = {}
    if voice_path and os.path.exists(voice_path):
        voice_data = load_json(voice_path)
        for vc in voice_data.get("characters", []):
            voice_map[vc["name"]] = {
                "voice_positioning": vc.get("voice_positioning", ""),
                "syntax_fingerprint": vc.get("syntax_fingerprint", {}),
                "cognitive_bias": vc.get("cognitive_bias", ""),
                "forbidden_speech": vc.get("forbidden_speech", []),
                "emotion_patterns": vc.get("emotion_patterns", {}),
            }

    cur.execute("SELECT * FROM character WHERE book_id = %s", (book_id,))
    before_map = {row["name"]: dict(row) for row in cur.fetchall()}

    # 删除该书旧角色数据
    cur.execute("DELETE FROM character WHERE book_id = %s", (book_id,))
    deleted = cur.rowcount
    if deleted:
        print(f"[DELETE] 清除旧角色 {deleted} 行")

    inserted = 0
    for char in skeleton.get("characters", []):
        name = char["name"]
        if not name:
            continue

        # 加载深层维度
        deep_path = os.path.join(deep_dir, f"{name}_deep.json")
        deep = {}
        if os.path.exists(deep_path):
            deep = load_json(deep_path)

        # 信念
        belief = beliefs_map.get(name, {})
        beliefs_data = {
            "core_belief": belief.get("core_belief", ""),
            "belief_source": belief.get("belief_source", ""),
            "author_perspective": belief.get("author_perspective", "ambiguous"),
        }
        beliefs_json = Json(beliefs_data)

        # 深层维度解包
        core_desire = deep.get("core_desire", {})
        deep_fear = deep.get("deep_fear", {})
        secret = deep.get("secret", {})
        bottom_line = deep.get("bottom_line", {})
        key_trauma = deep.get("key_trauma", {})
        internal_contradiction = deep.get("internal_contradiction", {})
        arc_potential = deep.get("arc_potential", {})

        # 声线
        voice_data = voice_map.get(name, {})
        voice_json = Json(voice_data)

        # extras: 放 world_anchor 等 skeleton 独有字段
        extras = {
            "world_anchor": char.get("world_anchor", {}),
            "relationships": char.get("relationships", []),
        }

        after_content = {
            "name": name,
            "role": char.get("role", ""),
            "aliases": char.get("aliases", []),
            "gender": char.get("gender", ""),
            "age": char.get("age", ""),
            "surface_goal": core_desire.get("surface_goal", ""),
            "deep_desire": core_desire.get("deep_desire", ""),
            "deep_fear": deep_fear,
            "secrets": secret,
            "bottom_line": bottom_line,
            "traumas": key_trauma,
            "contradictions": internal_contradiction,
            "arc_description": arc_potential,
            "world_position": char.get("world_position", {}),
            "essence": char.get("essence", ""),
            "beliefs": beliefs_data,
            "extras": extras,
            "voice": voice_data,
        }

        cur.execute("""
            INSERT INTO character (
                book_id, name, role, aliases,
                gender, age,
                surface_goal, deep_desire, deep_fear, secrets,
                bottom_line, traumas, contradictions, arc_description,
                world_position, essence, beliefs, extras, voice
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
        """, (
            book_id,
            name,
            char.get("role", ""),
            Json(char.get("aliases", [])),
            char.get("gender", ""),
            char.get("age", ""),
            core_desire.get("surface_goal", ""),
            core_desire.get("deep_desire", ""),
            Json(deep_fear),
            Json(secret),
            Json(bottom_line),
            Json(key_trauma),
            Json(internal_contradiction),
            Json(arc_potential),
            Json(char.get("world_position", {})),
            char.get("essence", ""),
            beliefs_json,
            Json(extras),
            voice_json,
        ))
        before_content = before_map.get(name) or {}
        before_content.pop("id", None)
        before_content.pop("book_id", None)
        insert_revision(
            cur, book_id, "character", name, before_content, after_content, "workflow",
            source_detail
            or workflow_source_detail(
                workflow_id,
                "json_to_db:upsert-characters",
            ),
            workflow_id=workflow_id,
            workflow_task_id=workflow_task_id,
        )
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"[INSERT] character 表写入 {inserted} 个角色")


# ══════════════════════════════════════════════
# upsert-story-plan: 写入 book 表的 story_plan 列
# ══════════════════════════════════════════════

def upsert_story_plan(book_id, story_plan_path, workflow_id=None, workflow_task_id=None, source_detail=None):
    """写入 book 表的 story_plan 列。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id, story_plan FROM book WHERE id = %s", (book_id,))
    before_row = cur.fetchone()
    if not before_row:
        print(f"[ERROR] book {book_id} 不存在", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(story_plan_path):
        print(f"[ERROR] story_plan 文件不存在: {story_plan_path}", file=sys.stderr)
        sys.exit(1)

    data = load_json(story_plan_path)
    before = as_plain(before_row["story_plan"])

    cur.execute(
        "UPDATE book SET story_plan = %s, updated_at = now() WHERE id = %s",
        (Json(data), book_id),
    )
    insert_revision(
        cur, book_id, "book", "story_plan", before, data, "workflow",
        source_detail
        or workflow_source_detail(
            workflow_id,
            "json_to_db:upsert-story-plan",
        ),
        workflow_id=workflow_id,
        workflow_task_id=workflow_task_id,
    )
    conn.commit()
    print("[UPDATE] book 表更新了 story_plan")

    cur.close()
    conn.close()


# ══════════════════════════════════════════════
# upsert-style-profile: 写入 book 表的 style_profile 列
# ══════════════════════════════════════════════

def upsert_style_profile(book_id, style_profile_path, workflow_id=None, workflow_task_id=None, source_detail=None):
    """写入 book 表的 style_profile 列。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id, style_profile FROM book WHERE id = %s", (book_id,))
    before_row = cur.fetchone()
    if not before_row:
        print(f"[ERROR] book {book_id} 不存在", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(style_profile_path):
        print(f"[ERROR] style_profile 文件不存在: {style_profile_path}", file=sys.stderr)
        sys.exit(1)

    data = load_json(style_profile_path)
    before = as_plain(before_row["style_profile"])

    cur.execute(
        "UPDATE book SET style_profile = %s, updated_at = now() WHERE id = %s",
        (Json(data), book_id),
    )
    insert_revision(
        cur, book_id, "book", "style_profile", before, data, "workflow",
        source_detail
        or workflow_source_detail(
            workflow_id,
            "json_to_db:upsert-style-profile",
        ),
        workflow_id=workflow_id,
        workflow_task_id=workflow_task_id,
    )
    conn.commit()
    print("[UPDATE] book 表更新了 style_profile")

    cur.close()
    conn.close()


# ══════════════════════════════════════════════
# upsert-book: 写入 story_plan + style_profile（旧接口，保留兼容）
# ══════════════════════════════════════════════

def upsert_book(book_id, story_plan_path=None, style_profile_path=None,
                workflow_id=None, workflow_task_id=None, source_detail=None):
    """写入 book 表的 story_plan 和 style_profile 列。保留兼容旧管线。"""
    if story_plan_path and os.path.exists(story_plan_path):
        upsert_story_plan(book_id, story_plan_path, workflow_id, workflow_task_id, source_detail)
    if style_profile_path and os.path.exists(style_profile_path):
        upsert_style_profile(book_id, style_profile_path, workflow_id, workflow_task_id, source_detail)
    if not (story_plan_path and os.path.exists(story_plan_path)) and \
       not (style_profile_path and os.path.exists(style_profile_path)):
        print("[SKIP] 无文件可更新")


# ══════════════════════════════════════════════
# upsert-character-skeleton: 骨架落库（阶段一）
# ══════════════════════════════════════════════

def upsert_character_skeleton(book_id, skeleton_path, workflow_id=None, workflow_task_id=None, source_detail=None):
    """从 skeleton.json 写入角色基础行。DELETE 旧数据 + INSERT 新数据。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id FROM book WHERE id = %s", (book_id,))
    if not cur.fetchone():
        print(f"[ERROR] book {book_id} 不存在", file=sys.stderr)
        sys.exit(1)

    skeleton = load_json(skeleton_path)
    characters = skeleton.get("characters", [])
    if not characters:
        print("[SKIP] skeleton 中没有角色，跳过")
        cur.close()
        conn.close()
        return

    # 读取 before（用于 revision）
    cur.execute("SELECT * FROM character WHERE book_id = %s", (book_id,))
    before_map = {row["name"]: dict(row) for row in cur.fetchall()}

    # DELETE 旧角色
    cur.execute("DELETE FROM character WHERE book_id = %s", (book_id,))
    deleted = cur.rowcount
    if deleted:
        print(f"[DELETE] 清除旧角色 {deleted} 行")

    inserted = 0
    for char in characters:
        name = char.get("name", "")
        if not name:
            continue

        extras = {
            "world_anchor": char.get("world_anchor", {}),
            "relationships": char.get("relationships", []),
        }

        cur.execute("""
            INSERT INTO character (
                book_id, name, role, aliases, gender, age,
                world_position, essence, extras
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            book_id,
            name,
            char.get("role", ""),
            Json(char.get("aliases", [])),
            char.get("gender", ""),
            char.get("age", ""),
            Json(char.get("world_position", {})),
            char.get("essence", ""),
            Json(extras),
        ))

        after_content = {
            "name": name,
            "role": char.get("role", ""),
            "aliases": char.get("aliases", []),
            "gender": char.get("gender", ""),
            "age": char.get("age", ""),
            "world_position": char.get("world_position", {}),
            "essence": char.get("essence", ""),
            "extras": extras,
        }
        before_content = before_map.get(name) or {}
        before_content.pop("id", None)
        before_content.pop("book_id", None)
        insert_revision(
            cur, book_id, "character", name, before_content, after_content, "workflow",
            source_detail
            or workflow_source_detail(
                workflow_id,
                "json_to_db:upsert-character-skeleton",
            ),
            workflow_id=workflow_id,
            workflow_task_id=workflow_task_id,
        )
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"[INSERT] character 表写入 {inserted} 个角色骨架")


# ══════════════════════════════════════════════
# upsert-character-beliefs: 信念落库（阶段二）
# ══════════════════════════════════════════════

def upsert_character_beliefs(book_id, beliefs_path, workflow_id=None, workflow_task_id=None, source_detail=None):
    """从 beliefs.json 读取全体角色信念，逐行 UPDATE character 表 beliefs 列。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id FROM book WHERE id = %s", (book_id,))
    if not cur.fetchone():
        print(f"[ERROR] book {book_id} 不存在", file=sys.stderr)
        sys.exit(1)

    beliefs_data = load_json(beliefs_path)
    beliefs_list = beliefs_data.get("beliefs", [])
    if not beliefs_list:
        print("[SKIP] beliefs.json 中没有信念数据，跳过")
        cur.close()
        conn.close()
        return

    # 读取 before
    cur.execute("SELECT name, beliefs FROM character WHERE book_id = %s", (book_id,))
    before_map = {row["name"]: as_plain(row["beliefs"]) for row in cur.fetchall()}

    updated = 0
    for entry in beliefs_list:
        name = entry.get("character", "")
        if not name:
            continue

        beliefs_payload = {
            "core_belief": entry.get("core_belief", ""),
            "belief_source": entry.get("belief_source", ""),
            "author_perspective": entry.get("author_perspective", "ambiguous"),
        }

        cur.execute(
            "UPDATE character SET beliefs = %s WHERE book_id = %s AND name = %s",
            (Json(beliefs_payload), book_id, name),
        )
        if cur.rowcount == 0:
            print(f"[WARN] 角色 {name} 不在 character 表中，跳过信念写入")
            continue

        before_content = {"beliefs": before_map.get(name, {})}
        after_content = {"beliefs": beliefs_payload}
        insert_revision(
            cur, book_id, "character", name, before_content, after_content, "workflow",
            source_detail
            or workflow_source_detail(
                workflow_id,
                "json_to_db:upsert-character-beliefs",
            ),
            workflow_id=workflow_id,
            workflow_task_id=workflow_task_id,
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"[UPDATE] character 表更新了 {updated} 个角色的信念")


# ══════════════════════════════════════════════
# upsert-character-deep: 单角色深层维度落库（阶段三·循环）
# ══════════════════════════════════════════════

def upsert_character_deep(book_id, deep_path, character_name, workflow_id=None, workflow_task_id=None, source_detail=None):
    """从 {name}_deep.json 更新单个角色的深层维度列。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id FROM book WHERE id = %s", (book_id,))
    if not cur.fetchone():
        print(f"[ERROR] book {book_id} 不存在", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(deep_path):
        print(f"[ERROR] 深层维度文件不存在: {deep_path}", file=sys.stderr)
        sys.exit(1)

    deep = load_json(deep_path)
    name = deep.get("name", character_name)
    if not name:
        name = character_name

    # 读取 before
    cur.execute(
        "SELECT surface_goal, deep_desire, deep_fear, secrets, bottom_line, traumas, contradictions, arc_description FROM character WHERE book_id = %s AND name = %s",
        (book_id, name),
    )
    existing = cur.fetchone()
    if not existing:
        print(f"[WARN] 角色 {name} 不在 character 表中，跳过深层维度写入")
        cur.close()
        conn.close()
        return

    before_content = {
        "surface_goal": existing["surface_goal"] or "",
        "deep_desire": existing["deep_desire"] or "",
        "deep_fear": as_plain(existing["deep_fear"]),
        "secrets": as_plain(existing["secrets"]),
        "bottom_line": as_plain(existing["bottom_line"]),
        "traumas": as_plain(existing["traumas"]),
        "contradictions": as_plain(existing["contradictions"]),
        "arc_description": as_plain(existing["arc_description"]),
    }

    core_desire = deep.get("core_desire", {})
    deep_fear = deep.get("deep_fear", {})
    secret = deep.get("secret", {})
    bottom_line = deep.get("bottom_line", {})
    key_trauma = deep.get("key_trauma", {})
    internal_contradiction = deep.get("internal_contradiction", {})
    arc_potential = deep.get("arc_potential", {})

    cur.execute("""
        UPDATE character SET
            surface_goal = %s,
            deep_desire = %s,
            deep_fear = %s,
            secrets = %s,
            bottom_line = %s,
            traumas = %s,
            contradictions = %s,
            arc_description = %s
        WHERE book_id = %s AND name = %s
    """, (
        core_desire.get("surface_goal", ""),
        core_desire.get("deep_desire", ""),
        Json(deep_fear),
        Json(secret),
        Json(bottom_line),
        Json(key_trauma),
        Json(internal_contradiction),
        Json(arc_potential),
        book_id,
        name,
    ))

    after_content = {
        "surface_goal": core_desire.get("surface_goal", ""),
        "deep_desire": core_desire.get("deep_desire", ""),
        "deep_fear": deep_fear,
        "secrets": secret,
        "bottom_line": bottom_line,
        "traumas": key_trauma,
        "contradictions": internal_contradiction,
        "arc_description": arc_potential,
    }
    insert_revision(
        cur, book_id, "character", name, before_content, after_content, "workflow",
        source_detail
        or workflow_source_detail(
            workflow_id,
            "json_to_db:upsert-character-deep",
        ),
        workflow_id=workflow_id,
        workflow_task_id=workflow_task_id,
    )

    conn.commit()
    cur.close()
    conn.close()
    print(f"[UPDATE] character.{name} 深层维度已写入")


# ══════════════════════════════════════════════
# upsert-character-voice: 声线落库（阶段四）
# ══════════════════════════════════════════════

def upsert_character_voice(book_id, voice_path, workflow_id=None, workflow_task_id=None, source_detail=None):
    """从 voice.json 读取全体角色声线，逐行 UPDATE character 表 voice 列。"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id FROM book WHERE id = %s", (book_id,))
    if not cur.fetchone():
        print(f"[ERROR] book {book_id} 不存在", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(voice_path):
        print(f"[ERROR] voice.json 不存在: {voice_path}", file=sys.stderr)
        sys.exit(1)

    voice_data = load_json(voice_path)
    voice_list = voice_data.get("characters", [])
    if not voice_list:
        print("[SKIP] voice.json 中没有角色数据，跳过")
        cur.close()
        conn.close()
        return

    # 读取 before
    cur.execute("SELECT name, voice FROM character WHERE book_id = %s", (book_id,))
    before_map = {row["name"]: as_plain(row["voice"]) for row in cur.fetchall()}

    updated = 0
    for vc in voice_list:
        name = vc.get("name", "")
        if not name:
            continue

        voice_payload = {
            "voice_positioning": vc.get("voice_positioning", ""),
            "syntax_fingerprint": vc.get("syntax_fingerprint", {}),
            "cognitive_bias": vc.get("cognitive_bias", ""),
            "forbidden_speech": vc.get("forbidden_speech", []),
            "emotion_patterns": vc.get("emotion_patterns", {}),
        }

        cur.execute(
            "UPDATE character SET voice = %s WHERE book_id = %s AND name = %s",
            (Json(voice_payload), book_id, name),
        )
        if cur.rowcount == 0:
            print(f"[WARN] 角色 {name} 不在 character 表中，跳过声线写入")
            continue

        before_content = {"voice": before_map.get(name, {})}
        after_content = {"voice": voice_payload}
        insert_revision(
            cur, book_id, "character", name, before_content, after_content, "workflow",
            source_detail
            or workflow_source_detail(
                workflow_id,
                "json_to_db:upsert-character-voice",
            ),
            workflow_id=workflow_id,
            workflow_task_id=workflow_task_id,
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"[UPDATE] character 表更新了 {updated} 个角色的声线")


# ══════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="JSON → 数据库写入")
    parser.add_argument("--book-id", required=True, help="书 UUID")
    parser.add_argument("--action", required=True, choices=[
        "upsert-world", "upsert-world-dimension",
        "upsert-character-skeleton", "upsert-character-beliefs",
        "upsert-character-deep", "upsert-character-voice",
        "upsert-characters", "upsert-book",
        "upsert-story-plan", "upsert-style-profile",
    ], help="操作模式")
    parser.add_argument("files", nargs="*", help="JSON 文件路径（upsert-world / upsert-world-dimension 用）")
    parser.add_argument("--dimension", default=None, choices=WORLD_DIMENSIONS, help="世界观维度（upsert-world-dimension 用）")

    # upsert-character-* 参数
    parser.add_argument("--skeleton", default=None, help="skeleton.json 路径（skeleton / upsert-characters 用）")
    parser.add_argument("--beliefs", default=None, help="beliefs.json 路径（beliefs / upsert-characters 用）")
    parser.add_argument("--deep-dir", default=None, help="存放 {name}_deep.json 的目录（upsert-characters 用）")
    parser.add_argument("--deep-file", default=None, help="单个 {name}_deep.json 路径（upsert-character-deep 用）")
    parser.add_argument("--character-name", default=None, help="角色名（upsert-character-deep 用）")
    parser.add_argument("--voice", default=None, help="voice.json 路径（voice / upsert-characters 用）")

    # upsert-book 参数
    parser.add_argument("--story-plan", default=None, help="story_plan.json 路径")
    parser.add_argument("--style-profile", default=None, help="style_profile.json 路径")

    # workflow 元信息（可由工作流节点脚本参数传入）
    parser.add_argument("--workflow-id", required=True, help="内部 workflow_id")
    parser.add_argument("--workflow-task-id", default=None, help="内部 workflow task_id")
    parser.add_argument("--source-detail", default=None, help="revision source_detail 覆盖值")

    args = parser.parse_args()

    if args.action == "upsert-world":
        file_map = {}
        for fpath in args.files:
            basename = os.path.basename(fpath)
            dim = os.path.splitext(basename)[0]
            if dim in WORLD_DIMENSIONS:
                file_map[dim] = fpath
            else:
                print(f"[WARN] 未知维度 {dim}，跳过", file=sys.stderr)

        if not file_map:
            print("[ERROR] 没有识别到任何有效维度文件", file=sys.stderr)
            sys.exit(1)

        upsert_world(
            args.book_id,
            file_map,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-world-dimension":
        if not args.dimension:
            print("[ERROR] upsert-world-dimension 需要 --dimension", file=sys.stderr)
            sys.exit(1)
        if len(args.files) != 1:
            print("[ERROR] upsert-world-dimension 需要且只需要一个 JSON 文件", file=sys.stderr)
            sys.exit(1)
        upsert_world_dimension(
            args.book_id,
            args.dimension,
            args.files[0],
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-character-skeleton":
        if not args.skeleton:
            print("[ERROR] upsert-character-skeleton 需要 --skeleton", file=sys.stderr)
            sys.exit(1)
        upsert_character_skeleton(
            args.book_id,
            args.skeleton,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-character-beliefs":
        if not args.beliefs:
            print("[ERROR] upsert-character-beliefs 需要 --beliefs", file=sys.stderr)
            sys.exit(1)
        upsert_character_beliefs(
            args.book_id,
            args.beliefs,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-character-deep":
        if not args.deep_file or not args.character_name:
            print("[ERROR] upsert-character-deep 需要 --deep-file, --character-name", file=sys.stderr)
            sys.exit(1)
        upsert_character_deep(
            args.book_id,
            args.deep_file,
            args.character_name,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-character-voice":
        if not args.voice:
            print("[ERROR] upsert-character-voice 需要 --voice", file=sys.stderr)
            sys.exit(1)
        upsert_character_voice(
            args.book_id,
            args.voice,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-characters":
        if not args.skeleton or not args.beliefs or not args.deep_dir:
            print("[ERROR] upsert-characters 需要 --skeleton, --beliefs, --deep-dir", file=sys.stderr)
            sys.exit(1)

        upsert_characters(
            args.book_id,
            args.skeleton,
            args.beliefs,
            args.deep_dir,
            args.voice,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-book":
        upsert_book(
            args.book_id,
            args.story_plan,
            args.style_profile,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-story-plan":
        upsert_story_plan(
            args.book_id,
            args.story_plan,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )

    elif args.action == "upsert-style-profile":
        upsert_style_profile(
            args.book_id,
            args.style_profile,
            workflow_id=args.workflow_id,
            workflow_task_id=args.workflow_task_id,
            source_detail=args.source_detail,
        )


if __name__ == "__main__":
    main()
