from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from ai_company_plugin_bishu_novel.backend.migration_runner import (
    AdoptionRequiredError,
    ChecksumMismatchError,
    MigrationError,
    MigrationRunner,
    SchemaMismatchError,
    catalog_for,
)
from ai_company_plugin_bishu_novel.backend.migrations_cli import _connection_options

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


NOVEL_IDS = [
    "20260601_novel_api_baseline",
    "20260609_product_schema",
    "20260613_book_scale_params",
    "20260613_book_soft_delete",
    "20260720_novel_runtime_schema",
]

def test_catalog_has_one_canonical_order() -> None:
    novel = catalog_for("novel", PLUGIN_ROOT)
    assert [migration.migration_id for migration in novel] == NOVEL_IDS


def test_plugin_does_not_own_database_bootstrap_or_sibling_schema() -> None:
    assert not (PLUGIN_ROOT / "resources" / "docker-init").exists()


def test_baseline_creates_every_novel_api_foundation_table_before_upgrades() -> None:
    baseline = (
        PLUGIN_ROOT / "resources/migrations/20260601_novel_api_baseline.sql"
    ).read_text(encoding="utf-8")
    for table in ("book", "world", "character", "outline", "chapter", "hook", "debt"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in baseline


def test_runtime_migration_adds_columns_and_fails_closed_before_unique_indexes() -> (
    None
):
    sql = (
        PLUGIN_ROOT / "resources/migrations/20260720_novel_runtime_schema.sql"
    ).read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS essence TEXT" in sql
    assert "ADD COLUMN IF NOT EXISTS post_hoc_status TEXT" in sql
    assert "RAISE EXCEPTION" in sql
    assert "HAVING count(*) > 1" in sql
    assert sql.index("RAISE EXCEPTION") < sql.index(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_novel_job_active_operation"
    )
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_novel_job_active_polish_chapter" in sql
    assert "operation <> 'chapter_polish'" in sql
    assert "operation = 'chapter_polish'" in sql
    assert "status IN ('queued', 'running')" in sql
    assert "request_payload->>'chapter_number'" in sql
    assert "DELETE FROM novel_job" not in sql


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeConnection:
    def __init__(
        self,
        *,
        relations: set[str] | None = None,
        relation_kinds: dict[str, str] | None = None,
        columns: set[tuple[str, str]] | None = None,
        column_signatures: dict[tuple[str, str], tuple[str, bool]] | None = None,
        constraints: set[tuple[str, str, str]] | None = None,
        index_signatures: dict[
            str,
            tuple[
                str,
                str,
                bool,
                bool,
                bool,
                bool,
                tuple[str, ...],
                str,
            ],
        ]
        | None = None,
        view_hashes: dict[str, str] | None = None,
        default_expressions: dict[tuple[str, str], str] | None = None,
        ledger_rows: list[dict] | None = None,
        fail_execute_contains: str | None = None,
        fail_advisory_lock: bool = False,
    ) -> None:
        self.relations = relations or set()
        self.relation_kinds = relation_kinds or {
            relation: "r" for relation in self.relations
        }
        self.columns = columns or set()
        self.column_signatures = column_signatures or {}
        self.constraints = constraints or set()
        self.index_signatures = index_signatures or {}
        self.view_hashes = view_hashes or {}
        self.default_expressions = default_expressions or {}
        self.ledger_rows = ledger_rows or []
        self.fail_execute_contains = fail_execute_contains
        self.fail_advisory_lock = fail_advisory_lock
        self.executed: list[tuple[str, tuple]] = []
        self.execute_calls: list[tuple[str, tuple]] = []
        self.locked = False
        self.lock_timeout = "0"

    def transaction(self):
        return _Transaction()

    async def fetchval(self, sql: str, *args):
        self.executed.append((sql, args))
        if "current_setting('lock_timeout')" in sql:
            return self.lock_timeout
        if "set_config('lock_timeout'" in sql:
            self.lock_timeout = args[0]
            return self.lock_timeout
        if "pg_advisory_lock" in sql:
            if self.fail_advisory_lock:
                raise TimeoutError("injected lock timeout")
            self.locked = True
            return True
        if "pg_advisory_unlock" in sql:
            self.locked = False
            return True
        if "relkind::text" in sql:
            return self.relation_kinds.get(args[0])
        if "pg_get_viewdef" in sql:
            return self.view_hashes.get(args[0].removeprefix("public."))
        if "pg_attrdef" in sql:
            return self.default_expressions.get((args[0], args[1]))
        if "to_regclass" in sql:
            return args[0].removeprefix("public.") in self.relations
        if "information_schema.columns" in sql:
            return (args[0], args[1]) in self.columns
        if "pg_constraint" in sql:
            return (args[0], args[1], args[2]) in self.constraints
        raise AssertionError(f"unexpected fetchval: {sql}")

    async def fetchrow(self, sql: str, *args):
        self.executed.append((sql, args))
        if "pg_attribute" in sql:
            signature = self.column_signatures.get((args[0], args[1]))
            if signature is None:
                return None
            return {"data_type": signature[0], "not_null": signature[1]}
        if "pg_index" in sql:
            signature = self.index_signatures.get(args[0])
            if signature is None:
                return None
            return {
                "table_name": signature[0],
                "access_method": signature[1],
                "is_unique": signature[2],
                "nulls_not_distinct": signature[3],
                "is_valid": signature[4],
                "is_ready": signature[5],
                "keys": signature[6],
                "predicate": signature[7],
            }
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def fetch(self, sql: str, *args):
        self.executed.append((sql, args))
        if "migration_id" in sql and "checksum_sha256" in sql:
            return self.ledger_rows
        raise AssertionError(f"unexpected fetch: {sql}")

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))
        self.execute_calls.append((sql, args))
        if self.fail_execute_contains and self.fail_execute_contains in sql:
            raise RuntimeError("injected migration failure")
        return "OK"


