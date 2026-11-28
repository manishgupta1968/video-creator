"""Money left with each paid service (read from the services whose API tells it) and spent by this tool."""
import asyncio

import httpx

from video_generator import balances
from video_generator.project import ProjectStore

REPLIES = {
    "api.elevenlabs.io": (200, {"character_count": 12000, "character_limit": 100000, "next_character_count_reset_unix": 1767225600, "tier": "creator"}),
    "api.fal.ai": (200, {"credits": {"current_balance": 24.5, "currency": "USD"}}),
    "api.dev.runwayml.com": (200, {"creditBalance": 5000}),
    "api.heygen.com": (200, {"data": {"remaining_quota": 3600}}),
    "api.lumalabs.ai": (403, {"detail": "forbidden"}),
}


def test_balances_are_read_from_each_service_and_spending_from_the_logs(svc, monkeypatch):
    for k in ("ELEVENLABS_API_KEY", "FAL_KEY", "RUNWAYML_API_SECRET", "HEYGEN_API_KEY", "LUMAAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(k, "x")
    seen = []

    async def get(self, url, headers=None, params=None, **k):
        host = httpx.URL(url).host
        seen.append((host, headers, params))
        code, data = REPLIES[host]
        return httpx.Response(code, json=data, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    p = svc.new_project("a test", seconds=8)
    ProjectStore.ledger_add(p.id, {"kind": "voice", "plugin": "elevenlabs", "catalog_id": "eleven_v3", "actual_usd": 0.12})
    ProjectStore.ledger_add(p.id, {"kind": "video", "plugin": "fal", "actual_usd": 1.5})
    rows = {r["service"]: r for r in asyncio.run(balances.balances(svc.catalog))}
    assert rows["ElevenLabs"]["left"] == "88,000 of 100,000 characters left this period (resets 01 Jan 2026) · plan: creator"
    assert rows["ElevenLabs"]["spent_usd"] == 0.12 and rows["fal.ai"]["spent_usd"] == 1.5
    assert rows["fal.ai"]["left"] == "24.50 USD of credit"
    assert rows["Runway"]["left"] == "5,000 credits" and rows["HeyGen"]["left"] == "60.0 credits"
    assert "may not read the balance" in rows["Luma"]["problem"]
    assert "does not tell the balance" in rows["OpenAI"]["problem"] and rows["OpenAI"]["link"].startswith("https://platform.openai.com")
    assert rows["Cartesia"]["problem"] == "no key"
    assert ("api.fal.ai", {"Authorization": "Key x"}, {"expand": "credits"}) in seen


def test_the_screen_gets_the_balances(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    with TestClient(appmod.app) as c:
        r = c.get("/api/settings/balances").json()
    names = [x["service"] for x in r["services"]]
    assert "ElevenLabs" in names and names[-1].startswith("Claude Code / Codex")
