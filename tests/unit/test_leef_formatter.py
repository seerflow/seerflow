"""Tests for the LEEF 2.0 (QRadar generic open format) alert formatter.

Conformance target — the LEEF 2.0 grammar::

    LEEF:2.0|Vendor|Product|Version|EventID|[DelimiterChar|]Attributes

The 6th ``DelimiterChar`` field is optional: it is emitted only when the
attribute delimiter is not the spec default (TAB).

Header escaping:    ``\\`` -> ``\\\\``, ``|`` -> ``\\|``; CR/LF stripped.
Attribute escaping: ``\\`` -> ``\\\\``, ``=`` -> ``\\=``, the active delimiter
escaped, newline -> ``\\n``, CR -> ``\\r``.
"""

from __future__ import annotations

import re
import uuid

import pytest

import seerflow
from seerflow.alerting.formatters import format_leef
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

_DEFAULT_DELIMITER = "\t"


def _make_alert(
    *,
    alert_id: str = "550e8400-e29b-41d4-a716-446655440000",
    alert_type: str = "ml",
    timestamp_ns: int = 1_700_000_000_000_000_000,
    severity_id: SeverityLevel = SeverityLevel.WARNING,
    rule_name: str = "hst-anomaly",
    description: str = "Test alert description",
    entity_uuid: str = "entity-uuid-001",
    entity_value: str = "192.168.1.1",
    entity_type: str = "ip",
    mitre_tactics: tuple[str, ...] = (),
    mitre_techniques: tuple[str, ...] = (),
    risk_score: float = 0.75,
    dedup_key: str = "test:dedup:key",
    dedup_count: int = 1,
) -> Alert:
    """Return a default Alert instance for testing."""
    return Alert(
        alert_id=alert_id,
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=timestamp_ns,
        severity_id=severity_id,
        rule_name=rule_name,
        description=description,
        entity_uuid=entity_uuid,
        entity_value=entity_value,
        entity_type=entity_type,  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        mitre_tactics=mitre_tactics,
        mitre_techniques=mitre_techniques,
        risk_score=risk_score,
        dedup_key=dedup_key,
        dedup_count=dedup_count,
    )


def _parse_header(line: str) -> tuple[list[str], str]:
    """Split a LEEF line into header tokens + the trailing attribute blob.

    Returns ``(tokens, attributes)`` where ``tokens`` is the list of header
    fields starting with the ``LEEF:2.0`` literal. Pipes inside a field are
    backslash-escaped per the LEEF header escaping rules.
    """
    assert line.startswith("LEEF:2.0|")
    tokens: list[str] = ["LEEF:2.0"]
    field_chars: list[str] = []
    i = len("LEEF:2.0|")
    # The header has 4 more pipe-separated fields after the version
    # (Vendor, Product, Version, EventID), optionally a DelimiterChar, then the
    # attribute blob. We split on unescaped pipes until the blob begins.
    # The number of leading header fields is determined by the producer, so we
    # split *all* unescaped pipes and let the caller interpret the tail.
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            field_chars.append(line[i : i + 2])
            i += 2
            continue
        if ch == "|":
            tokens.append("".join(field_chars))
            field_chars = []
            i += 1
            continue
        field_chars.append(ch)
        i += 1
    tokens.append("".join(field_chars))
    # The attribute blob is always the final token.
    attributes = tokens.pop()
    return tokens, attributes


def _header_fields(line: str) -> tuple[list[str], str, str]:
    """Return ``(vendor, product, version, event_id), delimiter, attributes``.

    Recovers the active delimiter: present iff the header carries the optional
    6th field (5 tokens after ``LEEF:2.0``), else the default TAB.
    """
    tokens, attributes = _parse_header(line)
    # tokens[0] == "LEEF:2.0"
    body = tokens[1:]
    if len(body) == 5:  # vendor product version eventID delimiter
        delimiter = body[4]
        header = body[:4]
    else:
        delimiter = _DEFAULT_DELIMITER
        header = body
    return header, delimiter, attributes


