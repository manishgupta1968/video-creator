"""The "Your next step" guide: reads the project as it is and says what to do next. Plain rules, no AI."""
import asyncio

import pytest

from video_generator import guide as G
from video_generator.models import (ActorDetails, ClipScript, Consent, ContextItem, ContextRole, ContextType, DialogueLine, Node,
                                    NodeKind, NodeStatus, Review, ShotType)
from video_generator.tree import add_child, leaves

from .fake_vendors import Vendors


def project(svc, n_clips=2, **settings):
    p = svc.new_project("Guide test", seconds=4 * n_clips, quality_mode="balanced")
    p.settings.budget_usd = 20
    for k, v in settings.items():
        setattr(p.settings, k, v)
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Story", goal="story", target_seconds=4.0 * n_clips))
    for i in range(n_clips):
        c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"Shot {i + 1}", goal="hills", target_seconds=4.0))
        c.script = ClipScript(shot_type=ShotType.landscape, visual="hills", sound_notes="wind")
    svc.save(p)
    return svc.load(p.id)


def guide(svc, p):
    return svc.summary(svc.load(p.id) if isinstance(p, str) else p)["guide"]


def cur(g):
    return g["current"]


def test_a_brand_new_project_without_keys_starts_with_connecting_services(svc):
    p = project(svc)
    g = guide(svc, p)
    assert cur(g) == "services" and g["action"]["kind"] == "settings" and "AI brain" in g["why"]
    assert [s["id"] for s in g["steps"]] == ["services", "plan", "cast", "cost", "make", "join", "finish"]
    assert sum(1 for s in g["steps"] if s["state"] == "current") == 1                      # always exactly one current step
    assert g["progress"]["total"] == 7


def test_free_preview_mode_does_not_nag_about_keys(svc):
    p = project(svc, quality_mode="free")
    assert guide(svc, p)["steps"][0]["state"] == "done" or "AI brain" in guide(svc, p)["why"]      # only the brain can still be missing
    g = guide(svc, p)
    assert "real video" not in g["steps"][0]["detail"]


