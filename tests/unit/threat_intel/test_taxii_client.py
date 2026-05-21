"""Unit tests for TAXIIClient (aiohttp + aioresponses)."""

from __future__ import annotations

import re

import aiohttp
from aioresponses import aioresponses

from seerflow.threat_intel.client import TAXIIClient

ROOT = "https://taxii.example/taxii2/"
COLLECTION_OBJECTS = "https://taxii.example/taxii2/api1/collections/abc/objects/"


async def test_get_objects_yields_indicators_across_pages() -> None:
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:
            m.get(
                COLLECTION_OBJECTS,
                status=200,
                payload={
                    "objects": [
                        {"type": "indicator", "id": "i1", "pattern": "[]"},
                        {"type": "indicator", "id": "i2", "pattern": "[]"},
                    ],
                    "more": True,
                    "next": "page-2",
                },
                headers={"X-TAXII-Date-Added-Last": "2026-04-28T00:00:00.000Z"},
            )
            m.get(
                COLLECTION_OBJECTS + "?next=page-2",
                status=200,
                payload={
                    "objects": [
                        {"type": "indicator", "id": "i3", "pattern": "[]"},
                    ],
                    "more": False,
                },
                headers={"X-TAXII-Date-Added-Last": "2026-04-28T00:01:00.000Z"},
            )

            collected: list[dict] = []
            cursor: str | None = None
            async for sdo, last_added in client.get_objects(COLLECTION_OBJECTS, added_after=None):
                collected.append(sdo)
                cursor = last_added

            assert [s["id"] for s in collected] == ["i1", "i2", "i3"]
            assert cursor == "2026-04-28T00:01:00.000Z"


async def test_get_objects_sends_added_after_param() -> None:
    captured: dict[str, dict] = {}

    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:

            def _cb(url, **kwargs):
                captured["params"] = kwargs.get("params") or {}
                from aioresponses.core import CallbackResult

                return CallbackResult(
                    status=200,
                    payload={"objects": [], "more": False},
                    headers={},
                )

            # Regex match: aiohttp/yarl + aioresponses double-encode ':' in
            # query strings, which breaks literal URL match. We assert on the
            # captured ``params`` kwarg instead — which is the contract.
            m.get(
                re.compile(re.escape(COLLECTION_OBJECTS) + r".*"),
                callback=_cb,
            )
            async for _sdo, _last in client.get_objects(
                COLLECTION_OBJECTS, added_after="2026-04-01T00:00:00.000Z"
            ):
                pass
            assert captured["params"]["added_after"] == "2026-04-01T00:00:00.000Z"


async def test_get_objects_sets_taxii_accept_header() -> None:
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:
            captured: dict[str, dict] = {}

            def _cb(url, **kwargs):
                captured["headers"] = kwargs.get("headers") or {}
                from aioresponses.core import CallbackResult

                return CallbackResult(
                    status=200, payload={"objects": [], "more": False}, headers={}
                )

            m.get(COLLECTION_OBJECTS, callback=_cb)
            async for _ in client.get_objects(COLLECTION_OBJECTS, added_after=None):
                pass
            assert captured["headers"].get("Accept") == "application/taxii+json;version=2.1"


async def test_get_objects_attaches_bearer_auth() -> None:
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(
            session=session,
            auth_header={"Authorization": "Bearer SECRET"},
        )
        with aioresponses() as m:
            captured: dict[str, dict] = {}

            def _cb(url, **kwargs):
                captured["headers"] = kwargs.get("headers") or {}
                from aioresponses.core import CallbackResult

                return CallbackResult(
                    status=200, payload={"objects": [], "more": False}, headers={}
                )

            m.get(COLLECTION_OBJECTS, callback=_cb)
            async for _ in client.get_objects(COLLECTION_OBJECTS, added_after=None):
                pass
            assert captured["headers"]["Authorization"] == "Bearer SECRET"
