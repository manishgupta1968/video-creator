"""Nothing outside Generate spends money without asking: the 3D film's real voices, a picture from a paid service, a
voice sample, and Generate typed in the command bar (which now opens the usual cost confirmation instead of starting)."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from video_generator.project import ProjectStore
from video_generator.scene3d import film
from video_generator.tree import find, leaves

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors
from .test_scene3d_change import project


@pytest.fixture
def client(svc, monkeypatch):
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    with TestClient(appmod.app) as c:
        yield c, appmod


def test_the_film_asks_before_making_paid_voices(svc, monkeypatch, client):
    c, appmod = client
    Vendors(svc, monkeypatch)
    p, ids = project(svc, monkeypatch)
    q = svc.load(p.id)
    find(q, ids[0]).script.narration = "shri guru charan saroj raj"
    q.settings.scene3d.film_voice = "service"
    svc.save(q)
    started = []
    monkeypatch.setattr(appmod, "bg", lambda coro, pid, label: (started.append(label), coro.close()))
    r = c.post(f"/api/projects/{p.id}/scene3d/film", json={}).json()
    assert r["needs_confirm"] and "elevenlabs" in r["quote"]["service"] and "clip 1.1" in r["quote"]["what"] and r["quote"]["usd"] > 0
    assert started == []                                                         # nothing started before your OK
    r = c.post(f"/api/projects/{p.id}/scene3d/film", json={"confirm": True}).json()
    assert r["ok"] and "paid" in r["using"] and started == ["Whole 3D film"]
    svc.config.confirm_paid = False                                              # you can switch the question off
    appmod.FILM_RUNS.discard(p.id)
    assert c.post(f"/api/projects/{p.id}/scene3d/film", json={}).json()["ok"]


@requires_ffmpeg
def test_without_your_ok_the_film_uses_the_free_voice_and_says_why(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    p, ids = project(svc, monkeypatch)
    q = svc.load(p.id)
    find(q, ids[0]).script.narration = "shri guru charan saroj raj"
    q.settings.scene3d.film_voice = "service"
    svc.save(q)

    class Free:
        async def synthesize(self, text, voice, out, model=""):
            from video_generator import media
            media.ff("-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(out))
    monkeypatch.setattr(film, "_free_voice", lambda svc_, lang: Free())
    f = asyncio.run(film.make_film(svc, p.id, prepare=True))                      # e.g. from "Ask AI": allow_paid is off
    assert v.calls["voice"] == [] and any("the real voice costs money" in n for n in f.notes)


def test_a_paid_picture_and_a_voice_sample_ask_first(svc, monkeypatch, client):
    c, appmod = client
    Vendors(svc, monkeypatch)
    p, _ = project(svc, monkeypatch)
    dan = next(x for x in svc.load(p.id).context if x.title == "Dan")
    started = []
    monkeypatch.setattr(appmod, "bg", lambda coro, pid, label: (started.append(label), coro.close()))
    r = c.post(f"/api/projects/{p.id}/context/{dan.id}/picture", json={}).json()
    assert r["needs_confirm"] and r["quote"]["what"] == "one picture of Dan" and started == []
    r = c.post(f"/api/projects/{p.id}/context/{dan.id}/picture", json={"confirm": True}).json()
    assert r["ok"] and "paid" in r["using"] and started == ["Picture Dan"]
    r = c.post(f"/api/projects/{p.id}/context/{dan.id}/voice-preview", json={}).json()
    assert r["needs_confirm"] and "voice sample of Dan" in r["quote"]["what"]


def test_generate_in_the_command_bar_opens_the_cost_confirmation_instead_of_starting(svc, monkeypatch, client):
    c, appmod = client
    p, ids = project(svc, monkeypatch)
    from video_generator.brain import CommandPlan
    started = []

    async def start(*a, **k):
        started.append(a)
    monkeypatch.setattr(appmod.engine, "start", start)
    monkeypatch.setattr(appmod.svc, "apply_command", lambda pid, plan: asyncio.sleep(0, result={"generate": "1.1"}))
    plan = CommandPlan(summary="make clip 1.1").model_dump()
    r = c.post(f"/api/projects/{p.id}/command/apply", json={"plan": plan}).json()
    assert started == [] and r["confirm_run"] == {"mode": "clip", "targets": [ids[0]]}
