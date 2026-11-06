"""Step 4 (v3.9): download any clip or part, and the background music is made ONCE and reused (by every join and every part)."""
import asyncio
import json
import re

import pytest

from video_generator import media, musictrack, policy as policy_mod
from video_generator.models import ClipScript, Node, NodeKind, NodeStatus, ShotType
from video_generator.plugins.base import Usage
from video_generator.project import ProjectStore
from video_generator.runner import Engine
from video_generator.tree import add_child, leaves

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors

pytestmark = requires_ffmpeg


def made_project(svc, monkeypatch, layout=(2, 1), music=True):
    """A project whose clips are already made (2 s each, real ffmpeg files) in parts of the given sizes."""
    Vendors(svc, monkeypatch)
    p = svc.new_project("Export test", seconds=2 * sum(layout), quality_mode="balanced")
    p.settings.review_enabled = False
    p.settings.music = music
    p.settings.resolution = "720p"
    p.music_advice = "subtle: calm"
    for i, n in enumerate(layout, start=1):
        part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title=f"Part {i}", goal="g", target_seconds=2.0 * n))
        for j in range(n):
            c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"Clip {i}.{j + 1}", goal="g", target_seconds=2.0))
            c.script = ClipScript(shot_type=ShotType.landscape, visual="hills", sound_notes="wind")
    svc.save(p)
    p = svc.load(p.id)
    base = ProjectStore.path_for(p.id)
    for leaf in leaves(p):
        f = base / "clips" / leaf.id / "final.mp4"
        f.parent.mkdir(parents=True, exist_ok=True)
        media.ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f))
        leaf.output = str(f.relative_to(base))
        leaf.status = NodeStatus.done
    # the voice of the first clip, so a subtitle exists
    first = leaves(p)[0]
    (base / "clips" / first.id / "voice_lines.json").write_text(json.dumps({"lead": 0.5, "gap": 0.6, "lines": [{"seconds": 1.0, "text": "hello there"}]}))
    svc.save(p)
    return svc.load(p.id)


def fake_music(svc):
    """A pretend music vendor: records every paid call, writes a real 10 s sound."""
    calls = []

    async def generate(prompt, seconds, out, model="", reference=None):
        calls.append({"prompt": prompt, "seconds": seconds})
        media.ff("-f", "lavfi", "-i", "sine=frequency=330:duration=10", "-f", "wav", str(out))
        return out, Usage(seconds=seconds)
    svc.reg.plugin("elevenlabs_music").generate = generate
    return calls


def run(coro):
    return asyncio.run(coro)


def streams(path):
    return {s["codec_type"] for s in media.probe(path)["streams"]}


# ------------------------------------------------------------------ a clip, a part
def test_a_finished_clip_can_be_downloaded_under_a_friendly_name(svc, monkeypatch):
    p = made_project(svc, monkeypatch, music=False)
    clip = leaves(p)[0]
    r = run(Engine(svc).export_node(p.id, clip.id))
    f = ProjectStore.path_for(p.id) / r["path"]
    assert f.exists() and f.suffix == ".mp4" and not r["with_music"]
    assert re.fullmatch(r"export-test-1-1-clip-1-1\.mp4", r["filename"]) and abs(media.probe_duration(f) - 2.0) < 0.3


def test_a_part_is_its_clips_joined_with_a_subtitle_file(svc, monkeypatch):
    p = made_project(svc, monkeypatch, music=False)
    part = p.root.children[0]
    r = run(Engine(svc).export_node(p.id, part.id))
    f = ProjectStore.path_for(p.id) / r["path"]
    assert abs(media.probe_duration(f) - 4.0) < 0.5 and {"video", "audio"} <= streams(f)
    assert r["filename"] == "export-test-1-part-1.mp4" and r["srt"]
    srt = (ProjectStore.path_for(p.id) / r["srt"]).read_text()
    assert "hello there" in srt and srt.startswith("1\n00:00:00,500")          # counted from the start of THIS part
    assert abs(media.probe_duration(ProjectStore.path_for(p.id) / run(Engine(svc).export_node(p.id, p.root.children[1].id))["path"]) - 2.0) < 0.4


def test_a_part_that_is_not_fully_made_is_refused_with_a_plain_message(svc, monkeypatch):
    p = made_project(svc, monkeypatch, music=False)
    leaves(p)[1].status = NodeStatus.ready
    svc.save(p)
    with pytest.raises(ValueError, match=r"1 of 2 clip\(s\) are still to make"):
        run(Engine(svc).export_node(p.id, p.root.children[0].id))
    with pytest.raises(ValueError, match="clip cannot be downloaded yet"):
        run(Engine(svc).export_node(p.id, leaves(p)[1].id))


