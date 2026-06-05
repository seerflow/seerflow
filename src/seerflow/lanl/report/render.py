"""Human-readable and JSON renderers for LANL benchmark reports (S-358, slice 3).

Public API
----------
render_table(report)  — plain-text, aligned terminal report.
render_json(report)   — JSON-serialisable dict (round-trips via msgspec).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import msgspec

if TYPE_CHECKING:
    from seerflow.lanl.report.schema import Report

# ---------------------------------------------------------------------------
# Internal formatting helpers
# ---------------------------------------------------------------------------

_COL_W = 28  # label column width


def _fmt_float(value: float, decimals: int = 4) -> str:
    """Format a float with a fixed number of decimal places."""
    return f"{value:.{decimals}f}"


def _humanize_seconds(seconds: float) -> str:
    """Convert seconds to a human-readable string like '5d 2h 30m' or '45m'."""
    total = int(seconds)
    days = total // 86_400
    remainder = total % 86_400
    hours = remainder // 3600
    remainder = remainder % 3600
    minutes = remainder // 60

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _row(label: str, value: object) -> str:
    return f"  {label:<{_COL_W}} {value}"


def _divider(title: str, width: int = 60) -> str:
    pad = max(0, width - len(title) - 4)
    return f"{'─' * 2} {title} {'─' * pad}"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_behavior_section(report: Report) -> list[str]:
    acc = report.accuracy
    lines: list[str] = [
        _divider("Behavior"),
        _row("precision", _fmt_float(acc.precision)),
        _row("recall", _fmt_float(acc.recall)),
        _row("f1", _fmt_float(acc.f1)),
        _row("auc", _fmt_float(acc.auc)),
        _row("false_positive_rate", _fmt_float(acc.false_positive_rate)),
        _row("true_positives", acc.true_positives),
        _row("false_positives", acc.false_positives),
        _row("false_negatives", acc.false_negatives),
        _row("total_alerts", acc.total_alerts),
        "",
        _row("patterns_detected", len(acc.patterns_detected)),
    ]
    for pat in acc.patterns_detected:
        lines.append(f"    · {pat}")

    lines.append("")
    lines.append(f"  {'Scenario':<30} {'Detected':<10} {'MTTD':>12}  {'Missed':>7}")
    lines.append(f"  {'─' * 30} {'─' * 8:<10} {'─' * 12:>12}  {'─' * 6:>7}")
    for sc in acc.scenarios:
        detected_str = "yes" if sc.detected else "no"
        mttd_str = _humanize_seconds(sc.mttd_seconds) if sc.mttd_seconds is not None else "—"
        lines.append(
            f"  {sc.name:<30} {detected_str:<10} {mttd_str:>12}  {sc.missed_record_count:>7}"
        )

    missed_count = len(acc.missed_attributions)
    lines.append("")
    lines.append(_row("missed_attributions (capped)", f"{missed_count} total"))
    return lines


def _render_comparison_section(report: Report) -> list[str]:
    lines: list[str] = [_divider("Comparison vs Baselines")]
    if not report.comparisons:
        lines.append("  no comparable baselines / no attacks in window")
        return lines

    col_metric = 22
    col_sf = 10
    col_bl = 10
    col_src = 28
    col_verdict = 8
    col_delta = 9

    header = (
        f"  {'metric':<{col_metric}} {'seerflow':>{col_sf}} {'baseline':>{col_bl}}"
        f"  {'source':<{col_src}} {'verdict':<{col_verdict}} {'delta':>{col_delta}}"
    )
    sep = (
        f"  {'─' * col_metric} {'─' * col_sf:>{col_sf}} {'─' * col_bl:>{col_bl}}"
        f"  {'─' * col_src:<{col_src}} {'─' * col_verdict:<{col_verdict}} {'─' * col_delta:>{col_delta}}"
    )
    lines += [header, sep]

    for row in report.comparisons:
        sign = "+" if row.delta >= 0 else ""
        delta_str = f"{sign}{row.delta:.4f}"
        lines.append(
            f"  {row.metric:<{col_metric}} {row.seerflow_value:>{col_sf}.4f}"
            f" {row.baseline_value:>{col_bl}.4f}  {row.baseline_name:<{col_src}}"
            f" {row.verdict:<{col_verdict}} {delta_str:>{col_delta}}"
        )
    return lines


def _render_efficiency_section(report: Report) -> list[str]:
    t = report.telemetry
    h = report.host
    mean_latency_ms = t.mean_latency_s * 1000
    lines: list[str] = [
        _divider("Efficiency & Host"),
        _row("throughput_eps", f"{t.throughput_eps:,.2f}"),
        _row("mean_latency_ms", f"{mean_latency_ms:.3f}"),
        _row("peak_rss_mb", f"{t.peak_rss_mb:.1f}" if t.peak_rss_mb is not None else "—"),
        _row("events_processed", f"{t.events_processed:,}"),
        _row("wall_s", f"{t.wall_s:.2f}"),
        "",
        _row("cpu_model", h.cpu_model or "—"),
        _row("physical_cores", h.physical_cores if h.physical_cores is not None else "—"),
        _row("logical_cores", h.logical_cores if h.logical_cores is not None else "—"),
        _row("ram_gb", f"{h.ram_gb:.1f}" if h.ram_gb is not None else "—"),
        _row("platform", h.platform),
    ]
    return lines


def _render_projection_section(report: Report) -> list[str]:
    lines: list[str] = [_divider("Hardware Projections")]
    for proj in report.projections:
        eta_str = _humanize_seconds(proj.eta_seconds) if proj.eta_seconds is not None else "—"
        prefix = "!!" if proj.kind == "caveat" else "  "
        lines.append(f"{prefix} [{proj.kind}] {proj.label}  eta={eta_str}")
        lines.append(f"     note: {proj.note}")
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_table(report: Report) -> str:
    """Render *report* as a human-readable, aligned plain-text terminal report.

    Includes four sections:
    1. Behavior — accuracy metrics and per-scenario MTTD.
    2. Comparison vs Baselines — delta table; fallback when comparisons is empty.
    3. Efficiency & Host — throughput / latency / hardware.
    4. Hardware Projections — ETA and caveat rows (caveat prefixed ``!! ``).

    Args:
        report: A frozen :class:`~seerflow.lanl.report.schema.Report`.

    Returns:
        A multi-line plain-text string suitable for terminal display.
    """
    sections: list[list[str]] = [
        _render_behavior_section(report),
        _render_comparison_section(report),
        _render_efficiency_section(report),
        _render_projection_section(report),
    ]
    all_lines: list[str] = []
    for section in sections:
        all_lines.extend(section)
        all_lines.append("")
    return "\n".join(all_lines)


def render_json(report: Report) -> dict[str, Any]:
    """Render *report* as a JSON-serialisable :class:`dict`.

    Encodes the report to JSON bytes via :func:`msgspec.json.encode`, then
    decodes back to plain Python types (dicts, lists, scalars) so that all
    tuple fields appear as :class:`list` — consistent with the JSON array
    type and compatible with :func:`json.dumps`.

    The returned dict round-trips through :func:`msgspec.json.encode`.

    Args:
        report: A frozen :class:`~seerflow.lanl.report.schema.Report`.

    Returns:
        A :class:`dict` containing the full report, suitable for
        ``json.dumps`` or ``msgspec.json.encode``.
    """
    raw: bytes = msgspec.json.encode(report)
    result: dict[str, Any] = msgspec.json.decode(raw)
    return result
