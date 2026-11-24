"""Low-poly 3D models of the characters and objects: written from what the story says (nothing hard-wired), built by
an agent in Blender, checked by the tool, reused in every clip's scene with the poses the plan asks for."""
import asyncio
import json
from pathlib import Path

import pytest

from video_generator.models import ActorDetails, ContextItem, ContextType
from video_generator.plugins.agent.cli_agents import ClaudeCodeAgent, CodexAgent
from video_generator.plugins.base import AgentResult, AgentTask
from video_generator.project import ProjectStore
from video_generator.scene3d import agent as ag
from video_generator.scene3d import models3d
from video_generator.scene3d import render as R
from video_generator.scene3d import service as s3
from video_generator.scene3d.spec import Key, ModelRef, ScenePlan, Thing, continue_from, normalise, visibility
from video_generator.tree import find

from .conftest import requires_ffmpeg
from .test_scenarios import actor, build, clip

blender = pytest.mark.skipif(not R.find_blender(), reason="Blender is not installed")


def guru_project(svc, monkeypatch, agent_name="fake_agent"):
    monkeypatch.setattr(ag, "pick_agents", lambda svc_, choice: (agent_name, None, []))
    cast = [actor("Guru", description="elderly guru with a long white beard in a saffron robe"),
            actor("Disciple", description="young man in a white kurta")]
    p, ids = build(svc, "A disciple visits his guru", cast, [
        clip("human_motion", "The disciple walks up, kneels and touches the ground beside the guru's feet",
             actors=["Disciple", "Guru"], seconds=4)])
    p.settings.scene3d.enabled = True
    p.settings.scene3d.renderer = "sketch"
    svc.save(p)
    q = svc.load(p.id)
    return q, ids, {c.title: c.id for c in q.context}


def test_the_brief_comes_from_the_story(svc, monkeypatch):
    p, ids, who = guru_project(svc, monkeypatch)
    assert [c.title for c in models3d.needed_items(p)] == ["Guru", "Disciple"]
    assert "kneels and touches the ground" in models3d.actions_of(p, find_item(p, who["Disciple"]))[0]
    m = asyncio.run(models3d.write_brief(svc, p.id, who["Disciple"]))
    names = [x["name"] for x in m.brief["poses"]]
    assert names[0] == "stand" and {"walk", "kneel", "touch_ground"} <= set(names)
    g = asyncio.run(models3d.write_brief(svc, p.id, who["Guru"]))
    assert g.brief["colours"]["clothes"] == "#f4a62a" and g.brief["colours"]["hair"] == "#e6e6e6"     # saffron robe, white beard


def find_item(p, cid):
    return next(c for c in p.context if c.id == cid)


def test_building_needs_blender_and_an_agent(svc, monkeypatch):
    p, ids, who = guru_project(svc, monkeypatch)
    monkeypatch.setattr("video_generator.scene3d.render.find_blender", lambda configured="": None)
    with pytest.raises(s3.Scene3DError, match="Blender is not installed"):
        asyncio.run(models3d.build_model(svc, p.id, who["Guru"]))
    notes = asyncio.run(models3d.ensure_models(svc, p.id))
    assert notes == ["Blender is not installed, so the characters stay plain shapes."]


@blender
@requires_ffmpeg
def test_the_agent_builds_a_model_the_tool_checks_it_and_keeps_it(svc, monkeypatch):
    p, ids, who = guru_project(svc, monkeypatch)
    m = asyncio.run(models3d.build_model(svc, p.id, who["Disciple"]))
    assert m.status == "built" and 1.6 < m.height < 1.85 and not m.missing
    assert {"stand", "walk", "kneel", "touch_ground"} <= set(m.poses)
    assert m.pose_heights["kneel"] < m.pose_heights["stand"] and m.pose_heights["touch_ground"] < m.pose_heights["kneel"]
    base = ProjectStore.path_for(p.id)
    assert (base / m.script).exists() and (base / m.blend).exists()
    assert {"front", "side", "back", "three_quarter", "pose_kneel"} <= set(m.previews)
    task = svc.reg.plugin("fake_agent").runs[-1]
    assert task.role == "model" and "def build(name)" in task.instructions and "kneel" in task.instructions
    assert task.allowed_command.endswith("-m video_generator.scene3d.model_check")


@blender
@requires_ffmpeg
def test_problems_go_back_to_the_agent_for_another_round(svc, monkeypatch):
    p, ids, who = guru_project(svc, monkeypatch)
    fake = svc.reg.plugin("fake_agent")
    real = fake.run
    rounds = []

    async def first_wrong(task):
        rounds.append(task)
        if len(rounds) == 1:
            (task.folder / "model.py").write_text("POSES = {}\ndef build(name):\n    return None\n")
            return AgentResult(ok=True, summary="a first try")
        return await real(task)
    monkeypatch.setattr(fake, "run", first_wrong)
    m = asyncio.run(models3d.build_model(svc, p.id, who["Guru"]))
    assert m.status == "built" and len(rounds) == 2
    assert "THE LAST CHECK FOUND THESE PROBLEMS" in rounds[1].instructions and "build(name) did not return" in rounds[1].instructions


