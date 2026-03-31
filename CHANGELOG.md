# Changelog

## [0.4.0](https://github.com/seerflow/seerflow/compare/v0.3.0...v0.4.0) (2026-03-31)


### Features

* [SEE-42] S-094: Risk accumulation — per-entity risk register with exponential decay ([cc438fd](https://github.com/seerflow/seerflow/commit/cc438fd5748d2273c1df56916973a8bbfd48b679))
* [SEE-43] S-034: UUID5 entity resolution for deterministic cross-source correlation ([01bac92](https://github.com/seerflow/seerflow/commit/01bac92f4727381d1526ff9b4f5d26d063516a80))
* [SEE-44] S-035: igraph entity graph with typed edges and SQLite persistence ([8f56767](https://github.com/seerflow/seerflow/commit/8f56767b9f3477515e57185a8ed84c94b2e3c643))
* [SEE-45] S-036: Graph algorithms — PageRank + Louvain community detection ([40eb2e2](https://github.com/seerflow/seerflow/commit/40eb2e23a558afa8d705bc415517ea9fe567c72f))
* [SEE-47] S-037: Entity timeline reconstruction — query by UUID, time range, source ([f161429](https://github.com/seerflow/seerflow/commit/f1614293768d5d6812d2a49500fb4b310500a6ea))
* [SEE-50] S-038: Entity-temporal sliding window buffer for correlation ([0c24e99](https://github.com/seerflow/seerflow/commit/0c24e9939c63bde8df78edba66729453b84e53b0))
* [SEE-52] S-039: Watermark-based late arrival tolerance ([e98d2e9](https://github.com/seerflow/seerflow/commit/e98d2e9b4e2e9a501b0b049d4df396d157d2fea1))
* [SEE-54] S-093: Additional graph algorithms — fan-out, betweenness, ego-graph ([021b119](https://github.com/seerflow/seerflow/commit/021b11998a570f2096e91e7efa985d7e5d05e0cf))

## [0.3.0](https://github.com/seerflow/seerflow/compare/v0.2.0...v0.3.0) (2026-03-29)


### Features

* [SEE-126] S-122: Smart receiver auto-enable + seerflow tail subcommand ([#54](https://github.com/seerflow/seerflow/issues/54)) ([19be98e](https://github.com/seerflow/seerflow/commit/19be98e6794d5a9fb76a6a70f709b6966702285f))
* [SEE-130] S-126: Timed batch flush — remove handler batch, per-event writes via WriteBuffer ([#58](https://github.com/seerflow/seerflow/issues/58)) ([1c16884](https://github.com/seerflow/seerflow/commit/1c168848c4283f843306d8188912d33ac6e76c25))
* [SEE-131] S-127: Template table — persist Drain3 templates with stats to SQLite ([#55](https://github.com/seerflow/seerflow/issues/55)) ([3061061](https://github.com/seerflow/seerflow/commit/3061061340f5dcec4dc281110bd72749c75851ec))
* [SEE-134] S-131: Git hooks for quality gates — pre-commit + 95% coverage ([#57](https://github.com/seerflow/seerflow/issues/57)) ([ef4af16](https://github.com/seerflow/seerflow/commit/ef4af168833c4c795b2ca4759c53c14db258eee1))


### Bug Fixes

* [SEE-133] S-130: FileTailReceiver — recursive=False + process new files immediately ([#56](https://github.com/seerflow/seerflow/issues/56)) ([8779f66](https://github.com/seerflow/seerflow/commit/8779f66f613d762a323dc6cea63f4b42a4be7585))
* tail mode resolves default storage path via load_config ([58a754c](https://github.com/seerflow/seerflow/commit/58a754caf3251989f626756df0a71b14e7696c55))

## [0.2.0](https://github.com/seerflow/seerflow/compare/v0.1.0...v0.2.0) (2026-03-25)


### Features

* automated releases with release-please + semantic versioning (S-128) ([#45](https://github.com/seerflow/seerflow/issues/45)) ([dd8487b](https://github.com/seerflow/seerflow/commit/dd8487b791b59a3217d976a1b859adc0829f914f))


### Bug Fixes

* address retroactive code review findings (S-109) ([#22](https://github.com/seerflow/seerflow/issues/22)) ([8e4b866](https://github.com/seerflow/seerflow/commit/8e4b8664d6741bc5ee44219be5f201a95716372e))
* inline PyPI publish in release workflow — GITHUB_TOKEN can't trigger other workflows ([623af91](https://github.com/seerflow/seerflow/commit/623af91b5509b3a53284c7f148f082fba1479237))
* smoke test validates semver format instead of hardcoded version ([c1a6fa7](https://github.com/seerflow/seerflow/commit/c1a6fa79e9cf5a9eb445e84e218cc1a529b7e7df))
