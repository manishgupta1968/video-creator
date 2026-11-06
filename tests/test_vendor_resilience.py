"""First real run: a picture model the key cannot use must not stop the clip; keys are checked with free calls."""
import asyncio
from pathlib import Path

import httpx
import openai
import pytest

from video_generator import doctor
from video_generator import media
from video_generator.plugins.base import ImageRequest, PluginError, Usage
from video_generator.plugins.image import openai_image as oi
from video_generator.project import ProjectStore
from video_generator.runner import Engine


# ------------------------------------------------------------------ choosing the newest picture model
def test_picks_the_newest_gpt_image_model():
    ids = ["gpt-5", "gpt-image-1", "gpt-image-1.5", "gpt-image-1-mini", "gpt-image-1.5-2026-01-01", "dall-e-3", "whisper-1"]
    assert oi.pick_image_model(ids) == "gpt-image-1.5"
    assert oi.pick_image_model(ids + ["gpt-image-2"]) == "gpt-image-2"
    assert oi.pick_image_model(["gpt-image-1"], avoid="gpt-image-1") == ""            # never the one that just failed
    assert oi.pick_image_model(["gpt-5", "dall-e-3"]) == ""


# ------------------------------------------------------------------ OpenAI plugin heals a wrong model name
def status_error(code: int, message: str):
    req = httpx.Request("POST", "https://api.openai.com/v1/images/edits")
    return openai.APIStatusError(message, response=httpx.Response(code, request=req), body={"error": {"message": message}})


class FakeOpenAI:
    """Pretends to be OpenAI: only `works` is a real model for this key."""
    def __init__(self, works="gpt-image-2", listed=("gpt-5", "gpt-image-2"), error=None):
        self.calls, self.works, self.listed, self.error = [], works, listed, error
        outer = self

        class Images:
            async def edit(self, model, image, prompt, size):
                return await outer._img(model)

            async def generate(self, model, prompt, size):
                return await outer._img(model)

        class Models:
            def list(self):
                async def gen():
                    for i in outer.listed:
                        yield type("M", (), {"id": i})()
                return gen()
        self.images, self.models = Images(), Models()

    async def _img(self, model):
        self.calls.append(model)
        if self.error:
            raise self.error
        if model != self.works:
            raise status_error(400, f"The model '{model}' does not exist.")
        import base64
        return type("R", (), {"data": [type("D", (), {"b64_json": base64.b64encode(b"PNGDATA").decode(), "url": None})()]})()


def run_openai(monkeypatch, tmp_path, fake, refs=True):
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda: fake)
    oi._WORKS.clear()
    ref = tmp_path / "r.png"
    ref.write_bytes(b"x")
    req = ImageRequest(prompt="lion", out=tmp_path / "o.png", model="gpt-image-1", references=[ref] if refs else [])
    return asyncio.run(oi.OpenAIImage().generate(req))


@pytest.mark.parametrize("refs", [True, False])
def test_wrong_model_name_is_replaced_by_one_the_key_can_use(monkeypatch, tmp_path, refs):
    fake = FakeOpenAI()
    out, usage = run_openai(monkeypatch, tmp_path, fake, refs)
    assert out.read_bytes() == b"PNGDATA" and fake.calls == ["gpt-image-1", "gpt-image-2"]
    fake.calls.clear()                                                             # remembered: no second wrong try
    asyncio.run(oi.OpenAIImage().generate(ImageRequest(prompt="x", out=tmp_path / "p.png", model="gpt-image-1")))
    assert fake.calls == ["gpt-image-2"]


def test_no_usable_openai_picture_model_gives_a_clear_error(monkeypatch, tmp_path):
    with pytest.raises(PluginError, match="not available to your key"):
        run_openai(monkeypatch, tmp_path, FakeOpenAI(works="none", listed=("gpt-5",)))


def test_unverified_organisation_gets_plain_instructions(monkeypatch, tmp_path):
    err = status_error(403, "Your organization must be verified to use the model `gpt-image-1`.")
    with pytest.raises(PluginError, match="Verify Organization"):
        run_openai(monkeypatch, tmp_path, FakeOpenAI(error=err))


