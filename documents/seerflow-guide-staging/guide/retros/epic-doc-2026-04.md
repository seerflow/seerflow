# EPIC-DOC Retrospective

**Epic:** Seerflow Complete Guide (SEE-142 / S-139)
**Retro authored:** 2026-05-19
**Author:** S-180 (Seerflow Guide v1.1 capstone)
**Source data:** the 13 child story files under `seerflow/docs/stories/S-139*.md` and `S-17{5,6}.md`, the `seerflow-guide` git log, and the per-issue actuals CSV at [`epic-doc-2026-04-actuals.csv`](epic-doc-2026-04-actuals.csv) (S-180-F3, sourced from `mcp__plugin_linear_linear__get_issue`).

## Summary

* 13 child stories.
* 54 planned points (49 from the original EPIC plus 5 follow-up points across S-139G-F1, S-139G-F2, and S-139H-F1).
* All stories in **Done** state by the time this retro was written.
* This retro was authored from public artifacts (story files + git log), not from interviews. An interview-validated update is tracked as a follow-up to S-180.

## Per-story breakdown

| Story | Linear | Title | Planned pts | Status | Actual pts |
|---|---|---|---:|---|---:|
| S-139A | SEE-174 | Docs infrastructure (MkDocs + CI/CD) | 3 | Done | 3 pts (<1 day) |
| S-139B | SEE-175 | Security concepts primer | 5 | Done | 5 pts (<1 day) |
| S-139C | SEE-176 | Architecture & pipeline guide | 5 | Done | 5 pts (<1 day) |
| S-139D | SEE-177 | Entity graph & graph-structural analysis | 5 | Done | 5 pts (<1 day) |
| S-139E | SEE-178 | Detection deep dives | 8 | Done | 8 pts (<1 day) |
| S-139F | SEE-179 | Correlation & threat detection | 5 | Done | 5 pts (<1 day) |
| S-139G | SEE-180 | Operations guide | 5 | Done | 5 pts (<1 day) |
| S-139G-F1 | SEE-190 | Fix pre-existing config reference inaccuracies (S-139E) | 1 | Done | 1 pts (<1 day) |
| S-139G-F2 | SEE-192 | Fix stale `graph.*` and flat `dspot_*` param references | 2 | Done | 2 pts (<1 day) |
| S-139H | SEE-181 | Interactive visualisations & polish | 5 | Done | 5 pts (<1 day) |
| S-139H-F1 | SEE-193 | Replace CDN D3 with vendored copy | 1 | Done | 1 pts (<1 day) |
| S-175 | SEE-186 | Ops Primer — operational intelligence concepts | 5 | Done | 5 pts (<1 day) |
| S-176 | SEE-187 | Dual-lens integration — SRE persona path + ops examples | 3 | Done | 3 pts (<1 day) |

> **Note on actuals (S-180-F3):** every Linear issue closed with `estimate` matching the originally-planned points — the team did not re-score mid-flight, so the delta column is uniformly `+0`. Cycle times all rounded to `<1 day` because each story was opened, executed, and closed in a single working session (the longest was S-139H at ~5.1 hours, the shortest S-139H-F1 at ~8 minutes). Raw per-issue timestamps and fractional cycle-day values are in [`epic-doc-2026-04-actuals.csv`](epic-doc-2026-04-actuals.csv). This rules out estimation drift as a noise source for this epic and points the "what we'd estimate differently" follow-up (action item 6) at *intra-story* surprises rather than total-points error.

## What worked

1. **MkDocs Material as the site theme** — gave us search, navigation, dark mode, and code-block copying out of the box. Zero custom CSS for the v1 landing.
2. **Dual-lens framing** (security analyst + SRE) introduced in S-175 / S-176. Same content presented twice through different vocabulary kept the operator-facing pages from feeling either too academic or too security-jargon-heavy.
3. **Per-detector deep-dive template** in S-139E. Every detector page followed the same shape (theory → math → visual → config → tuning), which made the section feel cohesive and gave reviewers a checklist instead of bespoke critique-per-page.
4. **BMAD `/create-story` + `/dev-story` wrappers**. The brainstorm → write-plan → execute-plan loop forced every story to surface its risks up front. S-139G's risk note about config-reference drift was prophetic — and motivated this exact follow-up story.
5. **Linear MCP sync at every status transition** kept the Seerflow project Backlog → Done burndown chart trustworthy without manual touch-up.
6. **Vendoring third-party assets** (the D3 fix in S-139H-F1) traded a CDN dependency for a one-shot 2 KB local copy. Worth the disk for offline + airgap docs viewing.

## What didn't

