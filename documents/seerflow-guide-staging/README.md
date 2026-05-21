# seerflow-guide staging

These artifacts are staged in the `seerflow` repository for the **S-180 cross-repo PR**.
A companion PR on `seerflow/seerflow-guide` (tracked as follow-up story **S-180-F1**) copies them verbatim into that repo per the file-map in the parent PR description.

## File map (staged → seerflow-guide)

> **Why `drift_check/` and `guide/` instead of `scripts/` and `docs/`?** The
> local `seerflow` repo has the top-level path components `scripts` and `docs`
> excluded via `.git/info/exclude`, which blocks any nested directory of those
> names anywhere in the tree from being committed without `git add -f` (which
> CLAUDE.md forbids). To keep the staged artifacts version-controlled here,
> the package is renamed `drift_check/` and the docs root is renamed `guide/`.
> The companion PR (S-180-F1) renames them back to `scripts/` and `docs/` when
> copying into `seerflow-guide`, which has no such exclude.

| Staged path (relative to this directory) | Target path in `seerflow-guide` |
|---|---|
| `pyproject.toml` (the docs-repo-specific keys only; see "Pyproject merge notes" below) | `pyproject.toml` |
| `drift_check/check_docs_drift.py` | `scripts/check_docs_drift.py` |
| `.markdown-link-check.json` | `.markdown-link-check.json` |
| `.github/workflows/docs-drift.yml` | `.github/workflows/docs-drift.yml` |
| `guide/quickstart.md` | `docs/quickstart.md` |
| `guide/reference/api.md` | `docs/reference/api.md` |
| `guide/reference/configuration.md` | `docs/reference/configuration.md` |
| `guide/reference/cli.md` | `docs/reference/cli.md` |
| `guide/frontend/index.md` | `docs/frontend/index.md` |
| `guide/examples/quickstart/sample-logs.jsonl` | `docs/examples/quickstart/sample-logs.jsonl` |
| `guide/examples/quickstart/generate.py` | `docs/examples/quickstart/generate.py` |
| `guide/examples/quickstart/docker-compose.yml` | `docs/examples/quickstart/docker-compose.yml` |
| `guide/retros/epic-doc-2026-04.md` | `docs/retros/epic-doc-2026-04.md` |

## Running drift check locally

From the project root of `seerflow-guide` (after the companion PR lands):

```bash
uv pip install -e .[dev]
uv pip install "seerflow @ git+https://github.com/seerflow/seerflow@main"
uv run python scripts/check_docs_drift.py --docs-dir docs --report-path drift-report.json
```

The script exits zero when documented config keys and CLI flags match the
installed `seerflow` package. On drift it writes `drift-report.json` and exits
non-zero; the `docs-drift` GitHub Action posts a PR comment with the contents
of that JSON.

## Pyproject merge notes

The staged `pyproject.toml` is **not** intended as a wholesale replacement of
the existing `seerflow-guide/pyproject.toml`. The companion PR should merge
the following keys only:

- Add `mkdocstrings[python]>=0.24` to the runtime `dependencies` block.
- Add (or extend) the `dev` optional dependency group with `pytest>=8.0` and
  `pytest-cov>=5.0`.
- Add a top-level `[tool.pytest.ini_options]` block with `testpaths = ["tests"]`
  if one does not exist.

## Verifying staged content in this repo

The drift helpers are exercised by tests under `tests/` here, using synthetic
fixtures so they run independently of the real `seerflow` package. Run them
from the project root of the `seerflow` repo:

```bash
uv run --python 3.11 pytest documents/seerflow-guide-staging/tests/ -v
```

To dogfood the drift check against the staged docs (config + CLI references
this directory ships), run from the project root of `seerflow`:

```bash
uv run --python 3.11 python documents/seerflow-guide-staging/drift_check/check_docs_drift.py \
  --docs-dir documents/seerflow-guide-staging/guide \
  --report-path /tmp/drift-report.json
```

Exit zero confirms the staged `docs/reference/configuration.md` and
`docs/reference/cli.md` document only real config keys and CLI flags from the
installed `seerflow` package.

## Cross-repo handoff to S-180-F1

The companion `seerflow-guide` PR (tracked as follow-up story **S-180-F1**)
owns:

* Copying every file in the file map above into `seerflow-guide`.
* Adding a "Retrospective" pointer line near the top of `seerflow/docs/stories/S-139.md`
  and an "EPIC-DOC retrospective" closing subsection in
  `seerflow/docs/sprint-plan-seerflow-2026-03-17.md`. (Those two seerflow-side
  files are excluded from git tracking via `.git/info/exclude` in the local
  development snapshot — they are not version-controlled here, so the cross-
  reference link is delegated to whoever lands S-180-F1 on a tracked branch
  or directly upstream.)
* Posting the staged retrospective markdown as a comment on Linear SEE-142
  and transitioning SEE-142 to **Done**.

Until S-180-F1 lands, SEE-195 (this story) stops at **In Review / QA** as
specified by the dev-story workflow — no `Done` transition on either issue.

## S-180-F1 closure note (2026-05-20)

Companion PR is open: <https://github.com/seerflow/seerflow-guide/pull/16>.

Tracked deltas in this seerflow-side PR are limited to this README closure
note because every other artifact intended for cross-repo handoff lives at
paths that are excluded by `.git/info/exclude` on this development snapshot:

* `docs/stories/S-180-F1.md` (Status flipped to **Done** locally)
* `docs/stories/S-139.md` (Retrospective pointer line added locally — see
  PR description below for the text the next tracked update should include)
* `docs/sprint-plan-seerflow-2026-03-17.md` (EPIC-DOC retrospective closing
  subsection added locally — same caveat as above)

The companion PR carries the full content: drift guard relocated to
`scripts/check_docs_drift.py`, quickstart + minimum-viable references +
frontend stub + EPIC-DOC retro under `docs/`, mkdocstrings wired into
`mkdocs.yml`, and `mkdocs build --strict` exits zero locally. The
`docs-drift` workflow ships in that same PR and dogfoods itself on the
introducing PR.

Linear sync planned by this story:

* Post the full markdown of `docs/retros/epic-doc-2026-04.md` (now landed in
  seerflow-guide via the companion PR) as a comment on SEE-142.
* Transition SEE-142 → **Done**.
* Transition SEE-195 → **Done** only after SEE-142 is Done.

Each Linear MCP call is best-effort under the free-issue quota policy:
updates to existing issues are allowed, only new issue creation is blocked.
On 429 / quota errors the call is deferred and surfaced in the parent
agent's deferred-issues list.
