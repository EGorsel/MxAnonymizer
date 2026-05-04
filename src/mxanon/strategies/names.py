"""Name strategies: first/last/full names with deterministic Faker seeding."""

from __future__ import annotations

from mxanon.determinism import seeded_faker
from mxanon.strategies import StrategyContext, register


def _faker(ctx: StrategyContext):
    return seeded_faker(ctx.secret, ctx.table, ctx.column, ctx.value, ctx.locale)


@register("fake_first_name")
def fake_first_name(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    return _faker(ctx).first_name()


@register("fake_last_name")
def fake_last_name(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    return _faker(ctx).last_name()


@register("fake_full_name")
def fake_full_name(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    return _faker(ctx).name()


@register("fake_initials")
def fake_initials(ctx: StrategyContext) -> str | None:
    """Return Dutch-style initials, e.g. `J.P.`."""
    if ctx.value is None:
        return None
    f = _faker(ctx)
    n = max(1, min(4, f.random_int(1, 3)))
    letters = [f.random_uppercase_letter() for _ in range(n)]
    return ".".join(letters) + "."