# ------------------------------------------------------------------ the engine moves on to another picture model
def test_engine_falls_back_to_the_next_picture_model_and_charges_only_that_one(svc, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("FAL_KEY", "x")
    svc.reload()
    p = svc.new_project("A lion", seconds=8, quality_mode="balanced")
    svc.save(p)
    first = svc.reg.choose("image", mode="balanced")
    others = [e for e in svc.reg.candidates("image", mode="balanced") if e.id != first.id and not e.is_free]
    assert others, "a second real picture model must be usable for this test"

    async def bad(req):
        raise PluginError("The model does not exist")

    async def good(req):
        Path(req.out).write_bytes(b"PNG")
        return req.out, Usage()
    monkeypatch.setattr(svc.reg.plugin(first.plugin), "generate", bad)
    for e in others:
        if e.plugin != first.plugin:
            monkeypatch.setattr(svc.reg.plugin(e.plugin), "generate", good)
    eng = Engine(svc)
    used, _ = asyncio.run(eng._make_image(p.id, first, lambda e: ImageRequest(prompt="x", out=tmp_path / "k.png", model=e.model), "keyframe t"))
    assert used.id != first.id and (tmp_path / "k.png").exists()
    rows = [r for r in ProjectStore.ledger(p.id) if r.get("kind") == "image"]
    assert len(rows) == 1 and rows[0]["catalog_id"] == used.id and f"because {first.id} failed" in rows[0]["what"]


def test_engine_reports_every_model_that_failed(svc, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    svc.reload()
    p = svc.new_project("A lion", seconds=8)
    svc.save(p)
    first = svc.reg.choose("image", mode="balanced")

    async def bad(req):
        raise PluginError("model gone")
    monkeypatch.setattr(svc.reg.plugin(first.plugin), "generate", bad)
    with pytest.raises(PluginError, match=f"No picture model worked.*{first.id}: model gone"):
        asyncio.run(Engine(svc)._make_image(p.id, first, lambda e: ImageRequest(prompt="x", out=tmp_path / "k.png", model=e.model), "keyframe t"))


# ------------------------------------------------------------------ vg doctor: free checks only
def mock(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def by_name(checks):
    return {c.name: c for c in checks}


def test_doctor_without_keys_skips_everything():
    checks = asyncio.run(doctor.run_checks(client=mock(lambda r: pytest.fail("no key, so no web call"))))
    assert {c.status for c in checks} == {doctor.SKIP}


def test_doctor_reports_good_and_bad_keys_in_plain_words(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    monkeypatch.setenv("FAL_KEY", "fal-test")
    calls = []

    def handler(r: httpx.Request):
        calls.append((r.method, r.url.host, r.url.path, r.content))
        if r.url.host == "api.openai.com":
            return httpx.Response(200, json={"data": [{"id": "gpt-5"}, {"id": "gpt-image-2"}]})
        if r.url.path == "/v1/user":
            return httpx.Response(200, json={"subscription": {"tier": "free", "character_count": 1000, "character_limit": 10000}})
        if r.url.path == "/v1/voices":
            return httpx.Response(200, json={"voices": [{"voice_id": "a", "labels": {"gender": "male"}}, {"voice_id": "b", "labels": {"gender": "female"}}]})
        if r.url.path == "/v1/models":
            return httpx.Response(200, json=[{"model_id": "eleven_v3"}, {"model_id": "eleven_flash_v2_5"}])
        return httpx.Response(403, text='{"detail": "Exhausted balance. User is locked."}')
    checks = by_name(asyncio.run(doctor.run_checks(client=mock(handler))))
    assert checks["OpenAI pictures"].status == doctor.OK and "gpt-image-2" in checks["OpenAI pictures"].message
    assert "9,000 characters left" in checks["ElevenLabs key"].message
    assert checks["ElevenLabs voice copy"].status == doctor.WARN and checks["ElevenLabs voice model"].status == doctor.OK
    assert checks["ElevenLabs voices"].status == doctor.OK and "1 male, 1 female" in checks["ElevenLabs voices"].message
    assert checks["fal.ai key"].status == doctor.BAD and "billing" in checks["fal.ai key"].message
    # only reading, plus empty permission probes ({}), which cannot make or charge anything
    assert all(m == "GET" or (m == "POST" and host == "api.elevenlabs.io" and body == b"{}") for m, host, _, body in calls)


def test_doctor_rejected_keys_and_restricted_elevenlabs_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "bad")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "limited")

    def handler(r: httpx.Request):
        if r.url.host == "api.openai.com":
            return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})
        if r.url.path in ("/v1/user", "/v1/voices"):
            return httpx.Response(401, json={"detail": {"status": "missing_permissions"}})
        return httpx.Response(200, json=[{"model_id": "eleven_v3"}])
    checks = by_name(asyncio.run(doctor.run_checks(client=mock(handler))))
    assert checks["OpenAI"].status == doctor.BAD and "api-keys" in checks["OpenAI"].message
    assert checks["ElevenLabs key"].status == doctor.OK and "limited permissions" in checks["ElevenLabs key"].message
    assert checks["ElevenLabs voices"].status == doctor.WARN and "Voices: Read" in checks["ElevenLabs voices"].message


