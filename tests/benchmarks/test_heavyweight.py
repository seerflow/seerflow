"""Heavyweight benchmarks — run with: pytest -m slow -v

These are excluded from default CI runs via addopts = "-m 'not slow'".

NOTE: heavyweight storage benchmarks were removed in favor of sync
wrappers using the benchmark fixture.  Only non-storage heavyweight
tests belong here.
"""
