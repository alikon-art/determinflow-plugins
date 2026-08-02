"""Content edit service with resource versioning and revision history."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from .dao import WORLD_DIMENSIONS, json_value
from .db import get_pool
from .errors import InvalidResourceError, NotFoundError, VersionConflictError


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def _as_jsonb(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _diff_json(before: Any, after: Any, path: str = "") -> tuple[list[str], list[str], list[str]]:
    changed: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    if isinstance(before, dict) and isinstance(after, dict):
        keys = set(before) | set(after)
        for key in sorted(keys):
            p = f"{path}/{key}" if path else f"/{key}"
            if key not in before:
                added.append(p)
            elif key not in after:
                removed.append(p)
            else:
                c, a, r = _diff_json(before[key], after[key], p)
                changed.extend(c)
                added.extend(a)
                removed.extend(r)
    elif isinstance(before, list) and isinstance(after, list):
        if before != after:
            changed.append(path or "/")
    else:
        if before != after:
            changed.append(path or "/")
    return changed, added, removed


def _diff_stats(before: Any, after: Any) -> dict:
    before_text = before.get("body") if isinstance(before, dict) else before
    after_text = after.get("body") if isinstance(after, dict) else after
    if isinstance(before_text, str) or isinstance(after_text, str):
        b = before_text or ""
        a = after_text or ""
        max_len = max(len(b), len(a), 1)
        common_prefix = 0
        for x, y in zip(b, a):
            if x != y:
                break
            common_prefix += 1
        common_suffix = 0
        for x, y in zip(reversed(b[common_prefix:]), reversed(a[common_prefix:])):
            if x != y:
                break
            common_suffix += 1
        changed_chars = max(len(b), len(a)) - common_prefix - common_suffix
        changed_chars = max(changed_chars, 0)
        return {
            "text_before_chars": len(b),
            "text_after_chars": len(a),
            "changed_chars": changed_chars,
            "change_ratio": round(changed_chars / max_len, 4),
            "word_count_delta": len(a) - len(b),
        }
    changed, added, removed = _diff_json(before, after)
    total = max(len(changed) + len(added) + len(removed), 1)
    return {
        "changed_paths": changed,
        "added_paths": added,
        "removed_paths": removed,
        "json_field_changed_count": total,
        "change_ratio": 0 if not (changed or added or removed) else min(1, total / 10),
    }


def _edit_intensity(stats: dict) -> str:
    ratio = float(stats.get("change_ratio") or 0)
    if ratio == 0:
        return "none"
    if ratio <= 0.05:
        return "minor"
    if ratio <= 0.25:
        return "moderate"
    if ratio <= 0.70:
        return "major"
    return "rewrite"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EditService:
    async def apply_edit(
        self,
        *,
        book_id: str,
        resource_type: str,
        resource_key: str,
        new_content: Any,
        base_version: int | None,
        source: str,
        source_detail: str | None = None,
        actor_ref: str | None = None,
        request_id: str | None = None,
        reason: str | None = None,
        metadata: dict | None = None,
        edit_mode: str = "replace",
        enforce_version: bool = True,
    ) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                before = await self._read_current(conn, book_id, resource_type, resource_key)
                state = await conn.fetchrow(
                    """SELECT current_version FROM novel_resource_state
                       WHERE book_id = $1 AND resource_type = $2 AND resource_key = $3
                       FOR UPDATE""",
                    book_id,
                    resource_type,
                    resource_key,
                )
                current_version = int(state["current_version"]) if state else 0
                if enforce_version:
                    if base_version is None:
                        raise VersionConflictError(
                            "缺少 base_version",
                            {"resource_type": resource_type, "resource_key": resource_key, "current_version": current_version},
                        )
                    if base_version != current_version:
                        raise VersionConflictError(
                            "内容已被修改，请刷新后重试",
                            {
                                "resource_type": resource_type,
                                "resource_key": resource_key,
                                "base_version": base_version,
                                "current_version": current_version,
                            },
                        )
                    new_version = current_version + 1
                else:
                    new_version = current_version + 1 if state else 1

                stats = _diff_stats(before, new_content)
                intensity = _edit_intensity(stats)
                diff = {
                    "before_hash": _content_hash(before),
                    "after_hash": _content_hash(new_content),
                    "stats": stats,
                }
                revision_id = str(uuid.uuid4())
                await conn.execute(
                    """INSERT INTO novel_resource_revision (
                           id, book_id, resource_type, resource_key, version, base_version, edit_mode,
                           source, source_detail, edit_intensity, diff_stats, actor_ref, request_id,
                           before_content, after_content, diff, summary, reason, metadata
                       ) VALUES (
                           $1, $2, $3, $4, $5, $6, $7,
                           $8, $9, $10, $11::jsonb, $12, $13,
                           $14::jsonb, $15::jsonb, $16::jsonb, $17, $18, $19::jsonb
                       )""",
                    revision_id,
                    book_id,
                    resource_type,
                    resource_key,
                    new_version,
                    base_version,
                    edit_mode,
                    source,
                    source_detail,
                    intensity,
                    _as_jsonb(stats),
                    actor_ref,
                    request_id,
                    _as_jsonb(before),
                    _as_jsonb(new_content),
                    _as_jsonb(diff),
                    self._summary(resource_type, resource_key, source, intensity),
                    reason,
                    _as_jsonb(metadata or {}),
                )

                await self._write_current(conn, book_id, resource_type, resource_key, new_content)

                if enforce_version:
                    await conn.execute(
                        """INSERT INTO novel_resource_state (
                               book_id, resource_type, resource_key, current_version,
                               current_revision_id, content_hash, created_at, updated_at
                           ) VALUES ($1, $2, $3, $4, $5, $6, now(), now())
                           ON CONFLICT (book_id, resource_type, resource_key) DO UPDATE SET
                               current_version = EXCLUDED.current_version,
                               current_revision_id = EXCLUDED.current_revision_id,
                               content_hash = EXCLUDED.content_hash,
                               updated_at = now()""",
                        book_id,
                        resource_type,
                        resource_key,
                        new_version,
                        revision_id,
                        _content_hash(new_content),
                    )
                return {
                    "book_id": book_id,
                    "resource_type": resource_type,
                    "resource_key": resource_key,
                    "version": new_version if enforce_version else None,
                    "revision_id": revision_id,
                    "updated_at": _now_iso(),
                }

    def _summary(self, resource_type: str, resource_key: str, source: str, intensity: str) -> str:
        return f"{source} {intensity} edit on {resource_type}/{resource_key}"

    async def _read_current(self, conn: asyncpg.Connection, book_id: str, resource_type: str, resource_key: str) -> Any:
        if resource_type == "world":
            self._validate_world_key(resource_key)
            row = await conn.fetchrow(f"SELECT {resource_key} FROM world WHERE book_id = $1", book_id)
            return json_value(row[resource_key]) if row else {}
        if resource_type == "chapter":
            chapter, field = self._parse_chapter_key(resource_key)
            if field == "body":
                row = await conn.fetchrow("SELECT body, title, status FROM chapter WHERE book_id = $1 AND chapter_number = $2", book_id, chapter)
                return {"body": row["body"] or "", "title": row["title"], "status": row["status"]} if row else {"body": ""}
            if field == "world":
                row = await conn.fetchrow("SELECT world_state, world_events FROM chapter WHERE book_id = $1 AND chapter_number = $2", book_id, chapter)
                return {"world_state": json_value(row["world_state"]), "world_events": json_value(row["world_events"])} if row else {"world_state": {}, "world_events": {}}
            row = await conn.fetchrow(f"SELECT {field} FROM chapter WHERE book_id = $1 AND chapter_number = $2", book_id, chapter)
            return json_value(row[field]) if row else {}
        if resource_type == "book":
            if resource_key == "meta":
                row = await conn.fetchrow("SELECT title, status, genre FROM book WHERE id = $1", book_id)
                if not row:
                    raise NotFoundError("书不存在", {"book_id": book_id})
                return dict(row)
            if resource_key in ("settings", "style_profile", "story_plan"):
                row = await conn.fetchrow(f"SELECT {resource_key} FROM book WHERE id = $1", book_id)
                if not row:
                    raise NotFoundError("书不存在", {"book_id": book_id})
                return json_value(row[resource_key]) or {}
        if resource_type == "character":
            row = await conn.fetchrow("SELECT * FROM character WHERE book_id = $1 AND name = $2", book_id, resource_key)
            if not row:
                return {}
            data = dict(row)
            data.pop("id", None)
            data.pop("book_id", None)
            data.pop("created_at", None)
            data.pop("updated_at", None)
            return {k: json_value(v) for k, v in data.items()}
        if resource_type == "outline":
            outline_type, volume = self._parse_outline_key(resource_key)
            row = await conn.fetchrow(
                "SELECT content FROM outline WHERE book_id = $1 AND type = $2 AND volume_number = $3",
                book_id,
                outline_type,
                volume,
            )
            return json_value(row["content"]) if row else {}
        if resource_type == "hook":
            row = await conn.fetchrow("SELECT * FROM hook WHERE book_id = $1 AND item_id = $2", book_id, resource_key)
            return self._clean_row(row)
        if resource_type == "debt":
            row = await conn.fetchrow("SELECT * FROM debt WHERE book_id = $1 AND item_id = $2", book_id, resource_key)
            return self._clean_row(row)
        raise InvalidResourceError("未知资源类型", {"resource_type": resource_type})

    async def _write_current(self, conn: asyncpg.Connection, book_id: str, resource_type: str, resource_key: str, content: Any) -> None:
        if resource_type == "world":
            self._validate_world_key(resource_key)
            await conn.execute(
                """INSERT INTO world (book_id, core_laws, space_time, society, history_culture, existence, information)
                   VALUES ($1, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
                   ON CONFLICT (book_id) DO NOTHING""",
                book_id,
            )
            await conn.execute(
                f"UPDATE world SET {resource_key} = $1::jsonb, updated_at = now() WHERE book_id = $2",
                _as_jsonb(content),
                book_id,
            )
            return
        if resource_type == "chapter":
            chapter, field = self._parse_chapter_key(resource_key)
            if field == "body":
                body = content.get("body", "") if isinstance(content, dict) else str(content)
                title = content.get("title") if isinstance(content, dict) else None
                status = content.get("status") if isinstance(content, dict) else None
                word_count = len(body)
                await conn.execute(
                    """INSERT INTO chapter (book_id, chapter_number, title, body, word_count, status)
                       VALUES ($1, $2, $3, $4, $5, COALESCE($6, 'draft'))
                       ON CONFLICT (book_id, chapter_number) DO UPDATE SET
                           title = COALESCE(EXCLUDED.title, chapter.title),
                           body = EXCLUDED.body,
                           word_count = EXCLUDED.word_count,
                           status = COALESCE(EXCLUDED.status, chapter.status),
                           updated_at = now()""",
                    book_id,
                    chapter,
                    title,
                    body,
                    word_count,
                    status,
                )
            elif field == "world":
                ws = content.get("world_state", {}) if isinstance(content, dict) else {}
                we = content.get("world_events", {}) if isinstance(content, dict) else {}
                await conn.execute(
                    """INSERT INTO chapter (book_id, chapter_number)
                       VALUES ($1, $2)
                       ON CONFLICT (book_id, chapter_number) DO NOTHING""",
                    book_id,
                    chapter,
                )
                await conn.execute(
                    """UPDATE chapter SET world_state = $1::jsonb, world_events = $2::jsonb, updated_at = now()
                       WHERE book_id = $3 AND chapter_number = $4""",
                    _as_jsonb(ws),
                    _as_jsonb(we),
                    book_id,
                    chapter,
                )
            else:
                await conn.execute(
                    """INSERT INTO chapter (book_id, chapter_number)
                       VALUES ($1, $2)
                       ON CONFLICT (book_id, chapter_number) DO NOTHING""",
                    book_id,
                    chapter,
                )
                await conn.execute(
                    f"UPDATE chapter SET {field} = $1::jsonb, updated_at = now() WHERE book_id = $2 AND chapter_number = $3",
                    _as_jsonb(content),
                    book_id,
                    chapter,
                )
            return
        if resource_type == "book":
            if resource_key == "meta":
                await conn.execute(
                    """UPDATE book SET
                           title = COALESCE($1, title),
                           status = COALESCE($2, status),
                           genre = COALESCE($3, genre),
                           estimated_length = COALESCE($4, estimated_length),
                           words_per_chapter = COALESCE($5, words_per_chapter),
                           updated_at = now()
                       WHERE id = $6""",
                    content.get("title"),
                    content.get("status"),
                    content.get("genre"),
                    content.get("estimated_length"),
                    content.get("words_per_chapter"),
                    book_id,
                )
                return
            if resource_key in ("settings", "style_profile", "story_plan"):
                await conn.execute(
                    f"UPDATE book SET {resource_key} = $1::jsonb, updated_at = now() WHERE id = $2",
                    _as_jsonb(content),
                    book_id,
                )
                return
        if resource_type == "character":
            await self._upsert_character(conn, book_id, resource_key, content)
            return
        if resource_type == "outline":
            outline_type, volume = self._parse_outline_key(resource_key)
            chapter_range = content.get("chapter_range", {}) if isinstance(content, dict) else {}
            await conn.execute(
                """INSERT INTO outline (book_id, type, volume_number, chapter_start, chapter_end, content)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                   ON CONFLICT (book_id, type, volume_number) DO UPDATE SET
                       chapter_start = EXCLUDED.chapter_start,
                       chapter_end = EXCLUDED.chapter_end,
                       content = EXCLUDED.content,
                       updated_at = now()""",
                book_id,
                outline_type,
                volume,
                chapter_range.get("start"),
                chapter_range.get("end"),
                _as_jsonb(content),
            )
            return
        if resource_type == "hook":
            await self._upsert_hook(conn, book_id, resource_key, content)
            return
        if resource_type == "debt":
            await self._upsert_debt(conn, book_id, resource_key, content)
            return
        raise InvalidResourceError("未知资源类型", {"resource_type": resource_type})

    def _validate_world_key(self, key: str) -> None:
        if key not in WORLD_DIMENSIONS:
            raise InvalidResourceError("世界观维度不存在", {"dimension": key})

    def _parse_chapter_key(self, key: str) -> tuple[int, str]:
        try:
            chapter_s, field = key.split(":", 1)
            chapter = int(chapter_s)
        except Exception as exc:
            raise InvalidResourceError("章节资源 key 不合法", {"resource_key": key}) from exc
        allowed = {"body", "guide", "world", "world_state", "world_events", "storyboard", "character_state", "character_minor", "world_rulings", "story_confirmed", "character_diff"}
        if field not in allowed:
            raise InvalidResourceError("章节字段不合法", {"field": field})
        return chapter, field

    def _parse_outline_key(self, key: str) -> tuple[str, int]:
        try:
            outline_type, volume_s = key.split(":", 1)
            volume = int(volume_s)
        except Exception as exc:
            raise InvalidResourceError("大纲资源 key 不合法", {"resource_key": key}) from exc
        if outline_type not in ("volume", "near_term"):
            raise InvalidResourceError("大纲类型不合法", {"outline_type": outline_type})
        return outline_type, volume

    def _clean_row(self, row: asyncpg.Record | None) -> dict:
        if not row:
            return {}
        data = dict(row)
        data.pop("id", None)
        data.pop("book_id", None)
        return {k: json_value(v) for k, v in data.items()}

    async def _upsert_character(self, conn: asyncpg.Connection, book_id: str, name: str, content: dict) -> None:
        await conn.execute(
            """INSERT INTO character (
                   book_id, name, true_name, role, gender, age, aliases, surface_goal, deep_desire,
                   deep_fear, secrets, bottom_line, traumas, contradictions, arc_description,
                   world_position, essence, beliefs, extras, voice
               ) VALUES (
                   $1, $2, $3, COALESCE($4, ''), $5, $6, $7::jsonb, $8, $9,
                   $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb,
                   $16::jsonb, $17, $18::jsonb, $19::jsonb, $20::jsonb
               )
               ON CONFLICT (book_id, name) DO UPDATE SET
                   true_name = EXCLUDED.true_name,
                   role = EXCLUDED.role,
                   gender = EXCLUDED.gender,
                   age = EXCLUDED.age,
                   aliases = EXCLUDED.aliases,
                   surface_goal = EXCLUDED.surface_goal,
                   deep_desire = EXCLUDED.deep_desire,
                   deep_fear = EXCLUDED.deep_fear,
                   secrets = EXCLUDED.secrets,
                   bottom_line = EXCLUDED.bottom_line,
                   traumas = EXCLUDED.traumas,
                   contradictions = EXCLUDED.contradictions,
                   arc_description = EXCLUDED.arc_description,
                   world_position = EXCLUDED.world_position,
                   essence = EXCLUDED.essence,
                   beliefs = EXCLUDED.beliefs,
                   extras = EXCLUDED.extras,
                   voice = EXCLUDED.voice,
                   updated_at = now()""",
            book_id,
            content.get("name") or name,
            content.get("true_name"),
            content.get("role"),
            content.get("gender"),
            content.get("age"),
            _as_jsonb(content.get("aliases", [])),
            content.get("surface_goal"),
            content.get("deep_desire"),
            _as_jsonb(content.get("deep_fear", {})),
            _as_jsonb(content.get("secrets", [])),
            _as_jsonb(content.get("bottom_line", {})),
            _as_jsonb(content.get("traumas", [])),
            _as_jsonb(content.get("contradictions", {})),
            _as_jsonb(content.get("arc_description", {})),
            _as_jsonb(content.get("world_position", {})),
            content.get("essence", ""),
            _as_jsonb(content.get("beliefs", {})),
            _as_jsonb(content.get("extras", {})),
            _as_jsonb(content.get("voice", {})),
        )

    async def _upsert_hook(self, conn: asyncpg.Connection, book_id: str, item_id: str, content: dict) -> None:
        await conn.execute(
            """INSERT INTO hook (book_id, item_id, description, status, chapter_created, chapter_resolved,
                                  expected_payoff, last_advanced, source, content)
               VALUES ($1,$2,$3,COALESCE($4,'open'),$5,$6,$7,$8,$9,$10::jsonb)
               ON CONFLICT (book_id, item_id) DO UPDATE SET
                   description = COALESCE(EXCLUDED.description, hook.description),
                   status = EXCLUDED.status,
                   chapter_created = COALESCE(EXCLUDED.chapter_created, hook.chapter_created),
                   chapter_resolved = EXCLUDED.chapter_resolved,
                   expected_payoff = EXCLUDED.expected_payoff,
                   last_advanced = EXCLUDED.last_advanced,
                   source = EXCLUDED.source,
                   content = EXCLUDED.content,
                   updated_at = now()""",
            book_id,
            item_id,
            content.get("description"),
            content.get("status"),
            content.get("chapter_created"),
            content.get("chapter_resolved"),
            content.get("expected_payoff"),
            content.get("last_advanced"),
            content.get("source"),
            _as_jsonb(content.get("content", {})),
        )

    async def _upsert_debt(self, conn: asyncpg.Connection, book_id: str, item_id: str, content: dict) -> None:
        await conn.execute(
            """INSERT INTO debt (book_id, item_id, description, status, chapter_created, chapter_resolved,
                                  expected_payoff, last_advanced, source, from_char, to_char, content)
               VALUES ($1,$2,$3,COALESCE($4,'open'),$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
               ON CONFLICT (book_id, item_id) DO UPDATE SET
                   description = COALESCE(EXCLUDED.description, debt.description),
                   status = EXCLUDED.status,
                   chapter_created = COALESCE(EXCLUDED.chapter_created, debt.chapter_created),
                   chapter_resolved = EXCLUDED.chapter_resolved,
                   expected_payoff = EXCLUDED.expected_payoff,
                   last_advanced = EXCLUDED.last_advanced,
                   source = EXCLUDED.source,
                   from_char = EXCLUDED.from_char,
                   to_char = EXCLUDED.to_char,
                   content = EXCLUDED.content,
                   updated_at = now()""",
            book_id,
            item_id,
            content.get("description"),
            content.get("status"),
            content.get("chapter_created"),
            content.get("chapter_resolved"),
            content.get("expected_payoff"),
            content.get("last_advanced"),
            content.get("source"),
            content.get("from_char"),
            content.get("to_char"),
            _as_jsonb(content.get("content", {})),
        )