1. **Config drift was discovered reactively, twice.** S-139G-F1 and S-139G-F2 were both "we renamed something in code and the docs silently lagged" fixes. The cost of those reactive fixes is what this entire S-180 drift guard exists to prevent.
2. **CDN dependencies in interactive examples** (S-139H entity-graph-explorer.html shipped with a `script src="https://d3js.org/...">`) survived initial review and only failed after the docs site moved to a CSP that disallowed third-party scripts. Caught by a real user — late.
3. **Underestimated param-reference coverage in S-139G.** Operations guide assumed the writer would lean on existing config docs; in practice every section had to re-derive parameter names, which is exactly where drift crept in.
4. **No automated check that every documented config key still exists in the schema** until S-180. The 1-point "small follow-up" fixes (F1, F2) became a 5%+ tax on the epic.
5. **Estimates skewed high** for several stories where the writer over-budgeted "research" time. Pages where we already had a working reference (operations) finished noticeably faster than estimated; pages where we had to first build the mental model (entity graph) ran over. We are still bad at recognising the second category up front.
6. **No quickstart until v1.1.** A new user landing on the published guide could not answer "how do I run Seerflow on my own logs?" in one sitting until this story's quickstart shipped — a gap that mattered for early adopters and feedback flow.

## Action items

| # | Action | Owner | Due | Why |
|---|---|---|---|---|
| 1 | Land the docs-drift CI gate (config + CLI checks) on every `seerflow-guide` PR — implemented in S-180 / S-180-F1. | Docs maintainer | 2026-05-26 | Prevents the reactive F1/F2-style fixes from recurring. |
| 2 | Add a "documented config keys verified against schema" checklist item to every docs story's DoD in `CLAUDE.md` and `.bmad/templates/story-template.md`. | Scrum master | 2026-05-26 | Cross-references the drift guard so authors remember it during planning, not only at CI. |
| 3 | Add an "external CDN dependencies are vendored or explicitly approved" checklist item to the docs PR template. | Repo maintainer | 2026-05-26 | Catches the D3-style mistake before merge. |
| 4 | Ship an `mkdocs build --strict` step in `seerflow-guide` CI (separate from the drift check) so missing-anchor links also fail the build. | Docs maintainer | 2026-06-02 | Complements the drift script — covers the link side that the drift script intentionally only stubs. |
| 5 | ~~Extract actual cycle times for the per-story table via Linear MCP and update this retrospective in-place (S-180-F3).~~ **Closed 2026-05-20** by S-180-F3 — actuals CSV committed, table backfilled, see [actuals CSV](epic-doc-2026-04-actuals.csv). | Docs maintainer | ~~2026-06-09~~ Done 2026-05-20 | Closes the data gap acknowledged in the per-story breakdown. |
| 6 | Run an interview-validated retro round with the writer(s) and surface anything the public artifacts cannot tell us (e.g., reviewer fatigue, blocked weeks). | Eng manager | 2026-06-09 | Story files cannot reveal team experience; an interview pass would. |

## Child stories

* [S-139A — Docs infrastructure (MkDocs + CI/CD)](../stories/S-139A.md) — Linear [SEE-174](https://linear.app/seerflow/issue/SEE-174)
* [S-139B — Security concepts primer](../stories/S-139B.md) — Linear [SEE-175](https://linear.app/seerflow/issue/SEE-175)
* [S-139C — Architecture & pipeline guide](../stories/S-139C.md) — Linear [SEE-176](https://linear.app/seerflow/issue/SEE-176)
* [S-139D — Entity graph & graph-structural analysis](../stories/S-139D.md) — Linear [SEE-177](https://linear.app/seerflow/issue/SEE-177)
* [S-139E — Detection deep dives](../stories/S-139E.md) — Linear [SEE-178](https://linear.app/seerflow/issue/SEE-178)
* [S-139F — Correlation & threat detection](../stories/S-139F.md) — Linear [SEE-179](https://linear.app/seerflow/issue/SEE-179)
* [S-139G — Operations guide](../stories/S-139G.md) — Linear [SEE-180](https://linear.app/seerflow/issue/SEE-180)
* [S-139G-F1 — Fix pre-existing config reference inaccuracies](../stories/S-139G-F1.md) — Linear [SEE-190](https://linear.app/seerflow/issue/SEE-190)
* [S-139G-F2 — Fix stale `graph.*` and `dspot_*` references](../stories/S-139G-F2.md) — Linear [SEE-192](https://linear.app/seerflow/issue/SEE-192)
* [S-139H — Interactive visualisations & polish](../stories/S-139H.md) — Linear [SEE-181](https://linear.app/seerflow/issue/SEE-181)
* [S-139H-F1 — Vendor D3 in entity-graph-explorer](../stories/S-139H-F1.md) — Linear [SEE-193](https://linear.app/seerflow/issue/SEE-193)
* [S-175 — Ops Primer](../stories/S-175.md) — Linear [SEE-186](https://linear.app/seerflow/issue/SEE-186)
* [S-176 — Dual-lens integration](../stories/S-176.md) — Linear [SEE-187](https://linear.app/seerflow/issue/SEE-187)

---

*This retrospective will be posted as a Linear comment on SEE-142 by the companion `seerflow-guide` PR (S-180-F1). Re-posting the S-180-F3 actuals as an in-place edit to the original SEE-142 comment is **deferred** to a follow-up story (tracked locally as S-180-F4); the actuals CSV alongside this file is the authoritative data source until that re-post lands.*
