# mxanon

Anonymize Mendix production PostgreSQL dumps so they're safe to debug against
locally. Targets ANWB Mendix apps (Studio Pro 10.x), but the engine is
generic — every PII rule lives in a per-app YAML manifest under `configs/`.

## How it works (plain English)

### The problem it solves

You have a production database with real customer data. To debug issues locally you need a copy of that database — but you can't use real names, emails, addresses, etc. (GDPR). This tool takes a production database dump and replaces all sensitive data with realistic-but-fake data, so developers can work safely.

### Step 1 — Load the rulebook

A YAML file (the *manifest*) tells the tool which tables and columns are sensitive and how to replace them. For example: "the `email` column in the `customer` table → generate a fake email address." This config is validated before anything runs, so typos are caught early.

### Step 2 — Handle Mendix system tables first

Before touching your app data, the tool:
- Resets **every user's password** to a single known dev password, so you can log in locally as any user.
- **Wipes file/document blobs** — large binary content that's not useful for debugging.
- **Clears all active sessions** — stale sessions from production are useless locally.

### Step 3 — Process tables row by row

The tool reads the database in chunks of 5 000 rows at a time (to keep memory usage low), applies all the replacement rules, and writes the updates back. Database triggers are disabled during this pass so no side effects fire.

### Step 4 — Generate consistent fake data

This is the key part: **the same real value always produces the same fake value**. If "Jan de Vries" appears in three different tables, all three become the same fake name — so relationships between records stay intact and you can still trace data across tables.

This works by combining the real value with a secret key (via HMAC) to seed a random number generator, then generating a fake name / email / address from that seed. Change the real value → different fake. Same real value → same fake, every time.

### Step 5 — Verify nothing leaked

After anonymization, the tool re-scans the database for patterns that look like real data (email addresses, phone numbers, postcodes, IBANs, etc.) and writes a JSON report. If anything suspicious is found, the script exits with an error — don't proceed past that.

### How the tool finds sensitive columns

During the one-time *discovery* step (`mxanon discover`), two signals are used to flag columns:

**1. Column name matching** — A built-in list maps known name patterns (Dutch + English) to strategies. The match is case-insensitive, strips underscores, and checks for a substring match, so all of these would be caught:

| Column name | Matched pattern | Strategy |
|---|---|---|
| `Email` | `email` | fake email |
| `EmailAddress` | `email` | fake email |
| `emailadres` | `emailadres` | fake email |
| `MailAddress` | `mailaddress` | fake email |

**2. Value sampling (fallback)** — If no column name matches, the tool samples up to 100 actual values from the column and tests them against regex patterns. If 70% or more of the sampled values look like an email address (or phone number, postcode, IBAN, etc.), the column is flagged — regardless of its name. A column called `contact_info` full of email addresses would still be caught.

Discovery produces a **draft YAML config for human review**. You review it, correct any mistakes, and commit it. After that, `mxanon run` only does what the committed config says — the two-signal detection is a one-time bootstrapping aid, not a live lookup.

---

## What it does

Given a freshly restored local copy of a Mendix prod DB, `mxanon` rewrites
PII columns in place using realistic Dutch fake values, while preserving:

- primary keys, foreign keys, and unique constraints
- enum/status columns (only declared columns are touched)
- `system$user` role associations (so the local app behaves like prod)
- referential integrity across `module$entity_assoc_*` link tables
  (skipped wholesale)

Same input value always maps to the same fake value (HMAC-seeded), so joins
and your "I remember customer X" intuition keep working across reruns.

## Install

Requires Python 3.11+ and PostgreSQL client tools (`psql`, `pg_restore`) on
`PATH`.

```powershell
pipx install .
```

Set the two required environment variables (e.g. in your shell profile or a
non-committed `.env`):

```powershell
$env:MXANON_SECRET = "any-long-random-string-keep-stable"
$env:MXANON_DEV_PASSWORD = "Devpass123!"
```

- `MXANON_SECRET` seeds deterministic pseudonymization. Pick once and don't
  change — changing it re-randomizes every value on the next run.
- `MXANON_DEV_PASSWORD` is the plaintext password every `system$user.Password`
  is reset to (bcrypt cost 10), so you can log in as any anonymized user.

## Daily flow

1. Download production dump from Mendix Cloud.
2. Restore it and anonymize in one go:

   ```powershell
   .\scripts\restore-and-anon.ps1 -DumpPath C:\Downloads\prod.backup -App pinkpro
   ```

   That script drops/recreates `pinkpro_local`, runs `pg_restore`, then
   `mxanon run` and `mxanon verify`. Exits non-zero if verification finds a
   leak — don't proceed in that case.

3. Point Studio Pro / the Mendix runtime at `pinkpro_local` and debug. Log
   in with any anonymized username (visible in `system$user.Name`) and
   `MXANON_DEV_PASSWORD`.

