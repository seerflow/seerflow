"""Tests for the CEF (ArcSight Common Event Format) alert formatter.

Conformance target — the CEF v0 grammar::

    CEF:0|DeviceVendor|DeviceProduct|DeviceVersion|SignatureID|Name|Severity|Extension

Header escaping: ``\\`` -> ``\\\\``, ``|`` -> ``\\|``.
Extension escaping: ``\\`` -> ``\\\\``, ``=`` -> ``\\=``, newline -> ``\\n``, CR -> ``\\r``.
"""

from __future__ import annotations

import re
import uuid

import seerflow
from seerflow.alerting.formatters import format_cef
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


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


# A header field is any run that is NOT an unescaped pipe. ``[^|\\]`` matches a
# plain char, ``\\.`` matches any escaped pair (``\|``, ``\\``). This is the
# canonical CEF header split: pipes inside fields are backslash-escaped.
_HEADER_FIELD = r"(?:[^|\\]|\\.)*"
_CEF_HEADER_RE = re.compile(
    r"^CEF:0\|"
    + r"\|".join([_HEADER_FIELD] * 6)  # vendor product version sigID name severity
    + r"\|(?P<extension>.*)$",
    re.DOTALL,
)


def _parse_header(line: str) -> list[str]:
    """Split a CEF line into its 8 header tokens (extension is the last)."""
    out: list[str] = []
    field_chars: list[str] = []
    # Skip the ``CEF:0|`` prefix deterministically.
    assert line.startswith("CEF:0|")
    i = len("CEF:0|")
    while i < len(line) and len(out) < 6:
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            field_chars.append(line[i : i + 2])
            i += 2
            continue
        if ch == "|":
            out.append("".join(field_chars))
            field_chars = []
            i += 1
            continue
        field_chars.append(ch)
        i += 1
    out.insert(0, "0")  # version token
    out.append(line[i:])  # remaining is the extension blob
    return out


def _parse_extension(blob: str) -> dict[str, str]:
    """Parse a CEF extension blob into a key->value dict (honours escaping)."""
    pairs: dict[str, str] = {}
    # CEF convention: ``key=value key2=value2`` where a key is a bare token and a
    # value runs up to the next `` key=`` boundary or end-of-string, honouring
    # backslash escaping inside the value.
    for m in re.finditer(r"(\w+)=((?:[^\\]|\\.)*?)(?=(?: \w+=)|$)", blob):
        key, raw = m.group(1), m.group(2)
        val = raw.replace("\\=", "=").replace("\\n", "\n").replace("\\r", "\r")
        val = val.replace("\\\\", "\\")
        pairs[key] = val
    return pairs


class TestHeaderShape:
    def test_starts_with_cef_zero(self) -> None:
        line = format_cef(_make_alert())
        assert line.startswith("CEF:0|")

    def test_has_eight_header_tokens(self) -> None:
        tokens = _parse_header(format_cef(_make_alert()))
        assert len(tokens) == 8

    def test_vendor_product_version_from_constants(self) -> None:
        tokens = _parse_header(format_cef(_make_alert()))
        _, vendor, product, version, *_ = tokens
        assert vendor == "Seerflow"
        assert product == "Seerflow"
        assert version == seerflow.__version__

    def test_signature_id_is_rule_name(self) -> None:
        tokens = _parse_header(format_cef(_make_alert(rule_name="my-rule")))
        assert tokens[4] == "my-rule"

    def test_signature_id_falls_back_to_alert_type(self) -> None:
        tokens = _parse_header(format_cef(_make_alert(rule_name="", alert_type="sigma")))
        assert tokens[4] == "sigma"

    def test_name_is_description(self) -> None:
        tokens = _parse_header(format_cef(_make_alert(description="Brute force")))
        assert tokens[5] == "Brute force"

    def test_single_line(self) -> None:
        line = format_cef(_make_alert(description="multi\nline\rdesc"))
        # The whole record must be one physical line.
        assert "\n" not in line
        assert "\r" not in line