def test_the_download_is_made_once_and_reused_until_a_clip_changes(svc, monkeypatch):
    p = made_project(svc, monkeypatch, music=False)
    part = p.root.children[0]

    async def flow():
        eng = Engine(svc)
        a = await eng.export_node(p.id, part.id)
        stamp = (ProjectStore.path_for(p.id) / a["path"]).stat().st_mtime_ns
        b = await eng.export_node(p.id, part.id)
        return a, b, stamp
    a, b, stamp = run(flow())
    assert a["path"] == b["path"] and (ProjectStore.path_for(p.id) / b["path"]).stat().st_mtime_ns == stamp
    # a clip is made again: a new file, not the old one
    q = svc.load(p.id)
    f = ProjectStore.path_for(p.id) / leaves(q)[0].output
    media.ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24", "-f", "lavfi", "-i", "sine=frequency=500", "-t", "2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-y", str(f))
    assert run(Engine(svc).export_node(p.id, part.id))["path"] != a["path"]


# ------------------------------------------------------------------ music: made once, reused everywhere
def test_music_in_a_part_asks_first_when_a_new_track_would_cost_money(svc, monkeypatch):
    p = made_project(svc, monkeypatch)
    calls = fake_music(svc)
    r = run(Engine(svc).export_node(p.id, p.root.children[0].id))
    assert r["needs_music_choice"] and r["cost_usd"] > 0 and r["model"] == "eleven_music"
    assert calls == []                                                                  # nothing was spent
    assert not list((ProjectStore.path_for(p.id) / "output" / "parts").glob("*.mp4")) and not musictrack.path(p.id)


def test_you_can_choose_no_music_for_a_part(svc, monkeypatch):
    p = made_project(svc, monkeypatch)
    calls = fake_music(svc)
    r = run(Engine(svc).export_node(p.id, p.root.children[0].id, "none"))
    assert not r["with_music"] and calls == [] and not musictrack.path(p.id)


def test_music_is_made_once_and_every_part_and_the_final_video_reuse_it(svc, monkeypatch):
    p = made_project(svc, monkeypatch)
    calls = fake_music(svc)

    async def flow():
        eng = Engine(svc)
        one = await eng.export_node(p.id, p.root.children[0].id, "new")        # you agreed: the track is made now, for the WHOLE video
        two = await eng.export_node(p.id, p.root.children[1].id)               # a second part: free, no question asked
        await eng.assemble(p.id)                                                # the final video: reuses the same track
        await eng.assemble(p.id)                                                # joining AGAIN does not buy it again
        return one, two
    one, two = run(flow())
    assert len(calls) == 1 and calls[0]["seconds"] == pytest.approx(6.0, abs=0.6)
    assert one["with_music"] and two["with_music"] and "audio" in streams(ProjectStore.path_for(p.id) / one["path"])
    assert musictrack.path(p.id).exists() and musictrack.read(p.id)["model"] == "eleven_music"
    assert svc.load(p.id).final_output and (ProjectStore.path_for(p.id) / svc.load(p.id).final_output).exists()


def test_a_part_with_music_sounds_different_from_the_same_part_without_it(svc, monkeypatch):
    p = made_project(svc, monkeypatch)
    fake_music(svc)

    async def flow():
        eng = Engine(svc)
        plain = await eng.export_node(p.id, p.root.children[0].id, "none")
        withm = await eng.export_node(p.id, p.root.children[0].id, "new")
        return plain, withm
    plain, withm = run(flow())
    assert plain["path"] != withm["path"] and not plain["with_music"] and withm["with_music"]
    assert abs(media.probe_duration(ProjectStore.path_for(p.id) / withm["path"]) - media.probe_duration(ProjectStore.path_for(p.id) / plain["path"])) < 0.3


def test_a_saved_track_makes_the_estimate_show_no_music_cost(svc, monkeypatch):
    p = made_project(svc, monkeypatch)
    fake_music(svc)
    before = svc.summary(svc.load(p.id))["cost_total"]
    assert any(l.item.startswith("Music share") for l in leaves(svc.load(p.id))[0].cost.lines)
    run(Engine(svc).export_node(p.id, p.root.children[0].id, "new"))
    q = svc.load(p.id)
    after = svc.summary(q)["cost_total"]
    line = next(l for l in leaves(q)[0].cost.lines if l.item.startswith("Music"))
    assert line.item == "Music (saved track, reused)" and line.cost == 0 and after < before


