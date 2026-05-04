# 🔒 MxAnonymizer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Mendix Support](https://img.shields.io/badge/Mendix-10%20--%2011-blue.svg)](https://docs.mendix.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/EGorsel/MxAnonymizer/graphs/commit-activity)

A manifest-driven CLI tool that anonymizes Mendix production PostgreSQL databases for safe local debugging. It replaces PII (names, emails, addresses, IBANs, and more) with realistic-but-fake data, so developers can restore a production dump locally without exposing real customer data.

Works with any Mendix Studio Pro 10.x PostgreSQL-backed app. Every PII rule lives in a per-app YAML manifest — no sensitive logic is baked into code.

---

### 💡 Why this Project?
Debugging Mendix apps with production data is risky and often illegal under GDPR. Manually scrubbing databases is slow, error-prone, and produces inconsistent results. MxAnonymizer solves this with a one-command pipeline that:

- **Resets every user password** to a single known dev password, so you can log in locally as any user.
- **Replaces PII columns** with realistic fake data — same real value always maps to the same fake value, so joins and cross-table relationships stay intact.
- **Strips file/document blobs** and clears stale sessions.
- **Verifies the result** by re-scanning for leak patterns before you use the database.

<div align="right"><b>Created by: <a href="https://github.com/EGorsel">Erik van Gorsel</a></b></div>

---

