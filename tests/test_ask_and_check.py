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


@requires_ffmpeg
def test_check_and_fix_runs_the_ai_even_when_the_measured_checks_pass(svc, monkeypatch):
    """The old "Fix with Codex" button stopped at once when the free measured checks found nothing: no AI ran and
    nothing was said. "Check and fix" always lets the AI checker look at the rendered preview, and the builder act."""
    from fastapi.testclient import TestClient
    from video_generator.scene3d.spec import check
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    asyncio.run(s3.build_clip(svc, p.id, ids[0]))
    assert not any(i.severity == "major" for i in check(find(svc.load(p.id), ids[0]).scene3d.plan))   # nothing measured
    fake = svc.reg.plugin("fake_agent")
    fake.checker_problems = [["The disciple's head goes under the guru's feet; bring the camera closer to see it."], []]
    with TestClient(appmod.app) as client:
        assert client.post(f"/api/projects/{p.id}/nodes/{ids[0]}/scene3d/fix", json={}).json() == {"ok": True}
        for _ in range(300):
            rv = find(svc.load(p.id), ids[0]).scene3d.review
            if rv and rv.note:
                break
            asyncio.run(asyncio.sleep(0.1))
    s = find(svc.load(p.id), ids[0]).scene3d
    assert s.review.passed and len(s.review.rounds) == 2 and s.review.rounds[0].fixed_by == "fake_agent"
    assert [t.role for t in fake.runs].count("reviewer") == 2
    assert any("measured checks found no problem, so the AI checker looks" in line for line in s.agent_log)


@requires_ffmpeg
def test_the_button_first_fixes_what_the_checker_already_found(svc, monkeypatch):
    """The checker failed the preview and wrote feedback; pressing the button must act on THAT feedback straight away
    (no new check first), then render and check again. Criteria written under the older, stricter rules are written
    again under the fair ones."""
    p, ids = project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    asyncio.run(s3.build_clip(svc, p.id, ids[0]))
    fake = svc.reg.plugin("fake_agent")
    fake.checker_problems = [["Bring the camera closer to Dan; he is too small at the end."]]
    rv = asyncio.run(ag.review_clip(svc, p.id, ids[0], rounds=1))           # the check you already ran: not passed
    assert not rv.passed and rv.rounds[-1].feedback and not rv.rounds[-1].fixed_by
    far = camera_distance(svc, p.id, ids[0])
    fake.runs.clear()
    fake.checker_problems = [[]]                                            # after the fix, the next check passes
    rv = asyncio.run(ag.check_and_fix(svc, p.id, ids[0], rounds=2))
    roles = [t.role for t in fake.runs]
    assert roles[0] == "builder" and roles.count("reviewer") == 1           # fixed first, then checked once
    assert "Bring the camera closer to Dan" in fake.runs[0].instructions
    assert camera_distance(svc, p.id, ids[0]) < far
    assert rv.passed and [r.round for r in rv.rounds] == [1, 2]             # the earlier round is kept
    assert rv.rounds[0].fixed_by == "fake_agent" and "acted on the checker's feedback" in rv.rounds[0].fix_summary
    # criteria written under older rules are written again
    q = svc.load(p.id)
    find(q, ids[0]).scene3d.review.rules = 1
    svc.save(q)
    fake.checker_problems = [[]]
    rv = asyncio.run(ag.review_clip(svc, p.id, ids[0], rounds=1))
    assert rv.rules == ag.CRITERIA_RULES and [r.round for r in rv.rounds] == [1]
    assert "Never about what happens BETWEEN the frames" in ag.REVIEW_TASK


def test_reading_a_project_does_not_change_it(svc, monkeypatch):
    """The screen reads the project every few seconds. Reading used to save it with a new 'last saved' time, so every
    panel tied to that time reloaded: the right panel flickered and open cards closed by themselves."""
    import time
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    p, _ = project(svc, monkeypatch)
    with TestClient(appmod.app) as client:
        first = client.get(f"/api/projects/{p.id}").json()["project"]["updated_at"]
        time.sleep(1.1)
        second = client.get(f"/api/projects/{p.id}").json()["project"]["updated_at"]
    assert first == second
