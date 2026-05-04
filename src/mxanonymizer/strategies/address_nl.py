"""Dutch address strategies: postcode, street, city, huisnummer.

Per-column strategies are independent. Use the `address_nl` row transformer
(see `address_row.py`) when columns must agree.
"""

from __future__ import annotations

import string

from mxanonymizer.determinism import seeded_faker
from mxanonymizer.strategies import StrategyContext, register


def _faker(ctx: StrategyContext):
    return seeded_faker(ctx.secret, ctx.table, ctx.column, ctx.value, ctx.locale)


@register("fake_postcode_nl")
def fake_postcode_nl(ctx: StrategyContext) -> str | None:
    """Dutch postcode `1234 AB`. Avoids leading zero (real postcodes start at 1011)."""
    if ctx.value is None:
        return None
    f = _faker(ctx)
    digits = f"{f.random_int(1011, 9999)}"
    letters = "".join(f.random_element(string.ascii_uppercase) for _ in range(2))
    return f"{digits} {letters}"


@register("fake_street_nl")
def fake_street_nl(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    return _faker(ctx).street_name()


@register("fake_city_nl")
def fake_city_nl(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    return _faker(ctx).city()


@register("fake_huisnummer")
def fake_huisnummer(ctx: StrategyContext) -> int | None:
    if ctx.value is None:
        return None
    return _faker(ctx).random_int(1, 350)


@register("fake_huisnummer_toevoeging")
def fake_huisnummer_toevoeging(ctx: StrategyContext) -> str | None:
    """Sometimes empty string, sometimes a single uppercase letter or roman numeral."""
    if ctx.value is None or ctx.value == "":
        return ctx.value
    f = _faker(ctx)
    return f.random_element(["", "A", "B", "C", "I", "II", "bis"])


@register("fake_country_nl")
def fake_country_nl(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    return "Nederland"
