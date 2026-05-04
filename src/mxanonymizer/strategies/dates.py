"""Date strategies: deterministic shift within a configurable range."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from mxanonymizer.determinism import seed_for
from mxanonymizer.strategies import StrategyContext, register


@register("shift_date_days")
def shift_date_days(ctx: StrategyContext):
    """Shift a date/datetime by a deterministic offset in `[-range, +range]` days."""
    if ctx.value is None:
        return None
    range_days = int(ctx.params.get("range", 365))
    seed = seed_for(ctx.secret, ctx.table, ctx.column, ctx.value)
    # Deterministic offset in [-range, +range] inclusive.
    offset = (seed % (2 * range_days + 1)) - range_days
    delta = timedelta(days=offset)
    if isinstance(ctx.value, datetime):
        return ctx.value + delta
    if isinstance(ctx.value, date):
        return ctx.value + delta
    raise TypeError(f"shift_date_days expected date/datetime, got {type(ctx.value).__name__}")
