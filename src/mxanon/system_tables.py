"""Mendix `system$*` table handling.

Special-cased because:
- `system$user`: bcrypt password reset, plus name/email anonymization. Roles
  must stay intact so the local app behaves like prod.
- `system$filedocument`: contents stripped to NULL (blobs may contain real PII
  in scans/PDFs).
- `system$session`: truncated — stale sessions are useless locally.

This module discovers the actual columns at runtime since Mendix versions
may differ in casing/columns. We only touch what exists.
"""

from __future__ import annotations

import logging
import os

import psycopg
from passlib.hash import bcrypt
from psycopg import sql

from mxanon.config import Manifest
from mxanon.db import describe_table

log = logging.getLogger("mxanon.system")

SYSTEM_USER_TABLE = "system$user"
SYSTEM_FILEDOC_TABLE = "system$filedocument"
SYSTEM_SESSION_TABLE = "system$session"


def _column_exists(info, name: str) -> str | None:
    """Return the actual column name in the DB (Mendix can be CamelCase or lower)."""
    target = name.lower()
    for col in info.columns:
        if col.lower() == target:
            return col
    return None


def _table_exists(conn: psycopg.Connection, table: str, schema: str = "public") -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
        return cur.fetchone() is not None


def reset_system_user_passwords(
    conn: psycopg.Connection, dev_password: str, schema: str = "public"
) -> int:
    """Set every `system$user.Password` to `bcrypt(dev_password)` (cost 10)."""
    if not _table_exists(conn, SYSTEM_USER_TABLE, schema):
        log.info("%s not present; skipping password reset", SYSTEM_USER_TABLE)
        return 0

    info = describe_table(conn, SYSTEM_USER_TABLE, schema)
    pw_col = _column_exists(info, "Password")
    if not pw_col:
        log.warning("%s has no Password column; skipping password reset", SYSTEM_USER_TABLE)
        return 0

    new_hash = bcrypt.using(rounds=10).hash(dev_password)
    with conn.cursor() as cur:
        stmt = sql.SQL("UPDATE {}.{} SET {} = %s").format(
            sql.Identifier(schema), sql.Identifier(SYSTEM_USER_TABLE), sql.Identifier(pw_col)
        )
        cur.execute(stmt, (new_hash,))
        return cur.rowcount or 0


def anonymize_system_user_identity(
    conn: psycopg.Connection,
    secret: bytes,
    locale: str = "nl_NL",
    schema: str = "public",
) -> int:
    """Anonymize Name/Email/FullName columns on system$user. Preserves PK and
    role association rows (we never touch those).
    """
    from mxanon.strategies import StrategyContext, get as get_strategy

    if not _table_exists(conn, SYSTEM_USER_TABLE, schema):
        return 0

    info = describe_table(conn, SYSTEM_USER_TABLE, schema)
    name_col = _column_exists(info, "Name")
    email_col = _column_exists(info, "Email")
    full_col = _column_exists(info, "FullName")

    targets: list[tuple[str, str]] = []
    if name_col:
        targets.append((name_col, "fake_email_from_name"))  # Name is the login handle
    if email_col:
        targets.append((email_col, "fake_email_from_name"))
    if full_col:
        targets.append((full_col, "fake_full_name"))

    if not targets:
        return 0

    pk = info.pk_column or "id"
    rewritten = 0

    select_sql = sql.SQL("SELECT {pk}, {cols} FROM {schema}.{table}").format(
        pk=sql.Identifier(pk),
        cols=sql.SQL(", ").join(sql.Identifier(c) for c, _ in targets),
        schema=sql.Identifier(schema),
        table=sql.Identifier(SYSTEM_USER_TABLE),
    )

    with conn.cursor() as read_cur, conn.cursor() as write_cur:
        read_cur.execute(select_sql)
        for row in read_cur.fetchall():
            pk_value = row[0]
            new_values: dict = {"pk": pk_value}
            for (col, strat_name), original in zip(targets, row[1:], strict=True):
                strategy = get_strategy(strat_name)
                ctx = StrategyContext(
                    secret=secret,
                    table=SYSTEM_USER_TABLE,
                    column=col,
                    value=original,
                    deterministic=True,
                    locale=locale,
                    pk_value=pk_value,
                )
                new_values[col] = strategy(ctx)
            stmt = sql.SQL("UPDATE {schema}.{table} SET {assigns} WHERE {pk} = %(pk)s").format(
                schema=sql.Identifier(schema),
                table=sql.Identifier(SYSTEM_USER_TABLE),
                assigns=sql.SQL(", ").join(
                    sql.SQL("{col} = %({param})s").format(
                        col=sql.Identifier(c), param=sql.SQL(c)
                    )
                    for c, _ in targets
                ),
                pk=sql.Identifier(pk),
            )
            write_cur.execute(stmt, new_values)
            rewritten += 1

    return rewritten


