"""End-to-end test against a real PostgreSQL.

Skipped unless `MXANON_TEST_DSN` is set (e.g. to a throwaway local DB).
The test loads `tests/fixtures/mini_mendix.sql`, runs the full anonymization +
verification pipeline, and asserts that no leaks remain and that joins still
work.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from mxanonymizer.config import load_manifest
from mxanonymizer.db import run_anonymization
from mxanonymizer.system_tables import apply_system_rules
from mxanonymizer.verify import run_verification

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mini_mendix.sql"
MANIFEST = REPO_ROOT / "configs" / "testapp.yaml"

DSN = os.environ.get("MXANON_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN, reason="Set MXANON_TEST_DSN to run E2E (e.g. 'postgresql://localhost/mxanonymizer_test')"
)


@pytest.fixture
def setup_db(monkeypatch):
    monkeypatch.setenv("MXANON_SECRET", "e2e-test-secret")
    monkeypatch.setenv("MXANON_DEV_PASSWORD", "Devpass123!")
    sql = FIXTURE.read_text(encoding="utf-8")
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql)
    yield


def test_anonymize_and_verify(setup_db):
    manifest = load_manifest(MANIFEST)
    with psycopg.connect(DSN) as conn:
        sys_stats = apply_system_rules(conn, manifest)
        anon_stats = run_anonymization(conn, manifest)
        conn.commit()

        ok, report = run_verification(conn, manifest)

        # Assert system handling worked.
        assert sys_stats["system_user_passwords_reset"] == 2
        assert sys_stats["filedocument_rows_stripped"] == 1
        assert sys_stats["system_sessions_truncated"] == 1
        assert sys_stats["system_user_identity_rows"] == 2

        # Assert PII columns are rewritten.
        with conn.cursor() as cur:
            cur.execute('SELECT "Email", "BSN", "IBAN", "Kenteken", "Notes" FROM public."crm$customer" ORDER BY id')
            rows = cur.fetchall()
            for email, bsn, iban, kenteken, notes in rows:
                assert "anwb" not in (email or "").lower()
                assert email and email.endswith("@anonymized.example.invalid")
                assert bsn is None  # null_value strategy
                assert iban and iban[4:8] in {"TEST", "FAKE", "MXAN", "ANON"}
                assert kenteken and len(kenteken) == 8 and kenteken[2] == "-"
                assert notes == "[REDACTED]"

            # FileDocument blobs stripped.
            cur.execute('SELECT "Contents", "HasContents", "Name" FROM public."system$filedocument"')
            for contents, has, name in cur.fetchall():
                assert contents is None
                assert has is False
                assert name == ""

            # Sessions truncated.
            cur.execute('SELECT count(*) FROM public."system$session"')
            assert cur.fetchone()[0] == 0

            # Customer/claim FK still valid.
            cur.execute(
                'SELECT count(*) FROM public."crm$claim" cl '
                'JOIN public."crm$customer" cu ON cl."customerId" = cu.id'
            )
            assert cur.fetchone()[0] == 1

        assert ok, f"Verify failed: {report}"
