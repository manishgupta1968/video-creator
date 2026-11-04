"""AI brain (vendor parity), consent, review loop, and the offline end-to-end run."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from video_generator.models import NodeStatus
from video_generator.tree import leaves, numbering

from .conftest import requires_ffmpeg


# ------------------------------------------------------------------ brain parity (recorded replies, no network)
REPLY = {"title": "T", "goal": "G", "seconds": 5, "change_summary": "x"}


def _fake_anthropic(monkeypatch, text):
    import anthropic

    class Msgs:
        async def create(self, **kw):
            return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                                   content=[SimpleNamespace(type="text", text=text)])

    class Client:
        messages = Msgs()
        beta = SimpleNamespace(messages=Msgs())
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda *a, **k: Client())


def _fake_openai(monkeypatch, text):
    import openai

    class Comp:
        async def create(self, **kw):
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                                   choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    class Client:
        chat = SimpleNamespace(completions=Comp())
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda *a, **k: Client())


@pytest.mark.parametrize("vendor", ["anthropic", "openai"])
def test_same_brain_task_works_for_both_vendors(vendor, monkeypatch):
    from video_generator.brain import GoalRevision
    from video_generator.config import Config
    from video_generator.registry import Registry
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    _fake_anthropic(monkeypatch, "```json\n" + json.dumps(REPLY) + "\n```")
    _fake_openai(monkeypatch, json.dumps(REPLY))
    reg = Registry(Config())
    plugin = reg.plugin(vendor)
    res, usage = asyncio.run(plugin.generate_json(system="s", user="u", schema=GoalRevision, model=""))
    assert res.goal == "G" and usage.input_tokens == 10


def test_brain_repairs_bad_json_once(monkeypatch):
    from video_generator.brain import GoalRevision
    from video_generator.config import Config
    from video_generator.registry import Registry
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    replies = iter(["not json", json.dumps(REPLY)])

    class Comp:
        async def create(self, **kw):
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))])
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=Comp())))
    res, _ = asyncio.run(Registry(Config()).plugin("openai").generate_json(system="s", user="u", schema=GoalRevision, model=""))
    assert res.title == "T"


# ------------------------------------------------------------------ planning with the offline brain
def test_draft_decompose_and_command(svc):
    p = svc.new_project("A 30-second advert where a presenter introduces our travel bag", seconds=30)
    p = asyncio.run(svc.draft(p.id))
    assert len(p.root.children) >= 2 and all(l.script for l in leaves(p))
    assert any(c.type.value == "actor" for c in p.context)
    first_part = p.root.children[0]
    p = asyncio.run(svc.decompose(p.id, first_part.id))
    assert len(p.root.children[0].children) >= 3
    plan = asyncio.run(svc.plan_command(p.id, "make it shorter", p.root.children[0].id))
    asyncio.run(svc.apply_command(p.id, plan))
    p = svc.load(p.id)
    assert p.root.children[0].target_seconds is not None


def test_text_only_actor_and_photo_actor(svc, sample_photo, sample_voice):
    p = svc.new_project("Priya presents the bag to camera", seconds=10)
    _, a = svc.add_context(p.id, {"type": "actor", "title": "Priya", "actor": {"description": "30s woman, short hair"}})
    _, b = svc.add_context(p.id, {"type": "actor", "title": "Rahul"})
    p = svc.load(p.id)
    svc.add_context_file(p, sample_photo, ctx_id=b.id, save=False)
    svc.add_context_file(p, sample_voice, ctx_id=b.id, save=False)
    svc.save(p)
    p = svc.load(p.id)
    rahul = next(c for c in p.context if c.id == b.id)
    assert rahul.files and rahul.actor.voice_sample and rahul.needs_consent
    assert "voice_check" in rahul.analysis
    svc.give_consent(p.id, b.id, "permission")
    assert next(c for c in svc.load(p.id).context if c.id == b.id).consent.confirmed


# ------------------------------------------------------------------ engine (offline, real ffmpeg)
@requires_ffmpeg
def test_consent_blocks_generation(svc, sample_photo):
    from video_generator.runner import Engine
    p = svc.new_project("Rahul walks to camera", seconds=6)
    p = asyncio.run(svc.draft(p.id))
    _, a = svc.add_context(p.id, {"type": "actor", "title": "Rahul"})
    p = svc.load(p.id)
    svc.add_context_file(p, sample_photo, ctx_id=a.id)
    clip = leaves(svc.load(p.id))[0]
    svc.update_node(p.id, clip.id, {"script": {"actors_in_shot": [{"actor_id": a.id, "clothing": "", "behaviour": ""}]}})
    eng = Engine(svc, stop_when_waiting=True)

    async def go():
        await eng.start(p.id, "clip", [clip.id])
        await eng.runs[p.id].task
    asyncio.run(go())
    n = next(l for l in leaves(svc.load(p.id)) if l.id == clip.id)
    assert n.status == NodeStatus.failed and "Consent" in n.warnings[0]


@requires_ffmpeg
def test_end_to_end_offline_render(svc, sample_pdf, sample_clip):
    """Goal -> draft -> slides + own clip + continues_from link -> next, then continue -> final video."""
    from video_generator import media
    from video_generator.project import ProjectStore
    from video_generator.runner import Engine
    p = svc.new_project("A 20-second video about our bag", seconds=20, files=[sample_pdf, sample_clip], quality_mode="free")
    p = asyncio.run(svc.draft(p.id))
    kinds = [l.kind.value for l in leaves(p)]
    assert "slides" in kinds and "user_clip" in kinds
    clips = [l for l in leaves(p) if l.kind.value == "clip"]
    svc.add_dependency(p.id, clips[0].id, clips[1].id, "continues_from")
    eng = Engine(svc, stop_when_waiting=True)

    async def go(mode):
        await eng.start(p.id, mode)
        await eng.runs[p.id].task
    asyncio.run(go("next"))
    p = svc.load(p.id)
    done = [l for l in leaves(p) if l.status == NodeStatus.done]
    assert len(done) == 1 and p.final_output is None
    asyncio.run(go("continue"))
    p = svc.load(p.id)
    assert all(l.status == NodeStatus.done for l in leaves(p)), [(numbering(p)[l.id], l.status, l.warnings) for l in leaves(p)]
    final = ProjectStore.path_for(p.id) / p.final_output
    assert final.exists() and media.has_video(final) and media.has_audio(final)
    total = media.probe_duration(final)
    assert abs(total - p.root.duration.likely_s) < max(4.0, 0.25 * total)
    second = next(l for l in leaves(p) if l.id == clips[1].id)
    assert second.takes[0].keyframe and "handoff_from" in second.takes[0].keyframe
    dep = next(d for d in p.dependencies if d.to_id == clips[1].id)
    assert dep.payload.get("handoff_frame")
    assert (ProjectStore.path_for(p.id) / "output" / "final.srt").exists()
    assert ProjectStore.ledger(p.id)  # spending log has rows (free tools log $0)


@requires_ffmpeg
def test_review_feedback_and_versions(svc):
    from video_generator.runner import Engine
    p = svc.new_project("A presenter explains our bag", seconds=8, quality_mode="free")
    p = asyncio.run(svc.draft(p.id))
    clip = leaves(p)[0]
    eng = Engine(svc, stop_when_waiting=True)

    async def go():
        await eng.start(p.id, "clip", [clip.id])
        await eng.runs[p.id].task
    asyncio.run(go())
    p = svc.load(p.id)
    n = next(l for l in leaves(p) if l.id == clip.id)
    assert n.takes and n.takes[0].review_id
    review = next(r for r in p.reviews if r.id == n.takes[0].review_id)
    prev = asyncio.run(svc.preview_remake(p.id, n.id, [s.id for s in review.suggestions], "make it slow motion"))
    assert prev["feedback"].startswith("USER FEEDBACK (highest priority): make it slow motion")
    svc.apply_remake(p.id, n.id, prev["new"], prev["feedback"])
    n2 = next(l for l in leaves(svc.load(p.id)) if l.id == clip.id)
    assert n2.version == 2 and n2.status == NodeStatus.ready and n2.versions[-1].feedback
    svc.revert_version(p.id, n.id, 1)
    n3 = next(l for l in leaves(svc.load(p.id)) if l.id == clip.id)
    assert n3.script.visual == n.script.visual


def test_undo_redo(svc):
    p = svc.new_project("goal", seconds=10)
    svc.update_project(p.id, {"name": "Renamed"})
    from video_generator.project import ProjectStore
    assert ProjectStore.undo(p.id).name != "Renamed"
    assert ProjectStore.redo(p.id).name == "Renamed"


def test_api_smoke(monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    with TestClient(appmod.app) as client:
        r = client.post("/api/projects", data={"goal": "A 15 second clip of a sunrise", "seconds": "15"})
        pid = r.json()["id"]
        v = client.get(f"/api/projects/{pid}").json()
        assert v["project"]["goal"].startswith("A 15")
        e = client.post(f"/api/projects/{pid}/estimate", json={"mode": "all"}).json()
        assert "cost_usd" in e and "time_s" in e
        s = client.get("/api/settings").json()
        assert any(x["id"] == "fal" for x in s["vendors"])
        assert client.get("/files/..%2F..%2Fvg/.env").status_code == 404
        assert client.get(f"/files/{pid}/..%2F..%2F.env").status_code in (403, 404)
        assert client.get("/api/projects/..%2Fx").status_code in (400, 404)
