"""Integration test: OTLP gRPC export with custom CA + mTLS handshake (S-049b).

Generates an ephemeral PKI in ``tmp_path`` (CA + server cert + client cert),
stands up an in-process ``grpc.aio`` ``LogsService`` requiring client auth
against the test CA, and drives ``OtlpSink`` through the full handshake
to verify the new ``tls_ca_file`` / ``mtls_cert_file`` / ``mtls_key_file``
plumbing reaches grpc-python's TLS layer.

The PKI is intentionally minimal — RSA-2048, 24h validity, single SAN —
because the goal is to exercise the seerflow code path, not to validate
cryptographic correctness.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import pathlib

cryptography = pytest.importorskip("cryptography")

import grpc  # noqa: E402
import grpc.aio  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (  # noqa: E402
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2_grpc import (  # noqa: E402
    LogsServiceServicer,
    add_LogsServiceServicer_to_server,
)

from seerflow.alerting.sinks.otlp import OtlpSink  # noqa: E402
from seerflow.models.alert import Alert  # noqa: E402
from seerflow.models.event import SeverityLevel  # noqa: E402

# ---------------------------------------------------------------------------
# PKI helpers
# ---------------------------------------------------------------------------


def _gen_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _build_ca(key: rsa.RSAPrivateKey, common_name: str) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, common_name)])
    now = dt.datetime.now(tz=dt.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(hours=24))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )


def _build_signed_cert(
    *,
    subject_cn: str,
    issuer_cert: x509.Certificate,
    issuer_key: rsa.RSAPrivateKey,
    subject_key: rsa.RSAPrivateKey,
    san: list[x509.GeneralName] | None = None,
) -> x509.Certificate:
    now = dt.datetime.now(tz=dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, subject_cn)]))
        .issuer_name(issuer_cert.subject)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(hours=24))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    return builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())


def _pem_cert(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _pem_key(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


# ---------------------------------------------------------------------------
# Servicer
# ---------------------------------------------------------------------------


class _RecordingLogsService(LogsServiceServicer):  # type: ignore[misc]
    """LogsServiceServicer that records each export call."""

    def __init__(self) -> None:
        self.received: list[ExportLogsServiceRequest] = []

    async def Export(  # noqa: N802 — gRPC method name fixed by .proto
        self,
        request: ExportLogsServiceRequest,
        context: grpc.aio.ServicerContext,
    ) -> ExportLogsServiceResponse:
        self.received.append(request)
        return ExportLogsServiceResponse()


# ---------------------------------------------------------------------------
# Alert helper
# ---------------------------------------------------------------------------


def _make_alert() -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.ERROR,
        rule_name="mtls-integration",
        description="mTLS integration alert",
        entity_uuid="entity-mtls",
        entity_value="10.0.0.1",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.9,
        dedup_key="test:mtls-integration",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOtlpMtlsEndToEnd:
    async def test_mtls_export_full_handshake(self, tmp_path: pathlib.Path) -> None:
        """End-to-end: OtlpSink → secure_channel → mTLS handshake → Export."""
        ca_key = _gen_key()
        ca_cert = _build_ca(ca_key, "seerflow-test-ca")
        ca_pem = _pem_cert(ca_cert)

        server_key = _gen_key()
        server_cert = _build_signed_cert(
            subject_cn="localhost",
            issuer_cert=ca_cert,
            issuer_key=ca_key,
            subject_key=server_key,
            san=[
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ],
        )
        client_key = _gen_key()
        client_cert = _build_signed_cert(
            subject_cn="seerflow-test-client",
            issuer_cert=ca_cert,
            issuer_key=ca_key,
            subject_key=client_key,
        )

        ca_path = tmp_path / "ca.pem"
        ca_path.write_bytes(ca_pem)
        client_cert_path = tmp_path / "client.crt"
        client_cert_path.write_bytes(_pem_cert(client_cert))
        client_key_path = tmp_path / "client.key"
        client_key_path.write_bytes(_pem_key(client_key))

        server_creds = grpc.ssl_server_credentials(
            private_key_certificate_chain_pairs=[
                (_pem_key(server_key), _pem_cert(server_cert)),
            ],
            root_certificates=ca_pem,
            require_client_auth=True,
        )

        servicer = _RecordingLogsService()
        # ``maximum_concurrent_rpcs=1`` keeps the server narrow — we only
        # need one Export() to confirm the handshake reached the application
        # layer. The thread-pool executor is required even for asyncio servers
        # because the underlying C runtime spins worker threads for I/O.
        server = grpc.aio.server(ThreadPoolExecutor(max_workers=2))
        add_LogsServiceServicer_to_server(servicer, server)
        port = server.add_secure_port("127.0.0.1:0", server_creds)
        await server.start()

        try:
            sink = OtlpSink(
                endpoint=f"127.0.0.1:{port}",
                protocol="grpc",
                export_interval=1,
                tls=True,
                tls_ca_file=str(ca_path),
                mtls_cert_file=str(client_cert_path),
                mtls_key_file=str(client_key_path),
            )
            # gRPC SAN verification matches the certificate's SAN against
            # ``grpc.ssl_target_name_override`` when supplied; the channel
            # is created inside _send_grpc on the loopback IP, which our
            # server SAN already covers (DNSName + IPAddress).
            task = asyncio.create_task(sink.run())
            sink.enqueue(_make_alert())
            # Two alert-poll intervals give the flush loop plenty of slack
            # under CI scheduling jitter without bloating wall-clock time.
            await asyncio.sleep(2.5)
            await sink.stop()
            await asyncio.wait_for(task, timeout=5.0)
            await sink.close()
        finally:
            await server.stop(grace=0.5)

        assert len(servicer.received) >= 1
        total = sum(
            len(rl.scope_logs[0].log_records)
            for req in servicer.received
            for rl in req.resource_logs
        )
        assert total >= 1
