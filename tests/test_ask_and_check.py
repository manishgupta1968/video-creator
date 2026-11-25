"""One "Ask AI" box for the story and the 3D scenes, the session history the agents read, and the AI checker of the
rendered 3D preview (success criteria, feedback to the builder, rounds). Real programs are replaced by stand-ins."""
import asyncio
import json

import pytest

from video_generator.project import ProjectStore
from video_generator.scene3d import agent as ag
from video_generator.scene3d import service as s3
from video_generator.tree import find

from .conftest import requires_ffmpeg
from .test_scene3d_change import project


def camera_distance(svc, pid, nid):
    plan = find(svc.load(pid), nid).scene3d.plan
    k = plan.camera.keys[-1]
    return sum((a - b) ** 2 for a, b in zip(k.at, k.look_at)) ** 0.5


@requires_ffmpeg
def test_the_checker_writes_criteria_gives_feedback_and_the_builder_fixes_until_it_passes(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    asyncio.run(s3.build_clip(svc, p.id, ids[0]))
    ag.remember_ask(svc, p.id, "clip 1.1", "keep Dan in the centre")
    far = camera_distance(svc, p.id, ids[0])
    fake = svc.reg.plugin("fake_agent")
    fake.checker_problems = [["Bring the camera closer to Dan; it is too far at the end."], []]
    rv = asyncio.run(ag.review_clip(svc, p.id, ids[0], rounds=3))
    assert rv.passed and len(rv.rounds) == 2 and "Passed in round 2" in rv.note
    assert any("As the user asked: keep Dan in the centre" in c for c in rv.criteria)      # your requests are criteria
    first = rv.rounds[0]
    assert not first.ok and first.feedback == ["Bring the camera closer to Dan; it is too far at the end."]
    assert first.fixed_by == "fake_agent" and "closer" in first.fix_summary
    assert camera_distance(svc, p.id, ids[0]) < far                                       # the feedback was acted on
    s = find(svc.load(p.id), ids[0]).scene3d
    assert s.review.passed and s.status in ("rendered", "approved") and not s3.stale_reason(find(svc.load(p.id), ids[0]))
    reviewer_runs = [t for t in fake.runs if t.role == "reviewer"]
    assert len(reviewer_runs) == 2 and "RENDERED preview" in reviewer_runs[0].instructions
    folder = reviewer_runs[0].folder
    assert (folder / "render" / "start.png").exists() and "keep Dan in the centre" in (folder / "history.md").read_text()
    builder = [t for t in fake.runs if t.role == "builder"][-1]
    assert "history.md" in builder.instructions and "Bring the camera closer" in builder.instructions


@requires_ffmpeg
def test_the_checker_stops_after_your_number_of_rounds_and_does_not_approve(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    q = svc.load(p.id)
    q.settings.scene3d.ai_check, q.settings.scene3d.check_rounds, q.settings.scene3d.auto_approve = True, 2, True
    svc.save(q)
    fake = svc.reg.plugin("fake_agent")
    fake.checker_problems = [["The camera should be closer to Dan."], ["The camera should be closer still."]]
    rep = asyncio.run(ag.prepare_clip(svc, p.id, ids[0]))          # plan, render, then the AI checker by itself
    assert rep.review is not None and not rep.review.passed and len(rep.review.rounds) == 2
    assert "Not passed after 2 round(s)" in rep.review.note
    s = find(svc.load(p.id), ids[0]).scene3d
    assert s.approved_by == "" and s.status == "rendered"           # not passed: you decide, it is not approved by itself


def test_the_session_history_is_given_to_the_agents_and_the_brain(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    ag.remember_ask(svc, p.id, "the whole video", "the camera low, at eye level, everywhere", "3D: changed clips 1.1, 1.2")
    text = ag.session_history(svc.load(p.id))
    assert "the whole video: the camera low, at eye level, everywhere" in text and "→ 3D: changed clips 1.1, 1.2" in text
    from video_generator.brain import render
    assert "WHAT HAPPENED SO FAR IN THIS SESSION" in render("scene_change", history=text)
    assert "{history}" not in render("film_change", history=text) and text in render("film_change", history=text)


@requires_ffmpeg
def test_one_ask_box_sends_camera_requests_to_the_3d_scene_and_story_requests_to_the_script(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/nodes/{ids[0]}/ask", json={"request": "bring the camera closer"}).json()
        assert r["scene"] == "bring the camera closer" and r["story"] == ""
        for _ in range(300):
            h = svc.load(p.id).ask_history
            if h and "3D:" in h[-1].result:
                break
            asyncio.run(asyncio.sleep(0.1))
        h = svc.load(p.id).ask_history
        assert h[-1].where == "clip 1.1" and h[-1].request == "bring the camera closer" and "3D:" in h[-1].result
        assert find(svc.load(p.id), ids[0]).scene3d.changes == ["bring the camera closer"]
        r = client.post(f"/api/projects/{p.id}/nodes/{ids[0]}/ask", json={"request": "make it more cheerful"}).json()
        assert r["story"] == "make it more cheerful" and r["scene"] == ""
        assert "Story changed." in svc.load(p.id).ask_history[-1].result
        assert client.post(f"/api/projects/{p.id}/nodes/{ids[0]}/ask", json={"request": " "}).status_code == 400


def test_without_3d_the_ask_box_changes_the_story_as_before(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    p, ids = project(svc, monkeypatch)
    q = svc.load(p.id)
    q.settings.scene3d.enabled = False
    svc.save(q)
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/nodes/{ids[0]}/ask", json={"request": "bring the camera closer"}).json()
    assert r["story"] == "bring the camera closer" and r["scene"] == ""
    assert svc.load(p.id).ask_history[-1].result == "Story changed."
