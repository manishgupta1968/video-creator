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
ALLOWED_DOMAINS = ("wikimedia.org", "pexels.com")          # the site itself or any of its sub-sites, over https only
ALLOWED_HOSTS = {"upload.wikimedia.org", "images.pexels.com"}   # the ones we normally see (kept for reference)
MAX_BYTES = 15_000_000
MAX_REDIRECTS = 3


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


def host_allowed(host: str) -> bool:
    """True for wikimedia.org / pexels.com and their sub-sites (upload.wikimedia.org, images.pexels.com ...).
    'notwikimedia.org' and 'wikimedia.org.evil.example' do NOT match: a sub-site needs the dot in front."""
    host = (host or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def clean_url(url: str) -> str:
    """Tidy an address that came from a search result: trim spaces, add https to '//host/path',
    and upgrade http to https (only for allowed sites; any other address is returned unchanged so it is refused)."""
    url = (url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    parts = urlparse(url)
    if parts.scheme == "http" and host_allowed(parts.hostname or ""):
        url = "https:" + url[len("http:"):]
    return url


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
        thumb = clean_url(info.get("thumburl") or info.get("url") or "")
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
        out.append(StockPhoto(source="pexels", title=ph.get("alt") or f"Photo {ph.get('id')}", thumb=clean_url(src.get("medium", "")),
                              url=clean_url(src.get("large2x") or src.get("large") or src.get("original", "")),
                              width=ph.get("width", 0), height=ph.get("height", 0), author=ph.get("photographer", "unknown"),
                              license="Pexels License", source_url=ph.get("url", "")))
    return [p for p in out if p.url]


def _check(url: str) -> str:
    """Refuse anything that is not https on an allowed site. The message names the host so a problem can be diagnosed."""
    url = clean_url(url)
    parts = urlparse(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not host_allowed(host):
        where = f"host: {host}" if host else "no web address"
        raise StockError(f"That address is not an allowed photo source ({where}).")
    return url


async def download(url: str, dest_dir: Path, name: str, client: Optional[httpx.AsyncClient] = None) -> Path:
    url = _check(url)
    own = client is None
    client = client or httpx.AsyncClient(timeout=60, headers={"User-Agent": UA}, follow_redirects=False)
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", url, headers={"User-Agent": UA}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = _check(str(httpx.URL(url).join(r.headers["location"])))     # every hop must be an allowed site too
                    continue
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
        raise StockError("The address redirected too many times.")
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


async def diagnose(query: str, dest_dir: Path, client: Optional[httpx.AsyncClient] = None,
                   download_client: Optional[httpx.AsyncClient] = None) -> tuple[list[str], Optional[Path]]:
    """Run the whole photo search step by step and describe each step in plain words.
    Used by `vg photo-test` so a problem on one computer can be understood in one command."""
    lines: list[str] = []
    saved: Optional[Path] = None
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=30, headers={"User-Agent": UA}, follow_redirects=True)
    try:
        found: list[StockPhoto] = []
        search_failed = False
        for source in sources_available():
            try:
                got = await search(query, source, limit=12, client=client)
                lines.append(f"1. Search on {source} for “{query}”: {len(got)} photo(s) came back.")
                found += got
            except Exception as exc:
                search_failed = True
                lines.append(f"1. Search on {source} FAILED: {exc}")
        if search_failed and not found:
            lines.append("The search itself could not run, so this computer cannot reach the photo site "
                         "(internet, VPN, firewall or proxy). The message above says why.")
            return lines, None
        kept = rank(found, query)
        lines.append(f"2. After removing maps, drawings, skeletons and photos with a NonCommercial/NoDerivatives licence: {len(kept)} left.")
        for p in found:
            if p not in kept:
                lines.append(f"     removed: “{p.title}” ({p.license})")
        if not kept:
            lines.append("   Nothing left to download. Try other words, for example: vg photo-test \"red fox in winter\".")
        for i, p in enumerate(kept[:4], 1):
            host = urlparse(p.url).hostname or "(none)"
            lines.append(f"3.{i} “{p.title}” by {p.author} ({p.license}); address host: {host}; allowed: {'yes' if host_allowed(host) and p.url.startswith('https://') else 'NO'}")
            if saved is None:
                try:
                    saved = await download(p.url, dest_dir, p.title, client=download_client)
                    lines.append(f"     downloaded OK → {saved}")
                except Exception as exc:
                    lines.append(f"     download FAILED: {exc}")
        if kept and saved is None:
            lines.append("None of the photos could be downloaded. Please copy this whole output and send it to your assistant.")
    finally:
        if own:
            await client.aclose()
    return lines, saved
