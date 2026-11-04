"""fal.ai queue client shared by the fal video/image/avatar/lipsync/music plugins.

Docs: https://docs.fal.ai/model-apis/model-endpoints/queue
Model ids live in catalog.yaml so they can be updated without code changes.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from .base import PluginError, data_uri, download, poll, raise_for

QUEUE = "https://queue.fal.run"


def _headers() -> dict:
    key = os.environ.get("FAL_KEY", "")
    if not key:
        raise PluginError("fal: missing FAL_KEY")
    return {"Authorization": f"Key {key}", "Content-Type": "application/json"}


def file_input(path: Path | None) -> str | None:
    """fal accepts base64 data URIs for file inputs."""
    if not path:
        return None
    p = Path(path)
    if p.stat().st_size > 25_000_000:
        raise PluginError(f"{p.name} is too large to send inline (>25 MB)")
    return data_uri(p)


async def run(model: str, payload: dict[str, Any], timeout: float = 1800) -> dict:
    payload = {k: v for k, v in payload.items() if v not in (None, "", [])}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{QUEUE}/{model}", headers=_headers(), json=payload)
        raise_for(r, f"fal {model}")
        sub = r.json()
        status_url = sub.get("status_url") or f"{QUEUE}/{model}/requests/{sub['request_id']}/status"
        response_url = sub.get("response_url") or f"{QUEUE}/{model}/requests/{sub['request_id']}"

        async def fetch():
            s = await client.get(status_url, headers=_headers())
            raise_for(s, "fal status")
            return s.json()

        def done(d):
            st = d.get("status")
            if st == "COMPLETED":
                return False if d.get("error") else True
            if st in ("FAILED", "ERROR", "CANCELLED"):
                return False
            return None

        await poll(fetch, done, interval=4, timeout=timeout)
        out = await client.get(response_url, headers=_headers())
        raise_for(out, "fal result")
        return out.json()


def first_url(result: dict, *keys: str) -> str:
    for k in keys:
        v = result.get(k)
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
        if isinstance(v, list) and v and isinstance(v[0], dict) and v[0].get("url"):
            return v[0]["url"]
        if isinstance(v, str) and v.startswith("http"):
            return v
    raise PluginError(f"fal: no output file in result: {str(result)[:300]}")


async def save(result: dict, out: Path, *keys: str) -> Path:
    return await download(first_url(result, *keys), out)
