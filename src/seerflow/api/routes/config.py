"""GET /api/v1/config -- running configuration with secrets redacted.

Uses an explicit allowlist of secret paths rather than ``repr=False``
introspection. A meta-test in ``tests/unit/test_api_config.py`` asserts
that every field with ``repr=False`` is either allowlisted as public or
redacted by this helper — forcing contributors to update both places
when adding new secrets.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request

from seerflow.alerting.mask import mask_webhook_url
from seerflow.api.limits import limiter, list_limit

if TYPE_CHECKING:
    from seerflow.config import SeerflowConfig

_MASK = "***"

# Keys that must be masked in raw-YAML dict entries (``alerting.webhooks[]``
# passes through as ``tuple[dict[str, Any], ...]`` — the typed dataclass
# walker cannot see inside). Extend this set when adding any new secret
# key to raw-dict config sections.
_RAW_DICT_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "auth_token",
        "api_key",
        "bearer_token",
        "password",
        "secret",
        "token",
    }
)
# Keys in raw-YAML dicts whose value is a URL that may embed credentials.
_RAW_DICT_URL_KEYS: frozenset[str] = frozenset({"url"})


def _scrub_raw_dict(entry: dict[str, Any]) -> None:
    """Mask known-secret keys inside a raw-YAML dict entry in place.

    Recurses into nested dicts and into lists of dicts so secrets embedded
    under nested configuration (e.g. ``custom_headers: {Authorization: "..."}``)
    are masked even if they are declared inside a sub-mapping.
    """
    for key in list(entry.keys()):
        value = entry.get(key)
        if key in _RAW_DICT_URL_KEYS and value:
            entry[key] = mask_webhook_url(value)
        elif key in _RAW_DICT_SECRET_KEYS and value:
            entry[key] = _MASK
        elif isinstance(value, dict):
            _scrub_raw_dict(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _scrub_raw_dict(item)


def redact_config(config: SeerflowConfig) -> dict[str, Any]:
    """Return a dict view of ``config`` with every known secret masked.

    The input ``config`` is never mutated — ``asdict`` returns a fresh
    nested dict structure that we then modify in place before returning.
    Empty secrets (empty strings) are left as-is, not masked to ``***``.
    """
    data = asdict(config)

    # storage
    if data["storage"].get("postgresql_url"):
        data["storage"]["postgresql_url"] = _MASK

    # alerting — typed WebhookTarget list
    if data["alerting"].get("pagerduty_routing_key"):
        data["alerting"]["pagerduty_routing_key"] = _MASK
    for target in data["alerting"].get("webhook_targets", ()):
        if isinstance(target, dict) and target.get("url"):
            target["url"] = mask_webhook_url(target["url"])

    # alerting.webhooks — raw YAML dict passthrough
    for wh in data["alerting"].get("webhooks", ()):
        if isinstance(wh, dict):
            _scrub_raw_dict(wh)

    # receivers.webhooks — typed WebhookEndpointConfig list
    for wh in data["receivers"].get("webhooks", ()):
        if isinstance(wh, dict) and wh.get("auth_token"):
            wh["auth_token"] = _MASK

    # api — redis connection URLs may embed credentials
    if data.get("api_rate_limit_redis_url"):
        data["api_rate_limit_redis_url"] = _MASK

    return data


router = APIRouter(tags=["system"])


@router.get(
    "/config",
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(list_limit)
async def get_config(request: Request) -> dict[str, Any]:
    """Return the running SeerflowConfig with secrets masked.

    Returns 503 if ``app.state.config`` is not set (test mode, or the API
    was constructed without a config — e.g. by a direct ``create_api_app``
    call without a YAML load).
    """
    config = getattr(request.app.state, "config", None)
    if config is None:
        raise HTTPException(status_code=503, detail="config not loaded")
    return redact_config(config)
