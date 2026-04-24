"""Tests for RiskHistory Pydantic schemas (S-060.F1)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from seerflow.api.schemas import (
    RiskBucketResponse,
    RiskHistoryMetaResponse,
    RiskHistoryResponse,
)


class TestRiskBucketResponse:
    def test_valid_bucket_roundtrips(self) -> None:
        bucket = RiskBucketResponse(
            bucket_start_ns=1_711_200_000_000_000_000,
            points=12.5,
            alert_count=3,
            top_rule_name="sigma.brute_force_ssh",
        )
        payload = json.loads(bucket.model_dump_json())
        assert payload["bucket_start_ns"] == "1711200000000000000"
        assert payload["points"] == 12.5
        assert payload["alert_count"] == 3
        assert payload["top_rule_name"] == "sigma.brute_force_ssh"

    def test_empty_bucket_has_flat_string_rule_name(self) -> None:
        bucket = RiskBucketResponse(
            bucket_start_ns=0,
            points=0.0,
            alert_count=0,
            top_rule_name="",
        )
        raw_json = bucket.model_dump_json()
        payload = json.loads(raw_json)
        assert payload["top_rule_name"] == ""
        assert '"top_rule_name":null' not in raw_json

    def test_negative_points_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RiskBucketResponse(bucket_start_ns=0, points=-0.1, alert_count=0, top_rule_name="")

    def test_negative_alert_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RiskBucketResponse(bucket_start_ns=0, points=0.0, alert_count=-1, top_rule_name="")


class TestRiskHistoryMetaResponse:
    def test_truncation_flag_roundtrips(self) -> None:
        meta = RiskHistoryMetaResponse(range="24h", resolution="15m", alert_count_truncated=True)
        payload = json.loads(meta.model_dump_json())
        assert payload == {
            "range": "24h",
            "resolution": "15m",
            "alert_count_truncated": True,
        }


class TestRiskHistoryResponse:
    def test_envelope_shape(self) -> None:
        resp = RiskHistoryResponse(
            meta=RiskHistoryMetaResponse(range="1h", resolution="1m", alert_count_truncated=False),
            items=[
                RiskBucketResponse(bucket_start_ns=0, points=0.0, alert_count=0, top_rule_name=""),
            ],
        )
        payload = json.loads(resp.model_dump_json())
        assert set(payload) == {"meta", "items"}
        assert payload["items"][0]["bucket_start_ns"] == "0"
