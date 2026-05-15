# Test conventions

## Async tests — no explicit `@pytest.mark.asyncio`

`pyproject.toml` configures pytest-asyncio with:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

In `auto` mode, **every** `async def` test function is collected and run by
pytest-asyncio automatically. An explicit `@pytest.mark.asyncio` decorator
(bare `@pytest.mark.asyncio` or the call form `@pytest.mark.asyncio()`) adds
**no behaviour** — it is pure visual noise and makes the convention ambiguous
for new contributors.

**Rule: never add `@pytest.mark.asyncio` to a test.** Write the test as a plain
`async def` and let auto-mode collect it. Other markers
(`@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.parametrize`,
`@pytest.mark.skipif`, ...) are unaffected and should still be used as normal.

```python
# WRONG — redundant decorator
@pytest.mark.unit
@pytest.mark.asyncio
async def test_something() -> None:
    ...

# RIGHT
@pytest.mark.unit
async def test_something() -> None:
    ...
```

### Enforcement

This convention is enforced in two complementary places (defence in depth):

1. **Suite-level meta-test** —
   `tests/unit/test_asyncio_marker_convention.py` scans the whole `tests/`
   tree and fails if any redundant decorator line is present. It runs as part
   of the normal `pytest` run and the 95 % coverage gate.
2. **Pre-commit hook** — the `no-redundant-asyncio-marker` hook in
   `.pre-commit-config.yaml` rejects any commit that reintroduces the
   decorator, before it ever reaches CI.
