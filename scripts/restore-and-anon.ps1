<#
.SYNOPSIS
  One-shot: restore a Mendix production database dump into a local database,
  anonymize it with MxAnonymizer, and verify no PII leaked.

.PARAMETER DumpPath
  Path to the pg_restore archive (typically a .backup custom-format file
  downloaded from Mendix Cloud or your own backup infrastructure).

.PARAMETER App
  Logical app name. Must match a `configs\<App>.yaml` manifest in the
  MxAnonymizer working directory.

.PARAMETER DbName
  Local database name to (re)create. Defaults to "<App>_local".

.PARAMETER PgUser
  PostgreSQL superuser or owner name. Defaults to "postgres".

.PARAMETER PgHost
  PostgreSQL host. Defaults to "localhost".

.PARAMETER PgPort
  PostgreSQL port. Defaults to 5432.

.EXAMPLE
  .\restore-and-anon.ps1 -DumpPath C:\Downloads\prod.backup -App myapp

.NOTES
  Prerequisites:
  - psql and pg_restore must be on PATH (install PostgreSQL client tools).
  - MxAnonymizer must be installed: pipx install <path-to-repo>
  - Two environment variables must be set before running:
      $env:MXANON_SECRET       - a long random string; keep stable across runs
      $env:MXANON_DEV_PASSWORD - the plaintext dev password every user is reset to

  If MxAnonymizer verify reports failures, check ./reports/ before using the DB.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)] [string] $DumpPath,
  [Parameter(Mandatory=$true)] [string] $App,
  [string] $DbName,
  [string] $PgUser = "postgres",
  [string] $PgHost = "localhost",
  [int]    $PgPort = 5432
)

$ErrorActionPreference = "Stop"

if (-not $DbName) { $DbName = "${App}_local" }
if (-not (Test-Path $DumpPath)) { throw "Dump not found: $DumpPath" }
# MXANON_SECRET seeds deterministic pseudonymization (same real value → same fake).
# MXANON_DEV_PASSWORD is the password every system$user is bcrypt-reset to.
foreach ($v in "MXANON_SECRET","MXANON_DEV_PASSWORD") {
  if (-not (Get-Item env:$v -ErrorAction SilentlyContinue)) {
    throw "Environment variable $v is not set. See .NOTES in this script for details."
  }
}

$dsn = "postgresql://${PgUser}@${PgHost}:${PgPort}/${DbName}"
$adminDsn = "postgresql://${PgUser}@${PgHost}:${PgPort}/postgres"

Write-Host "==> Dropping & recreating $DbName" -ForegroundColor Cyan
& psql $adminDsn -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS `"$DbName`";"
& psql $adminDsn -v ON_ERROR_STOP=1 -c "CREATE DATABASE `"$DbName`";"

Write-Host "==> Restoring $DumpPath into $DbName" -ForegroundColor Cyan
# --no-owner / --no-privileges: restore objects without original owner or permission
# grants, so the dump works regardless of which Postgres roles exist locally.
& pg_restore --no-owner --no-privileges --dbname=$dsn $DumpPath
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed (exit $LASTEXITCODE)" }

Write-Host "==> Anonymizing ($App)" -ForegroundColor Cyan
& MxAnonymizer run --app $App --conn $dsn
if ($LASTEXITCODE -ne 0) { throw "MxAnonymizer run failed (exit $LASTEXITCODE)" }

Write-Host "==> Verifying" -ForegroundColor Cyan
& MxAnonymizer verify --app $App --conn $dsn
if ($LASTEXITCODE -ne 0) {
  Write-Host "VERIFY FAILED — check ./reports/ before using this DB." -ForegroundColor Red
  exit 1
}

Write-Host "==> Done. DB ready: $dsn" -ForegroundColor Green
