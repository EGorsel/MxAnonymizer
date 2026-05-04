"""Contact strategies: email and phone (Dutch)."""

from __future__ import annotations

import re

from mxanon.determinism import seeded_faker, short_hash
from mxanon.strategies import StrategyContext, register

_FAKE_EMAIL_DOMAIN = "anonymized.example.invalid"  # RFC 2606 — never deliverable.

_DUTCH_MOBILE_PREFIX = "+316"
_DUTCH_LANDLINE_PREFIXES = ["+3120", "+3110", "+3130", "+3140", "+3150", "+3170"]


def _faker(ctx: StrategyContext):
    return seeded_faker(ctx.secret, ctx.table, ctx.column, ctx.value, ctx.locale)


@register("fake_email_from_name")
def fake_email_from_name(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    f = _faker(ctx)
    first = f.first_name().lower()
    last = f.last_name().lower()
    suffix = short_hash(ctx.secret, ctx.table, ctx.column, ctx.value, length=6)
    # Strip any non-ASCII chars defensively.
    handle = re.sub(r"[^a-z0-9.]", "", f"{first}.{last}.{suffix}")
    return f"{handle}@{_FAKE_EMAIL_DOMAIN}"


@register("fake_email")
def fake_email(ctx: StrategyContext) -> str | None:
    """Email without trying to look like the original person. Domain still fake."""
    if ctx.value is None:
        return None
    f = _faker(ctx)
    handle = f.user_name()
    return f"{handle}@{_FAKE_EMAIL_DOMAIN}"


def _looks_mobile(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    # +31 6..., 06..., 316...
    return digits.startswith("316") or digits.startswith("06") or digits.startswith("00316")


@register("fake_phone_nl")
def fake_phone_nl(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    f = _faker(ctx)
    if isinstance(ctx.value, str) and _looks_mobile(ctx.value):
        rest = "".join(str(f.random_digit()) for _ in range(8))
        return f"{_DUTCH_MOBILE_PREFIX}{rest}"
    prefix = f.random_element(_DUTCH_LANDLINE_PREFIXES)
    rest = "".join(str(f.random_digit()) for _ in range(7))
    return f"{prefix}{rest}"
