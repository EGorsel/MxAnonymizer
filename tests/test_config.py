"""Config loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from mxanonymizer.config import ConfigError, load_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_load_global_only_fails(tmp_path: Path):
    """A manifest must declare an `app:`."""
    p = tmp_path / "broken.yaml"
    p.write_text("tables: {}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_manifest(p)


def test_extends_merges_global(tmp_path: Path):
    global_yaml = tmp_path / "_global.yaml"
    global_yaml.write_text(
        "defaults:\n  locale: nl_NL\n  chunk_size: 100\n"
        "system_user:\n  reset_password_hash: true\n",
        encoding="utf-8",
    )
    app_yaml = tmp_path / "myapp.yaml"
    app_yaml.write_text(
        "app: myapp\n"
        "extends: _global.yaml\n"
        "defaults:\n  chunk_size: 999\n"
        "tables:\n  crm$customer:\n    columns:\n"
        "      Firstname: { strategy: fake_first_name, deterministic: true }\n",
        encoding="utf-8",
    )
    m = load_manifest(app_yaml)
    assert m.app == "myapp"
    assert m.defaults.locale == "nl_NL"  # from global
    assert m.defaults.chunk_size == 999  # overridden by app
    assert m.system_user.reset_password_hash is True
    assert "crm$customer" in m.tables


def test_unknown_key_rejected(tmp_path: Path):
    p = tmp_path / "broken.yaml"
    p.write_text("app: x\nbogus_top_level_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_manifest(p)


def test_real_global_loads():
    """The committed _global.yaml must be valid in conjunction with a minimal app."""
    configs_dir = REPO_ROOT / "configs"
    m = load_manifest(configs_dir / "testapp.yaml")
    assert m.app == "testapp"
    assert "crm$customer" in m.tables
    assert m.tables["crm$customer"].row_transformer == "address_nl"