def _parse_attributes(blob: str, delimiter: str) -> dict[str, str]:
    """Parse a LEEF attribute blob into a key->value dict (honours escaping)."""
    pairs: dict[str, str] = {}
    if not blob:
        return pairs
    # Split on *unescaped* delimiters.
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(blob):
        ch = blob[i]
        if ch == "\\" and i + 1 < len(blob):
            buf.append(blob[i : i + 2])
            i += 2
            continue
        if ch == delimiter:
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    for seg in segments:
        # Key runs up to the first *unescaped* '='.
        m = re.match(r"^([^=\\]+)=(.*)$", seg, re.DOTALL)
        assert m is not None, f"bad attribute segment: {seg!r}"
        key, raw = m.group(1), m.group(2)
        val = raw.replace("\\=", "=").replace("\\n", "\n").replace("\\r", "\r")
        # Unescape the delimiter then the backslash (order matters).
        val = val.replace("\\" + delimiter, delimiter).replace("\\\\", "\\")
        pairs[key] = val
    return pairs


def _attrs(line: str) -> dict[str, str]:
    """Convenience: parse the attributes of a LEEF line honouring its delimiter."""
    _, delimiter, blob = _header_fields(line)
    return _parse_attributes(blob, delimiter)


class TestHeaderShape:
    def test_starts_with_leef_two_zero(self) -> None:
        assert format_leef(_make_alert()).startswith("LEEF:2.0|")

    def test_default_header_has_five_fields(self) -> None:
        # LEEF:2.0 + Vendor Product Version EventID, no delimiter field (tab default).
        header, delimiter, _ = _header_fields(format_leef(_make_alert()))
        assert len(header) == 4
        assert delimiter == _DEFAULT_DELIMITER

    def test_vendor_product_version_from_constants(self) -> None:
        (vendor, product, version, _event_id), _, _ = _header_fields(format_leef(_make_alert()))
        assert vendor == "Seerflow"
        assert product == "Seerflow"
        assert version == seerflow.__version__

    def test_event_id_is_rule_name(self) -> None:
        header, _, _ = _header_fields(format_leef(_make_alert(rule_name="my-rule")))
        assert header[3] == "my-rule"

    def test_event_id_falls_back_to_alert_type(self) -> None:
        header, _, _ = _header_fields(format_leef(_make_alert(rule_name="", alert_type="sigma")))
        assert header[3] == "sigma"

    def test_single_line(self) -> None:
        line = format_leef(_make_alert(description="multi\nline\rdesc"))
        assert "\n" not in line
        assert "\r" not in line

    def test_returns_str(self) -> None:
        assert isinstance(format_leef(_make_alert()), str)


class TestHeaderEscaping:
    def test_pipe_in_header_is_escaped(self) -> None:
        header, _, _ = _header_fields(format_leef(_make_alert(rule_name="a|b")))
        assert header[3] == "a\\|b"

    def test_backslash_in_header_is_escaped(self) -> None:
        header, _, _ = _header_fields(format_leef(_make_alert(rule_name="a\\b")))
        assert header[3] == "a\\\\b"

    def test_backslash_escaped_before_pipe(self) -> None:
        # ``\|`` must become ``\\\|`` not ``\\|`` (which would read as
        # esc-backslash + bare pipe = field separator).
        header, _, _ = _header_fields(format_leef(_make_alert(rule_name="\\|")))
        assert header[3] == "\\\\\\|"


class TestAttributeEscaping:
    def test_equals_in_value_is_escaped(self) -> None:
        line = format_leef(_make_alert(entity_value="a=b", entity_type="user"))
        assert _attrs(line)["usrName"] == "a=b"

    def test_backslash_in_value_is_escaped(self) -> None:
        line = format_leef(_make_alert(entity_value="a\\b", entity_type="user"))
        assert _attrs(line)["usrName"] == "a\\b"

    def test_newline_in_value_is_escaped(self) -> None:
        line = format_leef(_make_alert(entity_value="a\nb", entity_type="user"))
        assert "\n" not in line
        assert "a\\nb" in line

    def test_cr_in_value_is_escaped(self) -> None:
        line = format_leef(_make_alert(entity_value="a\rb", entity_type="user"))
        assert "\r" not in line
        assert "a\\rb" in line


