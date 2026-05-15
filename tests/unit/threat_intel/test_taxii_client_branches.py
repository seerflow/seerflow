"""Branch coverage tests for TAXIIClient (S-067).

Targets the missing branches identified in coverage:
- ``discover()`` happy path and non-200 path.
- ``get_objects`` 304-Not-Modified short-circuit.
- ``get_objects`` non-200/non-304 raises GetWithRetryError.
- ``get_objects`` non-dict body raises GetWithRetryError.
- ``get_objects`` ``more=True`` but missing ``next`` returns cleanly.
"""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from seerflow.threat_intel.client import TAXIIClient
from seerflow.utils.http import GetWithRetryError

ROOT = "https://taxii.example/taxii2/"
OBJECTS = "https://taxii.example/taxii2/api1/collections/abc/objects/"


async def test_discover_returns_payload_on_200() -> None:
    payload = {"title": "Test", "api_roots": ["https://taxii.example/taxii2/api1/"]}
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:
            m.get(ROOT, status=200, payload=payload)
            result = await client.discover(ROOT)
            assert result == payload


async def test_discover_raises_on_non_200() -> None:
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:
            m.get(ROOT, status=404, payload={})
            with pytest.raises(GetWithRetryError, match="404"):
                await client.discover(ROOT)


async def test_get_objects_returns_silently_on_304() -> None:
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:
            m.get(OBJECTS, status=304, body="")
            collected = [sdo async for sdo, _ in client.get_objects(OBJECTS, added_after=None)]
            assert collected == []


async def test_get_objects_raises_on_non_200_non_304() -> None:
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:
            m.get(OBJECTS, status=404, payload={})
            with pytest.raises(GetWithRetryError, match="404"):
                async for _ in client.get_objects(OBJECTS, added_after=None):
                    pass  # pragma: no cover


async def test_get_objects_raises_on_non_dict_body() -> None:
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:
            # JSON list (not dict) -> non-dict body branch.
            m.get(OBJECTS, status=200, payload=["not-a-dict"])
            with pytest.raises(GetWithRetryError, match="non-json body"):
                async for _ in client.get_objects(OBJECTS, added_after=None):
                    pass  # pragma: no cover


async def test_get_objects_returns_when_more_true_but_no_next_token() -> None:
    async with aiohttp.ClientSession() as session:
        client = TAXIIClient(session=session)
        with aioresponses() as m:
            m.get(
                OBJECTS,
                status=200,
                payload={
                    "objects": [{"type": "indicator", "id": "i1", "pattern": "[]"}],
                    "more": True,
                    # Intentionally no "next" key.
                },
                headers={"X-TAXII-Date-Added-Last": "2026-04-28T00:00:00.000Z"},
            )
            collected = [sdo async for sdo, _ in client.get_objects(OBJECTS, added_after=None)]
            assert [s["id"] for s in collected] == ["i1"]
