"""Verification: post-anonymization leak and sanity checks.

Exits non-zero if any leak is found. Writes a JSON report to `./reports/`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql

from mxanon.config import Manifest
from mxanon.db import describe_table

log = logging.getLogger("mxanon.verify")

# Leak patterns: things that should NEVER appear in anonymized columns.
LEAK_PATTERNS: dict[str, re.Pattern] = {
    # Real-looking ANWB email domains.
    "anwb_email": re.compile(r"@anwb\.(nl|com)$", re.IGNORECASE),
    # Real Dutch IBAN bank codes (anonymized IBANs use TEST/FAKE/MXAN/ANON).
    "real_iban_bank": re.compile(r"^NL\d{2}(INGB|RABO|ABNA|TRIO|SNSB|ASNB|KNAB|BUNQ)\d{10}$"),
}


def _select_column_values(
    conn: psycopg.Connection, schema: str, table: str, column: str, limit: int = 10000
) -> list[str]:
    stmt = sql.SQL(
        "SELECT {col} FROM {schema}.{table} "
        "WHERE {col} IS NOT NULL LIMIT %s"
    ).format(
        col=sql.Identifier(column),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(stmt, (limit,))
            return [str(r[0]) for r in cur.fetchall() if r[0] is not None]
    except psycopg.Error:
        return []


def check_leaks(
    conn: psycopg.Connection, manifest: Manifest, schema: str = "public"
) -> list[dict]:
    """Scan every column the manifest claims to anonymize for leak patterns."""
    leaks: list[dict] = []
    for table_name, rule in manifest.tables.items():
        if rule.skip:
            continue
        anonymized_columns = list(rule.columns.keys())
        if rule.row_transformer:
            anonymized_columns += [
                c for c in rule.params.values() if isinstance(c, str)
            ]
        for col in anonymized_columns:
            values = _select_column_values(conn, schema, table_name, col)
            for label, pattern in LEAK_PATTERNS.items():
                hits = [v for v in values if pattern.search(v)]
                if hits:
                    leaks.append({
                        "table": table_name,
                        "column": col,
                        "pattern": label,
                        "samples": hits[:3],
                        "count": len(hits),
                    })
    return leaks


def check_filedocument_stripped(conn: psycopg.Connection, schema: str = "public") -> list[dict]:
    """Verify no Contents bytea column has a non-NULL row."""
    issues: list[dict] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.columns
            WHERE table_schema = %s AND lower(column_name) = 'contents' AND data_type = 'bytea'
            """,
            (schema,),
        )
        candidates = [r[0] for r in cur.fetchall()]
    for table in candidates:
        info = describe_table(conn, table, schema)
        contents_col = next((c for c in info.columns if c.lower() == "contents"), None)
        if not contents_col:
            continue
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT count(*) FROM {}.{} WHERE {} IS NOT NULL").format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                    sql.Identifier(contents_col),
                )
            )
            row = cur.fetchone()
            n = int(row[0]) if row else 0
            if n:
                issues.append({"table": table, "column": contents_col, "non_null_rows": n})
    return issues


def check_constraints(conn: psycopg.Connection) -> list[dict]:
    """Force every deferrable constraint to validate immediately. Catches FK/
    UNIQUE violations introduced by anonymization.
    """
    issues: list[dict] = []
    try:
        with conn.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
    except psycopg.Error as e:
        issues.append({"kind": "constraint_violation", "error": str(e)})
    return issues


def write_report(report: dict, app: str, reports_dir: Path | None = None) -> Path:
    reports_dir = reports_dir or Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = reports_dir / f"{app}-{ts}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return out


def run_verification(
    conn: psycopg.Connection, manifest: Manifest, schema: str = "public"
) -> tuple[bool, dict]:
    """Returns (ok, report). `ok` is True iff no leaks and no constraint issues."""
    leaks = check_leaks(conn, manifest, schema)
    blob_issues = check_filedocument_stripped(conn, schema)
    constraint_issues = check_constraints(conn)

    free_text_warnings = [
        {"table": e.table, "column": e.column}
        for e in manifest.free_text_review
    ]

    ok = not leaks and not blob_issues and not constraint_issues
    report = {
        "app": manifest.app,
        "ok": ok,
        "leaks": leaks,
        "filedocument_issues": blob_issues,
        "constraint_issues": constraint_issues,
        "free_text_warnings": free_text_warnings,
    }
    return ok, report