class TestHeaderEscaping:
    def test_pipe_in_header_is_escaped(self) -> None:
        line = format_cef(_make_alert(rule_name="a|b"))
        tokens = _parse_header(line)
        assert tokens[4] == "a\\|b"

    def test_backslash_in_header_is_escaped(self) -> None:
        line = format_cef(_make_alert(rule_name="a\\b"))
        tokens = _parse_header(line)
        assert tokens[4] == "a\\\\b"

    def test_matches_canonical_header_regex(self) -> None:
        line = format_cef(_make_alert(rule_name="a|b\\c", description="x|y"))
        assert _CEF_HEADER_RE.match(line) is not None

    def test_backslash_escaped_before_pipe(self) -> None:
        # ``\|`` must become ``\\\|`` not ``\\|`` (which would read as esc-backslash
        # + bare pipe = field separator).
        line = format_cef(_make_alert(rule_name="\\|"))
        tokens = _parse_header(line)
        assert tokens[4] == "\\\\\\|"


class TestExtensionEscaping:
    def test_equals_in_value_is_escaped(self) -> None:
        line = format_cef(_make_alert(description="ok", entity_value="a=b", entity_type="user"))
        ext = _parse_extension(_parse_header(line)[7])
        assert ext["suser"] == "a=b"

    def test_backslash_in_value_is_escaped(self) -> None:
        line = format_cef(_make_alert(entity_value="a\\b", entity_type="user"))
        ext = _parse_extension(_parse_header(line)[7])
        assert ext["suser"] == "a\\b"

    def test_newline_in_value_is_escaped(self) -> None:
        line = format_cef(_make_alert(entity_value="a\nb", entity_type="user"))
        # The raw line must not contain a literal newline.
        assert "\n" not in line
        assert "a\\nb" in line


class TestFieldMapping:
    def test_ip_entity_maps_to_src(self) -> None:
        ext = _parse_extension(
            _parse_header(format_cef(_make_alert(entity_value="10.0.0.1", entity_type="ip")))[7]
        )
        assert ext["src"] == "10.0.0.1"

    def test_user_entity_maps_to_suser(self) -> None:
        ext = _parse_extension(
            _parse_header(format_cef(_make_alert(entity_value="alice", entity_type="user")))[7]
        )
        assert ext["suser"] == "alice"

    def test_host_entity_maps_to_shost(self) -> None:
        ext = _parse_extension(
            _parse_header(format_cef(_make_alert(entity_value="web01", entity_type="host")))[7]
        )
        assert ext["shost"] == "web01"

    def test_other_entity_maps_to_cs1_with_label(self) -> None:
        ext = _parse_extension(
            _parse_header(format_cef(_make_alert(entity_value="evil.com", entity_type="domain")))[
                7
            ]
        )
        assert ext["cs1"] == "evil.com"
        assert ext["cs1Label"] == "domain"

    def test_entity_uuid_maps_to_cs2(self) -> None:
        ext = _parse_extension(_parse_header(format_cef(_make_alert(entity_uuid="uuid-xyz")))[7])
        assert ext["cs2"] == "uuid-xyz"
        assert ext["cs2Label"] == "SeerflowEntityUUID"

    def test_techniques_map_to_cs3(self) -> None:
        ext = _parse_extension(
            _parse_header(format_cef(_make_alert(mitre_techniques=("T1078", "T1110"))))[7]
        )
        assert ext["cs3"] == "T1078,T1110"
        assert ext["cs3Label"] == "MitreTechniques"

    def test_tactics_map_to_cs4(self) -> None:
        ext = _parse_extension(
            _parse_header(format_cef(_make_alert(mitre_tactics=("TA0001",))))[7]
        )
        assert ext["cs4"] == "TA0001"
        assert ext["cs4Label"] == "MitreTactics"

    def test_risk_score_maps_to_cn1(self) -> None:
        ext = _parse_extension(_parse_header(format_cef(_make_alert(risk_score=0.42)))[7])
        assert ext["cn1"] == "0.42"
        assert ext["cn1Label"] == "RiskScore"

    def test_alert_type_maps_to_cs5(self) -> None:
        ext = _parse_extension(_parse_header(format_cef(_make_alert(alert_type="ioc")))[7])
        assert ext["cs5"] == "ioc"
        assert ext["cs5Label"] == "AlertType"

    def test_alert_id_maps_to_external_id(self) -> None:
        ext = _parse_extension(_parse_header(format_cef(_make_alert(alert_id="abc-123")))[7])
        assert ext["externalId"] == "abc-123"

    def test_dedup_count_maps_to_cnt(self) -> None:
        ext = _parse_extension(_parse_header(format_cef(_make_alert(dedup_count=7)))[7])
        assert ext["cnt"] == "7"

    def test_timestamp_maps_to_rt_in_milliseconds(self) -> None:
        ext = _parse_extension(
            _parse_header(format_cef(_make_alert(timestamp_ns=1_700_000_000_000_000_000)))[7]
        )
        assert ext["rt"] == "1700000000000"


