"""Unit tests for LANL dataset CSV parser — AuthRecord, ProcRecord, FlowRecord, RedTeamRecord."""

from __future__ import annotations

import gzip
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.lanl.parser import (
    AuthRecord,
    DnsRecord,
    FlowRecord,
    ProcRecord,
    RedTeamRecord,
    iter_records,
    parse_auth_line,
    parse_dns_line,
    parse_flow_line,
    parse_proc_line,
    parse_redteam_line,
)


class TestParseAuthLine:
    def test_parse_auth_success(self) -> None:
        line = "1,U1@DOM1,U2@DOM2,C1,C2,NTLM,Network,LogOn,Success"
        record = parse_auth_line(line)
        assert isinstance(record, AuthRecord)
        assert record.time == 1
        assert record.src_user == "U1@DOM1"
        assert record.dst_user == "U2@DOM2"
        assert record.src_computer == "C1"
        assert record.dst_computer == "C2"
        assert record.auth_type == "NTLM"
        assert record.logon_type == "Network"
        assert record.auth_orientation == "LogOn"
        assert record.success is True

    def test_parse_auth_failure(self) -> None:
        line = "42,U3@DOM1,U4@DOM2,C3,C4,Kerberos,Interactive,LogOn,Fail"
        record = parse_auth_line(line)
        assert record.time == 42
        assert record.success is False
        assert record.auth_type == "Kerberos"
        assert record.logon_type == "Interactive"

    def test_parse_auth_missing_fields(self) -> None:
        line = "100,?,?,C5,C6,?,?,LogOn,Success"
        record = parse_auth_line(line)
        assert record.time == 100
        assert record.src_user == "?"
        assert record.dst_user == "?"
        assert record.auth_type == "?"
        assert record.logon_type == "?"
        assert record.success is True

    def test_auth_record_is_frozen(self) -> None:
        line = "1,U1@DOM1,U2@DOM2,C1,C2,NTLM,Network,LogOn,Success"
        record = parse_auth_line(line)
        with pytest.raises((AttributeError, TypeError)):
            record.time = 99  # type: ignore[misc]

    def test_auth_record_has_slots(self) -> None:
        assert AuthRecord.__slots__ is not None


class TestParseProcLine:
    def test_parse_proc_start(self) -> None:
        line = "200,U5@DOM1,C7,explorer.exe,Start"
        record = parse_proc_line(line)
        assert isinstance(record, ProcRecord)
        assert record.time == 200
        assert record.user == "U5@DOM1"
        assert record.computer == "C7"
        assert record.process_name == "explorer.exe"
        assert record.start_end == "Start"

    def test_parse_proc_end(self) -> None:
        line = "300,U6@DOM2,C8,cmd.exe,End"
        record = parse_proc_line(line)
        assert record.time == 300
        assert record.process_name == "cmd.exe"
        assert record.start_end == "End"

    def test_proc_record_is_frozen(self) -> None:
        line = "200,U5@DOM1,C7,explorer.exe,Start"
        record = parse_proc_line(line)
        with pytest.raises((AttributeError, TypeError)):
            record.time = 0  # type: ignore[misc]


class TestParseFlowLine:
    def test_parse_flow(self) -> None:
        line = "400,5,C9,1024,C10,443,6,10,1500"
        record = parse_flow_line(line)
        assert isinstance(record, FlowRecord)
        assert record.time == 400
        assert record.duration == 5
        assert record.src_computer == "C9"
        assert record.src_port == 1024
        assert record.dst_computer == "C10"
        assert record.dst_port == 443
        assert record.protocol == 6
        assert record.packet_count == 10
        assert record.byte_count == 1500

    def test_parse_flow_missing_port(self) -> None:
        line = "500,0,C11,?,C12,80,17,1,64"
        record = parse_flow_line(line)
        assert record.src_port == -1

    def test_flow_record_is_frozen(self) -> None:
        line = "400,5,C9,1024,C10,443,6,10,1500"
        record = parse_flow_line(line)
        with pytest.raises((AttributeError, TypeError)):
            record.time = 0  # type: ignore[misc]


class TestParseRedteamLine:
    def test_parse_redteam(self) -> None:
        line = "600,U7@DOM1,C13,C14"
        record = parse_redteam_line(line)
        assert isinstance(record, RedTeamRecord)
        assert record.time == 600
        assert record.user == "U7@DOM1"
        assert record.src_computer == "C13"
        assert record.dst_computer == "C14"

    def test_redteam_record_is_frozen(self) -> None:
        line = "600,U7@DOM1,C13,C14"
        record = parse_redteam_line(line)
        with pytest.raises((AttributeError, TypeError)):
            record.time = 0  # type: ignore[misc]


