# Contributing to MxAnonymizer

Thank you for considering a contribution. This document covers the most
common paths: setting up a dev environment, adding a new anonymization
strategy, and submitting a pull request.

## Dev environment

Requires Python 3.11+ and (for E2E tests) a local PostgreSQL instance.

```powershell
pip install -e ".[dev]"
```

Set the two required env vars (add these to your shell profile or a local
`.env`):

```powershell
$env:MXANON_SECRET = "any-long-random-string-keep-stable"
$env:MXANON_DEV_PASSWORD = "Devpass123!"
```

## Running tests

```powershell
pytest                          # unit tests (no DB required)

# E2E — needs a real Postgres instance:
$env:MXANON_TEST_DSN = "postgresql://localhost/mxanonymizer_test"
pytest tests/test_e2e.py

ruff check src tests            # lint
```

## Adding a new anonymization strategy

Strategies live in [src/mxanonymizer/strategies/](src/mxanonymizer/strategies/). Each
is a plain function that receives a `StrategyContext` and returns the
anonymized value (or `None` for SQL NULL).

**Step-by-step:**

1. Pick an existing module (`generic.py`, `contact.py`, etc.) or create a
   new leaf module in `src/mxanonymizer/strategies/`.

2. Decorate your function with `@register("your_strategy_name")`:
   ```python
   @register("fake_something")
   def fake_something(ctx: StrategyContext) -> str | None:
       if ctx.value is None:
           return None
       faker = seeded_faker(ctx.secret, ctx.table, ctx.column, ctx.value, ctx.locale)
       return faker.something()
   ```

3. Handle `ctx.value is None` — always return `None` to preserve SQL NULLs.

4. For deterministic output (same input → same fake), use `seeded_faker`
   from `mxanonymizer.determinism` to get a seeded Faker instance. If the result
   doesn't need to be deterministic, use `Faker(locale)` directly.

5. If you created a new module, add an import line at the bottom of
   [src/mxanonymizer/strategies/__init__.py](src/mxanonymizer/strategies/__init__.py).

6. Add unit tests in [tests/test_strategies.py](tests/test_strategies.py)
   covering: output format validity, `None` passthrough, and determinism
   where applicable.

7. Add the strategy name and a short description to the Strategy Reference
   table in [README.md](README.md).

## Pull request checklist

- [ ] `pytest` passes (unit tests, no DB required)
- [ ] `ruff check src tests` reports no errors
- [ ] New strategies have tests covering format validity and `None` passthrough
- [ ] `README.md` strategy table updated if you added a strategy
- [ ] No credentials, DSN strings, or org-specific data committed
