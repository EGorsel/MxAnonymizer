"""Vehicle strategies: Dutch license plate (kenteken), VIN/chassis."""

from __future__ import annotations

import string

from mxanon.determinism import seeded_faker
from mxanon.strategies import StrategyContext, register

# Dutch sidecode patterns. We use sidecode 6 (`12-AAA-1`) since it's currently
# in active issuance and easy to read.
_LETTERS = "BCDFGHJKLMNPRSTVWXYZ"  # consonants typically used; avoids vowel/letter clashes


def _faker(ctx: StrategyContext):
    return seeded_faker(ctx.secret, ctx.table, ctx.column, ctx.value, ctx.locale)


@register("fake_license_plate_nl")
def fake_license_plate_nl(ctx: StrategyContext) -> str | None:
    """Sidecode 6: `99-AAA-9`. Format-valid; not guaranteed to be unissued."""
    if ctx.value is None:
        return None
    f = _faker(ctx)
    nn = f"{f.random_int(10, 99)}"
    aaa = "".join(f.random_element(_LETTERS) for _ in range(3))
    n = f"{f.random_int(1, 9)}"
    return f"{nn}-{aaa}-{n}"


@register("fake_vin")
def fake_vin(ctx: StrategyContext) -> str | None:
    """17-char VIN-shaped string (not a valid checksum — labelled `MXANON`)."""
    if ctx.value is None:
        return None
    f = _faker(ctx)
    chars = string.ascii_uppercase.replace("I", "").replace("O", "").replace("Q", "") + string.digits
    body = "".join(f.random_element(chars) for _ in range(11))
    return f"MXANON{body}"
