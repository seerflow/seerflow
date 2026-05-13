"""Unit tests for ``seerflow._entity_detect`` (S-076)."""

from __future__ import annotations

import uuid

import pytest

from seerflow._entity_detect import EntityHit, detect_entity
from seerflow.models.entity import (
    generate_domain_id,
    generate_host_id,
    generate_ip_id,
    generate_user_id,
    normalize_username,
)


@pytest.mark.unit
def test_detect_entity_ipv4() -> None:
    hit = detect_entity("10.0.0.5")
    assert hit == EntityHit(
        entity_type="ip",
        entity_uuid=str(generate_ip_id("10.0.0.5")),
        entity_value="10.0.0.5",
    )


@pytest.mark.unit
def test_detect_entity_ipv6() -> None:
    hit = detect_entity("2001:db8::1")
    assert hit is not None
    assert hit.entity_type == "ip"
    assert hit.entity_uuid == str(generate_ip_id("2001:db8::1"))
    assert hit.entity_value == "2001:db8::1"


@pytest.mark.unit
def test_detect_entity_user_at_domain() -> None:
    hit = detect_entity("alice@example.com")
    username, domain = normalize_username("alice@example.com")
    assert hit == EntityHit(
        entity_type="user",
        entity_uuid=str(generate_user_id(username, domain)),
        entity_value="alice@example.com",
    )


@pytest.mark.unit
def test_detect_entity_user_domain_backslash() -> None:
    hit = detect_entity("CORP\\bob")
    username, domain = normalize_username("CORP\\bob")
    assert hit == EntityHit(
        entity_type="user",
        entity_uuid=str(generate_user_id(username, domain)),
        entity_value="CORP\\bob",
    )


@pytest.mark.unit
def test_detect_entity_host_dotted() -> None:
    hit = detect_entity("web-prod-01.example.com")
    assert hit == EntityHit(
        entity_type="host",
        entity_uuid=str(generate_host_id("web-prod-01.example.com")),
        entity_value="web-prod-01.example.com",
    )


@pytest.mark.unit
def test_detect_entity_uuid() -> None:
    value = str(uuid.uuid4())
    hit = detect_entity(value)
    assert hit == EntityHit(
        entity_type="uuid",
        entity_uuid=value,
        entity_value=value,
    )


@pytest.mark.unit
def test_detect_entity_uuid_uppercase_normalised() -> None:
    base = uuid.uuid4()
    hit = detect_entity(str(base).upper())
    # uuid.UUID(str) normalises to lowercase canonical form via str()
    assert hit is not None
    assert hit.entity_type == "uuid"
    assert hit.entity_uuid == str(base)


@pytest.mark.unit
def test_detect_entity_free_text_returns_none() -> None:
    assert detect_entity("failed login from 10.0.0.5") is None


@pytest.mark.unit
def test_detect_entity_numeric_label_returns_none() -> None:
    # "12345" is neither a valid IP nor a sensible hostname for routing.
    assert detect_entity("12345") is None


@pytest.mark.unit
def test_detect_entity_empty_string_returns_none() -> None:
    assert detect_entity("") is None


@pytest.mark.unit
def test_detect_entity_whitespace_returns_none() -> None:
    assert detect_entity("   ") is None


@pytest.mark.unit
def test_detect_entity_strips_surrounding_whitespace() -> None:
    hit = detect_entity("  10.0.0.5  ")
    assert hit is not None
    assert hit.entity_type == "ip"
    assert hit.entity_value == "10.0.0.5"


@pytest.mark.unit
def test_detect_entity_single_label_host_with_dash_rejected() -> None:
    # Single-label hostnames without a dot are too ambiguous for auto-routing.
    # They'd match too many natural-language tokens (e.g. "auth", "prod").
    assert detect_entity("web-prod-01") is None


@pytest.mark.unit
def test_detect_entity_domain_only_detected_as_host() -> None:
    hit = detect_entity("example.com")
    assert hit is not None
    assert hit.entity_type == "host"
    assert hit.entity_uuid == str(generate_host_id("example.com"))


@pytest.mark.unit
def test_detect_entity_user_at_invalid_domain_still_user() -> None:
    # "@" presence is enough to route as user; downstream search handles
    # zero-result gracefully.
    hit = detect_entity("svc-account@")
    assert hit is not None
    assert hit.entity_type == "user"


@pytest.mark.unit
def test_detect_entity_garbage_with_spaces_returns_none() -> None:
    assert detect_entity("hello@world.com today") is None


@pytest.mark.unit
def test_generate_domain_id_importable() -> None:
    # Sanity check that we didn't shadow the existing helper.
    assert generate_domain_id("example.com") is not None
