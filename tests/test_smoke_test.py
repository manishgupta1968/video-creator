"""vg smoke-test: a tiny real test of each vendor with a spending limit. Vendors are faked here."""
import asyncio
from pathlib import Path

import pytest
from PIL import Image

from video_generator import media, smoketest
from video_generator.plugins.base import PluginError, Usage
from video_generator.project import ProjectStore

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


def vendors(svc, monkeypatch, wan_refuses=False, picture_fails=False):
    for k in ("FAL_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(k, "x")
    svc.reload()
    reg = svc.reg
    calls = []

    async def synth(text, voice, out, model=""):
        calls.append(("voice", model))
        hz = 115 if (voice.voice_id or "").startswith("m") else 225
        media.ff("-f", "lavfi", "-i", f"sine=frequency={hz}", "-t", "1.6", str(out))
        return out, Usage()

    async def match(description, language="en"):
        return "voice-1"

    async def picture(req):
        calls.append(("picture", req.model))
        if picture_fails:
            raise PluginError("The model does not exist", retry_other_model=True)
        Image.new("RGB", (640, 360), (180, 140, 60)).save(req.out)
        return req.out, Usage()

    async def video(req):
        calls.append(("video", req.model))
        if wan_refuses and "wan/v2.6" in req.model:
            raise PluginError("fal.ai has no model called 'wan/v2.6/image-to-video'", retry_other_model=True)
        media.ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(req.out))
        return req.out, Usage()

    async def avatar(req):
        calls.append(("avatar", req.model))
        media.ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=24", "-i", str(req.audio), "-t", "1.6", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(req.out))
        return req.out, Usage()
    eleven = reg.plugin("elevenlabs")

    async def list_voices():
        return [{"voice_id": "m1", "name": "Marcus", "labels": {"gender": "male", "age": "middle_aged", "description": "deep"}},
                {"voice_id": "f1", "name": "Anna", "labels": {"gender": "female", "age": "young", "description": "bright"}}]

    async def sfx(prompt, seconds, out, model="", video=None, params=None):
        calls.append(("sfx", model))
        media.ff("-f", "lavfi", "-i", f"anoisesrc=color=pink:r=44100:d={seconds:.2f},volume=0.3", "-ac", "2", str(out))
        return out, Usage()
    monkeypatch.setattr(eleven, "list_voices", list_voices)
    monkeypatch.setattr(eleven, "synthesize", synth)
    monkeypatch.setattr(eleven, "match", match)
    monkeypatch.setattr(reg.plugin("fal_mmaudio"), "generate", sfx)
    for name in ("gpt_image", "fal_image"):
        monkeypatch.setattr(reg.plugin(name), "generate", picture)
    monkeypatch.setattr(reg.plugin("fal"), "generate", video)
    monkeypatch.setattr(reg.plugin("fal_avatar"), "generate", avatar)
    return calls


def run(svc, tmp_path, **kw):
    said = []
    kw.setdefault("ask", None)
    rep = asyncio.run(smoketest.run(svc, workdir=tmp_path, say=said.append, **kw))
    return rep, said


def status(rep):
    return {r.step: r for r in rep.results}


def no_leftover_projects(svc):
    return not any("Smoke test" in (p.get("name", "") if isinstance(p, dict) else getattr(p, "name", "")) for p in ProjectStore.list())


def test_every_step_runs_and_a_test_video_is_saved(svc, monkeypatch, tmp_path):
    calls = vendors(svc, monkeypatch)
    rep, said = run(svc, tmp_path, max_usd=2.0)
    st = status(rep)
    assert [st[k].status for k in ("Keys", "Voice", "Picture", "Video", "Sound", "Talking lion", "Join")] == ["ok"] * 7, rep.text()
    assert {c[0] for c in calls} == {"voice", "picture", "video", "avatar", "sfx"}
    assert "voice Marcus (male)" in st["Voice"].detail and "pitch 11" in st["Voice"].detail      # the report names the voice and its pitch
    assert (tmp_path / "smoke-test.mp4").exists() and (tmp_path / "smoke-test-report.txt").exists()
    assert 0.3 < rep.spent < 1.5 and st["Video"].cost > 0.2                 # Wan bills 5 s even for a short test
    assert "All steps worked" in rep.text() and any("Estimated total" in s for s in said)
    assert no_leftover_projects(svc)                                        # the scratch project is deleted


