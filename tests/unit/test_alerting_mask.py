"""Tests for the public mask_webhook_url helper."""

from __future__ import annotations

from seerflow.alerting.mask import mask_webhook_url


class TestMaskWebhookUrl:
    def test_masks_path_and_query(self) -> None:
        url = "https://hooks.slack.com/services/T123/B456/xyzSECRET"
        assert mask_webhook_url(url) == "https://hooks.slack.com/***"

    def test_preserves_scheme_and_host(self) -> None:
        assert mask_webhook_url("http://example.com/hook") == "http://example.com/***"

    def test_invalid_url_returns_placeholder(self) -> None:
        assert mask_webhook_url("not-a-url") == "<invalid-url>"

    def test_empty_string_returns_placeholder(self) -> None:
        assert mask_webhook_url("") == "<invalid-url>"

    def test_non_default_port_preserved(self) -> None:
        """Masked output keeps the port so operators can identify the target."""
        assert (
            mask_webhook_url("https://internal:9443/webhook/TOKEN") == "https://internal:9443/***"
        )

    def test_userinfo_stripped(self) -> None:
        """Any ``user:pass@`` prefix must never appear in the masked output."""
        masked = mask_webhook_url("https://user:pass@host:9443/path/SECRET")
        assert "user" not in masked
        assert "pass" not in masked
        assert masked == "https://host:9443/***"
