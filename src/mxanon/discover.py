"""PII discovery: produces a draft YAML manifest for human review.

Two signals:
1. Column-name heuristics (case-insensitive, NL + EN).
2. Value sampling — regex match on a sample of rows for non-matched text columns.

Output is intentionally annotated with comments so the developer can see
*why* each candidate was flagged.
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from dataclasses import dataclass

import psycopg
from psycopg import sql

log = logging.getLogger("mxanon.discover")

# (lowercased exact-match or substring rule, strategy, deterministic, category)
NAME_HEURISTICS: list[tuple[str, str, bool, str]] = [
    # Names
    ("firstname", "fake_first_name", True, "name"),
    ("voornaam", "fake_first_name", True, "name"),
    ("lastname", "fake_last_name", True, "name"),
    ("achternaam", "fake_last_name", True, "name"),
    ("surname", "fake_last_name", True, "name"),
    ("tussenvoegsel", "fake_last_name", True, "name"),
    ("fullname", "fake_full_name", True, "name"),
    ("volledigenaam", "fake_full_name", True, "name"),
    ("initials", "fake_initials", True, "name"),
    ("voorletters", "fake_initials", True, "name"),
    # Email
    ("email", "fake_email_from_name", False, "email"),
    ("e_mail", "fake_email_from_name", False, "email"),
    ("emailadres", "fake_email_from_name", False, "email"),
    ("mailaddress", "fake_email_from_name", False, "email"),
    # Phone
    ("phonenumber", "fake_phone_nl", False, "phone"),
    ("telefoonnummer", "fake_phone_nl", False, "phone"),
    ("telefoon", "fake_phone_nl", False, "phone"),
    ("mobiel", "fake_phone_nl", False, "phone"),
    ("mobile", "fake_phone_nl", False, "phone"),
    ("phone", "fake_phone_nl", False, "phone"),
    # Address
    ("street", "fake_street_nl", True, "address"),
    ("straat", "fake_street_nl", True, "address"),
    ("straatnaam", "fake_street_nl", True, "address"),
    ("huisnummertoevoeging", "fake_huisnummer_toevoeging", True, "address"),
    ("huisnummer", "fake_huisnummer", True, "address"),
    ("postcode", "fake_postcode_nl", True, "address"),
    ("zipcode", "fake_postcode_nl", True, "address"),
    ("woonplaats", "fake_city_nl", True, "address"),
    ("plaats", "fake_city_nl", True, "address"),
    ("city", "fake_city_nl", True, "address"),
    ("country", "fake_country_nl", False, "address"),
    ("land", "fake_country_nl", False, "address"),
    # IDs
    ("bsn", "null_value", False, "gov_id"),
    ("sofinummer", "null_value", False, "gov_id"),
    ("paspoort", "null_value", False, "gov_id"),
    ("idnumber", "hash", False, "gov_id"),
    ("rijbewijs", "null_value", False, "gov_id"),
    ("drivers_license", "null_value", False, "gov_id"),
    # Finance
    ("iban", "fake_iban_nl", True, "finance"),
    ("bankrekening", "fake_iban_nl", True, "finance"),
    ("rekeningnummer", "fake_account_number_nl", True, "finance"),
    ("creditcard", "null_value", False, "finance"),
    # Vehicle
    ("kenteken", "fake_license_plate_nl", True, "vehicle"),
    ("licenseplate", "fake_license_plate_nl", True, "vehicle"),
    ("chassisnummer", "fake_vin", True, "vehicle"),
    ("vin", "fake_vin", True, "vehicle"),
    # Birth
    ("geboortedatum", "shift_date_days", True, "dob"),
    ("dateofbirth", "shift_date_days", True, "dob"),
    ("birthdate", "shift_date_days", True, "dob"),
    ("dob", "shift_date_days", True, "dob"),
    # Membership
    ("lidnummer", "hash", True, "membership"),
    ("membershipnumber", "hash", True, "membership"),
    ("klantnummer", "hash", True, "membership"),
    ("customernumber", "hash", True, "membership"),
    ("relatienummer", "hash", True, "membership"),
    # Network
    ("ipaddress", "null_value", False, "network"),
    ("ip_adres", "null_value", False, "network"),
    ("useragent", "null_value", False, "network"),
]

# Free-text columns flagged for the `free_text_review` block.
FREE_TEXT_NAMES = {
    "notes", "opmerkingen", "comments", "description", "omschrijving", "toelichting", "freetext"
}

# Regex sampling patterns.
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RE_POSTCODE = re.compile(r"^\d{4}\s?[A-Z]{2}$")
RE_PHONE_NL = re.compile(r"^(\+31|0031|0)[\s\-]?[1-9][\s\-\d]{7,12}$")
RE_IBAN_NL = re.compile(r"^NL\d{2}[A-Z]{4}\d{10}$")
RE_BSN = re.compile(r"^\d{8,9}$")
RE_LICENSE = re.compile(r"^[A-Z0-9]{2}-?[A-Z0-9]{2,3}-?[A-Z0-9]{1,2}$")

VALUE_SAMPLE_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (RE_EMAIL, "fake_email_from_name", "email"),
    (RE_POSTCODE, "fake_postcode_nl", "postcode"),
    (RE_PHONE_NL, "fake_phone_nl", "phone"),
    (RE_IBAN_NL, "fake_iban_nl", "iban"),
    (RE_LICENSE, "fake_license_plate_nl", "license_plate"),
]


@dataclass
class ColumnCandidate:
    table: str
    column: str
    strategy: str | None
    deterministic: bool
    reason: str


def _matches_heuristic(column: str) -> tuple[str, bool, str] | None:
    lc = column.lower().replace("_", "")
    for token, strategy, deterministic, category in NAME_HEURISTICS:
        if token.replace("_", "") in lc:
            return strategy, deterministic, f"name match: {category} ({token!r})"
    return None


def _is_free_text(column: str) -> bool:
    return column.lower() in FREE_TEXT_NAMES


def _sample_text_column(
    conn: psycopg.Connection, schema: str, table: str, column: str, sample_size: int
) -> tuple[str | None, str] | None:
    """Sample up to `sample_size` non-null values; if a high fraction matches a
    PII regex, return (strategy, reason). Otherwise None.
    """
    stmt = sql.SQL(
        "SELECT {col} FROM {schema}.{table} "
        "WHERE {col} IS NOT NULL AND {col} <> '' LIMIT %s"
    ).format(
        col=sql.Identifier(column),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(stmt, (sample_size,))
            values = [r[0] for r in cur.fetchall()]
    except psycopg.Error:
        return None
    if not values:
        return None

    values_str = [str(v) for v in values]
    for pattern, strategy, label in VALUE_SAMPLE_PATTERNS:
        matches = sum(1 for v in values_str if pattern.match(v))
        ratio = matches / len(values_str)
        if ratio >= 0.7:
            return strategy, f"value sample: {matches}/{len(values_str)} ({ratio:.0%}) match {label}"
    return None


def _is_assoc_table(table: str) -> bool:
    return "_assoc_" in table


def _is_system_table(table: str) -> bool:
    return table.startswith("system$")


def discover(
    conn: psycopg.Connection,
    schema: str = "public",
    sample_size: int = 100,
) -> tuple[list[ColumnCandidate], list[tuple[str, str]]]:
    """Walk the schema; return PII candidates and free-text-review entries."""
    from mxanon.db import describe_table, list_tables

    candidates: list[ColumnCandidate] = []
    free_text: list[tuple[str, str]] = []

    tables = [t for t in list_tables(conn, schema) if not _is_system_table(t)]
    for table in tables:
        if _is_assoc_table(table):
            continue
        try:
            info = describe_table(conn, table, schema)
        except psycopg.Error as e:
            log.warning("Failed to describe %s: %s", table, e)
            continue

        for col_name, col_info in info.columns.items():
            if col_name == info.pk_column or col_name in info.fk_columns:
                continue
            if col_name.lower() == "id":
                continue

            heur = _matches_heuristic(col_name)
            if heur is not None:
                strategy, det, reason = heur
                candidates.append(ColumnCandidate(table, col_name, strategy, det, reason))
                continue

            if _is_free_text(col_name):
                free_text.append((table, col_name))
                continue

            # Value sampling — only on text-typed columns.
            if col_info.data_type in ("character varying", "text", "character"):
                sampled = _sample_text_column(conn, schema, table, col_name, sample_size)
                if sampled is not None:
                    strategy, reason = sampled
                    candidates.append(ColumnCandidate(table, col_name, strategy, False, reason))

    return candidates, free_text


def render_draft_yaml(
    app: str,
    candidates: list[ColumnCandidate],
    free_text: list[tuple[str, str]],
) -> str:
    """Hand-rolled YAML so we can include alignment + per-line comments."""
    by_table: OrderedDict[str, list[ColumnCandidate]] = OrderedDict()
    for c in candidates:
        by_table.setdefault(c.table, []).append(c)

    lines: list[str] = []
    lines.append(f"# Draft manifest for {app} — review every entry before committing.")
    lines.append(f"app: {app}")
    lines.append("extends: _global.yaml")
    lines.append("")
    lines.append("tables:")
    for table, cols in by_table.items():
        lines.append(f"  {table}:")
        lines.append("    columns:")
        for c in cols:
            det = "true" if c.deterministic else "false"
            strat = c.strategy or "TODO_REVIEW"
            lines.append(
                f"      {c.column}: {{ strategy: {strat}, deterministic: {det} }}"
                f"  # {c.reason}"
            )
        lines.append("")
    if free_text:
        lines.append("free_text_review:")
        for table, col in free_text:
            lines.append(f"  - {{ table: {table}, column: {col} }}  # may contain PII — decide redact vs. skip")
        lines.append("")
    return "\n".join(lines)
