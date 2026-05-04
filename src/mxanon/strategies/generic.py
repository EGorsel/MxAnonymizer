"""Generic strategies: null_value, redact, hash."""

from __future__ import annotations

from mxanon.determinism import short_hash
from mxanon.strategies import StrategyContext, register


@register("null_value")
def null_value(ctx: StrategyContext) -> None:
    return None


@register("redact")
def redact(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    replacement = ctx.params.get("replacement", "[REDACTED]")
    return replacement


@register("hash")
def hash_value(ctx: StrategyContext) -> str | None:
    if ctx.value is None:
        return None
    length = int(ctx.params.get("length", 16))
    return f"{ctx.column}_{short_hash(ctx.secret, ctx.table, ctx.column, ctx.value, length=length)}"