The four CLI subcommands the script wraps:

```
mxanon discover --app <name> --conn <dsn>     # generate draft configs/<name>.yaml
mxanon validate configs/<name>.yaml           # schema-check the manifest
mxanon run --app <name> --conn <dsn>          # apply anonymization
mxanon verify --app <name> --conn <dsn>       # leak + sanity checks
```

## Onboarding a new Mendix app

1. Restore prod into `<app>_local`.
2. Run discovery to get a starting point:
   ```powershell
   mxanon discover --app <app> --conn postgresql://localhost/<app>_local
   ```
3. Open `configs/<app>.yaml`. Every line ends in a comment explaining why
   the column was flagged. Review and:
   - keep / change strategies
   - replace `TODO_REVIEW` placeholders with a real strategy or `null_value`
   - decide each `free_text_review` entry: `redact` it, or accept the risk
4. `mxanon validate configs/<app>.yaml` to catch typos.
5. `mxanon run` and `mxanon verify` against the local DB. Iterate.
6. Commit `configs/<app>.yaml` to git.

When the prod schema changes (new fields), rerun `discover` to a temp file
and `git diff` against the committed manifest — new PII candidates surface
automatically.

## Strategy reference

| Strategy | What it produces |
|---|---|
| `null_value` | `NULL` |
| `redact` | configurable replacement string (default `[REDACTED]`) |
| `hash` | `<column>_<hex16>` opaque token |
| `fake_first_name` / `fake_last_name` / `fake_full_name` / `fake_initials` | Dutch-locale Faker output |
| `fake_email_from_name` | `<first>.<last>.<hash>@anonymized.example.invalid` (RFC 2606 — never deliverable) |
| `fake_email` | random Faker username at the same fake domain |
| `fake_phone_nl` | `+316XXXXXXXX` mobile or `+31XX…` landline (preserves shape of source) |
| `fake_postcode_nl` / `fake_street_nl` / `fake_city_nl` / `fake_huisnummer` / `fake_huisnummer_toevoeging` / `fake_country_nl` | Per-column Dutch address parts |
| `fake_iban_nl` | Valid NL IBAN with mod-97 check, fake bank code (`TEST`/`FAKE`/`MXAN`/`ANON`) |
| `fake_bsn_nl` | 9-digit number passing the eleven-test, in the reserved 9-prefix test range |
| `fake_account_number_nl` | Pre-IBAN 10-digit Dutch account number |
| `fake_license_plate_nl` | Sidecode 6 (`99-AAA-9`) |
| `fake_vin` | 17-char VIN-shaped string prefixed `MXANON` |
| `shift_date_days` | Original date ± deterministic offset within `params.range` (default 365) |

For coherent multi-column addresses, set `row_transformer: address_nl` on
the table and map logical names to your DB column names via `params:`.

## What it deliberately doesn't touch

- Primary keys, foreign keys, association tables — referential integrity
  stays intact.
- `system$role`, `system$language`, `system$usertheme` — config tables.
- `system$user` role associations — preserved so authorization still works.
- Enum/status columns — never auto-detected; only explicit rules apply.

## Out of scope

- Files stored *outside* the DB (S3, local filesystem). Only DB-backed
  FileDocument is handled.
- Production-side anonymization or "anonymous dump" generation.
- Encryption at rest of the local DB.
- Schema (DDL) changes — the tool only `UPDATE`s.

## Development

```powershell
pip install -e ".[dev]"
pytest                                              # unit tests
$env:MXANON_TEST_DSN = "postgresql://localhost/mxanon_test"
pytest tests/test_e2e.py                            # E2E (needs Postgres)
ruff check src tests
```

The E2E test loads `tests/fixtures/mini_mendix.sql` (a synthetic Mendix-shaped
schema with seeded fake PII), runs the full pipeline, and asserts no leaks
remain and FKs still validate. It auto-skips if `MXANON_TEST_DSN` is unset.

## File map

```
mxanon/
  src/mxanon/
    cli.py                 # Click entry point
    config.py              # YAML loader + pydantic schema + _global merge
    db.py                  # introspection, chunked UPDATE, replication guard
    determinism.py         # HMAC-seeded Faker
    discover.py            # PII discovery (heuristics + value sampling)
    row_transformers.py    # multi-column transformers (address_nl)
    strategies/            # leaf strategies registered into a registry
    system_tables.py       # system$user / system$filedocument / system$session
    verify.py              # leak + sanity checks, JSON report writer
  configs/
    _global.yaml           # cross-app defaults; never committed per-app
    testapp.yaml           # synthetic-app manifest (used by E2E test)
    <appname>.yaml         # one per onboarded Mendix app
  scripts/
    restore-and-anon.ps1   # one-shot restore + anonymize + verify
  tests/
    fixtures/mini_mendix.sql
    test_*.py
```
