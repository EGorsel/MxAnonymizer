"""Database helpers: introspection + chunked anonymization passes.

Mendix tables follow the convention `module$entity`. Primary key is `id`
(uuid or bigint). Anonymization always runs in batches keyed by `id` so
huge tables don't blow up memory or transactions.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from mxanonymizer.config import Manifest, TableRule
from mxanonymizer.determinism import get_secret, short_hash
from mxanonymizer.row_transformers import get as get_row_transformer
from mxanonymizer.strategies import StrategyContext, get as get_strategy

log = logging.getLogger("mxanonymizer.db")


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool


@dataclass
class TableInfo:
    schema: str
    name: str
    pk_column: str | None
    columns: dict[str, ColumnInfo]
    unique_columns: set[str]
    fk_columns: set[str]


def list_tables(conn: psycopg.Connection, schema: str = "public") -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (schema,),
        )
        return [r[0] for r in cur.fetchall()]


def describe_table(conn: psycopg.Connection, table: str, schema: str = "public") -> TableInfo:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        cols = {
            r["column_name"]: ColumnInfo(
                name=r["column_name"],
                data_type=r["data_type"],
                is_nullable=(r["is_nullable"] == "YES"),
            )
            for r in cur.fetchall()
        }

        # PK column (we assume single-column PK — the Mendix convention).
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s AND tc.table_name = %s
            ORDER BY kcu.ordinal_position
            """,
            (schema, table),
        )
        pk_rows = cur.fetchall()
        pk_column = pk_rows[0]["column_name"] if pk_rows else None

        # Unique columns (single-column unique constraints/indexes).
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'UNIQUE'
              AND tc.table_schema = %s AND tc.table_name = %s
            """,
            (schema, table),
        )
        unique_columns = {r["column_name"] for r in cur.fetchall()}

        # FK columns (any column appearing in a FK constraint on this table).
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s AND tc.table_name = %s
            """,
            (schema, table),
        )
        fk_columns = {r["column_name"] for r in cur.fetchall()}

    return TableInfo(
        schema=schema,
        name=table,
        pk_column=pk_column,
        columns=cols,
        unique_columns=unique_columns,
        fk_columns=fk_columns,
    )


@contextlib.contextmanager
def replication_guard(conn: psycopg.Connection) -> Iterator[None]:
    """Temporarily set `session_replication_role = replica` so triggers don't
    fire while we rewrite rows. Restored on exit.
    """
    prev = None
    with conn.cursor() as cur:
        cur.execute("SHOW session_replication_role")
        row = cur.fetchone()
        prev = row[0] if row else "origin"
        cur.execute("SET session_replication_role = replica")
    try:
        yield
    finally:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET session_replication_role = {}").format(sql.Literal(prev)))


def _row_count(conn: psycopg.Connection, table: str, schema: str = "public") -> int:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _iter_pk_chunks(
    conn: psycopg.Connection,
    table: str,
    pk_column: str,
    columns: list[str],
    chunk_size: int,
    schema: str = "public",
) -> Iterator[list[dict]]:
    """Yield batches of rows ordered by PK. Cursor avoids loading the full table."""
    query = sql.SQL("SELECT {pk}, {cols} FROM {schema}.{table} ORDER BY {pk}").format(
        pk=sql.Identifier(pk_column),
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
    )
    with conn.cursor(name="mxanon_chunk_cur", row_factory=dict_row) as cur:
        cur.itersize = chunk_size
        cur.execute(query)
        batch: list[dict] = []
        for row in cur:
            batch.append(row)
            if len(batch) >= chunk_size:
                yield batch
                batch = []
        if batch:
            yield batch


def _apply_unique_suffix(value, ctx: StrategyContext) -> str:
    """Append a deterministic short hash of the PK so a unique constraint is preserved.

    Only applied when the column is unique and the strategy returned a string.
    For email-shaped values the suffix is inserted into the local part so the
    `@domain` tail is preserved.
    """
    if not isinstance(value, str):
        return value
    suffix = short_hash(ctx.secret, ctx.table, ctx.column, ctx.pk_value, length=6)
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local}.{suffix}@{domain}"
    return f"{value}.{suffix}"


