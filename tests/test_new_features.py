"""Round 2: preview warnings, talking animals, stock photos, voice recording, final-video state,
length fitting, hand-off rule, live activity."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from video_generator import estimate as E
from video_generator import media, stock
from video_generator.models import (ActorDetails, ActorInShot, ClipScript, ContextItem, ContextType, DialogueLine,
                                    Dependency, Node, NodeKind, NodeStatus, Project, ShotType, Take)
from video_generator.project import ProjectStore
from video_generator.tree import add_child, leaves

from .conftest import requires_ffmpeg

ALL_KEYS = ("FAL_KEY", "ELEVENLABS_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")


def lion_project(svc, mode="balanced"):
    p = svc.new_project("Add a lion that speaks says hello how are you", seconds=15, quality_mode=mode)
    lion = ContextItem(type=ContextType.actor, title="Kito", actor=ActorDetails(
        kind="animal", description="adult male African lion, full mane", voice_description="deep, warm, growly"))
    p.context.append(lion)
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Greeting", goal="greeting"))
    clip = add_child(p, part.id, Node(kind=NodeKind.clip, title="Speaking close-up", goal="Kito says hello", target_seconds=5))
    clip.script = ClipScript(shot_type=ShotType.talking_head, visual="close-up of Kito", on_camera_speech=True,
                             actors_in_shot=[ActorInShot(actor_id=lion.id)],
                             dialogue=[DialogueLine(speaker=lion.id, text="hello how are you")])
    svc.save(p)
    return svc.load(p.id), lion, clip


# ------------------------------------------------------------------ preview warnings
def test_preview_flags_and_hints_without_and_with_keys(svc, monkeypatch):
    p, lion, clip = lion_project(svc)
    info = svc.summary(p)["preview"]
    assert info["all_preview"] and clip.id in info["clips"]
    assert {"avatar", "image", "voice"} <= set(info["jobs"])
    assert "FAL_KEY" in info["jobs"]["avatar"]
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    svc.reload()
    info = svc.summary(svc.load(p.id))["preview"]
    assert not info["all_preview"] and info["clips"] == {}


# ------------------------------------------------------------------ talking animal routing
def test_talking_animal_uses_non_human_avatar_model(svc, monkeypatch):
    p, lion, clip = lion_project(svc)
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    svc.reload()
    plan = E.plan_clip(p, clip, svc.reg)
    assert plan.route == "avatar" and plan.video.id == "kling_avatar"
    assert plan.voice.capabilities.get("clone") or plan.voice.plugin in ("elevenlabs", "cartesia")


def test_person_only_avatar_does_not_get_an_animal(svc, monkeypatch):
    p, lion, clip = lion_project(svc)
    monkeypatch.setenv("HEYGEN_API_KEY", "x")          # human-only avatar service
    monkeypatch.setenv("GEMINI_API_KEY", "x")          # real video model available
    svc.reload()
    plan = E.plan_clip(p, clip, svc.reg)
    assert plan.route == "video" and plan.video.plugin == "veo"
    assert plan.lipsync_needed


def test_presenter_prefers_real_video_over_free_avatar(svc, monkeypatch):
    p, lion, clip = lion_project(svc)
    lion.actor.kind = "ai_person"
    svc.save(p)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    svc.reload()
    plan = E.plan_clip(svc.load(p.id), clip, svc.reg)
    assert plan.route == "video"


def test_voice_sample_without_cloning_service_warns(svc, monkeypatch, sample_voice):
    p, lion, clip = lion_project(svc)
    svc.add_context_file(p, sample_voice, ctx_id=lion.id, save=False)
    svc.save(p)
    p = svc.load(p.id)
    plan = E.plan_clip(p, clip, svc.reg)
    assert any("voice sample" in w for w in plan.warnings)
    assert svc.summary(p)["preview"]["voice_sample_unused"]
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    svc.reload()
    plan = E.plan_clip(svc.load(p.id), clip, svc.reg)
    assert plan.voice.plugin == "elevenlabs" and not any("voice sample" in w for w in plan.warnings)


@requires_ffmpeg
def test_talking_lion_free_preview_end_to_end(svc):
    from video_generator.runner import Engine
    p, lion, clip = lion_project(svc, mode="free")
    eng = Engine(svc, stop_when_waiting=True)

    async def go():
        await eng.start(p.id, "clip", [clip.id], auto_pick=True)
        seen = set()
        while not eng.runs[p.id].task.done():
            for a in eng.status(p.id)["activity"]:
                seen.add(a["step"])
            await asyncio.sleep(0.03)
        return seen
    seen = asyncio.run(go())
    p = svc.load(p.id)
    n = next(l for l in leaves(p) if l.id == clip.id)
    assert n.status == NodeStatus.done and n.takes[0].model == "free_avatar"
    assert next(c for c in p.context if c.id == lion.id).actor.reference_sheet     # a picture was made first
    assert seen and any("voice" in x.lower() or "take" in x.lower() or "actors" in x.lower() for x in seen)
    assert eng.status(p.id)["activity"] == []                                      # indicator clears at the end


@requires_ffmpeg
def test_animal_photo_is_used_exactly_not_regenerated(svc, sample_photo, monkeypatch):
    from video_generator.runner import Engine
    monkeypatch.setenv("FAL_KEY", "x")           # a paid image model is "available"; it must NOT be called
    svc.reload()
    p, lion, clip = lion_project(svc)
    svc.add_context_file(p, sample_photo, ctx_id=lion.id, save=False)
    svc.save(p)
    eng = Engine(svc)
    entry = svc.catalog.get("flux_2")
    asyncio.run(eng._reference_sheet(p.id, lion.id, entry))
    sheet = next(c for c in svc.load(p.id).context if c.id == lion.id).actor.reference_sheet[0]
    assert sheet.endswith(".jpg") and (ProjectStore.path_for(p.id) / sheet).exists()


# ------------------------------------------------------------------ length fits the target
def test_draft_lengths_scale_to_target(svc):
    p = svc.new_project("short", seconds=15)
    for i in range(3):
        add_child(p, p.root.id, Node(kind=NodeKind.clip, title=f"c{i}", goal="g", target_seconds=10))
    svc._fit_to_target(p)
    secs = [c.target_seconds for c in p.root.children]
    assert secs == [5.0, 5.0, 5.0]
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="part", goal="g"))
    for _ in range(2):
        add_child(p, part.id, Node(kind=NodeKind.clip, title="x", goal="g", target_seconds=2))
    p.settings.target_seconds = 40
    svc._fit_to_target(p)
    assert part.target_seconds == sum(c.target_seconds for c in part.children)


# ------------------------------------------------------------------ final video state
def test_final_ready_and_stale(svc, tmp_path):
    p = svc.new_project("goal", seconds=10)
    clip = add_child(p, p.root.id, Node(kind=NodeKind.clip, title="c", goal="g", status=NodeStatus.done))
    base = ProjectStore.path_for(p.id)
    (base / "clips" / clip.id).mkdir(parents=True)
    (base / "clips" / clip.id / "out.mp4").write_bytes(b"one")
    clip.output = f"clips/{clip.id}/out.mp4"
    (base / "output" / "final.mp4").write_bytes(b"final")
    p.final_output = "output/final.mp4"
    p.final_hash = ProjectStore.final_signature(p)
    svc.save(p)
    info = svc.final_info(svc.load(p.id))
    assert info["final_ready"] and not info["final_stale"] and info["all_clips_done"]
    (base / "clips" / clip.id / "out.mp4").write_bytes(b"remade clip, different")
    assert svc.final_info(svc.load(p.id))["final_stale"]
    p = svc.load(p.id)
    p.final_hash = ""                       # projects made before this feature: assume up to date
    assert not svc.final_info(p)["final_stale"]


# ------------------------------------------------------------------ hand-off & activity & credits
def test_handoff_skips_free_preview_frames(svc):
    from video_generator.runner import Engine
    p = svc.new_project("g", seconds=10)
    a = add_child(p, p.root.id, Node(kind=NodeKind.clip, title="a", goal="g", status=NodeStatus.done, output="clips/x/o.mp4"))
    b = add_child(p, p.root.id, Node(kind=NodeKind.clip, title="b", goal="g"))
    a.takes = [Take(id="t1", model="free_preview", video="clips/x/o.mp4")]
    a.chosen_take = "t1"
    p.dependencies.append(Dependency(from_id=a.id, to_id=b.id, type="continues_from"))
    svc.save(p)
    assert asyncio.run(Engine(svc)._handoff_frame(p.id, b.id)) is None


def test_credits_file_written(svc, tmp_path):
    from video_generator.runner import Engine
    p = svc.new_project("g", seconds=10)
    item = ContextItem(type=ContextType.object, title="Lion photo",
                       analysis={"credits": [{"title": "Lion", "author": "A. Person", "license": "CC BY-SA 4.0", "source_url": "https://commons.example/x"}]})
    p.context.append(item)
    Engine(svc)._write_credits(p, tmp_path)
    text = (tmp_path / "credits.txt").read_text()
    assert "A. Person" in text and "CC BY-SA 4.0" in text
    p.context = []
    Engine(svc)._write_credits(p, tmp_path)
    assert not (tmp_path / "credits.txt").exists()


# ------------------------------------------------------------------ free preview card
def test_placeholder_card_handles_long_text(tmp_path):
    out = media.placeholder_image("word " * 400, tmp_path / "c.png", (1280, 720), label="Clip 1.1 · A very long clip title here")
    assert out.exists()


# ------------------------------------------------------------------ stock photos
WIKI = {"query": {"pages": {
    "1": {"index": 2, "title": "File:Lion small.jpg", "imageinfo": [{"mime": "image/jpeg", "width": 500, "height": 300, "thumburl": "https://upload.wikimedia.org/a.jpg"}]},
    "2": {"index": 1, "title": "File:Lion male.jpg", "imageinfo": [{
        "mime": "image/jpeg", "width": 4000, "height": 3000, "thumburl": "https://upload.wikimedia.org/b.jpg", "thumbwidth": 1280, "thumbheight": 960,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Lion_male.jpg",
        "extmetadata": {"Artist": {"value": "<a href='x'>Jane &amp; Co</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]},
    "3": {"index": 3, "title": "File:Lion map.svg", "imageinfo": [{"mime": "image/svg+xml", "width": 2000, "height": 2000, "thumburl": "https://upload.wikimedia.org/c.png"}]},
}}}


def test_wikimedia_search_parsing_and_filtering():
    def handler(request: httpx.Request):
        assert "commons.wikimedia.org" in request.url.host
        return httpx.Response(200, json=WIKI)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = asyncio.run(stock.search("lion", "wikimedia", client=client))
    assert [r.title for r in res] == ["Lion male"]
    assert res[0].author == "Jane & Co" and res[0].license == "CC BY-SA 4.0"


def test_stock_download_only_from_allowed_hosts(tmp_path):
    with pytest.raises(stock.StockError):
        asyncio.run(stock.download("https://evil.example/x.jpg", tmp_path, "x"))
    with pytest.raises(stock.StockError):
        asyncio.run(stock.download("http://upload.wikimedia.org/x.jpg", tmp_path, "x"))

    def handler(request):
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8abc")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    path = asyncio.run(stock.download("https://upload.wikimedia.org/x.jpg", tmp_path, "Lion male", client=client))
    assert path.suffix == ".jpg" and path.read_bytes().startswith(b"\xff\xd8")

    def not_image(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")
    client = httpx.AsyncClient(transport=httpx.MockTransport(not_image))
    with pytest.raises(stock.StockError):
        asyncio.run(stock.download("https://upload.wikimedia.org/x.jpg", tmp_path, "y", client=client))


def test_stock_photo_goes_to_animals_not_people(svc, sample_photo, monkeypatch):
    p, lion, clip = lion_project(svc)

    async def fake_download(url, dest_dir, name, client=None):
        dest = Path(dest_dir) / "lion.jpg"
        dest.write_bytes(sample_photo.read_bytes())
        return dest
    monkeypatch.setattr(stock, "download", fake_download)
    meta = {"title": "Lion male", "author": "Jane", "license": "CC BY-SA 4.0", "source_url": "https://commons.example", "source": "wikimedia"}
    p = asyncio.run(svc.add_stock_photo(p.id, lion.id, "https://upload.wikimedia.org/b.jpg", meta))
    item = next(c for c in p.context if c.id == lion.id)
    assert item.files and item.actor.kind == "animal" and item.analysis["credits"][0]["author"] == "Jane"
    assert not item.needs_consent                      # an animal photo needs no consent
    # a person must be uploaded, never taken from search
    _, person = svc.add_context(p.id, {"type": "actor", "title": "Some person", "actor": {"kind": "ai_person"}})
    with pytest.raises(ValueError, match="people"):
        asyncio.run(svc.add_stock_photo(p.id, person.id, "https://upload.wikimedia.org/b.jpg", meta))


# ------------------------------------------------------------------ voice recording
@requires_ffmpeg
def test_voice_recording_saved_as_sample_with_consent(svc, tmp_path):
    p = svc.new_project("g", seconds=10)
    _, me = svc.add_context(p.id, {"type": "actor", "title": "Me", "actor": {}})
    rec = tmp_path / "rec.m4a"
    media.ff("-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-c:a", "aac", str(rec))
    p = svc.add_voice_recording(p.id, me.id, rec.read_bytes(), "recording.m4a", consent_self=True)
    item = next(c for c in p.context if c.id == me.id)
    wav = ProjectStore.path_for(p.id) / item.actor.voice_sample
    assert wav.suffix == ".wav" and abs(media.probe_duration(wav) - 6) < 0.5
    assert item.actor.kind == "real_person" and item.consent.confirmed and item.consent.statement == "self"
    assert "voice_check" in item.analysis and item.actor.voice_id is None
    # not an actor / empty recording are rejected
    short = tmp_path / "short.wav"
    media.ff("-f", "lavfi", "-i", "sine=frequency=300:duration=0.4", str(short))
    with pytest.raises(ValueError, match="short"):
        svc.add_voice_recording(p.id, me.id, short.read_bytes(), "x.wav")
    with pytest.raises(ValueError):
        svc.add_voice_recording(p.id, me.id, b"not audio at all", "x.webm")


@requires_ffmpeg
def test_api_voice_recording_and_stock_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    rec = tmp_path / "r.wav"
    media.ff("-f", "lavfi", "-i", "sine=frequency=250:duration=3", str(rec))
    with TestClient(appmod.app) as client:
        pid = client.post("/api/projects", data={"goal": "Me talking", "seconds": "10"}).json()["id"]
        added = client.post(f"/api/projects/{pid}/context", json={"type": "actor", "title": "Me"}).json()
        cid = added["new_id"]
        r = client.post(f"/api/projects/{pid}/context/{cid}/voice-recording", files={"file": ("recording.wav", rec.read_bytes(), "audio/wav")},
                        data={"consent_self": "true"})
        assert r.status_code == 200
        item = next(c for c in r.json()["project"]["context"] if c["id"] == cid)
        assert item["actor"]["voice_sample"].endswith(".wav") and item["consent"]["confirmed"]
        assert "preview" in r.json()["summary"] and "final_ready" in r.json()["summary"]
        assert "activity" in r.json()["engine"]

        async def fake_search(q, source="wikimedia", limit=24, client=None):
            return [stock.StockPhoto("wikimedia", "Lion", "https://upload.wikimedia.org/t.jpg", "https://upload.wikimedia.org/t.jpg", 1280, 960, "Jane", "CC BY 4.0", "https://x")]
        monkeypatch.setattr(stock, "search", fake_search)
        s = client.get("/api/stock/search", params={"q": "lion"}).json()
        assert s["results"][0]["license"] == "CC BY 4.0" and "wikimedia" in s["sources"]
        person = client.post(f"/api/projects/{pid}/context", json={"type": "actor", "title": "Person"}).json()["new_id"]
        bad = client.post(f"/api/projects/{pid}/context/{person}/stock", json={"url": "https://upload.wikimedia.org/t.jpg"})
        assert bad.status_code == 400 and "people" in bad.json()["detail"]


def test_cost_includes_actor_reference_picture_once(svc, monkeypatch):
    for k in ("FAL_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(k, "x")
    svc.reload()
    p, lion, clip = lion_project(svc)
    second = add_child(p, p.root.id, Node(kind=NodeKind.clip, title="Again", goal="Kito again", target_seconds=5))
    second.script = ClipScript(shot_type=ShotType.talking_head, visual="close-up", on_camera_speech=True,
                               actors_in_shot=[ActorInShot(actor_id=lion.id)], dialogue=[DialogueLine(speaker=lion.id, text="hello")])
    svc.save(p)
    p = svc.load(p.id)
    first, other = leaves(p)[0], leaves(p)[1]
    assert any("Reference picture of Kito" in l.item for l in first.cost.lines)
    assert not any("Reference picture" in l.item for l in other.cost.lines)       # made once, not counted twice
    assert first.cost.likely_usd > 0.5                                           # the lion test needs real money, shown up front


def test_time_is_zero_after_everything_is_made(svc):
    p = svc.new_project("g", seconds=10)
    clip = add_child(p, p.root.id, Node(kind=NodeKind.clip, title="c", goal="g", status=NodeStatus.done))
    p.final_output = "output/final.mp4"
    svc.refresh(p)
    assert p.root.time.likely_s == 0
