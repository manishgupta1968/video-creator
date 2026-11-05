"""fal.ai queue client shared by the fal video/image/avatar/lipsync/music plugins.

Docs: https://docs.fal.ai/model-apis/model-endpoints/queue
Model ids live in catalog.yaml so they can be updated without code changes.

Two rules from fal's docs that matter here:
- The job is SUBMITTED to the full model id (queue.fal.run/<owner>/<app>/<path>).
- Status / result / cancel use ONLY owner/app (queue.fal.run/<owner>/<app>/requests/<id>), never the path.
  We use the status_url / response_url that fal returns, and only build one ourselves (owner/app only) if it is missing.
"""
from __future__ import annotations

import os
import re
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


def app_id(model: str) -> str:
    """owner/app of a model id: 'wan/v2.6/image-to-video' -> 'wan/v2.6'; 'fal-ai/flux/dev' -> 'fal-ai/flux'."""
    parts = [p for p in model.strip("/").split("/") if p]
    return "/".join(parts[:2]) if len(parts) >= 2 else model


def file_input(path: Path | None) -> str | None:
    """fal accepts base64 data URIs for file inputs."""
    if not path:
        return None
    p = Path(path)
    if p.stat().st_size > 25_000_000:
        raise PluginError(f"{p.name} is too large to send inline (>25 MB)")
    return data_uri(p)


def _no_such_model(model: str, r: httpx.Response) -> PluginError | None:
    """fal accepts a job for any path under an app, then answers 404 'Path /x not found' when it looks for the model."""
    if r.status_code == 404 and re.search(r"\bpath\b.*not found", r.text or "", re.I):
        return PluginError(f"fal.ai has no model called '{model}' (it answered: {' '.join((r.text or '').split())[:120]}). "
                           "The model name in catalog.yaml is out of date. Nothing was charged.", retry_other_model=True)
    return None


async def run(model: str, payload: dict[str, Any], timeout: float = 1800) -> dict:
    payload = {k: v for k, v in payload.items() if v not in (None, "", [])}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{QUEUE}/{model}", headers=_headers(), json=payload)
        raise_for(r, f"fal {model}")
        sub = r.json()
        rid = sub.get("request_id", "")
        base = f"{QUEUE}/{app_id(model)}/requests/{rid}"
        status_urls = [u for u in (sub.get("status_url"), f"{base}/status") if u]
        response_urls = [u for u in (sub.get("response_url"), base) if u]

        async def first_ok(urls: list[str], who: str) -> httpx.Response:
            last = None
            for u in dict.fromkeys(urls):                    # the URL fal gave us first, then the owner/app-only one
                resp = await client.get(u, headers=_headers())
                if resp.status_code < 400:
                    return resp
                bad = _no_such_model(model, resp)
                if bad:
                    raise bad
                last = resp
                if resp.status_code != 404:
                    break
            raise PluginError(f"{who}: HTTP {last.status_code}: {last.text[:500]}",
                              retry_other_model=last.status_code in (400, 422))

        async def fetch():
            return (await first_ok(status_urls, "fal status")).json()

        def done(d):
            st = d.get("status")
            if st == "COMPLETED":
                return False if d.get("error") else True
            if st in ("FAILED", "ERROR", "CANCELLED"):
                return False
            return None

        await poll(fetch, done, interval=4, timeout=timeout)
        return (await first_ok(response_urls, "fal result")).json()


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