def test_nothing_is_spent_without_a_yes(svc, monkeypatch, tmp_path):
    calls = vendors(svc, monkeypatch)
    asked = []
    rep, _ = run(svc, tmp_path, ask=lambda q: asked.append(q) or False)
    assert asked and "Spend up to about $" in asked[0]
    assert calls == [] and rep.spent == 0 and rep.results[0].step == "Cancelled"


def test_the_spending_limit_stops_steps_that_would_cross_it(svc, monkeypatch, tmp_path):
    vendors(svc, monkeypatch)
    rep, _ = run(svc, tmp_path, max_usd=0.2)
    st = status(rep)
    assert st["Video"].status == "skip" and "limit" in st["Video"].detail
    assert rep.spent <= 0.2 + 1e-6


def test_a_failing_step_does_not_stop_the_next_ones(svc, monkeypatch, tmp_path):
    vendors(svc, monkeypatch, picture_fails=True)
    rep, _ = run(svc, tmp_path, max_usd=2.0)
    st = status(rep)
    assert st["Picture"].status == "bad" and "does not exist" in st["Picture"].detail
    assert st["Video"].status == "ok"                                      # a placeholder start picture is used
    assert st["Talking lion"].status == "skip" and "needs the picture" in st["Talking lion"].detail
    assert "1 step(s) failed" in rep.text()


def test_the_next_video_model_is_tried_when_the_first_is_refused(svc, monkeypatch, tmp_path):
    calls = vendors(svc, monkeypatch, wan_refuses=True)
    rep, _ = run(svc, tmp_path, max_usd=3.0)
    v = status(rep)["Video"]
    video_calls = [c[1] for c in calls if c[0] == "video"]
    assert video_calls[0].startswith("wan/v2.6") and len(video_calls) >= 2           # Wan was tried first, then another model
    assert v.status == "warn" and v.model != "wan_2_6"                              # it worked, but the report flags the bad first choice
    assert "no model called 'wan/v2.6/image-to-video'" in v.detail
    assert "needed another model to take over" in rep.text()
    assert "Join" in status(rep) and status(rep)["Join"].status == "ok"


def test_without_keys_every_paid_step_is_skipped_with_advice(svc, tmp_path):
    rep, _ = run(svc, tmp_path, max_usd=1.0)
    st = status(rep)
    assert all(st[k].status == "skip" for k in ("Keys", "Voice", "Picture", "Video", "Talking lion", "Join"))
    assert "FAL_KEY" in st["Video"].detail and rep.spent == 0
    assert "Nothing was tested" in rep.text() and "All steps worked" not in rep.text()


def test_cli_wiring(monkeypatch, tmp_path):
    from typer.testing import CliRunner
    from video_generator.cli import app
    seen = {}

    async def fake_run(svc, max_usd, ask, say=print, workdir=None, all_video=False):
        seen.update(max_usd=max_usd, ask=ask, all_video=all_video)
        say("hello from the test")
        return smoketest.Report(results=[smoketest.Result("Voice", "ok", "eleven_v3", cost=0.002)], spent=0.002, limit=max_usd)
    monkeypatch.setattr(smoketest, "run", fake_run)
    out = CliRunner().invoke(app, ["smoke-test", "--yes", "--max-usd", "0.5"])
    assert out.exit_code == 0 and seen == {"max_usd": 0.5, "ask": None, "all_video": False}
    assert "✓ Voice" in out.output and "hello from the test" in out.output
    CliRunner().invoke(app, ["smoke-test"], input="n\n")
    assert callable(seen["ask"])                                            # without --yes the CLI asks first
