"""LANL Unified Host and Network Dataset v2 parser, converter, and validator.

Provides tools for loading LANL CSV data, converting it to SeerflowEvent
format, and validating the correlation engine against labeled red-team
ground truth.
"""

from __future__ import annotations

from seerflow.lanl.converter import (
    convert_auth_record,
    convert_flow_record,
    convert_proc_record,
)
from seerflow.lanl.hostmap import host_to_ip
from seerflow.lanl.parser import (
    AuthRecord,
    FlowRecord,
    ProcRecord,
    RedTeamRecord,
    parse_auth_line,
    parse_flow_line,
    parse_proc_line,
    parse_redteam_line,
)
from seerflow.lanl.validator import ValidationResult, run_validation

__all__ = [
    "AuthRecord",
    "FlowRecord",
    "ProcRecord",
    "RedTeamRecord",
    "ValidationResult",
    "convert_auth_record",
    "convert_flow_record",
    "convert_proc_record",
    "host_to_ip",
    "parse_auth_line",
    "parse_flow_line",
    "parse_proc_line",
    "parse_redteam_line",
    "run_validation",
]