def anonymize_table(
    conn: psycopg.Connection,
    table_name: str,
    rule: TableRule,
    manifest: Manifest,
    secret: bytes,
    schema: str = "public",
) -> dict:
    """Apply column rules to a single table. Returns a small stats dict."""
    if rule.skip:
        return {"table": table_name, "rows": 0, "skipped": True}

    info = describe_table(conn, table_name, schema=schema)
    if not info.pk_column:
        log.warning("Table %s has no PK; skipping (can't batch deterministically)", table_name)
        return {"table": table_name, "rows": 0, "skipped": True, "reason": "no_pk"}

    # Compose target columns from explicit `columns:` and from row-transformer params.
    target_columns: list[str] = []
    for col_name in rule.columns:
        if col_name not in info.columns:
            log.warning("Column %s.%s declared in manifest but not in DB; skipping", table_name, col_name)
            continue
        if col_name == info.pk_column or col_name in info.fk_columns:
            log.warning("Column %s.%s is PK/FK; refusing to anonymize", table_name, col_name)
            continue
        target_columns.append(col_name)

    rt_columns: list[str] = []
    if rule.row_transformer:
        for logical_name, db_col in rule.params.items():
            if not isinstance(db_col, str):
                continue
            if db_col not in info.columns:
                log.warning(
                    "Row-transformer column %s.%s missing in DB; skipping", table_name, db_col
                )
                continue
            if db_col == info.pk_column or db_col in info.fk_columns:
                log.warning("Row-transformer wants PK/FK %s.%s; refusing", table_name, db_col)
                continue
            if db_col not in target_columns:
                rt_columns.append(db_col)

    all_target_columns = target_columns + rt_columns
    if not all_target_columns:
        return {"table": table_name, "rows": 0, "skipped": True, "reason": "no_columns"}

    chunk_size = manifest.defaults.chunk_size
    total_rows = _row_count(conn, table_name, schema=schema)
    rewritten = 0

    update_stmt = sql.SQL("UPDATE {schema}.{table} SET {assigns} WHERE {pk} = %(pk)s").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
        assigns=sql.SQL(", ").join(
            sql.SQL("{col} = %({param})s").format(col=sql.Identifier(c), param=sql.SQL(c))
            for c in all_target_columns
        ),
        pk=sql.Identifier(info.pk_column),
    )

    row_transformer_fn = get_row_transformer(rule.row_transformer) if rule.row_transformer else None

    with conn.cursor() as write_cur:
        for batch in _iter_pk_chunks(
            conn, table_name, info.pk_column, all_target_columns, chunk_size, schema=schema
        ):
            params_list: list[dict] = []
            for row in batch:
                pk_value = row[info.pk_column]
                new_values: dict = {"pk": pk_value}

                # Per-column strategies.
                for col in target_columns:
                    rule_col = rule.columns[col]
                    if rule_col.strategy is None:
                        new_values[col] = None
                        continue
                    strategy = get_strategy(rule_col.strategy)
                    ctx = StrategyContext(
                        secret=secret,
                        table=table_name,
                        column=col,
                        value=row[col],
                        deterministic=rule_col.deterministic,
                        locale=manifest.defaults.locale,
                        params=rule_col.params,
                        pk_value=pk_value,
                    )
                    out = strategy(ctx)
                    if col in info.unique_columns and out is not None:
                        out = _apply_unique_suffix(out, ctx)
                    new_values[col] = out

                # Row transformer (writes to columns named in rule.params).
                if row_transformer_fn is not None:
                    rt_in = dict(row)
                    rt_in["__pk__"] = pk_value
                    rt_out = row_transformer_fn(
                        secret, table_name, rt_in, rule.params, manifest.defaults.locale
                    )
                    for col, val in rt_out.items():
                        new_values[col] = val

                params_list.append(new_values)
            write_cur.executemany(update_stmt, params_list)
            rewritten += len(params_list)
            log.info("  %s: %d/%d rows", table_name, rewritten, total_rows)

    return {"table": table_name, "rows": rewritten, "skipped": False}


def run_anonymization(conn: psycopg.Connection, manifest: Manifest, schema: str = "public") -> dict:
    """Top-level: apply manifest table-by-table inside one transaction with the
    replication guard active. Caller should commit/rollback.
    """
    secret = get_secret(manifest.defaults.determinism_secret_env)
    stats: list[dict] = []
    with replication_guard(conn):
        for table, rule in manifest.tables.items():
            log.info("Anonymizing %s", table)
            stats.append(anonymize_table(conn, table, rule, manifest, secret, schema=schema))
    return {"tables": stats}