def test_with_keys_the_first_blocking_step_is_making_the_first_clip(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p = project(svc)
    g = guide(svc, p)
    by = {s["id"]: s for s in g["steps"]}
    assert by["services"]["state"] == "done" or "brain" in by["services"]["detail"].lower()     # (offline brain may still be missing)
    monkeypatch.setattr(svc.reg, "llm_plugin_name", lambda task="default": "openai")
    g = guide(svc, svc.load(p.id))
    assert cur(g) == "make" and g["action"] == {"kind": "run", "label": "Make the first clip", "mode": "next", "title": "Generate the next clip", "help": "generate-next"}
    assert {s["id"]: s["state"] for s in g["steps"]}["plan"] == "done"


def test_clips_without_scripts_ask_for_scripts(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    monkeypatch.setattr(svc.reg, "llm_plugin_name", lambda task="default": "openai")
    p = project(svc)
    for l in leaves(p):
        l.script = None
    svc.save(p)
    g = guide(svc, p)
    assert cur(g) == "plan" and g["action"]["kind"] == "scripts"


def test_an_empty_project_points_at_breaking_the_goal_down(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    monkeypatch.setattr(svc.reg, "llm_plugin_name", lambda task="default": "openai")
    p = svc.new_project("Nothing yet", seconds=10)
    g = guide(svc, p)
    assert cur(g) == "plan" and g["action"]["kind"] == "show" and g["action"]["help"] == "breakdown"


def ready(svc, monkeypatch, n=2):
    Vendors(svc, monkeypatch)
    monkeypatch.setattr(svc.reg, "llm_plugin_name", lambda task="default": "openai")
    return project(svc, n)


def test_consent_photo_and_voice_problems_come_before_spending(svc, monkeypatch):
    p = ready(svc, monkeypatch)
    person = ContextItem(type=ContextType.actor, title="Meera", actor=ActorDetails(kind="real_person"), files=["inputs/m.png"])
    lion = ContextItem(type=ContextType.actor, title="Kito", actor=ActorDetails(kind="animal"), analysis={"auto_photo_error": "no suitable photo found"})
    p.context += [person, lion]
    svc.save(p)
    g = guide(svc, p)
    assert cur(g) == "cast" and "consent for Meera" in g["why"] and g["action"]["kind"] == "context" and g["action"]["id"] == person.id
    assert any("No photo was found for Kito" in x["text"] for x in g["steps"][2]["also"])        # the rest is listed too
    q = svc.load(p.id)
    next(c for c in q.context if c.title == "Meera").consent = Consent(confirmed=True, statement="self")
    svc.save(q)
    g = guide(svc, q)
    assert cur(g) == "cast" and "No photo was found for Kito" in g["why"]                         # advances after each fix
    q = svc.load(p.id)
    kito = next(c for c in q.context if c.title == "Kito")
    kito.analysis.pop("auto_photo_error")
    kito.actor.voice_note = "no male voice was found; check the voice"
    kito.id and q.root.children[0].children[0].script.dialogue.append(DialogueLine(speaker=kito.id, text="hello"))
    svc.save(q)
    g = guide(svc, q)
    assert cur(g) == "cast" and "Check the voice of Kito" in g["why"] and g["action"]["help"] == "preview-voice"
    q = svc.load(p.id)
    next(c for c in q.context if c.title == "Kito").analysis["voice_user_picked"] = True
    svc.save(q)
    assert cur(guide(svc, q)) == "make"                                                            # a voice the user chose is not nagged about


def test_over_budget_is_current_and_says_how_much(svc, monkeypatch):
    p = ready(svc, monkeypatch)
    p.settings.budget_usd = 0.05
    svc.save(p)
    g = guide(svc, p)
    assert cur(g) == "cost" and "over your budget" in g["why"] and g["action"]["kind"] == "budget"


def with_status(svc, p, *statuses):
    q = svc.load(p.id)
    for leaf, st in zip(leaves(q), statuses):
        leaf.status = st
        if st == NodeStatus.done:
            leaf.output = "clips/x/final.mp4"
    svc.save(q)
    return svc.load(p.id)


def test_failed_pick_running_paused_and_rest(svc, monkeypatch):
    p = ready(svc, monkeypatch, 3)
    q = with_status(svc, p, NodeStatus.done, NodeStatus.failed, NodeStatus.draft)
    leaves(q)[1].warnings = ["failed: fal.ai has no model called 'x'"]
    svc.save(q)
    g = guide(svc, q)
    assert cur(g) == "make" and "Clip 1.2 could not be made" in g["why"] and "no model called" in g["why"] and g["action"]["kind"] == "select"
    q = with_status(svc, p, NodeStatus.done, NodeStatus.needs_pick, NodeStatus.draft)
    g = guide(svc, q)
    assert "pick the best" in g["why"] and g["action"]["help"] == "pick-take"
    q = with_status(svc, p, NodeStatus.done, NodeStatus.draft, NodeStatus.draft)
    g = guide(svc, q)
    assert g["action"]["mode"] == "continue" and "1 of 3" in g["why"]
    q = svc.load(p.id)
    q.run.status = "running"
    svc.save(q)
    g = guide(svc, q)
    assert cur(g) == "make" and g["action"] is None and "Working now" in g["why"]
    q = svc.load(p.id)
    q.run.status = "paused"
    svc.save(q)
    assert guide(svc, q)["action"]["kind"] == "resume"


def test_urgent_work_comes_before_missing_keys(svc):
    p = project(svc)
    q = with_status(svc, p, NodeStatus.done, NodeStatus.failed)
    g = guide(svc, q)
    assert [s["state"] for s in g["steps"]][0] in ("todo", "done") and cur(g) == "make"             # keys are missing, but the failed clip is first


def test_all_clips_done_then_join_then_download(svc, monkeypatch):
    p = ready(svc, monkeypatch)
    q = with_status(svc, p, NodeStatus.done, NodeStatus.done)
    g = guide(svc, q)
    assert cur(g) == "join" and g["action"]["kind"] == "assemble"
    # final video present and up to date
    from video_generator.project import ProjectStore
    q = svc.load(p.id)
    out = ProjectStore.path_for(p.id) / "output"
    out.mkdir(exist_ok=True)
    (out / "final.mp4").write_bytes(b"x")
    q.final_output = "output/final.mp4"
    q.final_hash = ProjectStore.final_signature(q)
    svc.save(q)
    g = guide(svc, q)
    assert cur(g) == "finish" and g["action"]["kind"] == "final" and g["progress"]["done"] >= 5
    # something changes: the final video is out of date
    q = svc.load(p.id)
    leaves(q)[0].target_seconds = 6.0
    q.final_hash = "old"
    svc.save(q)
    g = guide(svc, q)
    assert cur(g) == "join" and g["action"]["label"] == "Update final video"


def test_unfinished_setup_no_longer_blocks_when_everything_is_made(svc, monkeypatch):
    p = ready(svc, monkeypatch)
    q = svc.load(p.id)
    q.context.append(ContextItem(type=ContextType.actor, title="Meera", actor=ActorDetails(kind="real_person"), files=["inputs/m.png"]))
    svc.save(q)
    q = with_status(svc, p, NodeStatus.done, NodeStatus.done)
    g = guide(svc, q)
    assert cur(g) == "join" and {s["id"]: s["state"] for s in g["steps"]}["cast"] == "attention"


def test_review_flags_are_listed_but_do_not_block(svc, monkeypatch):
    p = ready(svc, monkeypatch)
    q = with_status(svc, p, NodeStatus.done, NodeStatus.done)
    q.reviews.append(Review(target=leaves(q)[1].id, verdict="does_not_meet_goal", scores={}, summary="the clip does not match"))
    svc.save(q)
    g = guide(svc, q)
    assert cur(g) == "join" and any("Review Agent" in i["text"] and "clip 1.2" in i["text"] for i in g["issues"])


def test_guide_is_part_of_the_project_view(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as webapp
    c = TestClient(webapp.app)
    r = c.post("/api/projects", data={"goal": "A short test video", "seconds": "8"})
    assert r.status_code in (200, 201), r.text
    pid = r.json().get("id") or r.json()["project"]["id"]
    v = c.get(f"/api/projects/{pid}").json()
    assert v["summary"]["guide"]["steps"] and v["summary"]["guide"]["current"]


def test_a_clip_that_needs_splitting_is_split_before_anything_is_spent(svc, monkeypatch):
    p = ready(svc, monkeypatch)
    q = svc.load(p.id)
    animal = ContextItem(type=ContextType.actor, title="Deer", actor=ActorDetails(kind="animal", voice_gender="female"))
    q.context.append(animal)
    leaf = leaves(q)[0]
    leaf.script.on_camera_speech = True
    leaf.script.motion = "body"
    leaf.script.actors_in_shot = [__import__("video_generator.models", fromlist=["ActorInShot"]).ActorInShot(actor_id=animal.id)]
    leaf.script.dialogue = [DialogueLine(speaker=animal.id, text="Goodbye.")]
    svc.save(q)
    g = guide(svc, q)
    assert cur(g) == "make" and g["action"]["kind"] == "split" and g["action"]["id"] == leaf.id and "Split it first" in g["why"]
