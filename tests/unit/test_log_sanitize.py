"""Unit tests for :mod:`seerflow.utils.log_sanitize` (S-080).

Carries the DSN/password/dsn-kv scrubbing requested in the S-056 code review:
``asyncpg`` exceptions occasionally embed the connection string (with
password) in ``args``/``__cause__``. The sanitizer must strip these before
they hit log handlers.
"""

from __future__ import annotations

from seerflow.utils.log_sanitize import sanitize_exception


class TestSanitizeException:
    """The redaction contract for connection-string secrets."""

    def test_strips_postgres_dsn(self) -> None:
        exc = RuntimeError("connect failed: postgresql://user:s3cr3t@host:5432/db")
        out = sanitize_exception(exc)
        assert "s3cr3t" not in out
        assert "postgres://***@" in out or "postgresql://***@" in out

    def test_strips_uppercase_dsn_scheme(self) -> None:
        """libpq / asyncpg sometimes emit ``POSTGRESQL://`` or ``Postgres://``."""
        exc = RuntimeError("connect failed: POSTGRESQL://user:Sup3r@host/db")
        out = sanitize_exception(exc)
        assert "Sup3r" not in out
        assert "***@" in out

    def test_strips_dsn_with_at_in_password(self) -> None:
        """``user:p@ssword@host`` — embedded ``@`` must not leak the tail."""
        exc = RuntimeError("connect failed: postgres://user:p@ssword@host/db")
        out = sanitize_exception(exc)
        assert "ssword" not in out
        assert "@host/db" in out

    def test_strips_password_kv(self) -> None:
        exc = RuntimeError("auth error password=hunter2 user=postgres")
        out = sanitize_exception(exc)
        assert "hunter2" not in out
        assert "password=***" in out.lower() or "password = ***" in out.lower()

    def test_strips_passwd_variant(self) -> None:
        """``passwd=`` is a common asyncpg/psycopg variant."""
        exc = RuntimeError("Passwd=hunter2 host=db")
        out = sanitize_exception(exc)
        assert "hunter2" not in out

    def test_strips_dsn_kv(self) -> None:
        exc = RuntimeError("config error dsn=postgresql://u:p@h/d")
        out = sanitize_exception(exc)
        # Both the dsn= label value AND any embedded DSN must be scrubbed.
        assert "p@h" not in out
        # Either the whole dsn=... value got replaced or the embedded DSN did.
        assert ("dsn=***" in out.lower()) or ("postgres://***@" in out)

    def test_walks_cause_chain(self) -> None:
        inner = RuntimeError("inner postgresql://u:innerpw@h/d")
        try:
            try:
                raise inner
            except RuntimeError as e:
                raise RuntimeError("outer wrap") from e
        except RuntimeError as exc:
            out = sanitize_exception(exc)
        assert "innerpw" not in out
        assert "outer wrap" in out

    def test_walks_context_chain(self) -> None:
        """Implicit ``__context__`` (bare ``raise`` inside ``except``) must be walked.

        Adapters that catch a DSN-bearing exception and re-raise a generic
        wrapper without ``from`` leave the original in ``__context__``, not
        ``__cause__`` — the sanitizer must still scrub it.
        """
        try:
            try:
                raise RuntimeError("inner postgresql://u:ctxpw@h/d")
            except RuntimeError:
                raise RuntimeError("outer wrap")  # noqa: B904
        except RuntimeError as exc:
            out = sanitize_exception(exc)
        assert "ctxpw" not in out
        assert "outer wrap" in out

    def test_safe_no_secrets(self) -> None:
        exc = RuntimeError("plain error message, no secrets here")
        out = sanitize_exception(exc)
        assert "plain error message" in out

    def test_caps_cause_depth_2(self) -> None:
        # Build a 5-deep cause chain; sanitizer must walk only 2 levels.
        deepest = RuntimeError("level5 postgresql://u:DEEPEST_PW@h/d")
        try:
            try:
                try:
                    try:
                        try:
                            raise deepest
                        except RuntimeError as e4:
                            raise RuntimeError("level4") from e4
                    except RuntimeError as e3:
                        raise RuntimeError("level3") from e3
                except RuntimeError as e2:
                    raise RuntimeError("level2") from e2
            except RuntimeError as e1:
                raise RuntimeError("level1 outer") from e1
        except RuntimeError as exc:
            out = sanitize_exception(exc)

        # Depth-bounded: we visit outer + 2 cause hops -> 3 frames max.
        assert "level1" in out
        # Crucially, the secret beyond depth 2 must NOT appear.
        assert "DEEPEST_PW" not in out
        # And we never blow up despite the depth.
        assert isinstance(out, str)

    def test_handles_non_string_args(self) -> None:
        """``Exception.args`` may contain non-strings (ints, dicts) — must not raise."""
        exc = RuntimeError(500, {"detail": "boom"})
        out = sanitize_exception(exc)
        # Returns a string; no crash.
        assert isinstance(out, str)
        assert "boom" in out or "500" in out