## 🗺️ Quick Links
| [📥 Install](#-1-quick-start) | [📖 How it Works](#️-2-how-it-works) | [⚙️ Onboarding](#️-3-onboarding-a-new-mendix-app) | [🐛 Report Bug](SECURITY.md) | [🤝 Contribute](CONTRIBUTING.md) | [⚖️ License](LICENSE) |
| :--- | :--- | :--- | :--- | :--- | :--- |

---

## 📖 1. Quick Start

This section gets you from a fresh machine to a working anonymized database. It should take about 15 minutes on first setup.

### 🔧 1.1. Requirements

Before you begin, make sure you have:

- **Python 3.11 or newer** — [download from python.org](https://www.python.org/downloads/). During installation, tick the box that says "Add Python to PATH".
- **PostgreSQL client tools** (`psql` and `pg_restore`) — these come with a standard [PostgreSQL installation](https://www.postgresql.org/download/windows/). If you already have PostgreSQL running locally, you likely have these.
- A production database dump (`.backup` file) downloaded from Mendix Cloud.

---

### 📥 1.2. Install

Open **PowerShell** (search for it in the Start menu) and run:

```powershell
pipx install git+https://github.com/EGorsel/MxAnonymizer.git
```

> [!NOTE]
> If PowerShell says `pipx` is not recognised, install it first with `pip install pipx`, then run the command above again.

---

### 🔑 1.3. Set Up Your Secret Key and Dev Password

MxAnonymizer needs two settings saved in your PowerShell profile so they are available every time you open a terminal.

**Step 1** — Open your PowerShell profile in Notepad:

```powershell
notepad $PROFILE
```

If PowerShell says the file does not exist, create it first:

```powershell
New-Item -ItemType File -Force $PROFILE ; notepad $PROFILE
```

**Step 2** — Add these two lines to the file. Replace the example values with your own (see the guidance below):

```powershell
$env:MXANON_SECRET      = "replace-this-with-your-own-long-random-string"
$env:MXANON_DEV_PASSWORD = "MxAdmin1"
```

**Step 3** — Save and close Notepad, then **close and reopen PowerShell** so the settings take effect.

> [!IMPORTANT]
> **`MXANON_SECRET`** is a private key that drives fake-data generation. Keep it secret and never change it after your first run — changing it produces different fake values, breaking cross-run consistency. Generate a random string of 30+ characters and treat it like a password.
>
> **`MXANON_DEV_PASSWORD`** is the password every user account in your local database will be reset to. After anonymization you can log in to your local Mendix app as any user with this password.

---

### ▶️ 1.4. Restore and Anonymize

Run this single command, replacing the path and app name with your own:

```powershell
.\scripts\restore-and-anon.ps1 -DumpPath C:\Downloads\prod.backup -App myapp
```

This script does everything in one go:
1. Drops and recreates the local database `myapp_local`.
2. Restores the production dump into it.
3. Replaces all sensitive data with realistic fake data.
4. Runs a leak check to confirm no real data remains.

When it finishes successfully you will see a green summary. If the leak check finds something suspicious it exits with an error — check the `reports/` folder for details before using the database.

---

### 🖥️ 1.5. Connect Studio Pro

Point your local Mendix runtime at `myapp_local` (same host/port as your other local databases). Log in with any username visible in `system$user.Name` and the password you set in `MXANON_DEV_PASSWORD`.

> [!NOTE]
> **Setting up a new app for the first time?** The tool needs a one-time config file before it can anonymize a new app. See [Onboarding a new Mendix app](#️-3-onboarding-a-new-mendix-app) below.

---

## ⚙️ 2. How it Works

### 🔍 2.1. The Problem it Solves

You have a production database with real customer data. To debug issues locally you need a copy — but you cannot use real names, emails, addresses, etc. (GDPR). MxAnonymizer takes a production database dump and replaces all sensitive data with realistic-but-fake data so developers can work safely.

---

### 📋 2.2. Step by Step

1. **Load the rulebook** — A YAML file (the *manifest*) declares which tables and columns are sensitive and how to replace them. It is validated before anything runs, so typos are caught early.

2. **Handle Mendix system tables** — Before touching app data, the tool resets every user password, strips file/document blobs, and clears all active sessions.

3. **Process tables row by row** — The database is read in chunks of 5 000 rows at a time to keep memory usage low. All replacement rules are applied and written back. Database triggers are disabled during this pass so no side effects fire.

4. **Generate consistent fake data** — The same real value always produces the same fake value. If "Jan de Vries" appears in three tables, all three become the same fake name — relationships between records stay intact. This works by combining the real value with `MXANON_SECRET` via HMAC to seed a random number generator.

5. **Verify nothing leaked** — After anonymization, the tool re-scans the database for patterns that look like real data (emails, phone numbers, postcodes, IBANs, etc.) and writes a JSON report to `reports/`. If anything suspicious is found, the script exits with an error.

---

### 🔎 2.3. How the Tool Finds Sensitive Columns

During the one-time *discovery* step, two signals are used to flag columns:

**1. Column name matching** — A built-in list maps known name patterns (Dutch + English) to strategies. The match is case-insensitive and checks for substring matches:

| Column name | Matched pattern | Strategy |
| :--- | :--- | :--- |
| `Email` | `email` | fake email |
| `EmailAddress` | `email` | fake email |
| `emailadres` | `emailadres` | fake email |
| `MailAddress` | `mailaddress` | fake email |

**2. Value sampling (fallback)** — If no column name matches, the tool samples up to 100 actual values and tests them against regex patterns. If 70% or more look like an email address (or phone number, postcode, IBAN, etc.), the column is flagged regardless of its name.

Discovery produces a **draft YAML config for human review**. You review it, correct any mistakes, and commit it. After that, `mxanon run` only does what the committed config says.

---

## 🛠️ 3. Onboarding a New Mendix App

1. Restore prod into `<app>_local`.
2. Run discovery to generate a starting-point config:
   ```powershell
   mxanon discover --app <app> --conn postgresql://localhost/<app>_local
   ```
3. Open `configs/<app>.yaml`. Every flagged column has a comment explaining *why* it was flagged. Review and:
   - Keep or change strategies.
   - Replace `TODO_REVIEW` placeholders with a real strategy or `null_value`.
   - Decide each `free_text_review` entry: `redact` it, or accept the risk.
   - Add `verify_patterns:` entries for any org-specific email domains or ID formats that should never appear after anonymization.
4. Validate the config to catch typos:
   ```powershell
   mxanon validate configs/<app>.yaml
   ```
5. Run and verify against the local DB, then iterate:
   ```powershell
   mxanon run --app <app> --conn postgresql://localhost/<app>_local
   mxanon verify --app <app> --conn postgresql://localhost/<app>_local
   ```
6. Commit `configs/<app>.yaml` to git.

> [!NOTE]
> When the production schema changes (new fields), rerun `mxanon discover` to a temp file and diff it against the committed manifest — new PII candidates surface automatically.

### 🔎 Configuring Leak Detection

By default, `mxanon verify` checks anonymized columns for real Dutch IBAN bank codes (INGB, RABO, ABNA, etc.). Add org-specific patterns to your manifest:

```yaml
verify_patterns:
  - label: org_email
    pattern: '@mycompany\.(nl|com)$'
  - label: internal_id_format
    pattern: '^EMP-\d{6}$'
```

Patterns are Python regular expressions (case-insensitive). The `label` appears in the verify report when a match is found.

---

## 📂 4. Architecture

| Component | Responsibility |
| :--- | :--- |
| `src/mxanon/cli.py` | **Entry point**: Click-based CLI, subcommand routing. |
| `src/mxanon/config.py` | **Manifest loader**: YAML parsing, pydantic validation, `_global.yaml` merge. |
| `src/mxanon/db.py` | **DB pass**: introspection, chunked UPDATE, replication guard. |
| `src/mxanon/determinism.py` | **HMAC seeding**: same input → same fake value, every time. |
| `src/mxanon/discover.py` | **Discovery**: column-name heuristics + value sampling → draft YAML. |
| `src/mxanon/row_transformers.py` | **Multi-column coherence**: e.g. `address_nl` produces matching street/postcode/city. |
| `src/mxanon/strategies/` | **Leaf strategies**: self-registering via `@register("name")`. |
| `src/mxanon/system_tables.py` | **Mendix system tables**: `system$user`, FileDocument blobs, `system$session`. |
| `src/mxanon/verify.py` | **Leak checker**: regex scan of anonymized columns → JSON report. |
| `configs/_global.yaml` | Cross-app defaults; extended by per-app manifests. |
| `scripts/restore-and-anon.ps1` | One-shot restore + anonymize + verify wrapper. |

---

## 🃏 5. Strategy Reference

| Strategy | What it produces |
| :--- | :--- |
| `null_value` | `NULL` |
| `redact` | Configurable replacement string (default `[REDACTED]`) |
| `hash` | `<column>_<hex16>` opaque token |
| `fake_first_name` / `fake_last_name` / `fake_full_name` / `fake_initials` | Dutch-locale Faker output |
| `fake_email_from_name` | `<first>.<last>.<hash>@anonymized.example.invalid` (RFC 2606 — never deliverable) |
| `fake_email` | Random Faker username at the same fake domain |
| `fake_phone_nl` | `+316XXXXXXXX` mobile or `+31XX…` landline (preserves shape of source) |
| `fake_postcode_nl` / `fake_street_nl` / `fake_city_nl` / `fake_huisnummer` / `fake_huisnummer_toevoeging` / `fake_country_nl` | Per-column Dutch address parts |
| `fake_iban_nl` | Valid NL IBAN with mod-97 check, fake bank code (`TEST`/`FAKE`/`MXAN`/`ANON`) |
| `fake_bsn_nl` | 9-digit number passing the eleven-test, in the reserved 9-prefix test range |
| `fake_account_number_nl` | Pre-IBAN 10-digit Dutch account number |
| `fake_license_plate_nl` | Sidecode 6 (`99-AAA-9`) |
| `fake_vin` | 17-char VIN-shaped string prefixed `MxAnonymizer` |
| `shift_date_days` | Original date ± deterministic offset within `params.range` (default 365) |

For coherent multi-column addresses, set `row_transformer: address_nl` on the table and map logical names to your DB column names via `params:`.

---

## 🚫 6. What it Deliberately Does Not Touch

- Primary keys, foreign keys, and association tables (`module$entity_assoc_*`) — referential integrity stays intact.
- `system$role`, `system$language`, `system$usertheme` — config tables.
- `system$user` role associations — preserved so authorization still works like production.
- Enum/status columns — never auto-detected; only explicit rules apply.

**Out of scope:**
- Files stored outside the DB (S3, local filesystem). Only DB-backed FileDocument is handled.
- Production-side anonymization or "anonymous dump" generation.
- Encryption at rest of the local DB.
- Schema (DDL) changes — the tool only issues `UPDATE` statements.

---

## 🤝 7. Contributing & Support

This is a **community-driven** project. Contributions of all kinds are welcome!

- **Contributing**: Please read the [Contribution Guide](CONTRIBUTING.md) before submitting a pull request.
- **Security**: Report vulnerabilities privately via [SECURITY.md](SECURITY.md).

### 🧑‍💻 Development

```powershell
cd mxanon
pip install -e ".[dev]"
pytest                                               # unit tests
$env:MXANON_TEST_DSN = "postgresql://localhost/mxanonymizer_test"
pytest tests/test_e2e.py                             # E2E (needs Postgres)
ruff check src tests
```

The E2E test loads `tests/fixtures/mini_mendix.sql` (a synthetic Mendix-shaped schema with seeded fake PII), runs the full pipeline, and asserts no leaks remain and FKs still validate. It auto-skips if `MXANON_TEST_DSN` is unset.

---

<div align="center">
  <sub>Built with ❤️ for the Mendix Community</sub>
</div>
