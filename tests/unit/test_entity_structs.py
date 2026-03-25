"""Tests for entity struct definitions and tagged-union decoding."""

from __future__ import annotations

import uuid

import msgspec
import pytest

from seerflow.models.entity import (
    DomainEntity,
    FileEntity,
    HostEntity,
    IPEntity,
    ProcessEntity,
    SecurityEntity,
    UserEntity,
)

_NOW = 1_700_000_000_000_000_000


class TestUserEntity:
    def test_create_required_fields(self) -> None:
        e = UserEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, username="alice")
        assert e.username == "alice"
        assert e.domain is None
        assert e.groups == ()
        assert e.is_service_account is False
        assert e.source_count == 1
        assert e.confidence == 1.0

    def test_create_all_fields(self) -> None:
        e = UserEntity(
            entity_id=uuid.uuid4(),
            first_seen=_NOW,
            last_seen=_NOW,
            username="svc",
            domain="corp.local",
            email="svc@corp.local",
            sid="S-1-5-21-123",
            uid=1001,
            groups=("admins", "users"),
            is_service_account=True,
            source_count=5,
            confidence=0.9,
        )
        assert e.is_service_account is True
        assert e.groups == ("admins", "users")

    def test_frozen(self) -> None:
        e = UserEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, username="alice")
        with pytest.raises(AttributeError):
            e.username = "bob"  # type: ignore[misc]


class TestIPEntity:
    def test_create_defaults(self) -> None:
        e = IPEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, address="10.0.0.1")
        assert e.version == 4
        assert e.is_private is False
        assert e.is_tor_exit is False

    def test_frozen(self) -> None:
        e = IPEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, address="10.0.0.1")
        with pytest.raises(AttributeError):
            e.address = "1.2.3.4"  # type: ignore[misc]


class TestHostEntity:
    def test_create_defaults(self) -> None:
        e = HostEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, hostname="web01")
        assert e.fqdn is None
        assert e.ip_addresses == ()
        assert e.mac_addresses == ()

    def test_frozen(self) -> None:
        e = HostEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, hostname="web01")
        with pytest.raises(AttributeError):
            e.hostname = "web02"  # type: ignore[misc]


class TestProcessEntity:
    def test_create_defaults(self) -> None:
        e = ProcessEntity(
            entity_id=uuid.uuid4(),
            first_seen=_NOW,
            last_seen=_NOW,
            pid=1234,
            name="sshd",
        )
        assert e.command_line is None
        assert e.hashes == {}
        assert e.parent_pid is None

    def test_hashes_default_factory_isolation(self) -> None:
        a = ProcessEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, pid=1, name="a")
        b = ProcessEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, pid=2, name="b")
        assert a.hashes is not b.hashes

    def test_frozen(self) -> None:
        e = ProcessEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, pid=1, name="a")
        with pytest.raises(AttributeError):
            e.pid = 2  # type: ignore[misc]


class TestFileEntity:
    def test_create_defaults(self) -> None:
        e = FileEntity(
            entity_id=uuid.uuid4(),
            first_seen=_NOW,
            last_seen=_NOW,
            path="/var/log/syslog",
        )
        assert e.name == ""
        assert e.hashes == {}
        assert e.size is None

    def test_hashes_default_factory_isolation(self) -> None:
        a = FileEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, path="/a")
        b = FileEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, path="/b")
        assert a.hashes is not b.hashes

    def test_frozen(self) -> None:
        e = FileEntity(entity_id=uuid.uuid4(), first_seen=_NOW, last_seen=_NOW, path="/a")
        with pytest.raises(AttributeError):
            e.path = "/b"  # type: ignore[misc]


class TestDomainEntity:
    def test_create_defaults(self) -> None:
        e = DomainEntity(
            entity_id=uuid.uuid4(),
            first_seen=_NOW,
            last_seen=_NOW,
            domain="example.com",
        )
        assert e.registrar is None
        assert e.is_dga is False

    def test_frozen(self) -> None:
        e = DomainEntity(
            entity_id=uuid.uuid4(),
            first_seen=_NOW,
            last_seen=_NOW,
            domain="example.com",
        )
        with pytest.raises(AttributeError):
            e.domain = "evil.com"  # type: ignore[misc]


class TestSecurityEntityUnion:
    def test_round_trip_each_type(self) -> None:
        eid = uuid.uuid4()
        entities = [
            UserEntity(entity_id=eid, first_seen=_NOW, last_seen=_NOW, username="alice"),
            IPEntity(entity_id=eid, first_seen=_NOW, last_seen=_NOW, address="10.0.0.1"),
            HostEntity(entity_id=eid, first_seen=_NOW, last_seen=_NOW, hostname="web01"),
            ProcessEntity(entity_id=eid, first_seen=_NOW, last_seen=_NOW, pid=1, name="sshd"),
            FileEntity(entity_id=eid, first_seen=_NOW, last_seen=_NOW, path="/var/log/syslog"),
            DomainEntity(entity_id=eid, first_seen=_NOW, last_seen=_NOW, domain="example.com"),
        ]
        for original in entities:
            data = msgspec.json.encode(original)
            decoded = msgspec.json.decode(data, type=SecurityEntity)
            assert type(decoded) is type(original)
            assert decoded.entity_id == original.entity_id

    def test_unknown_tag_raises(self) -> None:
        bad = (
            b'{"entity_type":"unknown",'
            b'"entity_id":"00000000-0000-0000-0000-000000000000",'
            b'"first_seen":0,"last_seen":0}'
        )
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(bad, type=SecurityEntity)

    def test_equality(self) -> None:
        eid = uuid.uuid4()
        a = UserEntity(entity_id=eid, first_seen=_NOW, last_seen=_NOW, username="alice")
        b = UserEntity(entity_id=eid, first_seen=_NOW, last_seen=_NOW, username="alice")
        assert a == b
