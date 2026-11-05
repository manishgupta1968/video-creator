"""Search for real photos to use as the picture of an animal, object, place or style.

Sources:
- Wikimedia Commons: no key needed; every result carries its licence and author.
- Pexels: optional free key (PEXELS_API_KEY).

Only these hosts are ever downloaded from, with a size limit. Photos of
people are deliberately NOT offered through this route (consent / likeness).
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

UA = "video-generator/0.1 (local desktop app; https://github.com/manishgupta1968/video-creator)"
ALLOWED_HOSTS = {"upload.wikimedia.org", "images.pexels.com"}
MAX_BYTES = 15_000_000


class StockError(RuntimeError):
    pass


@dataclass
class StockPhoto:
    source: str            # wikimedia | pexels
    title: str
    thumb: str             # small preview url
    url: str               # the image we download (about 1280 px wide)
    width: int
    height: int
    author: str
    license: str
    source_url: str        # the photo's own web page


def _strip(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def sources_available() -> list[str]:
    out = ["wikimedia"]
    if os.environ.get("PEXELS_API_KEY"):
        out.append("pexels")
    return out


async def search(query: str, source: str = "wikimedia", limit: int = 24, client: Optional[httpx.AsyncClient] = None) -> list[StockPhoto]:
    query = query.strip()
    if not query:
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, headers={"User-Agent": UA}, follow_redirects=True)
    try:
        if source == "pexels":
            return await _pexels(client, query, limit)
        return await _wikimedia(client, query, limit)
    finally:
        if own:
            await client.aclose()


async def _wikimedia(client: httpx.AsyncClient, query: str, limit: int) -> list[StockPhoto]:
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": str(limit * 2),
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "1280",
    }
    r = await client.get("https://commons.wikimedia.org/w/api.php", params=params, headers={"User-Agent": UA})
    if r.status_code >= 400:
        raise StockError(f"Wikimedia Commons error {r.status_code}")
    pages = (r.json().get("query") or {}).get("pages") or {}
    out: list[StockPhoto] = []
    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if (info.get("width") or 0) < 800:
            continue
        meta = info.get("extmetadata") or {}
        thumb = info.get("thumburl") or info.get("url")
        if not thumb:
            continue
        title = page.get("title", "").removeprefix("File:").rsplit(".", 1)[0]
        out.append(StockPhoto(
            source="wikimedia", title=title, thumb=thumb, url=thumb, width=info.get("thumbwidth") or info["width"],
            height=info.get("thumbheight") or info["height"],
            author=_strip((meta.get("Artist") or {}).get("value", "")) or "unknown",
            license=_strip((meta.get("LicenseShortName") or {}).get("value", "")) or "see source",
            source_url=info.get("descriptionurl") or ""))
        if len(out) >= limit:
            break
    return out


async def _pexels(client: httpx.AsyncClient, query: str, limit: int) -> list[StockPhoto]:
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        raise StockError("Add PEXELS_API_KEY in Settings to search Pexels (free key from pexels.com/api).")
    r = await client.get("https://api.pexels.com/v1/search", params={"query": query, "per_page": str(limit)},
                         headers={"Authorization": key, "User-Agent": UA})
    if r.status_code >= 400:
        raise StockError(f"Pexels error {r.status_code}")
    out = []
    for ph in r.json().get("photos", []):
        src = ph.get("src") or {}
        out.append(StockPhoto(source="pexels", title=ph.get("alt") or f"Photo {ph.get('id')}", thumb=src.get("medium", ""),
                              url=src.get("large2x") or src.get("large") or src.get("original", ""),
                              width=ph.get("width", 0), height=ph.get("height", 0), author=ph.get("photographer", "unknown"),
                              license="Pexels License", source_url=ph.get("url", "")))
    return [p for p in out if p.url]


async def download(url: str, dest_dir: Path, name: str, client: Optional[httpx.AsyncClient] = None) -> Path:
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or host not in ALLOWED_HOSTS:
        raise StockError("That address is not an allowed photo source.")
    own = client is None
    client = client or httpx.AsyncClient(timeout=60, headers={"User-Agent": UA}, follow_redirects=False)
    try:
        async with client.stream("GET", url, headers={"User-Agent": UA}) as r:
            if r.status_code >= 400:
                raise StockError(f"Could not download the photo ({r.status_code}).")
            ctype = r.headers.get("content-type", "")
            if not ctype.startswith("image/"):
                raise StockError("The address did not return an image.")
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(ctype.split(";")[0], ".jpg")
            dest_dir.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name)[:50] or "photo"
            path = dest_dir / f"{safe}{ext}"
            size = 0
            with open(path, "wb") as f:
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        path.unlink(missing_ok=True)
                        raise StockError("The photo is too large.")
                    f.write(chunk)
        return path
    finally:
        if own:
            await client.aclose()


BAD_WORDS = ("map", "diagram", "skeleton", "skull", "drawing", "illustration", "logo", "flag", "coat of arms", "statue",
             "painting", "stamp", "sketch", "cartoon", "toy", "taxidermy", "fossil", "mosaic", "sculpture", "poster", "cub")
GOOD_LICENCE = ("cc0", "public domain", "pd", "cc by", "cc-by", "pexels")


def licence_ok(lic: str) -> bool:
    """We animate and may sell the result: no NonCommercial (NC) or NoDerivatives (ND) licences."""
    l = (lic or "").lower()
    if re.search(r"\bnc\b|\bnd\b|non-?commercial|no-?derivs?", l):
        return False
    return any(g in l for g in GOOD_LICENCE)


def rank(photos: list[StockPhoto], query: str) -> list[StockPhoto]:
    words = [w for w in re.findall(r"[a-z]{3,}", query.lower()) if w not in ("male", "female", "the", "and")]
    scored = []
    for p in photos:
        if not licence_ok(p.license):
            continue
        t = p.title.lower()
        score = 0.0
        score += 2 * sum(1 for w in words if w in t)
        if any(re.search(rf"\b{re.escape(b)}", t) for b in BAD_WORDS):
            continue                      # maps, skeletons, drawings, statues…: not a photo of the real subject
        if p.width >= 1280:
            score += 1
        ratio = (p.width / p.height) if p.height else 0
        if 1.2 <= ratio <= 1.9:
            score += 1
        if p.source == "pexels":
            score += 0.5            # curated, consistent quality
        scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for s, p in scored if s > -1]


def to_dict(p: StockPhoto) -> dict:
    return asdict(p)
