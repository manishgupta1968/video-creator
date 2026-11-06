"""Every model, in plain words: what it costs, what it can do, and why it cannot be used yet.

Also reads a vendor's OWN list of models with your key (free, read-only), so a model that did not exist when the
catalogue was written can still be found and chosen. How to ask each vendor (address, headers, which items are chat
models) is data in `data/vendors.yaml` under `models_list`, not code.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from .catalog import CatalogEntry

# what a catalogue capability means, in words a person reads in a dropdown (generic: any model can have any of them)
ABILITY_WORDS = {
    "start_frame": "starts from a picture", "end_frame": "can end on a picture", "native_audio": "makes its own sound",
    "speech": "speaks the line itself", "clone": "copies a voice", "vision": "sees pictures", "video": "watches whole videos",
    "voice_preview": "has a free sample to listen to", "non_human": "works for animals and objects",
}
MOTION_WORDS = {"face": "moves only the face", "body": "moves the body", "scene": "moves the whole scene"}
UNIT_WORDS = {"second": "per second", "image": "per image", "1k_chars": "per 1,000 characters", "minute": "per minute",
              "request": "per request", "1m_tokens": "per 1M tokens"}


def _n(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".") if x < 1 else f"{x:g}"


def price_text(e: CatalogEntry) -> str:
    if e.is_free:
        return "free"
    if e.price.unit == "1m_tokens":
        return f"${_n(e.price.usd_in)} in / ${_n(e.price.usd_out)} out per 1M tokens"
    return f"${_n(e.unit_price)} {UNIT_WORDS.get(e.price.unit, 'per ' + e.price.unit)}"


def abilities(e: CatalogEntry) -> list[str]:
    caps = e.capabilities or {}
    out = [words for key, words in ABILITY_WORDS.items() if caps.get(key)]
    if caps.get("animates") in MOTION_WORDS:
        out.append(MOTION_WORDS[caps["animates"]])
    if caps.get("max_seconds"):
        out.append(f"clips up to {float(caps['max_seconds']):g} s")
    if caps.get("length") == "follows_audio":
        out.append("as long as the voice")
    return out


def row(e: CatalogEntry, usable: bool, why_not: str, draft_cost: Optional[float] = None) -> dict[str, Any]:
    """One catalogue entry as the screen shows it in a list of choices. Every model is listed, usable or not."""
    d = e.model_dump(exclude={"live_price"})
    d.update({"usable": usable, "why_not": why_not, "price_text": price_text(e), "unit_price": e.unit_price, "is_free": e.is_free,
              "abilities": abilities(e), "days_old": e.days_since_checked(), "price_verified": bool(e.last_checked) and e.days_since_checked() <= 90,
              "source": "catalogue"})
    if draft_cost is not None:
        d["draft_cost_usd"] = round(draft_cost, 3)
    return d


# ------------------------------------------------------------------ the vendor's own list
class ListError(Exception):
    pass


def _dig(data: Any, path: str) -> Any:
    for part in [p for p in (path or "").split(".") if p]:
        data = data.get(part) if isinstance(data, dict) else None
    return data


async def fetch(spec: dict, key: str, client: Optional[httpx.AsyncClient] = None) -> list[dict]:
    """The models one vendor offers this key: [{id, name}]. `spec` is the vendor's `models_list` data. Raises ListError."""
    url = spec["url"].replace("{key}", key)
    headers = {k: str(v).replace("{key}", key) for k, v in (spec.get("headers") or {}).items()}
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise ListError(f"cannot reach the vendor ({exc.__class__.__name__})") from exc
    finally:
        if own:
            await client.aclose()
    if r.status_code in (401, 403):
        raise ListError("the vendor refused the key (check it, or its permissions)")
    if r.status_code >= 400:
        raise ListError(f"the vendor answered with an error ({r.status_code})")
    try:
        items = _dig(r.json(), spec.get("items", "data")) or []
    except ValueError as exc:
        raise ListError("the vendor's answer could not be read") from exc
    inc = re.compile(spec["include"], re.I) if spec.get("include") else None
    exc_ = re.compile(spec["exclude"], re.I) if spec.get("exclude") else None
    need = spec.get("require") or {}
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mid = str(it.get(spec.get("id", "id")) or "")
        if spec.get("strip_prefix") and mid.startswith(spec["strip_prefix"]):
            mid = mid[len(spec["strip_prefix"]):]
        if not mid or (inc and not inc.search(mid)) or (exc_ and exc_.search(mid)):
            continue
        if need and need.get("contains") not in (it.get(need.get("field", "")) or []):
            continue
        out.append({"id": mid, "name": str(it.get(spec.get("name", "")) or mid)})
    return out