def test_doctor_command_prints_a_summary(monkeypatch):
    from typer.testing import CliRunner
    from video_generator.cli import app
    out = CliRunner().invoke(app, ["doctor"])
    assert out.exit_code == 0 and "No problems found" in out.output


# ------------------------------------------------------------------ a key without a permission: plain words, next model, no crash
MUSIC_PERMISSION = ('{"detail":{"type":"authentication_error","code":"unauthorized","message":"The API key you used is missing the permission '
                    'music_generation to execute this operation.","status":"missing_permissions"}}')


def test_permission_errors_are_explained_in_plain_words():
    from video_generator.plugins.base import PermissionProblem, permission_in, raise_for
    assert permission_in(401, MUSIC_PERMISSION) == "music_generation" and permission_in(401, "Incorrect API key") is None
    assert permission_in(500, MUSIC_PERMISSION) is None
    with pytest.raises(PermissionProblem) as ei:
        raise_for(httpx.Response(401, text=MUSIC_PERMISSION), "ElevenLabs Music")
    msg = str(ei.value)
    assert "missing the permission 'music_generation'" in msg and "API-key settings" in msg and "Nothing was charged" in msg
    assert ei.value.retry_other_model is True and ei.value.permission == "music_generation"


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg not installed")
def test_music_without_permission_falls_back_then_is_skipped_with_a_visible_note(svc, monkeypatch, tmp_path):
    from video_generator.plugins.base import PermissionProblem
    from .fake_vendors import Vendors
    from .test_scenarios import build, clip, run_all
    v = Vendors(svc, monkeypatch)

    async def refused(prompt, seconds, out, model="", reference=None):
        raise PermissionProblem("ElevenLabs Music: your ElevenLabs key is missing the permission 'music_generation'.", "music_generation")
    monkeypatch.setattr(svc.reg.plugin("elevenlabs_music"), "generate", refused)
    seen = []

    async def fal_music(prompt, seconds, out, model="", reference=None):
        seen.append(model)
        media.ff("-f", "lavfi", "-i", f"sine=frequency=330:d={max(seconds, 1):.1f}", "-ac", "2", str(out))
        return out, Usage(seconds=seconds)
    monkeypatch.setattr(svc.reg.plugin("fal_music"), "generate", fal_music)
    p, ids = build(svc, "Hills", [], [clip("landscape", "Hills", sound="wind")], music=True)
    run_all(svc, p.id)
    q = svc.load(p.id)
    assert q.final_output and seen == ["fal-ai/minimax-music/v2"] and q.final_notes == []           # the next music model took over
    # the music is made ONCE: joining again reuses the saved track, so no music vendor is asked (and none can refuse)
    monkeypatch.setattr(svc.reg.plugin("fal_music"), "generate", refused)
    from video_generator.runner import Engine
    asyncio.run(Engine(svc)._assemble(p.id))
    q = svc.load(p.id)
    assert q.final_output and q.final_notes == []
    # new music is asked for on purpose and every music model refuses: the video is still made, and the user is told why
    asyncio.run(Engine(svc)._assemble(p.id, "new"))
    q = svc.load(p.id)
    assert q.final_output and any("music_generation" in n for n in q.final_notes)
    assert any("music_generation" in i["text"] for i in svc.summary(q)["guide"]["issues"])         # and the guide shows it


def test_doctor_names_a_missing_elevenlabs_permission(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")

    def handler(r: httpx.Request):
        if r.method == "POST" and r.url.path == "/v1/music":
            return httpx.Response(401, text=MUSIC_PERMISSION)
        if r.method == "POST":
            return httpx.Response(422, json={"detail": "invalid body"})
        if r.url.path == "/v1/user":
            return httpx.Response(200, json={"subscription": {"tier": "creator", "character_count": 1, "character_limit": 100}})
        if r.url.path == "/v1/voices":
            return httpx.Response(200, json={"voices": []})
        return httpx.Response(200, json=[{"model_id": "eleven_v3"}])
    checks = {c.name: c for c in asyncio.run(doctor.run_checks(client=mock(handler)))}
    assert checks["ElevenLabs permission: music"].status == doctor.WARN and "music_generation" in checks["ElevenLabs permission: music"].message
    assert checks["ElevenLabs permission: sound effects"].status == doctor.OK