def _complete_connection() -> FakeConnection:
    migrations = catalog_for("novel", PLUGIN_ROOT)
    ledger = "novel_schema_migration"
    relation_kinds = {ledger: "r"}
    columns = {
        (ledger, "migration_id"),
        (ledger, "checksum_sha256"),
        (ledger, "release_revision"),
        (ledger, "applied_at"),
    }
    column_signatures = {
        (ledger, "migration_id"): ("text", True),
        (ledger, "checksum_sha256"): ("text", False),
        (ledger, "release_revision"): ("text", False),
        (ledger, "applied_at"): ("timestamp with time zone", True),
    }
    constraints: set[tuple[str, str, str]] = set()
    index_signatures = {}
    view_hashes = {}
    default_expressions = {
        (ledger, "applied_at"): "now()",
    }
    for migration in migrations:
        relation_kinds.update(dict(migration.relation_signatures))
        columns.update(migration.columns)
        column_signatures.update(
            {
                (table, column): (data_type, not_null)
                for table, column, data_type, not_null in migration.column_signatures
            }
        )
        columns.update(column_signatures)
        constraints.update(migration.constraints)
        index_signatures.update(
            {signature[0]: signature[1:] for signature in migration.indexes}
        )
        view_hashes.update(dict(migration.views))
        default_expressions.update(
            {
                (table, column): expression
                for table, column, expression in migration.defaults
            }
        )
    ledger_rows = [
        {
            "migration_id": migration.migration_id,
            "checksum_sha256": migration.checksum_sha256,
            "release_revision": "test",
        }
        for migration in migrations
    ]
    return FakeConnection(
        relations=set(relation_kinds),
        relation_kinds=relation_kinds,
        columns=columns,
        column_signatures=column_signatures,
        constraints=constraints,
        index_signatures=index_signatures,
        view_hashes=view_hashes,
        default_expressions=default_expressions,
        ledger_rows=ledger_rows,
    )


def test_existing_database_without_ledger_requires_explicit_adoption() -> None:
    connection = FakeConnection(relations={"book"})
    runner = MigrationRunner(PLUGIN_ROOT)

    with pytest.raises(AdoptionRequiredError, match="adopt"):
        asyncio.run(runner.migrate(connection, "novel", release_revision="test"))

    assert connection.locked is False
    assert not any(
        "20260601_novel_api_baseline" in sql for sql, _ in connection.executed
    )


def test_legacy_ledger_requires_adoption_before_it_is_altered() -> None:
    connection = FakeConnection(
        relations={"book", "novel_schema_migration"},
        ledger_rows=[
            {
                "migration_id": "20260601_novel_api_baseline",
                "checksum_sha256": None,
                "release_revision": None,
            }
        ],
    )
    runner = MigrationRunner(PLUGIN_ROOT)

    with pytest.raises(AdoptionRequiredError, match="checksum contract"):
        asyncio.run(runner.migrate(connection, "novel", release_revision="test"))

    assert connection.locked is False
    assert not any(
        sql.lstrip().startswith("ALTER TABLE") for sql, _ in connection.executed
    )


def test_checksum_drift_is_rejected_without_exposing_database_changes() -> None:
    baseline = catalog_for("novel", PLUGIN_ROOT)[0]
    connection = _complete_connection()
    connection.ledger_rows[0]["checksum_sha256"] = "0" * 64
    runner = MigrationRunner(PLUGIN_ROOT)

    with pytest.raises(ChecksumMismatchError, match=baseline.migration_id):
        asyncio.run(runner.verify(connection, "novel"))

    assert connection.locked is False
    assert connection.execute_calls == []


