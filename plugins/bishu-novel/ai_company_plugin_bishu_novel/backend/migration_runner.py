"""Transactional PostgreSQL migration execution and verification."""

from __future__ import annotations

from pathlib import Path

from .migration_catalog import (
    Family,
    MigrationSpec,
    catalog_for,
)
from .migration_catalog import (
    plugin_root as _plugin_root,
)


class MigrationError(RuntimeError):
    """Operator-actionable migration failure."""


class AdoptionRequiredError(MigrationError):
    """An existing unledgered database must be explicitly adopted."""


class ChecksumMismatchError(MigrationError):
    """A previously applied migration no longer matches its source."""


class SchemaMismatchError(MigrationError):
    """The live schema cannot prove the claimed migration state."""


_LEDGER = {
    "novel": "novel_schema_migration",
}

_APP_SENTINELS = {
    "novel": ("book", "novel_job"),
}
_LOCK_TIMEOUT = "30s"


def _without_outer_transaction(sql: str) -> str:
    lines = sql.splitlines()
    return "\n".join(
        line for line in lines if line.strip().upper() not in {"BEGIN;", "COMMIT;"}
    )


class MigrationRunner:
    def __init__(self, root: Path | None = None) -> None:
        self.root = _plugin_root(root)

    async def migrate(
        self,
        connection,
        family: Family,
        *,
        release_revision: str,
    ) -> list[str]:
        return await self._locked(
            connection,
            family,
            self._migrate_locked,
            release_revision=release_revision,
        )

    async def adopt(
        self,
        connection,
        family: Family,
        *,
        release_revision: str,
    ) -> list[str]:
        return await self._locked(
            connection,
            family,
            self._adopt_locked,
            release_revision=release_revision,
        )

    async def verify(self, connection, family: Family) -> list[str]:
        return await self._locked(connection, family, self._verify_locked)

    async def _locked(self, connection, family: Family, operation, **kwargs):
        lock_name = f"{family}:schema-migrations"
        previous_timeout = await connection.fetchval(
            "SELECT current_setting('lock_timeout')"
        )
        await connection.fetchval(
            "SELECT set_config('lock_timeout', $1, false)",
            _LOCK_TIMEOUT,
        )
        locked = False
        try:
            try:
                await connection.fetchval(
                    "SELECT pg_advisory_lock(hashtext($1)::bigint)", lock_name
                )
                locked = True
            except Exception as exc:
                raise MigrationError(
                    f"migration lock acquisition failed within {_LOCK_TIMEOUT}"
                ) from exc
            return await operation(connection, family, **kwargs)
        finally:
            try:
                if locked:
                    await connection.fetchval(
                        "SELECT pg_advisory_unlock(hashtext($1)::bigint)", lock_name
                    )
            finally:
                await connection.fetchval(
                    "SELECT set_config('lock_timeout', $1, false)",
                    previous_timeout,
                )

    async def _migrate_locked(
        self,
        connection,
        family: Family,
        *,
        release_revision: str,
    ) -> list[str]:
        ledger_exists = await self._relation_exists(connection, _LEDGER[family])
        has_application_data = await self._has_application_schema(connection, family)
        if has_application_data and not ledger_exists:
            raise AdoptionRequiredError(
                f"existing {family} database has no checksum ledger; run adopt first"
            )
        if ledger_exists and not all(
            [
                await self._column_exists(
                    connection, _LEDGER[family], "checksum_sha256"
                ),
                await self._column_exists(
                    connection, _LEDGER[family], "release_revision"
                ),
            ]
        ):
            raise AdoptionRequiredError(
                f"existing {family} ledger has no checksum contract; run adopt first"
            )

        await self._ensure_ledger(connection, family)
        rows = await self._ledger_rows(connection, family)
        applied = self._validated_ledger(family, rows, require_complete=False)
        self._require_prefix(family, applied)

        applied_now: list[str] = []
        for migration in catalog_for(family, self.root):
            if migration.migration_id in applied:
                continue
            try:
                async with connection.transaction():
                    sql = _without_outer_transaction(
                        migration.path.read_text(encoding="utf-8")
                    )
                    await connection.execute(sql)
                    await self._record(
                        connection,
                        family,
                        migration,
                        release_revision=release_revision,
                    )
                    await self._require_schema(connection, migration)
            except MigrationError:
                raise
            except Exception as exc:
                raise MigrationError(
                    f"migration failed: {migration.migration_id} ({type(exc).__name__})"
                ) from exc
            applied_now.append(migration.migration_id)
        return applied_now

    async def _adopt_locked(
        self,
        connection,
        family: Family,
        *,
        release_revision: str,
    ) -> list[str]:
        if not await self._has_application_schema(connection, family):
            raise SchemaMismatchError(
                f"empty {family} database must be migrated, not adopted"
            )

        async with connection.transaction():
            await self._ensure_ledger(connection, family)
            rows = await self._ledger_rows(connection, family)
            existing = {str(row["migration_id"]): row for row in rows}
            known = {
                migration.migration_id for migration in catalog_for(family, self.root)
            }
            unknown = sorted(set(existing) - known)
            if unknown:
                raise SchemaMismatchError(
                    f"{family} ledger contains unknown migrations: {', '.join(unknown)}"
                )

            adopted: list[str] = []
            reached_gap = False
            for migration in catalog_for(family, self.root):
                schema_matches = await self._schema_matches(connection, migration)
                row = existing.get(migration.migration_id)
                if reached_gap:
                    if row or schema_matches:
                        raise SchemaMismatchError(
                            f"{family} schema is not a provable migration prefix at "
                            f"{migration.migration_id}"
                        )
                    continue
                if not schema_matches:
                    if row:
                        raise SchemaMismatchError(
                            "ledgered migration lacks required schema: "
                            f"{migration.migration_id}"
                        )
                    reached_gap = True
                    continue
                if (
                    row
                    and row.get("checksum_sha256") not in (None, "")
                    and str(row["checksum_sha256"]) != migration.checksum_sha256
                ):
                    raise ChecksumMismatchError(
                        f"migration checksum changed: {migration.migration_id}"
                    )
                await self._record(
                    connection,
                    family,
                    migration,
                    release_revision=release_revision,
                )
                adopted.append(migration.migration_id)

            if not adopted:
                raise SchemaMismatchError(
                    f"existing {family} schema does not match the first migration"
                )
            return adopted

    async def _verify_locked(self, connection, family: Family) -> list[str]:
        await self._require_ledger_contract(connection, family)
        rows = await self._ledger_rows(connection, family)
        self._validated_ledger(family, rows, require_complete=True)
        for migration in catalog_for(family, self.root):
            await self._require_schema(connection, migration)
        return [migration.migration_id for migration in catalog_for(family, self.root)]

    async def _require_ledger_contract(self, connection, family: Family) -> None:
        table = _LEDGER[family]
        if await self._relation_kind(connection, table) != "r":
            raise AdoptionRequiredError(f"{family} checksum ledger is missing")
        expected_columns = (
            ("migration_id", "text", True),
            ("checksum_sha256", "text", False),
            ("release_revision", "text", False),
            ("applied_at", "timestamp with time zone", True),
        )
        for column, data_type, not_null in expected_columns:
            if await self._column_signature(connection, table, column) != (
                data_type,
                not_null,
            ):
                raise AdoptionRequiredError(
                    f"{family} checksum ledger contract is incomplete; run adopt first"
                )
        if await self._default_expression(connection, table, "applied_at") != "now()":
            raise AdoptionRequiredError(
                f"{family} checksum ledger contract is incomplete; run adopt first"
            )

    async def _has_application_schema(self, connection, family: Family) -> bool:
        for relation in _APP_SENTINELS[family]:
            if await self._relation_exists(connection, relation):
                return True
        return False

    async def _ensure_ledger(self, connection, family: Family) -> None:
        table = _LEDGER[family]
        await connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                migration_id TEXT PRIMARY KEY,
                checksum_sha256 TEXT,
                release_revision TEXT,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CHECK (
                    checksum_sha256 IS NULL
                    OR checksum_sha256 ~ '^[0-9a-f]{{64}}$'
                )
            )
            """
        )
        await connection.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS checksum_sha256 TEXT"
        )
        await connection.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS release_revision TEXT"
        )

    async def _ledger_rows(self, connection, family: Family) -> list[dict]:
        table = _LEDGER[family]
        rows = await connection.fetch(
            f"SELECT migration_id, checksum_sha256, release_revision "
            f"FROM {table} ORDER BY migration_id"
        )
        return [dict(row) for row in rows]

    def _validated_ledger(
        self,
        family: Family,
        rows: list[dict],
        *,
        require_complete: bool,
    ) -> set[str]:
        migrations = {
            migration.migration_id: migration
            for migration in catalog_for(family, self.root)
        }
        applied: set[str] = set()
        for row in rows:
            migration_id = str(row["migration_id"])
            migration = migrations.get(migration_id)
            if migration is None:
                raise SchemaMismatchError(
                    f"{family} ledger contains unknown migration: {migration_id}"
                )
            checksum = row.get("checksum_sha256")
            if not checksum:
                raise AdoptionRequiredError(
                    f"migration has no checksum; run adopt first: {migration_id}"
                )
            if str(checksum) != migration.checksum_sha256:
                raise ChecksumMismatchError(
                    f"migration checksum changed: {migration_id}"
                )
            applied.add(migration_id)
        self._require_prefix(family, applied)
        if require_complete and len(applied) != len(migrations):
            raise SchemaMismatchError(f"{family} migration ledger is incomplete")
        return applied

    def _require_prefix(self, family: Family, applied: set[str]) -> None:
        ids = [migration.migration_id for migration in catalog_for(family, self.root)]
        expected = set(ids[: len(applied)])
        if applied != expected:
            raise SchemaMismatchError(
                f"{family} migration ledger is not an ordered prefix"
            )

    async def _record(
        self,
        connection,
        family: Family,
        migration: MigrationSpec,
        *,
        release_revision: str,
    ) -> None:
        table = _LEDGER[family]
        await connection.execute(
            f"""
            INSERT INTO {table} (
                migration_id, checksum_sha256, release_revision, applied_at
            ) VALUES ($1, $2, $3, now())
            ON CONFLICT (migration_id) DO UPDATE SET
                checksum_sha256 = EXCLUDED.checksum_sha256,
                release_revision = COALESCE({table}.release_revision, EXCLUDED.release_revision)
            WHERE {table}.checksum_sha256 IS NULL
               OR {table}.checksum_sha256 = EXCLUDED.checksum_sha256
            """,
            migration.migration_id,
            migration.checksum_sha256,
            release_revision,
        )

    async def _relation_exists(self, connection, relation: str) -> bool:
        return bool(
            await connection.fetchval(
                "SELECT to_regclass($1) IS NOT NULL", f"public.{relation}"
            )
        )

    async def _relation_kind(self, connection, relation: str) -> str | None:
        value = await connection.fetchval(
            """
            SELECT relation.relkind::text
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = $1
            """,
            relation,
        )
        return str(value) if value is not None else None

    async def _column_exists(self, connection, table: str, column: str) -> bool:
        return bool(
            await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = $1
                      AND column_name = $2
                )
                """,
                table,
                column,
            )
        )

    async def _view_hash(self, connection, view: str) -> str | None:
        value = await connection.fetchval(
            """
            SELECT encode(
                digest(pg_get_viewdef($1::regclass, true), 'sha256'),
                'hex'
            )
            """,
            f"public.{view}",
        )
        return str(value) if value is not None else None

    async def _column_signature(
        self, connection, table: str, column: str
    ) -> tuple[str, bool] | None:
        row = await connection.fetchrow(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod) AS data_type,
                   attribute.attnotnull AS not_null
            FROM pg_attribute AS attribute
            JOIN pg_class AS relation ON relation.oid = attribute.attrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = $1
              AND attribute.attname = $2
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            """,
            table,
            column,
        )
        if row is None:
            return None
        return str(row["data_type"]), bool(row["not_null"])

    async def _default_expression(
        self, connection, table: str, column: str
    ) -> str | None:
        value = await connection.fetchval(
            """
            SELECT pg_get_expr(default_row.adbin, default_row.adrelid, true)
            FROM pg_attrdef AS default_row
            JOIN pg_class AS relation ON relation.oid = default_row.adrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = relation.oid
             AND attribute.attnum = default_row.adnum
            WHERE namespace.nspname = 'public'
              AND relation.relname = $1
              AND attribute.attname = $2
            """,
            table,
            column,
        )
        return str(value) if value is not None else None

    async def _constraint_exists(
        self,
        connection,
        table: str,
        constraint_type: str,
        definition: str,
    ) -> bool:
        return bool(
            await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint AS constraint_row
                    JOIN pg_class AS relation
                      ON relation.oid = constraint_row.conrelid
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = $1
                      AND constraint_row.contype::text = $2
                      AND pg_get_constraintdef(constraint_row.oid) = $3
                )
                """,
                table,
                constraint_type,
                definition,
            )
        )

    async def _index_signature(
        self, connection, index_name: str
    ) -> (
        tuple[
            str,
            str,
            bool,
            bool,
            bool,
            bool,
            tuple[str, ...],
            str,
        ]
        | None
    ):
        row = await connection.fetchrow(
            """
            SELECT table_relation.relname AS table_name,
                   access_method.amname AS access_method,
                   index_row.indisunique AS is_unique,
                   index_row.indnullsnotdistinct AS nulls_not_distinct,
                   index_row.indisvalid AS is_valid,
                   index_row.indisready AS is_ready,
                   ARRAY(
                       SELECT pg_get_indexdef(
                           index_row.indexrelid, position, true
                       )
                       FROM generate_series(1, index_row.indnkeyatts) AS position
                   ) AS keys,
                   COALESCE(
                       pg_get_expr(index_row.indpred, index_row.indrelid, true),
                       ''
                   ) AS predicate
            FROM pg_index AS index_row
            JOIN pg_class AS index_relation
              ON index_relation.oid = index_row.indexrelid
            JOIN pg_class AS table_relation
              ON table_relation.oid = index_row.indrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = index_relation.relnamespace
            JOIN pg_am AS access_method
              ON access_method.oid = index_relation.relam
            WHERE namespace.nspname = 'public'
              AND index_relation.relname = $1
            """,
            index_name,
        )
        if row is None:
            return None
        return (
            str(row["table_name"]),
            str(row["access_method"]),
            bool(row["is_unique"]),
            bool(row["nulls_not_distinct"]),
            bool(row["is_valid"]),
            bool(row["is_ready"]),
            tuple(str(value) for value in row["keys"]),
            str(row["predicate"]),
        )

    async def _schema_matches(self, connection, migration: MigrationSpec) -> bool:
        for relation, relation_kind in migration.relation_signatures:
            if await self._relation_kind(connection, relation) != relation_kind:
                return False
        for table, column in migration.columns:
            if not await self._column_exists(connection, table, column):
                return False
        for table, column in migration.absent_columns:
            if await self._column_exists(connection, table, column):
                return False
        for table, column, data_type, not_null in migration.column_signatures:
            if await self._column_signature(connection, table, column) != (
                data_type,
                not_null,
            ):
                return False
        for view, definition_hash in migration.views:
            if await self._view_hash(connection, view) != definition_hash:
                return False
        for table, column, expression in migration.defaults:
            if await self._default_expression(connection, table, column) != expression:
                return False
        for table, constraint_type, definition in migration.constraints:
            if not await self._constraint_exists(
                connection,
                table,
                constraint_type,
                definition,
            ):
                return False
        for (
            index_name,
            table_name,
            access_method,
            is_unique,
            nulls_not_distinct,
            is_valid,
            is_ready,
            keys,
            predicate,
        ) in migration.indexes:
            if await self._index_signature(connection, index_name) != (
                table_name,
                access_method,
                is_unique,
                nulls_not_distinct,
                is_valid,
                is_ready,
                keys,
                predicate,
            ):
                return False
        return True

    async def _require_schema(self, connection, migration: MigrationSpec) -> None:
        if not await self._schema_matches(connection, migration):
            raise SchemaMismatchError(
                f"migration did not produce its required schema: {migration.migration_id}"
            )
