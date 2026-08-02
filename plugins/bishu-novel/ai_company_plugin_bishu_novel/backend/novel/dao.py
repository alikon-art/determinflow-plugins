"""Data access layer for the novel production API."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from .db import get_pool
from .errors import NotFoundError


WORLD_DIMENSIONS = {
    "core_laws",
    "space_time",
    "society",
    "history_culture",
    "existence",
    "information",
}

CHAPTER_STATE_COLUMNS = {
    "guide",
    "world_state",
    "world_events",
    "storyboard",
    "character_state",
    "character_minor",
    "world_rulings",
    "story_confirmed",
    "character_diff",
}


def json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def row_to_dict(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    return {k: json_value(v) for k, v in dict(row).items()}


async def fetch_book(conn: asyncpg.Connection, book_id: str) -> dict | None:
    row = await conn.fetchrow(
        "SELECT id, external_ref, title, status, genre, estimated_length, words_per_chapter, "
        "settings, created_at, updated_at "
        "FROM book WHERE id = $1 AND deleted_at IS NULL",
        book_id,
    )
    return row_to_dict(row)


async def ensure_book(conn: asyncpg.Connection, book_id: str) -> dict:
    book = await fetch_book(conn, book_id)
    if not book:
        raise NotFoundError("书不存在", {"book_id": book_id})
    return book


class NovelDAO:
    async def list_books(self, limit: int = 50, offset: int = 0) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT b.id, b.external_ref, b.title, b.status, b.genre,
                          b.estimated_length, b.words_per_chapter, b.created_at, b.updated_at,
                          COALESCE(MAX(c.chapter_number), 0) AS last_chapter
                   FROM book b
                   LEFT JOIN chapter c ON c.book_id = b.id
                   WHERE b.deleted_at IS NULL
                   GROUP BY b.id
                   ORDER BY b.updated_at DESC NULLS LAST, b.created_at DESC
                   LIMIT $1 OFFSET $2""",
                limit,
                offset,
            )
        return [row_to_dict(r) for r in rows]

    async def create_book(
        self, title: str, external_ref: str | None, genre: str | None, settings: dict
    ) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO book (title, external_ref, genre, estimated_length, words_per_chapter, style_profile, story_plan, settings)
                   VALUES ($1, $2, $3, '中', '2000-2500', '{}'::jsonb, '{}'::jsonb, $4::jsonb)
                   RETURNING id, external_ref, title, status, genre, estimated_length, words_per_chapter, settings, created_at, updated_at""",
                title,
                external_ref,
                genre,
                json.dumps(settings or {}, ensure_ascii=False),
            )
        return row_to_dict(row)

    async def get_book(self, book_id: str) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await ensure_book(conn, book_id)

    async def get_world(self, book_id: str) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await ensure_book(conn, book_id)
            row = await conn.fetchrow(
                """SELECT core_laws, space_time, society, history_culture, existence, information,
                          created_at, updated_at
                   FROM world WHERE book_id = $1""",
                book_id,
            )
        if not row:
            return {"book_id": book_id, "status": "pending", "dimensions": {}}
        data = row_to_dict(row)
        return {
            "book_id": book_id,
            "status": "ready",
            "dimensions": {d: data.get(d) for d in WORLD_DIMENSIONS},
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    async def get_world_dimension(self, book_id: str, dimension: str) -> dict:
        if dimension not in WORLD_DIMENSIONS:
            raise NotFoundError("世界观维度不存在", {"dimension": dimension})
        pool = await get_pool()
        async with pool.acquire() as conn:
            await ensure_book(conn, book_id)
            row = await conn.fetchrow(
                f"SELECT {dimension}, updated_at FROM world WHERE book_id = $1",
                book_id,
            )
            state = await self.get_resource_state_conn(
                conn, book_id, "world", dimension
            )
        if not row:
            return {
                "book_id": book_id,
                "dimension": dimension,
                "version": 0,
                "content": {},
                "updated_at": None,
            }
        return {
            "book_id": book_id,
            "dimension": dimension,
            "version": state.get("current_version", 0) if state else 0,
            "content": json_value(row[dimension]) or {},
            "updated_at": row["updated_at"],
        }

    async def get_book_json_resource(self, book_id: str, resource_key: str) -> dict:
        if resource_key not in {"settings", "style_profile", "story_plan"}:
            raise NotFoundError("书级资源不存在", {"resource_key": resource_key})
        pool = await get_pool()
        async with pool.acquire() as conn:
            await ensure_book(conn, book_id)
            row = await conn.fetchrow(
                f"SELECT {resource_key}, updated_at FROM book WHERE id = $1", book_id
            )
            state = await self.get_resource_state_conn(
                conn, book_id, "book", resource_key
            )
        return {
            "book_id": book_id,
            "resource_type": "book",
            "resource_key": resource_key,
            "version": state.get("current_version", 0) if state else 0,
            "content": json_value(row[resource_key]) or {},
            "updated_at": row["updated_at"],
        }

    async def list_chapters(self, book_id: str) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.chapter_number, c.title, c.word_count, c.status,
                          c.post_hoc_status,
                          COALESCE(s.current_version, 0) AS version,
                          s.current_revision_id AS revision_id,
                          c.created_at, c.updated_at
                   FROM chapter c
                   LEFT JOIN novel_resource_state s
                     ON s.book_id = c.book_id
                    AND s.resource_type = 'chapter'
                    AND s.resource_key = (
                      CASE
                        WHEN c.chapter_number < 0 THEN
                          '-' || lpad(
                            substring(c.chapter_number::text FROM 2),
                            GREATEST(3, length(c.chapter_number::text) - 1),
                            '0'
                          )
                        ELSE lpad(
                          c.chapter_number::text,
                          GREATEST(4, length(c.chapter_number::text)),
                          '0'
                        )
                      END
                    ) || ':body'
                   WHERE c.book_id = $1
                   ORDER BY c.chapter_number""",
                book_id,
            )
        return [row_to_dict(r) for r in rows]

    async def get_chapter(self, book_id: str, chapter_number: int) -> dict:
        pool = await get_pool()
        resource_key = f"{chapter_number:04d}:body"
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT c.chapter_number, c.title, c.body, c.word_count, c.status,
                          c.post_hoc_status,
                          COALESCE(s.current_version, 0) AS version,
                          s.current_revision_id AS revision_id,
                          c.created_at, c.updated_at
                   FROM chapter c
                   LEFT JOIN novel_resource_state s
                     ON s.book_id = c.book_id
                    AND s.resource_type = 'chapter'
                    AND s.resource_key = $3
                   WHERE c.book_id = $1 AND c.chapter_number = $2""",
                book_id,
                chapter_number,
                resource_key,
            )
            if not row:
                raise NotFoundError(
                    "章节不存在", {"book_id": book_id, "chapter_number": chapter_number}
                )
        return row_to_dict(row)

    async def get_chapter_state(self, book_id: str, chapter_number: int) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT guide, world_state, world_events, storyboard, character_state, character_minor,
                          world_rulings, story_confirmed, character_diff
                   FROM chapter
                   WHERE book_id = $1 AND chapter_number = $2""",
                book_id,
                chapter_number,
            )
            if not row:
                raise NotFoundError(
                    "章节不存在", {"book_id": book_id, "chapter_number": chapter_number}
                )
            states = await conn.fetch(
                """SELECT resource_key, current_version
                   FROM novel_resource_state
                   WHERE book_id = $1 AND resource_type = 'chapter'""",
                book_id,
            )
        version_map = {r["resource_key"]: r["current_version"] for r in states}
        data = row_to_dict(row)
        result = {}
        for col in CHAPTER_STATE_COLUMNS:
            result[col] = {
                "version": version_map.get(f"{chapter_number:04d}:{col}", 0),
                "content": data.get(col) or {},
            }
        return result

    async def get_chapter_world(self, book_id: str, chapter_number: int) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT world_state, world_events FROM chapter
                   WHERE book_id = $1 AND chapter_number = $2""",
                book_id,
                chapter_number,
            )
            if not row:
                raise NotFoundError(
                    "章节不存在", {"book_id": book_id, "chapter_number": chapter_number}
                )
            version_key = f"{chapter_number:04d}:world"
            state = await self.get_resource_state_conn(
                conn, book_id, "chapter", version_key
            )
        data = row_to_dict(row)
        data["version"] = state.get("current_version", 0) if state else 0
        return data

    async def get_chapter_guide(self, book_id: str, chapter_number: int) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT guide FROM chapter
                   WHERE book_id = $1 AND chapter_number = $2""",
                book_id,
                chapter_number,
            )
            if not row:
                raise NotFoundError(
                    "章节不存在", {"book_id": book_id, "chapter_number": chapter_number}
                )
            hooks = await conn.fetch(
                "SELECT item_id, description, status, chapter_created, chapter_resolved,"
                "       expected_payoff, last_advanced, source, content, created_at, updated_at"
                " FROM hook WHERE book_id = $1 ORDER BY item_id",
                book_id,
            )
            debts = await conn.fetch(
                "SELECT item_id, description, status, chapter_created, chapter_resolved,"
                "       expected_payoff, last_advanced, source, content, created_at, updated_at"
                " FROM debt WHERE book_id = $1 ORDER BY item_id",
                book_id,
            )
            version_key = f"{chapter_number:04d}:guide"
            state = await self.get_resource_state_conn(
                conn, book_id, "chapter", version_key
            )
        data = row_to_dict(row)
        data["version"] = state.get("current_version", 0) if state else 0
        data["hooks"] = [row_to_dict(r) for r in hooks]
        data["debts"] = [row_to_dict(r) for r in debts]
        return data

    async def list_characters(self, book_id: str) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT name, true_name, role, gender, age, aliases, surface_goal, deep_desire, essence, updated_at
                   FROM character WHERE book_id = $1 ORDER BY created_at""",
                book_id,
            )
        return [row_to_dict(r) for r in rows]

    async def get_character(self, book_id: str, name: str) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT name, true_name, role, gender, age, aliases, surface_goal, deep_desire, essence,
                          deep_fear, secrets, bottom_line, traumas, contradictions, arc_description,
                          world_position, beliefs, extras, voice, created_at, updated_at
                   FROM character WHERE book_id = $1 AND name = $2""",
                book_id,
                name,
            )
            if not row:
                raise NotFoundError("角色不存在", {"book_id": book_id, "name": name})
            state = await self.get_resource_state_conn(conn, book_id, "character", name)
        data = row_to_dict(row)
        data["version"] = state.get("current_version", 0) if state else 0
        return data

    async def list_outlines(self, book_id: str) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT type, volume_number, chapter_start, chapter_end, content, created_at, updated_at
                   FROM outline WHERE book_id = $1 ORDER BY type, volume_number""",
                book_id,
            )
            states = await conn.fetch(
                """SELECT resource_key, current_version
                   FROM novel_resource_state WHERE book_id = $1 AND resource_type = 'outline'""",
                book_id,
            )
        version_map = {r["resource_key"]: r["current_version"] for r in states}
        result = []
        for row in rows:
            data = row_to_dict(row)
            key = f"{data['type']}:{data.get('volume_number') or 1}"
            data["resource_key"] = key
            data["version"] = version_map.get(key, 0)
            result.append(data)
        return result

    async def get_outline(
        self, book_id: str, outline_type: str, volume_number: int
    ) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT type, volume_number, chapter_start, chapter_end, content, created_at, updated_at
                   FROM outline WHERE book_id = $1 AND type = $2 AND volume_number = $3""",
                book_id,
                outline_type,
                volume_number,
            )
            if not row:
                raise NotFoundError(
                    "大纲不存在",
                    {
                        "book_id": book_id,
                        "type": outline_type,
                        "volume_number": volume_number,
                    },
                )
            key = f"{outline_type}:{volume_number}"
            state = await self.get_resource_state_conn(conn, book_id, "outline", key)
        data = row_to_dict(row)
        data["resource_key"] = key
        data["version"] = state.get("current_version", 0) if state else 0
        return data

    async def get_latest_outline(self, book_id: str, outline_type: str) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT type, volume_number, chapter_start, chapter_end, content, created_at, updated_at
                   FROM outline WHERE book_id = $1 AND type = $2
                   ORDER BY volume_number DESC LIMIT 1""",
                book_id,
                outline_type,
            )
            if not row:
                raise NotFoundError(
                    "大纲不存在", {"book_id": book_id, "type": outline_type}
                )
            data = row_to_dict(row)
            key = f"{outline_type}:{data['volume_number']}"
            data["resource_key"] = key
            state = await self.get_resource_state_conn(conn, book_id, "outline", key)
        data["version"] = state.get("current_version", 0) if state else 0
        return data

    async def list_hooks(self, book_id: str) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT item_id, description, status, chapter_created, chapter_resolved,
                          expected_payoff, last_advanced, source, content, created_at, updated_at
                   FROM hook WHERE book_id = $1 ORDER BY item_id""",
                book_id,
            )
        return [row_to_dict(r) for r in rows]

    async def list_debts(self, book_id: str) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT item_id, description, status, chapter_created, chapter_resolved,
                          expected_payoff, last_advanced, source, from_char, to_char, content, created_at, updated_at
                   FROM debt WHERE book_id = $1 ORDER BY item_id""",
                book_id,
            )
        return [row_to_dict(r) for r in rows]

    async def delete_book(self, book_id: str) -> dict:
        """软删除书籍——设置 deleted_at 时间戳"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE book SET deleted_at = now(), updated_at = now() "
                "WHERE id = $1 AND deleted_at IS NULL "
                "RETURNING id, title, deleted_at, updated_at",
                book_id,
            )
            if not row:
                raise NotFoundError("书不存在或已删除", {"book_id": book_id})
            return row_to_dict(row)

    async def get_resource_state_conn(
        self,
        conn: asyncpg.Connection,
        book_id: str,
        resource_type: str,
        resource_key: str,
    ) -> dict | None:
        row = await conn.fetchrow(
            """SELECT current_version, current_revision_id, content_hash, updated_at
               FROM novel_resource_state
               WHERE book_id = $1 AND resource_type = $2 AND resource_key = $3""",
            book_id,
            resource_type,
            resource_key,
        )
        return row_to_dict(row)

    async def list_revisions(
        self, book_id: str, resource_type: str, resource_key: str
    ) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            state = await self.get_resource_state_conn(
                conn, book_id, resource_type, resource_key
            )
            rows = await conn.fetch(
                """SELECT id AS revision_id, version, base_version, edit_mode, source, source_detail,
                          edit_intensity, diff_stats, actor_ref, request_id, summary, reason,
                          metadata, created_at
                   FROM novel_resource_revision
                   WHERE book_id = $1 AND resource_type = $2 AND resource_key = $3
                   ORDER BY version DESC""",
                book_id,
                resource_type,
                resource_key,
            )
        return {
            "book_id": book_id,
            "resource_type": resource_type,
            "resource_key": resource_key,
            "current_version": state.get("current_version", 0) if state else 0,
            "revisions": [row_to_dict(r) for r in rows],
        }

    async def get_revision(
        self, book_id: str, resource_type: str, resource_key: str, revision_id: str
    ) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id AS revision_id, book_id, resource_type, resource_key, version, base_version,
                          edit_mode, source, source_detail, edit_intensity, diff_stats, actor_ref,
                          request_id, before_content, after_content, diff, summary, reason, metadata, created_at
                   FROM novel_resource_revision
                   WHERE book_id = $1 AND resource_type = $2 AND resource_key = $3 AND id = $4""",
                book_id,
                resource_type,
                resource_key,
                revision_id,
            )
        if not row:
            raise NotFoundError("修订记录不存在", {"revision_id": revision_id})
        return row_to_dict(row)
