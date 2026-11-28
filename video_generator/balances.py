"""How much is left with each paid service, and how much this tool has spent with it.

"Left" is read from the service itself, for the services whose API tells it:
  ElevenLabs  GET https://api.elevenlabs.io/v1/user/subscription          character_limit - character_count, reset time
  fal.ai      GET https://api.fal.ai/v1/account/billing?expand=credits    credits.current_balance (the key may need the
                                                                          permission to read billing)
  Runway      GET https://api.dev.runwayml.com/v1/organization            creditBalance (X-Runway-Version 2024-11-06)
  HeyGen      GET https://api.heygen.com/v2/user/remaining_quota          remaining_quota (60 = one credit)
  Luma        GET https://api.lumalabs.ai/dream-machine/v1/credits        credit_balance
OpenAI, Anthropic and Google do not tell a balance to a normal API key; Cartesia, Kling and Replicate have no balance
API that we know of; Claude Code and Codex subscriptions have usage limits, shown only in their own apps. For those,
the link to the service's own billing page is given.

"Spent by this tool" is added up from every project's spending log (ledger.jsonl), so it is always available.
Reading a balance is free: it only reads.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

SERVICES = [
    # (name, env key, vendor in the catalogue, billing page)
    ("ElevenLabs", "ELEVENLABS_API_KEY", "elevenlabs", "https://elevenlabs.io/app/subscription"),
    ("fal.ai", "FAL_KEY", "fal", "https://fal.ai/dashboard/billing"),
    ("Runway", "RUNWAYML_API_SECRET", "runway", "https://dev.runwayml.com/"),
    ("HeyGen", "HEYGEN_API_KEY", "heygen", "https://app.heygen.com/settings/billing"),
    ("Luma", "LUMAAI_API_KEY", "luma", "https://lumalabs.ai/api/billing"),
    ("OpenAI", "OPENAI_API_KEY", "openai", "https://platform.openai.com/settings/organization/billing/overview"),
    ("Anthropic (Claude API)", "ANTHROPIC_API_KEY", "anthropic", "https://console.anthropic.com/settings/billing"),
    ("Google (Gemini)", "GEMINI_API_KEY", "google", "https://aistudio.google.com/usage"),
    ("Cartesia", "CARTESIA_API_KEY", "cartesia", "https://play.cartesia.ai/subscription"),
    ("Kling", "KLING_ACCESS_KEY", "kling", "https://app.klingai.com/global/dev/account"),
    ("Replicate", "REPLICATE_API_TOKEN", "replicate", "https://replicate.com/account/billing"),
]


def _when(unix) -> str:
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc).strftime("%d %b %Y")
    except (TypeError, ValueError, OSError):
        return ""


async def _get(client: httpx.AsyncClient, url: str, headers: dict, params: Optional[dict] = None) -> dict:
    r = await client.get(url, headers=headers, params=params)
    if r.status_code in (401, 403):
        raise PermissionError("the key was refused, or it may not read the balance (check its permissions)")
    r.raise_for_status()
    return r.json()


async def _left(name: str, key: str, client: httpx.AsyncClient) -> str:
    if name == "ElevenLabs":
        d = await _get(client, "https://api.elevenlabs.io/v1/user/subscription", {"xi-api-key": key})
        used, limit = int(d.get("character_count") or 0), int(d.get("character_limit") or 0)
        reset = _when(d.get("next_character_count_reset_unix"))
        return (f"{max(limit - used, 0):,} of {limit:,} characters left this period" + (f" (resets {reset})" if reset else "")
                + (f" · plan: {d['tier']}" if d.get("tier") else ""))
    if name == "fal.ai":
        d = await _get(client, "https://api.fal.ai/v1/account/billing", {"Authorization": f"Key {key}"}, {"expand": "credits"})
        c = d.get("credits") or {}
        if c.get("current_balance") is None:
            raise ValueError("the balance was not in the reply")
        return f"{float(c['current_balance']):,.2f} {c.get('currency') or 'USD'} of credit"
    if name == "Runway":
        d = await _get(client, "https://api.dev.runwayml.com/v1/organization",
                       {"Authorization": f"Bearer {key}", "X-Runway-Version": "2024-11-06"})
        if d.get("creditBalance") is None:
            raise ValueError("the balance was not in the reply")
        return f"{d['creditBalance']:,} credits"
    if name == "HeyGen":
        d = await _get(client, "https://api.heygen.com/v2/user/remaining_quota", {"X-Api-Key": key})
        q = (d.get("data") or {}).get("remaining_quota")
        if q is None:
            raise ValueError("the quota was not in the reply")
        return f"{float(q) / 60:,.1f} credits"
    if name == "Luma":
        d = await _get(client, "https://api.lumalabs.ai/dream-machine/v1/credits", {"Authorization": f"Bearer {key}"})
        if d.get("credit_balance") is None:
            raise ValueError("the balance was not in the reply")
        return f"{d['credit_balance']:,} credit balance (as Luma reports it)"
    raise NotImplementedError


def spent_by_tool(catalog) -> dict[str, float]:
    """What this tool has spent with each vendor, over every project (from the spending logs)."""
    from .project import ProjectStore
    vendor_of = {}
    for e in catalog.entries:
        vendor_of.setdefault(e.plugin, e.vendor)
        vendor_of.setdefault(e.id, e.vendor)
    out: dict[str, float] = {}
    for pid in [x["id"] for x in ProjectStore.list()]:
        try:
            rows = ProjectStore.ledger(pid)
        except Exception:
            continue
        for r in rows:
            usd = r.get("actual_usd", r.get("estimated_usd")) or 0
            v = vendor_of.get(r.get("catalog_id") or "") or vendor_of.get(r.get("plugin") or "") or r.get("plugin") or "other"
            out[v] = round(out.get(v, 0.0) + float(usd), 4)
    return out


async def balances(catalog) -> list[dict]:
    spent = spent_by_tool(catalog)
    rows = []
    async with httpx.AsyncClient(timeout=20) as client:
        async def one(name, env, vendor, link):
            key = os.environ.get(env, "")
            row = {"service": name, "connected": bool(key), "left": "", "problem": "", "spent_usd": spent.get(vendor, 0.0), "link": link}
            if not key:
                row["problem"] = "no key"
                return row
            try:
                row["left"] = await _left(name, key, client)
            except NotImplementedError:
                row["problem"] = "this service does not tell the balance to the tool; see its billing page"
            except PermissionError as exc:
                row["problem"] = str(exc)
            except Exception as exc:
                row["problem"] = f"could not be read ({str(exc)[:100]})"
            return row
        rows = await asyncio.gather(*(one(*s) for s in SERVICES))
    rows += [{"service": "Claude Code / Codex (your subscriptions)", "connected": True, "left": "", "spent_usd": 0.0,
              "problem": "usage limits, not money: shown only in their own apps (no per-call cost in this tool)",
              "link": ""}]
    return list(rows)