class TestParseDnsLine:
    """S-315 / FR-081: LANL ``dns.txt`` 3-field schema parser."""

    def test_parse_dns(self) -> None:
        record = parse_dns_line("2,C4653,C5030")
        assert isinstance(record, DnsRecord)
        assert record.time == 2
        assert record.src_computer == "C4653"
        assert record.resolved_computer == "C5030"

    def test_parse_dns_missing_resolved_marker(self) -> None:
        record = parse_dns_line("9,C17693,?")
        assert record.resolved_computer == "?"

    def test_parse_dns_strips_whitespace(self) -> None:
        record = parse_dns_line("  3,C1,C2  \n")
        assert record == DnsRecord(time=3, src_computer="C1", resolved_computer="C2")

    def test_dns_record_is_frozen(self) -> None:
        record = parse_dns_line("2,C4653,C5030")
        with pytest.raises((AttributeError, TypeError)):
            record.time = 0  # type: ignore[misc]

    def test_parse_dns_line_wrong_field_count(self) -> None:
        with pytest.raises(ValueError, match="3 fields"):
            parse_dns_line("2,C4653")

    def test_parse_dns_line_too_many_fields(self) -> None:
        with pytest.raises(ValueError, match="3 fields"):
            parse_dns_line("2,C4653,C5030,extra")


class TestIterRecords:
    def test_iter_records_from_file(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "auth.csv"
        csv_file.write_text(
            "1,U1@DOM1,U2@DOM2,C1,C2,NTLM,Network,LogOn,Success\n"
            "2,U3@DOM1,U4@DOM2,C3,C4,Kerberos,Interactive,LogOn,Fail\n"
        )
        records = list(iter_records(csv_file, "auth"))
        assert len(records) == 2
        assert all(isinstance(r, AuthRecord) for r in records)
        assert records[0].time == 1
        assert records[1].success is False

    def test_iter_records_proc(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "proc.csv"
        csv_file.write_text("100,U1@DOM1,C1,svchost.exe,Start\n200,U2@DOM2,C2,notepad.exe,End\n")
        records = list(iter_records(csv_file, "proc"))
        assert len(records) == 2
        assert all(isinstance(r, ProcRecord) for r in records)

    def test_iter_records_flow(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "flow.csv"
        csv_file.write_text("400,5,C9,1024,C10,443,6,10,1500\n")
        records = list(iter_records(csv_file, "flow"))
        assert len(records) == 1
        assert isinstance(records[0], FlowRecord)

    def test_iter_records_redteam(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "redteam.csv"
        csv_file.write_text("600,U7@DOM1,C13,C14\n")
        records = list(iter_records(csv_file, "redteam"))
        assert len(records) == 1
        assert isinstance(records[0], RedTeamRecord)

    def test_iter_records_dns(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "dns.csv"
        csv_file.write_text("2,C4653,C5030\n3,C17693,?\n")
        records = list(iter_records(csv_file, "dns"))
        assert len(records) == 2
        assert all(isinstance(r, DnsRecord) for r in records)
        assert records[1].resolved_computer == "?"

    def test_iter_records_gz(self, tmp_path: Path) -> None:
        gz_file = tmp_path / "auth.csv.gz"
        content = b"1,U1@DOM1,U2@DOM2,C1,C2,NTLM,Network,LogOn,Success\n"
        with gzip.open(gz_file, "wb") as f:
            f.write(content)
        records = list(iter_records(gz_file, "auth"))
        assert len(records) == 1
        assert isinstance(records[0], AuthRecord)
        assert records[0].time == 1

    def test_iter_records_skips_empty_lines(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "auth.csv"
        csv_file.write_text(
            "1,U1@DOM1,U2@DOM2,C1,C2,NTLM,Network,LogOn,Success\n"
            "\n"
            "2,U3@DOM1,U4@DOM2,C3,C4,Kerberos,Interactive,LogOn,Fail\n"
        )
        records = list(iter_records(csv_file, "auth"))
        assert len(records) == 2

    def test_iter_records_invalid_type(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("1,a,b\n")
        with pytest.raises(ValueError, match="Unknown record_type"):
            list(iter_records(csv_file, "unknown"))

    # --- Field count validation per parse function ---------------------------

    def test_parse_auth_line_wrong_field_count(self) -> None:
        with pytest.raises(ValueError, match="9 fields"):
            parse_auth_line("1,2,3")

    def test_parse_proc_line_wrong_field_count(self) -> None:
        with pytest.raises(ValueError, match="5 fields"):
            parse_proc_line("1,2")

    def test_parse_flow_line_wrong_field_count(self) -> None:
        with pytest.raises(ValueError, match="9 fields"):
            parse_flow_line("1,2,3,4")

    def test_parse_redteam_line_wrong_field_count(self) -> None:
        with pytest.raises(ValueError, match="4 fields"):
            parse_redteam_line("1,2")

    def test_iter_records_is_lazy(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "auth.csv"
        lines = "\n".join(
            f"{i},U1@DOM1,U2@DOM2,C1,C2,NTLM,Network,LogOn,Success" for i in range(1000)
        )
        csv_file.write_text(lines + "\n")
        gen = iter_records(csv_file, "auth")
        first = next(gen)
        assert first.time == 0
