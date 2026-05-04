"""Unit tests for the leaf strategies: format validity and determinism."""

from __future__ import annotations

import re
from datetime import date

import pytest

from mxanonymizer.strategies import StrategyContext, get
from mxanonymizer.strategies.finance import _bsn_eleven_test_passes, _iban_check_digits

SECRET = b"unit-test-secret"


def _ctx(column: str, value, table="crm$customer", **kw):
    return StrategyContext(
        secret=SECRET, table=table, column=column, value=value, deterministic=True, **kw
    )


def test_null_value_returns_none():
    assert get("null_value")(_ctx("X", "anything")) is None


def test_redact_replaces_value():
    out = get("redact")(_ctx("Notes", "real PII", params={"replacement": "[X]"}))
    assert out == "[X]"


def test_redact_preserves_null():
    assert get("redact")(_ctx("Notes", None)) is None


def test_hash_is_deterministic_and_prefixed():
    a = get("hash")(_ctx("Klantnummer", "12345"))
    b = get("hash")(_ctx("Klantnummer", "12345"))
    assert a == b
    assert a.startswith("Klantnummer_")


def test_fake_first_name_deterministic():
    a = get("fake_first_name")(_ctx("Firstname", "Jan"))
    b = get("fake_first_name")(_ctx("Firstname", "Jan"))
    c = get("fake_first_name")(_ctx("Firstname", "Marieke"))
    assert a == b
    assert a != c


def test_fake_email_uses_invalid_tld():
    out = get("fake_email_from_name")(_ctx("Email", "real@anwb.nl"))
    assert out.endswith("@anonymized.example.invalid")
    assert "anwb" not in out


def test_fake_phone_mobile_format():
    out = get("fake_phone_nl")(_ctx("Phone", "+31612345678"))
    assert out.startswith("+316")
    assert len(out) == 12


def test_fake_phone_landline_format():
    out = get("fake_phone_nl")(_ctx("Phone", "+31201234567"))
    assert out.startswith("+31") and not out.startswith("+316")


def test_fake_postcode_format():
    out = get("fake_postcode_nl")(_ctx("Postcode", "2596 EC"))
    assert re.match(r"^\d{4} [A-Z]{2}$", out)


def test_fake_iban_nl_passes_mod97():
    out = get("fake_iban_nl")(_ctx("IBAN", "NL91INGB0417164300"))
    assert out.startswith("NL")
    bank = out[4:8]
    account = out[8:]
    expected_check = _iban_check_digits("NL", bank, account)
    assert out[2:4] == expected_check


def test_fake_iban_uses_fake_bank_code():
    out = get("fake_iban_nl")(_ctx("IBAN", "NL91INGB0417164300"))
    bank = out[4:8]
    assert bank in {"TEST", "FAKE", "MXAN", "ANON"}


def test_fake_bsn_passes_eleven_test():
    out = get("fake_bsn_nl")(_ctx("BSN", "123456782"))
    assert _bsn_eleven_test_passes(out)
    assert out.startswith("9")  # reserved test range


def test_fake_license_plate_format():
    out = get("fake_license_plate_nl")(_ctx("Kenteken", "12-ABC-3"))
    assert re.match(r"^\d{2}-[A-Z]{3}-\d$", out)


def test_shift_date_within_range():
    src = date(1980, 5, 15)
    out = get("shift_date_days")(_ctx("DOB", src, params={"range": 365}))
    assert isinstance(out, date)
    diff = abs((out - src).days)
    assert diff <= 365


def test_shift_date_deterministic():
    src = date(1980, 5, 15)
    a = get("shift_date_days")(_ctx("DOB", src, params={"range": 365}))
    b = get("shift_date_days")(_ctx("DOB", src, params={"range": 365}))
    assert a == b


def test_eleven_test_known_valid():
    # Known valid BSN test value (publicly published).
    assert _bsn_eleven_test_passes("111222333")
    # Random invalid number.
    assert not _bsn_eleven_test_passes("123456789")


def test_unknown_strategy_raises():
    with pytest.raises(KeyError):
        get("does_not_exist")