def test_a_scene_uses_a_model_its_size_and_only_the_poses_it_knows():
    ref = ModelRef(script="/x/model.py", height=1.72, width=0.3, depth=0.5, poses=["stand", "walk", "kneel"],
                   pose_heights={"stand": 1.72, "walk": 1.7, "kneel": 1.25}, version="v1")
    plan = ScenePlan(seconds=4, things=[Thing(id="d", actor_id="c1", kind="figure", keys=[
        Key(t=0, at=[0, 0, 0], pose="walk"), Key(t=3, at=[2, 0, 0], pose="kneel"), Key(t=4, at=[2, 0, 0], pose="fly")]),
        Thing(id="x", actor_id="c2")])
    p = s3.attach_models(plan, {"c1": ref})
    d, x = p.things
    assert d.model == "c1" and d.size == [0.5, 0.3, 1.72] and [k.pose for k in d.keys] == ["walk", "kneel", None]
    assert x.model == "" and set(p.models) == {"c1"}
    from video_generator.scene3d.spec import corners
    assert max(c[2] for c in corners(d, 3.5, p)) == pytest.approx(1.25)     # kneeling is lower
    nxt = continue_from(normalise(p), ScenePlan(seconds=2, things=[Thing(id="d", keys=[Key(t=2, at=[3, 0, 0])])]))
    assert nxt.things[0].keys[0].pose == "kneel"                         # the next clip starts in the same pose


@blender
@requires_ffmpeg
def test_preparing_a_clip_builds_its_models_plans_with_poses_and_renders_them(svc, monkeypatch):
    p, ids, who = guru_project(svc, monkeypatch)
    q = svc.load(p.id)
    q.settings.scene3d.renderer = "auto"                                 # Blender, with the models
    svc.save(q)
    rep = asyncio.run(ag.prepare_clip(svc, p.id, ids[0], fix=False))
    q = svc.load(p.id)
    s = find(q, ids[0]).scene3d
    assert rep.status == "rendered" and s.renderer == "blender", s.notes
    assert set(s.plan.models) == {who["Guru"], who["Disciple"]}
    disciple = next(t for t in s.plan.things if t.actor_id == who["Disciple"])
    assert disciple.model == who["Disciple"] and any(k.pose == "touch_ground" for k in disciple.keys)
    assert not models3d.needed_items(q) or all(c.model3d.status == "built" for c in models3d.needed_items(q))
    # a model that is changed makes the preview (and the film) out of date
    s3.approve(svc, p.id, ids[0])
    asyncio.run(models3d.build_model(svc, p.id, who["Guru"], change="make the robe blue"))
    q = svc.load(p.id)
    assert "3D model of Guru changed" in s3.models_changed(q, find(q, ids[0]))
    assert s3.ready_reference(q, find(q, ids[0])) is None
    assert find_item(q, who["Guru"]).model3d.changes == ["make the robe blue"]


# ----------------------------------------------------------------- choosing the agent's model
def test_you_choose_the_model_each_agent_uses_for_3d_work(svc, monkeypatch, tmp_path):
    p, ids, who = guru_project(svc, monkeypatch)
    q = svc.load(p.id)
    q.settings.scene3d.agent_models = {"fake_agent": "opus"}
    svc.save(q)
    task = AgentTask(folder=tmp_path, instructions="x", role="checker")
    asyncio.run(ag._call(svc, p.id, "fake_agent", task, "test"))
    assert task.model == "opus"
    exe = tmp_path / "tool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("VG_CLAUDE", str(exe))
    monkeypatch.setenv("VG_CODEX", str(exe))
    cmd = ClaudeCodeAgent().command(AgentTask(folder=tmp_path, instructions="x", model="sonnet"))
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    cmd = CodexAgent().command(AgentTask(folder=tmp_path, instructions="x", model="gpt-5.1-codex"))
    assert cmd[cmd.index("-m") + 1] == "gpt-5.1-codex" and cmd[-1] == "x"
    assert "--model" not in ClaudeCodeAgent().command(AgentTask(folder=tmp_path, instructions="x"))


def test_the_screen_builds_and_opens_a_model(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    p, ids, who = guru_project(svc, monkeypatch)
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/context/{who['Guru']}/model3d/open")
        assert r.status_code == 400 and "has not been built yet" in r.json()["detail"]
        v = client.post(f"/api/projects/{p.id}/context/{who['Guru']}/model3d/brief").json()
        guru = next(c for c in v["project"]["context"] if c["id"] == who["Guru"])
        assert guru["model3d"]["brief"]["kind"] == "character"
