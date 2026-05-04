<#
.SYNOPSIS
  One-shot: restore a Mendix prod dump into a local DB, anonymize, verify.

.PARAMETER DumpPath
  Path to the pg_restore archive downloaded from Mendix Cloud (typically .backup).

.PARAMETER App
  Logical app name. Must match a `configs\<App>.yaml` manifest.

.PARAMETER DbName
  Local DB name to (re)create. Defaults to "<App>_local".

.PARAMETER PgUser
  Postgres superuser name. Defaults to "postgres".

.PARAMETER PgHost
  Defaults to "localhost".

.PARAMETER PgPort
  Defaults to 5432.

.EXAMPLE
  .\restore-and-anon.ps1 -DumpPath C:\Downloads\prod.backup -App pinkpro

.NOTES
  Requires: psql, pg_restore on PATH; mxanon installed (`pipx install <repo>`);
  $env:MXANON_SECRET and $env:MXANON_DEV_PASSWORD set.
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
foreach ($v in "MXANON_SECRET","MXANON_DEV_PASSWORD") {
  if (-not (Get-Item env:$v -ErrorAction SilentlyContinue)) {
    throw "Environment variable $v is not set."
  }
}

$dsn = "postgresql://${PgUser}@${PgHost}:${PgPort}/${DbName}"
$adminDsn = "postgresql://${PgUser}@${PgHost}:${PgPort}/postgres"

Write-Host "==> Dropping & recreating $DbName" -ForegroundColor Cyan
& psql $adminDsn -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS `"$DbName`";"
& psql $adminDsn -v ON_ERROR_STOP=1 -c "CREATE DATABASE `"$DbName`";"

Write-Host "==> Restoring $DumpPath into $DbName" -ForegroundColor Cyan
& pg_restore --no-owner --no-privileges --dbname=$dsn $DumpPath
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed (exit $LASTEXITCODE)" }

Write-Host "==> Anonymizing ($App)" -ForegroundColor Cyan
& mxanon run --app $App --conn $dsn
if ($LASTEXITCODE -ne 0) { throw "mxanon run failed (exit $LASTEXITCODE)" }

Write-Host "==> Verifying" -ForegroundColor Cyan
& mxanon verify --app $App --conn $dsn
if ($LASTEXITCODE -ne 0) {
  Write-Host "VERIFY FAILED — check ./reports/ before using this DB." -ForegroundColor Red
  exit 1
}

Write-Host "==> Done. DB ready: $dsn" -ForegroundColor Green
