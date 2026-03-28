"""Tests for the Seerflow Sigma processing pipeline."""

from __future__ import annotations

from sigma.rule import SigmaRule

from seerflow.sigma.pipeline import seerflow_pipeline


class TestSeerflowPipeline:
    def test_commandline_maps_to_message(self) -> None:
        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: process_creation
            detection:
                sel:
                    CommandLine|contains: whoami
                condition: sel
            level: medium
        """)
        seerflow_pipeline().apply(rule)
        item = rule.detection.detections["sel"].detection_items[0]
        assert item.field == "message"

    def test_user_maps_to_related_users(self) -> None:
        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    User: root
                condition: sel
            level: medium
        """)
        seerflow_pipeline().apply(rule)
        item = rule.detection.detections["sel"].detection_items[0]
        assert item.field == "related_users"

    def test_sourceip_maps_to_related_ips(self) -> None:
        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    SourceIp: 10.0.0.1
                condition: sel
            level: medium
        """)
        seerflow_pipeline().apply(rule)
        item = rule.detection.detections["sel"].detection_items[0]
        assert item.field == "related_ips"

    def test_hostname_maps_to_related_hosts(self) -> None:
        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    HostName: server01
                condition: sel
            level: medium
        """)
        seerflow_pipeline().apply(rule)
        item = rule.detection.detections["sel"].detection_items[0]
        assert item.field == "related_hosts"

    def test_unmapped_field_stays_as_is(self) -> None:
        rule = SigmaRule.from_yaml("""
            title: Test
            status: test
            logsource:
                category: test
            detection:
                sel:
                    SomeCustomField: value
                condition: sel
            level: medium
        """)
        seerflow_pipeline().apply(rule)
        item = rule.detection.detections["sel"].detection_items[0]
        assert item.field == "SomeCustomField"
