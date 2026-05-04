"""Determinism module tests."""

from __future__ import annotations

import os

import pytest

from mxanonymizer.determinism import DeterminismError, get_secret, seed_for, seeded_faker, short_hash


def test_get_secret_missing(monkeypatch):
    monkeypatch.delenv("MXANON_SECRET", raising=False)
    with pytest.raises(DeterminismError):
        get_secret("MXANON_SECRET")


def test_get_secret_present(monkeypatch):
    monkeypatch.setenv("MXANON_SECRET", "hunter2")
    assert get_secret("MXANON_SECRET") == b"hunter2"


def test_seed_for_is_stable():
    s = b"unit-test-secret"
    a = seed_for(s, "tbl", "col", "value")
    b = seed_for(s, "tbl", "col", "value")
    assert a == b


def test_seed_for_differs_per_input():
    s = b"unit-test-secret"
    assert seed_for(s, "tbl", "col", "a") != seed_for(s, "tbl", "col", "b")
    assert seed_for(s, "tbl", "col1", "v") != seed_for(s, "tbl", "col2", "v")


def test_seeded_faker_repro():
    s = b"unit-test-secret"
    f1 = seeded_faker(s, "t", "c", "x")
    out1 = f1.first_name()
    f2 = seeded_faker(s, "t", "c", "x")
    out2 = f2.first_name()
    assert out1 == out2


def test_short_hash_length():
    s = b"unit-test-secret"
    assert len(short_hash(s, "x", length=8)) == 8
    assert len(short_hash(s, "x", length=12)) == 12