def test_advisory_lock_is_released_when_migration_execution_fails() -> None:
    connection = FakeConnection(fail_execute_contains="CREATE EXTENSION")
    runner = MigrationRunner(PLUGIN_ROOT)

    with pytest.raises(MigrationError, match="20260601_novel_api_baseline"):
        asyncio.run(runner.migrate(connection, "novel", release_revision="test"))

    assert connection.locked is False


def test_advisory_lock_timeout_is_operator_actionable_and_restored() -> None:
    connection = FakeConnection(fail_advisory_lock=True)
    runner = MigrationRunner(PLUGIN_ROOT)

    with pytest.raises(MigrationError, match="lock acquisition failed within 30s"):
        asyncio.run(runner.verify(connection, "novel"))

    assert connection.locked is False
    assert connection.lock_timeout == "0"


def test_adoption_rejects_a_relation_set_with_the_wrong_column_signature() -> None:
    baseline = catalog_for("novel", PLUGIN_ROOT)[0]
    column_signatures = {
        (table, column): (data_type, not_null)
        for table, column, data_type, not_null in baseline.column_signatures
    }
    column_signatures[("book", "id")] = ("text", True)
    connection = FakeConnection(
        relations=set(baseline.relations),
        column_signatures=column_signatures,
        constraints=set(baseline.constraints),
    )
    runner = MigrationRunner(PLUGIN_ROOT)

    with pytest.raises(SchemaMismatchError, match="first migration"):
        asyncio.run(runner.adopt(connection, "novel", release_revision="test"))

    assert connection.locked is False


def test_verify_success_is_read_only() -> None:
    connection = _complete_connection()

    verified = asyncio.run(MigrationRunner(PLUGIN_ROOT).verify(connection, "novel"))

    assert verified == NOVEL_IDS
    assert connection.locked is False
    assert connection.execute_calls == []


def test_verify_rejects_an_incomplete_ledger_without_writing() -> None:
    connection = _complete_connection()
    connection.column_signatures.pop(("novel_schema_migration", "release_revision"))

    with pytest.raises(AdoptionRequiredError, match="ledger contract"):
        asyncio.run(MigrationRunner(PLUGIN_ROOT).verify(connection, "novel"))

    assert connection.locked is False
    assert connection.execute_calls == []


def test_verify_rejects_missing_dao_column_without_writing() -> None:
    baseline = catalog_for("novel", PLUGIN_ROOT)[0]
    assert ("chapter", "body", "text", False) in baseline.column_signatures
    connection = _complete_connection()
    connection.column_signatures.pop(("chapter", "body"))

    with pytest.raises(SchemaMismatchError, match=baseline.migration_id):
        asyncio.run(MigrationRunner(PLUGIN_ROOT).verify(connection, "novel"))

    assert connection.execute_calls == []


def test_verify_rejects_missing_runtime_default_without_writing() -> None:
    baseline = catalog_for("novel", PLUGIN_ROOT)[0]
    assert ("book", "id", "gen_random_uuid()") in baseline.defaults
    connection = _complete_connection()
    connection.default_expressions.pop(("book", "id"))

    with pytest.raises(SchemaMismatchError, match=baseline.migration_id):
        asyncio.run(MigrationRunner(PLUGIN_ROOT).verify(connection, "novel"))

    assert connection.execute_calls == []


@pytest.mark.parametrize(
    ("field_index", "wrong_value"),
    [
        (0, "book"),
        (1, "hash"),
        (3, False),
        (4, False),
        (5, False),
        (7, "status = 'queued'::text"),
    ],
)
def test_verify_rejects_wrong_same_name_partial_index_signature(
    field_index: int,
    wrong_value,
) -> None:
    connection = _complete_connection()
    name = "uq_novel_job_active_polish_chapter"
    signature = list(connection.index_signatures[name])
    signature[field_index] = wrong_value
    connection.index_signatures[name] = tuple(signature)

    with pytest.raises(SchemaMismatchError, match="runtime_schema"):
        asyncio.run(MigrationRunner(PLUGIN_ROOT).verify(connection, "novel"))

    assert connection.execute_calls == []


def test_connection_reads_password_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "db-password"
    password_file.write_text("shared-password\n", encoding="utf-8")
    monkeypatch.setenv("DB_PASSWORD_FILE", str(password_file))
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    assert _connection_options()["password"] == "shared-password"  # pragma: allowlist secret