def strip_filedocument_blobs(conn: psycopg.Connection, schema: str = "public") -> int:
    """For `system$filedocument` and any FileDocument-like table (those with a
    `Contents` column), set `Contents=NULL`, `HasContents=false`, `Name=''`,
    `Size=0`. Subclasses inherit columns; we walk every public table that has
    a `Contents` bytea column.
    """
    rewritten_total = 0
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.columns
            WHERE table_schema = %s AND lower(column_name) = 'contents'
              AND data_type = 'bytea'
            """,
            (schema,),
        )
        candidate_tables = [r[0] for r in cur.fetchall()]

    for table in candidate_tables:
        info = describe_table(conn, table, schema)
        sets: list[tuple[str, object]] = []
        if c := _column_exists(info, "Contents"):
            sets.append((c, None))
        if c := _column_exists(info, "HasContents"):
            sets.append((c, False))
        if c := _column_exists(info, "Name"):
            sets.append((c, ""))
        if c := _column_exists(info, "Size"):
            sets.append((c, 0))
        if not sets:
            continue

        stmt = sql.SQL("UPDATE {}.{} SET {}").format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(col)) for col, _ in sets
            ),
        )
        with conn.cursor() as cur:
            cur.execute(stmt, [v for _, v in sets])
            rewritten_total += cur.rowcount or 0
            log.info("Stripped blobs from %s (%d rows)", table, cur.rowcount or 0)

    return rewritten_total


def truncate_sessions(conn: psycopg.Connection, schema: str = "public") -> int:
    if not _table_exists(conn, SYSTEM_SESSION_TABLE, schema):
        return 0
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DELETE FROM {}.{}").format(
            sql.Identifier(schema), sql.Identifier(SYSTEM_SESSION_TABLE)
        ))
        return cur.rowcount or 0


def apply_system_rules(conn: psycopg.Connection, manifest: Manifest, schema: str = "public") -> dict:
    """Apply all `_global`-driven system$* rules per the manifest."""
    from mxanon.determinism import get_secret

    stats: dict = {}

    if manifest.file_document.strategy == "strip_blobs":
        stats["filedocument_rows_stripped"] = strip_filedocument_blobs(conn, schema)

    if manifest.system_user.anonymize_email or manifest.system_user.anonymize_name:
        secret = get_secret(manifest.defaults.determinism_secret_env)
        stats["system_user_identity_rows"] = anonymize_system_user_identity(
            conn, secret, locale=manifest.defaults.locale, schema=schema
        )

    if manifest.system_user.reset_password_hash:
        dev_password = os.environ.get(manifest.system_user.dev_password_env)
        if not dev_password:
            raise RuntimeError(
                f"Environment variable {manifest.system_user.dev_password_env} is not set "
                "(needed to reset system$user passwords)."
            )
        stats["system_user_passwords_reset"] = reset_system_user_passwords(
            conn, dev_password, schema
        )

    stats["system_sessions_truncated"] = truncate_sessions(conn, schema)
    return stats
