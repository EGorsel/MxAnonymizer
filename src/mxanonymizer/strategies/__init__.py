"""Strategy registry.

A strategy is a callable:
    fn(ctx: StrategyContext) -> Any

It receives the original value plus enough context (secret, table, column,
deterministic flag, params) to compute a fake. Returning `None` means SQL NULL.

Strategies are registered via `@register("name")` and discovered by importing
this package — each leaf module imports below triggers registration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategyContext:
    secret: bytes
    table: str
    column: str
    value: Any
    deterministic: bool = False
    locale: str = "nl_NL"
    params: dict[str, Any] = field(default_factory=dict)
    pk_value: Any = None  # used for unique-suffixing


Strategy = Callable[[StrategyContext], Any]

_REGISTRY: dict[str, Strategy] = {}


def register(name: str) -> Callable[[Strategy], Strategy]:
    def decorator(fn: Strategy) -> Strategy:
        if name in _REGISTRY:
            raise RuntimeError(f"Strategy already registered: {name}")
        _REGISTRY[name] = fn
        return fn

    return decorator


def get(name: str) -> Strategy:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy: {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def known() -> list[str]:
    return sorted(_REGISTRY)


# Trigger registration of all leaf strategies.
from mxanonymizer.strategies import (  # noqa: E402,F401
    address_nl,
    contact,
    dates,
    finance,
    generic,
    names,
    vehicle,
)
