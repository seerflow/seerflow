"""Tests for the alerts REST route."""

from __future__ import annotations


def test_list_alerts_severity_param_uses_shared_bounds() -> None:
    """list_alerts severity query constraints must reference the shared
    SEVERITY_MIN/SEVERITY_MAX constants from models.event, not literals."""
    from fastapi.routing import APIRoute

    from seerflow.api.routes.alerts import router
    from seerflow.models.event import SEVERITY_MAX, SEVERITY_MIN

    route = next(r for r in router.routes if isinstance(r, APIRoute) and r.path == "/alerts")
    severity_param = next(p for p in route.dependant.query_params if p.name == "severity")
    assert severity_param.field_info.metadata is not None
    ge_values = [m.ge for m in severity_param.field_info.metadata if hasattr(m, "ge")]
    le_values = [m.le for m in severity_param.field_info.metadata if hasattr(m, "le")]
    assert SEVERITY_MIN in ge_values
    assert SEVERITY_MAX in le_values
