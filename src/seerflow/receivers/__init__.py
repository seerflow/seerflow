"""Receivers: Protocol, RawEvent, ReceiverManager, and concrete receivers."""

from __future__ import annotations

from seerflow.receivers.base import RawEvent, Receiver
from seerflow.receivers.file_tail import FileTailReceiver
from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.otlp_grpc import OtlpGrpcReceiver
from seerflow.receivers.otlp_http import OtlpHttpReceiver
from seerflow.receivers.syslog import SyslogReceiver
from seerflow.receivers.webhook import WebhookConfig, WebhookReceiver

__all__ = [
    "FileTailReceiver",
    "OtlpGrpcReceiver",
    "OtlpHttpReceiver",
    "RawEvent",
    "Receiver",
    "ReceiverManager",
    "SyslogReceiver",
    "WebhookConfig",
    "WebhookReceiver",
]
