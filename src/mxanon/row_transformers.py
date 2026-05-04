"""Row transformers — strategies that write multiple columns coherently.

Use a row transformer when columns must agree (street/postcode/city must form
one plausible Dutch address). Configured per-table:

    tables:
      crm$customer:
        row_transformer: address_nl
        params:
          street: Street
          huisnummer: HouseNumber
          postcode: PostalCode
          city: City
          country: Country     # optional

The transformer receives the full row (read-only) plus the params and returns
a `{column_name: new_value}` dict. Only columns present in `params` are
considered; missing keys mean "skip that field".
"""

from __future__ import annotations

import string
from collections.abc import Callable
from typing import Any

from mxanon.determinism import seeded_faker

RowTransformer = Callable[[bytes, str, dict[str, Any], dict[str, str], str], dict[str, Any]]

_REGISTRY: dict[str, RowTransformer] = {}


def register(name: str) -> Callable[[RowTransformer], RowTransformer]:
    def decorator(fn: RowTransformer) -> RowTransformer:
        _REGISTRY[name] = fn
        return fn

    return decorator


def get(name: str) -> RowTransformer:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown row_transformer: {name!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


@register("address_nl")
def address_nl(
    secret: bytes,
    table: str,
    row: dict[str, Any],
    params: dict[str, str],
    locale: str,
) -> dict[str, Any]:
    """Generate a coherent Dutch address keyed off the row's PK so determinism
    holds: same row → same fake address every time.
    """
    pk_value = row.get("__pk__")
    f = seeded_faker(secret, table, "__address__", pk_value, locale)
    out: dict[str, Any] = {}

    if col := params.get("street"):
        out[col] = f.street_name()
    if col := params.get("huisnummer"):
        out[col] = f.random_int(1, 350)
    if col := params.get("huisnummer_toevoeging"):
        # ~70% empty, otherwise a single suffix.
        out[col] = "" if f.random_int(0, 9) < 7 else f.random_element(["A", "B", "I", "II", "bis"])
    if col := params.get("postcode"):
        digits = f"{f.random_int(1011, 9999)}"
        letters = "".join(f.random_element(string.ascii_uppercase) for _ in range(2))
        out[col] = f"{digits} {letters}"
    if col := params.get("city"):
        out[col] = f.city()
    if col := params.get("country"):
        out[col] = "Nederland"

    return out
