"""The 3D camera reference, as in the video: describe the scene and change it in plain words (it is applied, checked,
fixed when needed and rendered by itself), and open it in your own Blender to look around."""
import asyncio
import json
import sys

import pytest

from video_generator.brain import render
from video_generator.plugins.base import AgentResult
from video_generator.project import ProjectStore
from video_generator.scene3d import agent as ag
from video_generator.scene3d import service as s3
from video_generator.scene3d import viewer
from video_generator.scene3d.spec import CameraKey, check, normalise
from video_generator.tree import find

from .conftest import requires_ffmpeg
from .test_scene3d import chase, two_shot_project


def project(svc, monkeypatch, agent="fake_agent"):
    monkeypatch.setattr(ag, "pick_agents", lambda svc_, choice: (agent, None, []))
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.renderer = "sketch"
    svc.save(p)
    return p, ids


def lizard(svc, pid, nid):
    return next(t for t in find(svc.load(pid), nid).scene3d.plan.things if t.label == "Lizard")


def test_the_planner_is_given_your_words():
    text = render("scene_plan", wishes="a big empty kitchen, the chef at the far end")
    assert "WHAT THE USER WANTS IN THIS 3D SCENE" in text and "a big empty kitchen, the chef at the far end" in text


@requires_ffmpeg
def test_describing_a_scene_plans_and_renders_it_from_your_words(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    seen = {}
    real = svc.brain.scene_plan

    async def spy(project_, node, shared_set="", previous="", wishes=""):
        seen["wishes"] = wishes
        return await real(project_, node, shared_set=shared_set, previous=previous, wishes=wishes)
    monkeypatch.setattr(svc.brain, "scene_plan", spy)
    rep = asyncio.run(ag.change_clip(svc, p.id, ids[0], "a big empty terrarium, the lizard far behind them"))
    assert rep.planned and rep.changed and rep.status == "rendered"
    assert seen["wishes"] == "a big empty terrarium, the lizard far behind them"
    s = find(svc.load(p.id), ids[0]).scene3d
    assert s.wishes == "a big empty terrarium, the lizard far behind them" and s.video and s.changes == []


@requires_ffmpeg
def test_a_change_is_made_by_the_agent_then_checked_and_rendered_and_undo_takes_it_back(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    asyncio.run(s3.build_clip(svc, p.id, ids[0]))
    before = lizard(svc, p.id, ids[0]).size
    rep = asyncio.run(ag.change_clip(svc, p.id, ids[0], "make the lizard twice as big"))
    assert rep.changed and rep.by == "fake_agent" and "Lizard 2 times the size" in rep.summary and rep.status == "rendered"
    assert lizard(svc, p.id, ids[0]).size == pytest.approx([v * 2 for v in before])
    others = [t for t in find(svc.load(p.id), ids[0]).scene3d.plan.things if t.label != "Lizard"]
    assert all(t.size[2] < 2 for t in others)                         # only what was asked for changed
    s = find(svc.load(p.id), ids[0]).scene3d
    assert s.changes == ["make the lizard twice as big"] and any("Change \"make the lizard twice as big\"" in l for l in s.agent_log)
    task = svc.reg.plugin("fake_agent").runs[-1]
    assert task.role == "change" and task.request == "make the lizard twice as big" and task.allowed_command == ag.check_command()
    assert "THE USER ASKS:\nmake the lizard twice as big" in task.instructions
    ProjectStore.undo(p.id)                                           # ONE undo takes the whole change back
    assert lizard(svc, p.id, ids[0]).size == pytest.approx(before)
    assert find(svc.load(p.id), ids[0]).scene3d.changes == []
    ProjectStore.redo(p.id)
    assert lizard(svc, p.id, ids[0]).size == pytest.approx([v * 2 for v in before])


@requires_ffmpeg
def test_with_no_agent_the_ai_brain_makes_the_change(svc, monkeypatch):
    p, ids = project(svc, monkeypatch, agent=None)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    keys = find(svc.load(p.id), ids[0]).scene3d.plan.camera.keys
    rep = asyncio.run(ag.change_clip(svc, p.id, ids[0], "move the camera closer"))
    assert rep.by == "the AI brain" and rep.changed and rep.summary == "The AI brain changed the plan."
    new = find(svc.load(p.id), ids[0]).scene3d.plan.camera.keys
    def dist(k):
        return sum((a - b) ** 2 for a, b in zip(k.at, k.look_at)) ** 0.5
    assert dist(new[0]) < dist(keys[0])
    assert any(r["what"] == f"3D change {ids[0]}" for r in ProjectStore.ledger(p.id) if r["kind"] == "llm")


def test_a_change_nobody_understood_leaves_the_plan_as_it_was(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    before = find(svc.load(p.id), ids[0]).scene3d.plan
    rep = asyncio.run(ag.change_clip(svc, p.id, ids[0], "make it feel more poetic", render=False))
    assert not rep.changed and "did not understand" in rep.summary
    assert find(svc.load(p.id), ids[0]).scene3d.plan == before
    with pytest.raises(s3.Scene3DError, match="Say what you want"):
        asyncio.run(ag.change_clip(svc, p.id, ids[0], "   "))


def test_a_change_that_breaks_the_shot_is_fixed_by_itself(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    fake = svc.reg.plugin("fake_agent")
    real = fake.run

    async def careless(task):                 # the change turns the camera away from everyone
        if task.role == "change":
            plan = json.loads((task.folder / "plan.json").read_text())
            plan["camera"]["keys"] = [{"t": 0, "at": [0, 30, 1.6], "look_at": [0, 60, 1.6]}]
            (task.folder / "plan.json").write_text(json.dumps(plan))
            return AgentResult(ok=True, summary="turned the camera")
        return await real(task)
    monkeypatch.setattr(fake, "run", careless)
    rep = asyncio.run(ag.change_clip(svc, p.id, ids[0], "turn the camera around", render=False))
    assert rep.changed and rep.fix and rep.fix.fixed
    assert not [i for i in check(find(svc.load(p.id), ids[0]).scene3d.plan) if i.severity == "major"]


def test_your_change_may_recolour_or_remove_but_a_fix_may_not():
    before = normalise(chase(4))
    after = before.model_copy(deep=True)
    after.things[0].colour = "#000000"
    after.things = [t for t in after.things if t.id != "bruiser"]
    yours = ag._kept(before, after, strict=False)
    assert yours.things[0].colour == "#000000" and "bruiser" not in {t.id for t in yours.things}
    fix = ag._kept(before, after)
    assert fix.things[0].colour == before.things[0].colour and "bruiser" in {t.id for t in fix.things}


# ----------------------------------------------------------------- open in Blender
def stand_in_blender(tmp_path, monkeypatch):
    log = tmp_path / "blender_args.json"
    exe = tmp_path / "blender"
    exe.write_text(f"#!{sys.executable}\nimport json, sys\nopen({str(log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n")
    exe.chmod(0o755)
    monkeypatch.setenv("VG_BLENDER", str(exe))
    return log


@requires_ffmpeg
def test_open_in_blender_starts_blender_on_the_scene_looking_through_the_camera(svc, monkeypatch, tmp_path):
    log = stand_in_blender(tmp_path, monkeypatch)
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    asyncio.run(s3.build_clip(svc, p.id, ids[0]))                     # the free sketch: no Blender file
    with pytest.raises(s3.Scene3DError, match="free sketch"):
        viewer.open_in_blender(svc, p.id, ids[0])
    q = svc.load(p.id)                                                # pretend Blender rendered it
    blend = ProjectStore.path_for(p.id) / "clips" / ids[0] / "scene3d" / "scene.blend"
    blend.write_bytes(b"BLENDER")
    find(q, ids[0]).scene3d.blend = str(blend.relative_to(ProjectStore.path_for(p.id)))
    svc.save(q)
    r = viewer.open_in_blender(svc, p.id, ids[0])
    assert "looking through the camera" in r["note"] and "not used" in r["note"]
    for _ in range(50):
        if log.exists():
            break
        asyncio.run(asyncio.sleep(0.1))
    args = json.loads(log.read_text())
    assert args[0] == str(blend) and args[1] == "--python-expr" and 'view_perspective = "CAMERA"' in args[2]
    compile(viewer.LOOK_THROUGH_CAMERA, "look", "exec")


def test_open_in_blender_says_why_it_cannot(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    with pytest.raises(s3.Scene3DError, match="no 3D scene yet"):
        viewer.open_in_blender(svc, p.id, ids[0])


# ----------------------------------------------------------------- the screen
@requires_ffmpeg
def test_the_screen_sends_a_change_and_it_is_done_in_the_background(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    with TestClient(appmod.app) as client:
        base = f"/api/projects/{p.id}/nodes/{ids[0]}/scene3d"
        assert client.post(f"{base}/change", json={"request": ""}).status_code == 400
        assert client.post(f"{base}/change", json={"request": "make the lizard twice as big"}).json() == {"ok": True}
        for _ in range(300):
            s = find(svc.load(p.id), ids[0]).scene3d
            if s.changes and s.status == "rendered":
                break
            asyncio.run(asyncio.sleep(0.1))
        assert s.changes == ["make the lizard twice as big"] and s.status == "rendered"
        r = client.post(f"{base}/open")
        assert r.status_code == 400 and "free sketch" in r.json()["detail"]
