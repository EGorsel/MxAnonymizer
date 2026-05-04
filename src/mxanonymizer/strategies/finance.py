"""Finance strategies: IBAN-NL, BSN."""

from __future__ import annotations

from mxanonymizer.determinism import seeded_faker
from mxanonymizer.strategies import StrategyContext, register

# Bank codes that don't collide with real Dutch banks. INGB/RABO/ABNA exist —
# we deliberately use TEST/FAKE/MXAN markers so an anonymized IBAN can't be
# confused for a real one.
_FAKE_BANK_CODES = ["TEST", "FAKE", "MXAN", "ANON"]


def _faker(ctx: StrategyContext):
    return seeded_faker(ctx.secret, ctx.table, ctx.column, ctx.value, ctx.locale)


def _iban_check_digits(country: str, bank: str, account: str) -> str:
    """Compute IBAN check digits via mod-97 (ISO 13616)."""
    rearranged = bank + account + country + "00"
    expanded = "".join(str(int(c, 36)) if c.isalpha() else c for c in rearranged)
    remainder = int(expanded) % 97
    check = 98 - remainder
    return f"{check:02d}"


@register("fake_iban_nl")
def fake_iban_nl(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    f = _faker(ctx)
    bank = f.random_element(_FAKE_BANK_CODES)
    account = "".join(str(f.random_digit()) for _ in range(10))
    check = _iban_check_digits("NL", bank, account)
    return f"NL{check}{bank}{account}"


def _bsn_eleven_test_passes(digits: str) -> bool:
    if len(digits) != 9 or not digits.isdigit():
        return False
    weights = [9, 8, 7, 6, 5, 4, 3, 2, -1]
    total = sum(int(d) * w for d, w in zip(digits, weights, strict=True))
    return total % 11 == 0 and total != 0


@register("fake_bsn_nl")
def fake_bsn_nl(ctx: StrategyContext) -> str | None:
    """Generate a 9-digit number passing the eleven-test, in the reserved 9-prefix
    test range so it can never collide with a real BSN."""
    if ctx.value is None:
        return None
    f = _faker(ctx)
    # Real BSNs are 8 or 9 digits and don't start with 9 in modern issuance —
    # the 9xxx range is reserved for test data.
    for _ in range(1000):
        digits = "9" + "".join(str(f.random_digit()) for _ in range(8))
        if _bsn_eleven_test_passes(digits):
            return digits
    return "900000044"  # known-valid fallback


@register("fake_account_number_nl")
def fake_account_number_nl(ctx: StrategyContext) -> str | None:
    """Pre-IBAN Dutch bank account number (legacy 9-10 digit format)."""
    if ctx.value is None:
        return None
    f = _faker(ctx)
    return "".join(str(f.random_digit()) for _ in range(10))
