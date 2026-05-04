"""mxanon CLI."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import click
import psycopg

from mxanon.config import ConfigError, Manifest, load_manifest
from mxanon.db import run_anonymization
from mxanon.discover import discover, render_draft_yaml
from mxanon.system_tables import apply_system_rules, reset_system_user_passwords
from mxanon.verify import run_verification, write_report


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _default_configs_dir() -> Path:
    """Resolve the configs directory.

    1. `MXANON_CONFIGS_DIR` env var if set.
    2. `./configs` relative to cwd if it exists.
    3. The packaged `configs/` directory next to the source tree.
    """
    if env := os.environ.get("MXANON_CONFIGS_DIR"):
        return Path(env)
    cwd_configs = Path.cwd() / "configs"
    if cwd_configs.is_dir():
        return cwd_configs
    return Path(__file__).resolve().parent.parent.parent / "configs"


def _load(app: str) -> Manifest:
    configs_dir = _default_configs_dir()
    manifest_path = configs_dir / f"{app}.yaml"
    return load_manifest(manifest_path, configs_dir=configs_dir)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """Anonymize a Mendix production PostgreSQL DB for safe local debugging."""
    ctx.ensure_object(dict)
    _setup_logging(verbose)


@main.command()
@click.option("--app", required=True, help="Logical app name (writes configs/<app>.yaml).")
@click.option("--conn", required=True, help="psycopg connection string.")
@click.option("--out", type=click.Path(path_type=Path), default=None, help="Output path.")
@click.option("--sample-size", type=int, default=100)
def discover_cmd(app: str, conn: str, out: Path | None, sample_size: int) -> None:
    """Scan a restored DB and emit a draft anonymization manifest."""
    out = out or (_default_configs_dir() / f"{app}.yaml")
    with psycopg.connect(conn) as connection:
        connection.read_only = True
        candidates, free_text = discover(connection, sample_size=sample_size)
    text = render_draft_yaml(app, candidates, free_text)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    click.echo(f"Wrote draft to {out}  ({len(candidates)} candidates, {len(free_text)} free-text)")


main.add_command(discover_cmd, name="discover")


@main.command("validate")
@click.argument("manifest_path", type=click.Path(exists=True, path_type=Path))
def validate_cmd(manifest_path: Path) -> None:
    """Validate a manifest YAML against the schema."""
    try:
        m = load_manifest(manifest_path)
    except ConfigError as e:
        click.secho(str(e), fg="red", err=True)
        sys.exit(2)
    click.echo(
        f"OK: {m.app} ({len(m.tables)} tables, {len(m.free_text_review)} free-text entries)"
    )


@main.command("run")
@click.option("--app", required=True)
@click.option("--conn", required=True)
@click.option("--dry-run", is_flag=True, help="Roll back the transaction at the end.")
def run_cmd(app: str, conn: str, dry_run: bool) -> None:
    """Apply the anonymization manifest to a DB."""
    manifest = _load(app)
    with psycopg.connect(conn) as connection:
        try:
            sys_stats = apply_system_rules(connection, manifest)
            stats = run_anonymization(connection, manifest)
        except Exception:
            connection.rollback()
            raise
        if dry_run:
            connection.rollback()
            click.secho("Dry run — rolled back.", fg="yellow")
        else:
            connection.commit()
    click.echo(json.dumps({"system": sys_stats, **stats}, indent=2, default=str))


@main.command("verify")
@click.option("--app", required=True)
@click.option("--conn", required=True)
@click.option("--reports-dir", type=click.Path(path_type=Path), default=Path("reports"))
def verify_cmd(app: str, conn: str, reports_dir: Path) -> None:
    """Run leak/sanity checks against an anonymized DB."""
    manifest = _load(app)
    with psycopg.connect(conn) as connection:
        ok, report = run_verification(connection, manifest)
    out = write_report(report, app, reports_dir)
    if ok:
        click.secho(f"OK: no leaks. Report: {out}", fg="green")
    else:
        click.secho(f"FAIL: leaks/issues found. Report: {out}", fg="red", err=True)
        sys.exit(1)


@main.command("reset-passwords")
@click.option("--conn", required=True)
@click.option("--password", required=True, help="Plain dev password to bcrypt-hash.")
def reset_passwords_cmd(conn: str, password: str) -> None:
    """Reset every system$user.Password to bcrypt(<password>). Useful as a
    one-shot if you skipped this in `run`.
    """
    with psycopg.connect(conn) as connection:
        n = reset_system_user_passwords(connection, password)
        connection.commit()
    click.echo(f"Reset {n} system$user passwords.")


if __name__ == "__main__":
    main()
