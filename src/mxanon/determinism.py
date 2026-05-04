"""HMAC-seeded Faker for deterministic pseudonymization.

Same `(table, column, value)` tuple under the same `MXANON_SECRET` always
yields the same fake value, across tables and across runs. Different
columns of the same table can map the same source string to different
fakes — the column name is part of the seed.

The seed key is read from the env var named by `Defaults.determinism_secret_env`
(default `MXANON_SECRET`). If the env var is missing we fail loudly: silently
falling back to a constant would defeat the point.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from functools import lru_cache

from faker import Faker


class DeterminismError(Exception):
    pass


def get_secret(env_var: str = "MXANON_SECRET") -> bytes:
    secret = os.environ.get(env_var)
    if not secret:
        raise DeterminismError(
            f"Environment variable {env_var} is not set. "
            "Deterministic pseudonymization requires a stable secret. "
            "Set it in your shell or .env file."
        )
    return secret.encode("utf-8")


def seed_for(secret: bytes, table: str, column: str, value: object) -> int:
    """Return a 64-bit integer seed derived from HMAC-SHA256."""
    msg = f"{table}.{column}:{value!r}".encode()
    digest = hmac.new(secret, msg, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


@lru_cache(maxsize=8)
def _faker_for_locale(locale: str) -> Faker:
    return Faker(locale)


def seeded_faker(
    secret: bytes,
    table: str,
    column: str,
    value: object,
    locale: str = "nl_NL",
) -> Faker:
    """Return a Faker instance seeded deterministically for this row.

    Re-seeds a shared per-locale Faker instance. Faker's internal RNG is
    advanced by each call, so callers MUST treat the returned Faker as a
    one-shot: pull what they need immediately, don't share across calls.
    """
    fake = _faker_for_locale(locale)
    fake.seed_instance(seed_for(secret, table, column, value))
    return fake


def short_hash(secret: bytes, *parts: object, length: int = 8) -> str:
    """Short hex digest, used for unique-suffixing and email handles."""
    msg = "|".join(repr(p) for p in parts).encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:length]
