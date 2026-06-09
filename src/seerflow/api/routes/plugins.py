"""GET /api/v1/plugins — loaded-plugin inventory (S-370 AC-4).

Exposes the observable inventory of entry-point plugins discovered + validated
by :func:`seerflow.plugins.load_plugins`: each row carries the namespaced
``id`` (``group:name``), the declared ``version``, the public ``protocol`` the
plugin satisfies, and its lifecycle ``status`` (``loaded`` / ``started`` /
``stopped`` / ``failed``).

Read-only and side-effect free: the route serialises an immutable inventory
snapshot held on ``app.state.plugins``. When no plugins are wired (test mode /
plugins disabled) it returns an empty list — never a 500.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Request

from seerflow.api.deps import get_plugin_inventory
from seerflow.api.limits import limiter, list_limit
from seerflow.api.schemas import PluginInfo, PluginInventoryResponse

if TYPE_CHECKING:
    from seerflow.plugins.lifecycle import PluginInventory

router = APIRouter(tags=["system"])

PluginInventoryDep = Annotated["PluginInventory", Depends(get_plugin_inventory)]


@router.get(
    "/plugins",
    response_model=PluginInventoryResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(list_limit)
async def list_plugins(
    request: Request,
    inventory: PluginInventoryDep,
) -> PluginInventoryResponse:
    """Return the inventory of all loaded plugins."""
    rows = [
        PluginInfo(
            id=entry.id,
            version=entry.version,
            protocol=entry.protocol,
            status=entry.status.value,
        )
        for entry in inventory.entries()
    ]
    return PluginInventoryResponse(plugins=rows, total=len(rows))
