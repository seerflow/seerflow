# Contributing to Seerflow

Thanks for your interest in improving Seerflow. This guide describes the
exact workflow the project enforces — following it keeps CI green and PRs
mergeable.

## Development Setup

Requirements:

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment
  management

```bash
git clone https://github.com/seerflow/seerflow.git
cd seerflow

# Create the virtualenv and install all dependencies
uv sync

# Install the git hooks (one-time, after cloning)
uv run pre-commit install
uv run pre-commit install --hook-type pre-push
```

Run Seerflow locally (zero-config, SQLite default):

```bash
uv run python -m seerflow start
```

## Quality Gates

Every change must pass the same gates CI and the release workflow enforce.
Run them locally before pushing:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run bandit -r src/ -c pyproject.toml
uv run pytest --cov=src/seerflow --cov-fail-under=95
```

Or all at once:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ \
  && uv run bandit -r src/ -c pyproject.toml \
  && uv run pytest --cov=src/seerflow --cov-fail-under=95
```

The hooks installed above run a subset automatically:

- **pre-commit** (every commit): `ruff check`, `ruff format`, `mypy`, the
  `no-redundant-asyncio-marker` check.
- **pre-push** (before push): `bandit`, `pytest` with the
  `--cov-fail-under=95` coverage gate.

Run the full hook suite manually at any time:

```bash
uv run pre-commit run --all-files
uv run pre-commit run --all-files --hook-stage pre-push
```

### Testing rules

- Minimum **95% coverage** overall and on changed files (critical paths:
  parsers, entity resolution, correlation, ML).
- **Test-driven development**: write the failing test first, then the
  implementation. New code without tests will not be merged.
- Add **unit tests** under `tests/unit/` and, for pipeline-stage / storage
  behaviour, **integration tests** under `tests/integration/`.
- `asyncio_mode = "auto"` is set — **never** add `@pytest.mark.asyncio` to
  an `async def` test; it is redundant and enforced against by the
  `no-redundant-asyncio-marker` hook.

## Branching

- **`main`** — production-ready, protected. Released to PyPI via
  release-please.
- **`dev`** — the integration branch. **All feature work merges here first.**
- **Feature branches** — branch off `dev`, named
  `feat/S-XXX-short-description` (use the story ID where one exists).

The only pull requests that target `main` are `dev` → `main` release PRs.
Feature branches **never** target `main` directly.

## Commits

Use the [Conventional Commits](https://www.conventionalcommits.org/) format —
release-please derives the changelog and version bump from commit/PR types:

```
<type>(<scope>): <summary>

<optional body>
```

Types: `feat` (minor bump), `fix` (patch), `chore` / `refactor` / `docs` /
`perf` / `ci` / `test` (no bump). Append `!` for a breaking change (major).

## Pull Requests

1. Branch off `dev`; keep the change focused on one story / concern.
2. Ensure all quality gates pass locally (see above).
3. Open the PR with **base branch `dev`** — never `main` for feature work:

   ```bash
   gh pr create --base dev --title "feat(SEE-XXX): summary [S-XXX]" --body "..."
   ```

4. Fill in the pull request template (`.github/pull_request_template.md`):
   unit + integration tests for changed code, no hardcoded secrets,
   immutable data, functions < 50 lines, files < 800 lines, inputs validated
   at boundaries.
5. A reviewer must approve before merge. CI must be green on `dev` before any
   `dev` → `main` release PR.

## License

By contributing you agree that your contributions are licensed under the
project's [AGPL-3.0](LICENSE) license.
