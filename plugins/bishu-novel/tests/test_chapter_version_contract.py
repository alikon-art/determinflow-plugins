"""Chapter summaries and details expose the same body revision identity."""

from __future__ import annotations

import asyncio

import pytest

from ai_company_plugin_bishu_novel.backend.novel import dao as dao_module
from ai_company_plugin_bishu_novel.backend.novel.dao import NovelDAO


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Context(self.connection)


class _ListConnection:
    def __init__(self):
        self.query = ""

    async def fetch(self, query, *_args):
        self.query = " ".join(query.split())
        return [
            {
                "chapter_number": 1,
                "title": "潮汐印记",
                "word_count": 1200,
                "status": "draft",
                "post_hoc_status": None,
                "version": 3,
                "revision_id": "00000000-0000-0000-0000-000000000003",
                "created_at": None,
                "updated_at": None,
            }
        ]


class _DetailConnection:
    def __init__(self, *, with_resource_state: bool = True):
        self.calls = 0
        self.query = ""
        self.args = ()
        self.with_resource_state = with_resource_state

    async def fetchrow(self, query, *args):
        self.calls += 1
        self.query = " ".join(query.split())
        self.args = args
        return {
            "chapter_number": 1,
            "title": "潮汐印记",
            "body": "正文",
            "word_count": 2,
            "status": "draft",
            "post_hoc_status": None,
            "version": 3 if self.with_resource_state else 0,
            "revision_id": (
                "00000000-0000-0000-0000-000000000003"
                if self.with_resource_state
                else None
            ),
            "created_at": None,
            "updated_at": None,
        }


def test_list_chapters_joins_body_resource_state(monkeypatch):
    connection = _ListConnection()

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(dao_module, "get_pool", fake_get_pool)
    chapters = asyncio.run(NovelDAO().list_chapters("book-1"))

    assert "novel_resource_state" in connection.query
    assert "current_version" in connection.query
    assert "current_revision_id" in connection.query
    assert "GREATEST(4, length(c.chapter_number::text))" in connection.query
    assert "WHEN c.chapter_number < 0" in connection.query
    assert chapters[0]["version"] == 3
    assert chapters[0]["revision_id"] == "00000000-0000-0000-0000-000000000003"


def test_get_chapter_returns_version_and_revision_id(monkeypatch):
    connection = _DetailConnection()

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(dao_module, "get_pool", fake_get_pool)
    chapter = asyncio.run(NovelDAO().get_chapter("book-1", 1))

    assert connection.calls == 1
    assert "LEFT JOIN novel_resource_state" in connection.query
    assert "COALESCE(s.current_version, 0)" in connection.query
    assert "s.current_revision_id AS revision_id" in connection.query
    assert "s.resource_key = $3" in connection.query
    assert connection.args == ("book-1", 1, "0001:body")
    assert chapter["version"] == 3
    assert chapter["revision_id"] == "00000000-0000-0000-0000-000000000003"


def test_get_chapter_without_resource_state_uses_zero_and_null(monkeypatch):
    connection = _DetailConnection(with_resource_state=False)

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(dao_module, "get_pool", fake_get_pool)
    chapter = asyncio.run(NovelDAO().get_chapter("book-1", 1))

    assert connection.calls == 1
    assert "LEFT JOIN novel_resource_state" in connection.query
    assert chapter["version"] == 0
    assert chapter["revision_id"] is None


@pytest.mark.parametrize(
    ("chapter_number", "resource_key"),
    ((10_000, "10000:body"), (-1, "-001:body")),
)
def test_get_chapter_uses_the_writer_resource_key_contract_at_boundaries(
    monkeypatch, chapter_number, resource_key
):
    connection = _DetailConnection()

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(dao_module, "get_pool", fake_get_pool)
    asyncio.run(NovelDAO().get_chapter("book-1", chapter_number))

    assert connection.calls == 1
    assert connection.args == ("book-1", chapter_number, resource_key)