class TestFieldMapping:
    def test_ip_entity_maps_to_src(self) -> None:
        line = format_leef(_make_alert(entity_value="10.0.0.1", entity_type="ip"))
        assert _attrs(line)["src"] == "10.0.0.1"

    def test_user_entity_maps_to_usrname(self) -> None:
        line = format_leef(_make_alert(entity_value="alice", entity_type="user"))
        assert _attrs(line)["usrName"] == "alice"

    def test_host_entity_maps_to_ident_hostname(self) -> None:
        line = format_leef(_make_alert(entity_value="web01", entity_type="host"))
        assert _attrs(line)["identHostName"] == "web01"

    def test_other_entity_maps_to_cs1_with_label(self) -> None:
        line = format_leef(_make_alert(entity_value="evil.com", entity_type="domain"))
        attrs = _attrs(line)
        assert attrs["cs1"] == "evil.com"
        assert attrs["cs1Label"] == "domain"

    def test_entity_uuid_maps_to_cs2(self) -> None:
        attrs = _attrs(format_leef(_make_alert(entity_uuid="uuid-xyz")))
        assert attrs["cs2"] == "uuid-xyz"
        assert attrs["cs2Label"] == "SeerflowEntityUUID"

    def test_techniques_map_to_cs3(self) -> None:
        attrs = _attrs(format_leef(_make_alert(mitre_techniques=("T1078", "T1110"))))
        assert attrs["cs3"] == "T1078,T1110"
        assert attrs["cs3Label"] == "MitreTechniques"

    def test_tactics_map_to_cs4(self) -> None:
        attrs = _attrs(format_leef(_make_alert(mitre_tactics=("TA0001",))))
        assert attrs["cs4"] == "TA0001"
        assert attrs["cs4Label"] == "MitreTactics"

    def test_risk_score_maps_to_cn1(self) -> None:
        attrs = _attrs(format_leef(_make_alert(risk_score=0.42)))
        assert attrs["cn1"] == "0.42"
        assert attrs["cn1Label"] == "RiskScore"

    def test_alert_type_maps_to_cs5(self) -> None:
        attrs = _attrs(format_leef(_make_alert(alert_type="ioc")))
        assert attrs["cs5"] == "ioc"
        assert attrs["cs5Label"] == "AlertType"

    def test_alert_id_maps_to_external_id(self) -> None:
        attrs = _attrs(format_leef(_make_alert(alert_id="abc-123")))
        assert attrs["externalId"] == "abc-123"

    def test_dedup_count_maps_to_cnt(self) -> None:
        attrs = _attrs(format_leef(_make_alert(dedup_count=7)))
        assert attrs["cnt"] == "7"

    def test_timestamp_maps_to_devtime_in_milliseconds(self) -> None:
        attrs = _attrs(format_leef(_make_alert(timestamp_ns=1_700_000_000_000_000_000)))
        assert attrs["devTime"] == "1700000000000"

    def test_devtime_format_is_epoch_millis(self) -> None:
        attrs = _attrs(format_leef(_make_alert()))
        assert attrs["devTimeFormat"] == "epochMillis"

    def test_coverage_matches_cef(self) -> None:
        # Same field-mapping coverage as CEF: every mapped concept is present.
        attrs = _attrs(
            format_leef(
                _make_alert(
                    entity_value="alice",
                    entity_type="user",
                    mitre_tactics=("TA0006",),
                    mitre_techniques=("T1110",),
                )
            )
        )
        for key in ("devTime", "externalId", "cnt", "cn1", "cs5", "usrName", "cs2", "cs3", "cs4"):
            assert key in attrs


class TestSeverityMapping:
    def test_all_levels_in_leef_range(self) -> None:
        for level in SeverityLevel:
            attrs = _attrs(format_leef(_make_alert(severity_id=level)))
            assert 1 <= int(attrs["sev"]) <= 10

    def test_severity_monotonic(self) -> None:
        sevs = [
            int(_attrs(format_leef(_make_alert(severity_id=lvl)))["sev"]) for lvl in SeverityLevel
        ]
        assert sevs == sorted(sevs)

    def test_trace_low_fatal_ten(self) -> None:
        low = int(_attrs(format_leef(_make_alert(severity_id=SeverityLevel.TRACE)))["sev"])
        high = int(_attrs(format_leef(_make_alert(severity_id=SeverityLevel.FATAL)))["sev"])
        assert low == 1
        assert high == 10


