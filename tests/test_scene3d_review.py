"""The 3D camera reference add-on, phase 5 (numbers and review): the 3D step in the cost and time estimate, the free
measurement of how closely a clip followed its reference camera, and the camera check in the Review Agent."""
import asyncio
import random
import shutil

import pytest
from PIL import Image, ImageFilter

from video_generator import estimate as E
from video_generator import media
from video_generator.brain import ReviewDraft, Scores
from video_generator.reviewer import apply_quality_rules
from video_generator.scene3d import follow
from video_generator.scene3d import render as R
from video_generator.scene3d import service as s3
from video_generator.tree import find

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors
from .test_scenarios import run_all
from .test_scene3d import approved, two_shot_project


def texture(path, seed):
    random.seed(seed)
    im = Image.new("RGB", (1600, 400))
    px = im.load()
    for x in range(0, 1600, 8):
        for y in range(0, 400, 8):
            c = tuple(random.randint(0, 255) for _ in range(3))
            for i in range(8):
                for j in range(8):
                    px[x + i, y + j] = c
    im.filter(ImageFilter.GaussianBlur(2)).save(path)
    return path


def pan(tmp_path, name, seed, x_expr):
    """A 4 s video of a camera moving across a still texture (x_expr says where the camera is at time t)."""
    out = tmp_path / f"{name}.mp4"
    media.ff("-loop", "1", "-i", str(texture(tmp_path / f"{name}.png", seed)), "-t", "4", "-r", "24",
             "-vf", f"crop=640:360:'{x_expr}':20", "-pix_fmt", "yuv420p", str(out))
    return out


# ----------------------------------------------------------------- the measurement
@requires_ffmpeg
def test_the_measured_camera_match_tells_same_from_opposite_and_still(tmp_path):
    ref = pan(tmp_path, "ref", 1, "t*100")                    # the reference camera moves right
    same = follow.compare(ref, pan(tmp_path, "same", 2, "t*90"))       # another place, the same move
    opposite = follow.compare(ref, pan(tmp_path, "opposite", 2, "900-t*90"))
    still_video = pan(tmp_path, "still", 2, "300")
    still = follow.compare(ref, still_video)
    assert same["camera_follow"] > 0.9
    assert opposite["camera_follow"] < 0.45 and still["camera_follow"] < 0.45
    assert same["camera_reference_move"] == pytest.approx(0.625, abs=0.1)       # 400 px of a 640 px wide picture
    calm = pan(tmp_path, "calm", 3, "200")
    assert follow.compare(calm, still_video)["camera_follow"] == 1.0                    # a still reference and a still clip
    assert follow.compare(calm, pan(tmp_path, "moves", 4, "t*100"))["camera_follow"] < 0.45


