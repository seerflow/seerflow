"""Sidecar I/O for LANL benchmark reports (S-358, slice 3).

The sidecar stores *raw inputs* (accuracy, telemetry, host) — NOT the built
:class:`~seerflow.lanl.report.schema.Report` — so a later re-render can
rebuild comparisons and projections against the current baselines registry.

Public API
----------
ReportInputs                  — frozen envelope struct.
write_report_json(path, ...)  — encode ReportInputs to pretty-printed JSON.
load_report_inputs(path)      — decode ReportInputs from a sidecar JSON file.
"""

from __future__ import annotations

from pathlib import Path

import msgspec

from seerflow.lanl.report.schema import AccuracySummary, HostInfo, RunTelemetry  # noqa: TC001

# ---------------------------------------------------------------------------
# Envelope struct
# ---------------------------------------------------------------------------


class ReportInputs(msgspec.Struct, frozen=True):
    """Frozen envelope for the three raw benchmark inputs.

    Storing only the inputs (not the assembled :class:`Report`) means that
    re-rendering always picks up the latest baselines and projection logic
    without manual migration.

    Fields
    ------
    accuracy:  Accuracy metrics captured during the validation run.
    telemetry: Wall-clock and throughput metrics from the run.
    host:      Hardware / OS metadata for the benchmarked machine.
    """

    accuracy: AccuracySummary
    telemetry: RunTelemetry
    host: HostInfo


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

_ENCODER: msgspec.json.Encoder = msgspec.json.Encoder()
_DECODER: msgspec.json.Decoder[ReportInputs] = msgspec.json.Decoder(ReportInputs)


def write_report_json(
    path: Path,
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
) -> None:
    """Encode *accuracy*, *telemetry*, and *host* to pretty-printed JSON at *path*.

    Parent directories are created automatically (``mkdir -p`` semantics).

    Args:
        path:      Destination file path.
        accuracy:  Accuracy metrics to persist.
        telemetry: Telemetry metrics to persist.
        host:      Host hardware metadata to persist.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = ReportInputs(accuracy=accuracy, telemetry=telemetry, host=host)
    raw = _ENCODER.encode(envelope)
    pretty = msgspec.json.format(raw)
    path.write_bytes(pretty)


def load_report_inputs(path: Path) -> ReportInputs:
    """Decode a :class:`ReportInputs` envelope from the JSON file at *path*.

    Args:
        path: Path to the sidecar JSON file written by :func:`write_report_json`.

    Returns:
        A frozen :class:`ReportInputs` instance.

    Raises:
        FileNotFoundError: If *path* does not exist.
        msgspec.ValidationError: If the file contents do not match the schema.
    """
    return _DECODER.decode(Path(path).read_bytes())
