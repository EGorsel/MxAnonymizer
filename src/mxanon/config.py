"""Config loader for mxanon.

Loads a per-app YAML manifest, merges it with `_global.yaml`, and validates
the result with pydantic. Failed validation raises with a clear error pointing
at the offending key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ColumnRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str | None
    deterministic: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class TableRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skip: bool = False
    row_transformer: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    columns: dict[str, ColumnRule] = Field(default_factory=dict)


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str = "nl_NL"
    determinism_secret_env: str = "MXANON_SECRET"
    chunk_size: int = 5000


class FileDocumentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["strip_blobs", "keep"] = "strip_blobs"


class SystemUserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset_password_hash: bool = True
    dev_password_env: str = "MXANON_DEV_PASSWORD"
    anonymize_email: bool = True
    anonymize_name: bool = True
    preserve_role_associations: bool = True


class FreeTextEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    column: str


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: str
    extends: str | None = None
    defaults: Defaults = Field(default_factory=Defaults)
    file_document: FileDocumentSettings = Field(default_factory=FileDocumentSettings)
    system_user: SystemUserSettings = Field(default_factory=SystemUserSettings)
    tables: dict[str, TableRule] = Field(default_factory=dict)
    free_text_review: list[FreeTextEntry] = Field(default_factory=list)


class ConfigError(Exception):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Top-level YAML in {path} must be a mapping")
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `overlay` into `base`. Overlay wins on conflict.

    Lists and scalars are replaced wholesale (no concatenation) — keeps
    behavior predictable for column rules.
    """
    out = dict(base)
    for key, val in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_manifest(path: str | Path, configs_dir: Path | None = None) -> Manifest:
    """Load a per-app YAML manifest and merge with its `extends:` parent.

    `configs_dir` defaults to the directory containing `path`; relative
    `extends` are resolved against it.
    """
    path = Path(path).resolve()
    configs_dir = configs_dir or path.parent

    raw = _read_yaml(path)
    extends = raw.get("extends")
    if extends:
        parent_path = (configs_dir / extends).resolve()
        parent_raw = _read_yaml(parent_path)
        # Parent must not itself extend anything (one level only).
        if parent_raw.get("extends"):
            raise ConfigError(
                f"Nested extends not supported: {parent_path} extends {parent_raw['extends']}"
            )
        # Strip parent's own metadata that doesn't make sense to inherit.
        parent_raw.pop("app", None)
        merged = _deep_merge(parent_raw, raw)
    else:
        merged = raw

    try:
        return Manifest.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(f"Invalid manifest {path}:\n{e}") from e