class TestSeverityMapping:
    def test_all_severity_levels_in_cef_range(self) -> None:
        for level in SeverityLevel:
            line = format_cef(_make_alert(severity_id=level))
            sev = _parse_header(line)[6]
            assert 0 <= int(sev) <= 10

    def test_severity_monotonic(self) -> None:
        sevs = [
            int(_parse_header(format_cef(_make_alert(severity_id=lvl)))[6])
            for lvl in SeverityLevel
        ]
        assert sevs == sorted(sevs)

    def test_trace_is_zero_fatal_is_ten(self) -> None:
        low = int(_parse_header(format_cef(_make_alert(severity_id=SeverityLevel.TRACE)))[6])
        high = int(_parse_header(format_cef(_make_alert(severity_id=SeverityLevel.FATAL)))[6])
        assert low == 0
        assert high == 10


class TestGracefulDegradation:
    def test_empty_entity_omits_entity_keys(self) -> None:
        line = format_cef(_make_alert(entity_value="", entity_type="ip"))
        ext = _parse_extension(_parse_header(line)[7])
        assert "src" not in ext

    def test_no_mitre_omits_mitre_keys(self) -> None:
        ext = _parse_extension(
            _parse_header(format_cef(_make_alert(mitre_tactics=(), mitre_techniques=())))[7]
        )
        assert "cs3" not in ext
        assert "cs4" not in ext

    def test_empty_uuid_omits_cs2(self) -> None:
        ext = _parse_extension(_parse_header(format_cef(_make_alert(entity_uuid="")))[7])
        assert "cs2" not in ext

    def test_always_present_keys(self) -> None:
        # Even a maximally-empty alert yields a valid header + core keys.
        line = format_cef(
            _make_alert(
                entity_value="",
                entity_uuid="",
                rule_name="",
                description="",
                mitre_tactics=(),
                mitre_techniques=(),
            )
        )
        assert _CEF_HEADER_RE.match(line) is not None
        ext = _parse_extension(_parse_header(line)[7])
        assert "rt" in ext
        assert "externalId" in ext
        assert "cnt" in ext
        assert "cn1" in ext


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
        line = format_cef(alert)
        m = _CEF_HEADER_RE.match(line)
        assert m is not None
        ext = _parse_extension(m.group("extension"))
        assert ext["suser"] == "alice"
        assert ext["cs3"] == "T1110"
        assert ext["cs4"] == "TA0006"
        assert ext["cn1"] == "0.91"
        assert ext["cnt"] == "3"
        assert ext["externalId"] == alert.alert_id

    def test_returns_str(self) -> None:
        assert isinstance(format_cef(_make_alert()), str)
