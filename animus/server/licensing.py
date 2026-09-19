"""Datano product-license gate for Animus peers.

The existing HMAC proves possession of the Hub secret.  This gate adds the
operator-controlled entitlement for the authenticated ``node_id``.  A short
cache makes status changes responsive, while the last successful grant can be
used during a bounded control-plane outage.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from fastapi import HTTPException

_cache: dict[str, tuple[float, float, dict[str, Any]]] = {}


def _settings() -> tuple[str, str, int, int]:
    url = os.environ.get("ANIMUS_LICENSE_API_URL", "").rstrip("/")
    secret = os.environ.get("ANIMUS_LICENSE_API_SECRET", "").strip()
    ttl = max(5, int(os.environ.get("ANIMUS_LICENSE_CACHE_SECONDS", "60")))
    grace = max(0, int(os.environ.get("ANIMUS_LICENSE_OFFLINE_GRACE_SECONDS", "86400")))
    return url, secret, ttl, grace


def clear_license_cache() -> None:
    _cache.clear()


async def require_peer_license(
    node_id: str,
    *,
    node_name: str = "",
    hostname: str = "",
    client_version: str = "",
) -> dict[str, Any]:
    url, secret, ttl, grace = _settings()
    if not url or not secret:
        return {"allowed": True, "status": "unmanaged", "subject_id": node_id}

    now = time.monotonic()
    cached = _cache.get(node_id)
    if cached and cached[0] > now:
        result = cached[2]
        if not result.get("allowed"):
            raise HTTPException(status_code=403, detail="Animus license is not active")
        return result

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{url}/api/v1/products/animus/check",
                headers={"Authorization": f"Bearer {secret}", "X-Datano-Actor": "animus-hub"},
                json={
                    "node_id": node_id,
                    "node_name": node_name or None,
                    "hostname": hostname or None,
                    "client_version": client_version or None,
                },
            )
        response.raise_for_status()
        result = response.json()
        _cache[node_id] = (now + ttl, now, result)
    except (httpx.HTTPError, ValueError) as exc:
        if cached and cached[2].get("allowed") and now - cached[1] <= grace:
            return {**cached[2], "offline": True}
        raise HTTPException(status_code=503, detail="License control plane unavailable") from exc

    if not result.get("allowed"):
        raise HTTPException(status_code=403, detail="Animus license is not active")
    return result