def test_the_join_button_can_say_what_the_music_costs_before_it_spends(svc, monkeypatch):
    p = made_project(svc, monkeypatch)
    fake_music(svc)
    st = svc.music_status(p.id)
    assert st["enabled"] and not st["saved"] and st["cost_usd"] > 0 and st["model"] == "eleven_music" and st["cost_usd"] == st["cost_new_usd"]
    run(Engine(svc).export_node(p.id, p.root.children[0].id, "new"))
    st = svc.music_status(p.id)
    assert st["saved"] and st["reusable"] and st["cost_usd"] == 0 and st["cost_new_usd"] > 0


def test_a_saved_track_is_not_reused_when_the_mood_changed_or_the_video_got_much_longer(svc, monkeypatch):
    p = made_project(svc, monkeypatch)
    fake_music(svc)
    run(Engine(svc).export_node(p.id, p.root.children[0].id, "new"))
    q = svc.load(p.id)
    assert musictrack.status(q, 6.0)["reusable"]
    assert musictrack.status(q, 5.0)["reusable"]                                   # a shorter video just uses less of it
    tol = policy_mod.current().music_reuse_tolerance
    assert musictrack.status(q, 6.0 * (1 + tol) + 0.4)["reusable"]                 # a little longer: the track repeats
    longer = musictrack.status(q, 6.0 * (1 + tol) + 1.5)
    assert not longer["reusable"] and "saved music was made for 6 s" in longer["why"]
    q.music_advice = "full: loud and energetic"
    assert "mood or example changed" in musictrack.status(q, 6.0)["why"]


def test_a_part_download_still_uses_an_older_saved_track_and_says_so(svc, monkeypatch):
    p = made_project(svc, monkeypatch)
    calls = fake_music(svc)
    run(Engine(svc).export_node(p.id, p.root.children[0].id, "new"))
    q = svc.load(p.id)
    q.music_advice = "full: loud and energetic"
    svc.save(q)
    r = run(Engine(svc).export_node(p.id, p.root.children[1].id))
    assert r["with_music"] and len(calls) == 1 and any("saved track" in n for n in r["notes"])      # no silent spending


def test_music_that_is_switched_off_stays_off_in_a_part(svc, monkeypatch):
    p = made_project(svc, monkeypatch, music=False)
    calls = fake_music(svc)
    r = run(Engine(svc).export_node(p.id, p.root.children[0].id))
    assert not r["with_music"] and calls == [] and "needs_music_choice" not in r


# ------------------------------------------------------------------ the slice itself
def test_a_music_slice_has_the_asked_length_even_past_the_end_of_the_track(tmp_path):
    track = tmp_path / "t.wav"
    media.ff("-f", "lavfi", "-i", "sine=frequency=300:duration=5", str(track))
    inside = media.music_slice(track, tmp_path / "a.wav", 1.0, 3.0, 1.0)
    past = media.music_slice(track, tmp_path / "b.wav", 4.0, 4.0, 1.0)             # runs past the end: the track repeats
    assert abs(media.probe_duration(inside) - 3.0) < 0.1 and abs(media.probe_duration(past) - 4.0) < 0.1


def test_the_music_settings_are_named_policy_settings_with_help_text():
    names = {n: why for n, _, why in policy_mod.describe()}
    assert names["music_reuse_tolerance"] and names["music_part_fade_s"]


# ------------------------------------------------------------------ the web API
def test_api_export_returns_a_download_address_with_a_friendly_name(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    p = made_project(svc, monkeypatch, music=False)
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    part = p.root.children[0]
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/nodes/{part.id}/export", json={})
        assert r.status_code == 200 and r.json()["url"].startswith(f"/files/{p.id}/output/parts/") and "download=export-test-1-part-1.mp4" in r.json()["url"]
        got = client.get(r.json()["url"])
        assert got.status_code == 200 and 'filename="export-test-1-part-1.mp4"' in got.headers["content-disposition"] and len(got.content) > 1000
        assert client.post(f"/api/projects/{p.id}/nodes/{part.id}/export", json={"music": "sometimes"}).status_code == 400
        assert client.post(f"/api/projects/{p.id}/assemble", json={"music": "sometimes"}).status_code == 400
        m = client.get(f"/api/projects/{p.id}/music").json()
        assert m["saved"] is False and m["enabled"] is False                         # music is off in this project


def test_api_refuses_a_half_made_part_with_a_plain_message(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    p = made_project(svc, monkeypatch, music=False)
    leaves(p)[0].status = NodeStatus.ready
    svc.save(p)
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/nodes/{p.root.children[0].id}/export", json={})
        assert r.status_code == 400 and "still to make" in r.json()["detail"]
