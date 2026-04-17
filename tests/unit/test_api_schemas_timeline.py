"""Regression tests for TimelineResponse Pydantic models."""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestTimelineResponseSchemas:
    def test_timeline_bucket_response_validates_happy_path(self) -> None:
        from seerflow.api.schemas import TimelineBucketResponse

        data = {
            "bucket_start_ns": 1_713_000_000_000_000_000,
            "max_score": 0.7,
            "avg_score": 0.5,
            "event_count": 3,
            "upper_threshold": 0.9,
            "alert_count": 1,
        }
        m = TimelineBucketResponse.model_validate(data)
        assert m.bucket_start_ns == data["bucket_start_ns"]
        assert m.alert_count == 1

    def test_timeline_bucket_response_allows_null_scores(self) -> None:
        from seerflow.api.schemas import TimelineBucketResponse

        data = {
            "bucket_start_ns": 0,
            "max_score": None,
            "avg_score": None,
            "event_count": 0,
            "upper_threshold": None,
            "alert_count": 0,
        }
        m = TimelineBucketResponse.model_validate(data)
        assert m.max_score is None

    def test_timeline_meta_response_defaults_truncated_false(self) -> None:
        from seerflow.api.schemas import TimelineMetaResponse

        data = {
            "range": "1h",
            "resolution": "1m",
            "source": None,
        }
        m = TimelineMetaResponse.model_validate(data)
        assert m.alert_count_truncated is False

    def test_timeline_response_validates_existing_wire_shape(self) -> None:
        """Regression: the dict shape returned by the S-059 endpoint must
        validate against the new Pydantic model without changes."""
        from seerflow.api.schemas import TimelineResponse

        existing = {
            "meta": {"range": "1h", "resolution": "1m", "source": None},
            "items": [
                {
                    "bucket_start_ns": 0,
                    "max_score": 0.3,
                    "avg_score": 0.2,
                    "event_count": 2,
                    "upper_threshold": 0.9,
                    "alert_count": 0,
                },
            ],
        }
        m = TimelineResponse.model_validate(existing)
        assert len(m.items) == 1
        assert m.meta.range == "1h"
        assert m.meta.alert_count_truncated is False