def test_an_unreadable_video_gives_no_measurement(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    assert follow.compare(bad, bad) is None


# ----------------------------------------------------------------- the quality rules
def draft(**scores):
    return ReviewDraft(verdict="meets_goal", scores=Scores(**{"goal": 5, "script": 5, "realism": 5, "motion": 5, **scores}),
                       issues=[], suggestions=[], summary="")


def test_measured_camera_match_wins_over_the_ai(monkeypatch):
    d = apply_quality_rules(draft(camera=5), {"camera_follow": 0.3}, placeholder=False, speech_expected=False)
    assert d.scores.camera == 2 and d.verdict == "does_not_meet_goal"
    assert any(i.check == "camera" and i.severity == "major" for i in d.issues)
    loose = apply_quality_rules(draft(camera=5), {"camera_follow": 0.55}, placeholder=False, speech_expected=False)
    assert loose.scores.camera == 3 and loose.verdict == "minor_issues"
    close = apply_quality_rules(draft(camera=5), {"camera_follow": 0.9}, placeholder=False, speech_expected=False)
    assert close.scores.camera == 5 and not [i for i in close.issues if i.check == "camera"]
    none = apply_quality_rules(draft(camera=4), {}, placeholder=False, speech_expected=False)
    assert none.scores.camera == 0                               # no reference: no camera score, whatever the AI said


# ----------------------------------------------------------------- the estimate
def test_the_3d_step_is_in_the_cost_and_time_of_a_clip(svc, monkeypatch):
    p, ids = two_shot_project(svc)
    n = find(p, ids[0])
    before = E.estimate_clip_cost(p, n, svc.reg)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.renderer = "sketch"
    svc.save(p)
    q = svc.load(p.id)
    n = find(q, ids[0])
    cost, time = E.estimate_clip_cost(q, n, svc.reg)
    items = {l.item: l for l in cost.lines}
    assert "AI brain: 3D plan" in items and "3D reference render" in items and "3D plan fixes by the agent" in items
    assert items["3D reference render"].cost == 0 and "free sketch" in items["3D reference render"].calc
    assert "at most $2.00" in items["3D plan fixes by the agent"].calc
    assert cost.max_usd >= before[0].max_usd + 2.0 - 0.01       # the agent counts only in the highest figure
    assert cost.likely_usd == pytest.approx(before[0].likely_usd + items["AI brain: 3D plan"].cost, abs=0.01)
    assert time.likely_s > before[1].likely_s


@requires_ffmpeg
def test_an_approved_reference_costs_nothing_more_to_prepare(svc):
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    svc.save(p)
    approved(svc, p.id, ids[0])
    q = svc.load(p.id)
    lines = {l.item for l in E.estimate_clip_cost(q, find(q, ids[0]), svc.reg)[0].lines}
    assert not lines & {"AI brain: 3D plan", "3D reference render", "3D plan fixes by the agent"}


def test_render_time_follows_the_engine_that_can_run_here(monkeypatch):
    R._likely_engine.cache_clear()
    assert R.expected_seconds(10, renderer="sketch") == pytest.approx(6, abs=1)
    monkeypatch.setattr(R, "find_blender", lambda b="": "/usr/bin/blender")
    import ctypes.util
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
    monkeypatch.setattr("sys.platform", "linux")
    R._likely_engine.cache_clear()
    assert R.likely_engine() == "CYCLES"                        # no graphics libraries: Workbench cannot run
    assert R.expected_seconds(10) == pytest.approx(8 + 380)
    R._likely_engine.cache_clear()


# ----------------------------------------------------------------- the review of a made clip
@requires_ffmpeg
def panning_reference(svc, pid, nid):
    """Plan the clip, turn its camera into a pan from left to right (the whole picture moves), render and approve it."""
    from video_generator.scene3d.spec import CameraKey
    asyncio.run(s3.plan_clip(svc, pid, nid))
    plan = find(svc.load(pid), nid).scene3d.plan.model_copy(deep=True)
    plan.camera.keys = [CameraKey(t=0, at=[0, -12, 1.7], look_at=[-9, 0, 1]), CameraKey(t=plan.seconds, at=[0, -12, 1.7], look_at=[9, 0, 1])]
    s3.set_plan(svc, pid, nid, plan)
    asyncio.run(s3.build_clip(svc, pid, nid, renderer="sketch"))
    return s3.approve(svc, pid, nid)


def test_the_review_measures_the_camera_and_flags_a_clip_that_did_not_follow(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.review_enabled = True
    find(p, ids[1]).scene3d_enabled = False         # only the first clip has a reference (a run would ask about the second)
    svc.save(p)
    panning_reference(svc, p.id, ids[0])
    run_all(svc, p.id)                              # the pretend reference model makes a STILL clip from its first picture
    q = svc.load(p.id)
    n = find(q, ids[0])
    review = next(r for r in q.reviews if r.target in {t.id for t in n.takes})
    assert "camera_follow" in review.measurements
    other = find(q, ids[1])
    other_review = next(r for r in q.reviews if r.target in {t.id for t in other.takes})
    assert "camera_follow" not in other_review.measurements and other_review.scores.get("camera", 0) == 0
    assert review.measurements["camera_reference_move"] >= follow.STILL       # the reference camera pans
    assert review.measurements["camera_follow"] < 0.65
    assert review.scores["camera"] <= 3 and any(i.check == "camera" for i in review.issues)


@requires_ffmpeg
def test_a_clip_that_copies_the_reference_camera_passes_the_camera_check(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.review_enabled = True
    find(p, ids[1]).scene3d_enabled = False         # only the first clip has a reference (a run would ask about the second)
    svc.save(p)
    panning_reference(svc, p.id, ids[0])
    fal = svc.reg.plugin("fal")
    still = fal.generate

    async def copies(req):                          # a perfect follower: its clip moves exactly like the reference
        if req.reference_video:
            shutil.copy(req.reference_video, req.out)
            from video_generator.plugins.base import Usage
            return req.out, Usage()
        return await still(req)
    monkeypatch.setattr(fal, "generate", copies)
    run_all(svc, p.id)
    q = svc.load(p.id)
    n = find(q, ids[0])
    review = next(r for r in q.reviews if r.target in {t.id for t in n.takes})
    assert review.measurements["camera_reference_move"] >= follow.STILL
    assert review.measurements["camera_follow"] >= 0.65
    assert not [i for i in review.issues if i.check == "camera"]


# ----------------------------------------------------------------- the screen (web routes)
@requires_ffmpeg
def test_the_screen_can_switch_build_approve_and_edit_the_reference(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p, ids = two_shot_project(svc)
    part = p.root.children[0].id
    with TestClient(appmod.app) as client:
        base = f"/api/projects/{p.id}"
        info = client.get(f"{base}/nodes/{ids[0]}/scene3d").json()
        assert info["enabled"] is False and info["legend"] == [] and set(info["agents"]) == {"builder", "checker", "notes"}
        # on for one part only, then for the whole video with the sketch renderer
        r = client.patch(f"{base}/nodes/{part}", json={"scene3d_enabled": True}).json()
        assert r["project"]["root"]["children"][0]["scene3d_enabled"] is True
        assert client.get(f"{base}/nodes/{ids[0]}/scene3d").json()["enabled"] is True
        assert client.patch(f"{base}/nodes/{part}", json={"scene3d_enabled": "maybe"}).status_code == 400
        st = r["project"]["settings"]["scene3d"]
        client.patch(base, json={"settings": {"scene3d": {**st, "enabled": True, "renderer": "sketch"}}})
        assert svc.load(p.id).settings.scene3d.renderer == "sketch"
        # build runs in the background and the screen is told when it is done
        assert client.post(f"{base}/nodes/{ids[0]}/scene3d/build", json={}).json() == {"ok": True}
        for _ in range(200):
            s = find(svc.load(p.id), ids[0]).scene3d
            if s and s.status == "rendered":
                break
            asyncio.run(asyncio.sleep(0.1))
        info = client.get(f"{base}/nodes/{ids[0]}/scene3d").json()
        assert [l["is"] for l in info["legend"]] == ["Dan", "Bruiser", "Lizard"] and info["renderer"] == "sketch" and not info["ready"]
        view = client.post(f"{base}/nodes/{ids[0]}/scene3d/approve").json()
        assert view["project"]["root"]["children"][0]["children"][0]["scene3d"]["approved_by"] == "you"
        assert client.get(f"{base}/nodes/{ids[0]}/scene3d").json()["ready"] is True
        # an edit by hand makes it out of date; a broken plan is refused
        plan = find(svc.load(p.id), ids[0]).scene3d.plan.model_dump()
        plan["camera"]["lens_mm"] = 70
        client.put(f"{base}/nodes/{ids[0]}/scene3d/plan", json=plan)
        assert "plan changed" in client.get(f"{base}/nodes/{ids[0]}/scene3d").json()["stale"]
        assert client.put(f"{base}/nodes/{ids[0]}/scene3d/plan", json={"things": "no"}).status_code == 400
        assert client.post(f"{base}/nodes/{ids[0]}/scene3d/approve").status_code == 400


def test_the_screen_shows_what_this_computer_can_use(svc, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    blender = tmp_path / "blender"
    blender.write_text("#!/bin/sh\necho 'Blender 9.9.9'\n")
    blender.chmod(0o755)
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\nexit 0\n")
    claude.chmod(0o755)
    monkeypatch.setenv("VG_BLENDER", str(blender))
    monkeypatch.setenv("VG_CLAUDE", str(claude))
    monkeypatch.setenv("VG_CODEX", "/no/such/codex")
    monkeypatch.setenv("PATH", "/nonexistent")
    R._likely_engine.cache_clear()
    with TestClient(appmod.app) as client:
        d = client.get("/api/scene3d/status").json()
    R._likely_engine.cache_clear()
    assert d["blender"] == {**d["blender"], "found": True, "version": "Blender 9.9.9", "path": str(blender)}
    assert d["claude_code"]["found"] is True and d["codex"] == {"found": False, "path": ""}
