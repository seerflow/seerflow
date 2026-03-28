"""Seerflow processing pipeline for Sigma field name mapping."""

from __future__ import annotations

from sigma.processing.pipeline import ProcessingItem, ProcessingPipeline
from sigma.processing.transformations import FieldMappingTransformation

_FIELD_MAPPING: dict[str | None, str | list[str]] = {
    # Command execution
    "CommandLine": "message",
    "command_line": "message",
    "ParentCommandLine": "message",
    "Image": "message",
    "ParentImage": "message",
    "OriginalFileName": "message",
    # Users
    "User": "related_users",
    "SourceUser": "related_users",
    "TargetUser": "related_users",
    "SubjectUserName": "related_users",
    "TargetUserName": "related_users",
    # IPs
    "SourceIp": "related_ips",
    "DestinationIp": "related_ips",
    "IpAddress": "related_ips",
    "SourceAddress": "related_ips",
    "DestinationAddress": "related_ips",
    # Hosts
    "HostName": "related_hosts",
    "ComputerName": "related_hosts",
    "Workstation": "related_hosts",
    "SourceHostname": "related_hosts",
    "DestinationHostname": "related_hosts",
    # Hashes
    "Hashes": "related_hashes",
    "FileHash": "related_hashes",
    "md5": "related_hashes",
    "sha256": "related_hashes",
    # Event ID
    "EventID": "template_id",
    "EventId": "template_id",
}

# Fields that are tuples on SeerflowEvent and need contains-matching
TUPLE_FIELDS: frozenset[str] = frozenset({
    "related_ips",
    "related_users",
    "related_hosts",
    "related_hashes",
})


def seerflow_pipeline() -> ProcessingPipeline:
    """Create a pySigma processing pipeline that maps Sigma fields to SeerflowEvent attributes."""
    return ProcessingPipeline(
        items=[
            ProcessingItem(
                transformation=FieldMappingTransformation(_FIELD_MAPPING),
                identifier="seerflow_field_mapping",
            ),
        ],
        name="seerflow",
    )