class TestDelimiter:
    def test_default_delimiter_is_tab(self) -> None:
        line = format_leef(_make_alert())
        _, delimiter, _ = _header_fields(line)
        assert delimiter == "\t"

    def test_custom_delimiter_emits_header_field(self) -> None:
        line = format_leef(_make_alert(), delimiter="^")
        header, delimiter, _ = _header_fields(line)
        assert len(header) == 4
        assert delimiter == "^"

    def test_custom_delimiter_separates_attributes(self) -> None:
        line = format_leef(_make_alert(dedup_count=5), delimiter="^")
        assert _attrs(line)["cnt"] == "5"
        # No raw tab present when a custom delimiter is used.
        assert "\t" not in line

    def test_delimiter_in_value_is_escaped(self) -> None:
        line = format_leef(_make_alert(entity_value="a^b", entity_type="user"), delimiter="^")
        assert _attrs(line)["usrName"] == "a^b"

    def test_tab_in_value_is_escaped_for_default(self) -> None:
        line = format_leef(_make_alert(entity_value="a\tb", entity_type="user"))
        # The literal value tab must not split attributes — it is escaped.
        assert _attrs(line)["usrName"] == "a\tb"


class TestGracefulDegradation:
    def test_empty_entity_omits_entity_keys(self) -> None:
        attrs = _attrs(format_leef(_make_alert(entity_value="", entity_type="ip")))
        assert "src" not in attrs

    def test_no_mitre_omits_mitre_keys(self) -> None:
        attrs = _attrs(format_leef(_make_alert(mitre_tactics=(), mitre_techniques=())))
        assert "cs3" not in attrs
        assert "cs4" not in attrs

    def test_empty_uuid_omits_cs2(self) -> None:
        attrs = _attrs(format_leef(_make_alert(entity_uuid="")))
        assert "cs2" not in attrs

    def test_always_present_keys(self) -> None:
        line = format_leef(
            _make_alert(
                entity_value="",
                entity_uuid="",
                rule_name="",
                description="",
                mitre_tactics=(),
                mitre_techniques=(),
            )
        )
        attrs = _attrs(line)
        assert "devTime" in attrs
        assert "devTimeFormat" in attrs
        assert "externalId" in attrs
        assert "cnt" in attrs
        assert "cn1" in attrs


class TestConformanceRoundTrip:
    def test_full_alert_round_trips(self) -> None:
        alert = _make_alert(
            rule_name="brute|force\\rule",
            description="Many failed logins for user=admin",
            entity_value="alice",
            entity_type="user",
            mitre_tactics=("TA0006",),
            mitre_techniques=("T1110",),
            risk_score=0.91,
            dedup_count=3,
        )
        line = format_leef(alert)
        header, delimiter, blob = _header_fields(line)
        # ``_header_fields`` returns header tokens in their on-wire escaped form
        # (it preserves ``\.`` escape pairs); ``|`` -> ``\|`` and ``\`` -> ``\\``.
        assert header == ["Seerflow", "Seerflow", seerflow.__version__, "brute\\|force\\\\rule"]
        attrs = _parse_attributes(blob, delimiter)
        assert attrs["usrName"] == "alice"
        assert attrs["cs3"] == "T1110"
        assert attrs["cs4"] == "TA0006"
        assert attrs["cn1"] == "0.91"
        assert attrs["cnt"] == "3"
        assert attrs["externalId"] == alert.alert_id

    def test_full_alert_round_trips_custom_delimiter(self) -> None:
        alert = _make_alert(entity_value="bob=carol", entity_type="user", dedup_count=4)
        line = format_leef(alert, delimiter="^")
        _header, delimiter, blob = _header_fields(line)
        assert delimiter == "^"
        attrs = _parse_attributes(blob, delimiter)
        assert attrs["usrName"] == "bob=carol"
        assert attrs["cnt"] == "4"


class TestDelimiterValidation:
    """A delimiter must be a single char and must not break the grammar.

    ``|`` collides with the header field separator and CR/LF would split the
    single-line record, so both are rejected with a clear ``ValueError``.
    """

    def test_pipe_delimiter_rejected(self) -> None:
        with pytest.raises(ValueError, match="delimiter"):
            format_leef(_make_alert(), delimiter="|")

    def test_empty_delimiter_rejected(self) -> None:
        with pytest.raises(ValueError, match="delimiter"):
            format_leef(_make_alert(), delimiter="")

    def test_multichar_delimiter_rejected(self) -> None:
        with pytest.raises(ValueError, match="delimiter"):
            format_leef(_make_alert(), delimiter="ab")

    def test_newline_delimiter_rejected(self) -> None:
        with pytest.raises(ValueError, match="delimiter"):
            format_leef(_make_alert(), delimiter="\n")
