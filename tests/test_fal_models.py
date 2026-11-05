"""fal.ai: model names and field names, queue URLs, billing by the length the model really makes, video fall-back."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from video_generator import doctor, estimate as E
from video_generator.catalog import Catalog
from video_generator.models import ClipScript, Node, NodeKind, ShotType
from video_generator.plugins import fal_common
from video_generator.plugins.base import PluginError, Usage, VideoRequest
from video_generator.plugins.video import fal as fal_video
from video_generator.project import ProjectStore
from video_generator.runner import Engine
from video_generator.tree import add_child, leaves


def entry(id_):
    return Catalog.load().get(id_)


# ------------------------------------------------------------------ the catalogue itself
def test_fal_model_names_are_the_ones_fal_lists():
    cat = Catalog.load()
    ids = {e.id: e.model for e in cat.entries if e.vendor == "fal"}
    assert ids["wan_2_6"] == "wan/v2.6/image-to-video"
    assert ids["seedance_2"] == "bytedance/seedance-2.0/image-to-video"
    assert ids["seedance_2_fast"] == "bytedance/seedance-2.0/fast/image-to-video"
    assert ids["kling_3"] == "fal-ai/kling-video/v3/pro/image-to-video"
    assert ids["kling_avatar"] == "fal-ai/kling-video/ai-avatar/v2/pro"
    assert not any("wan/v3" in m or "seedance/v2" in m for m in ids.values())        # names that do not exist on fal.ai
    for e in cat.entries:
        if e.vendor == "fal":
            assert e.last_checked and e.pricing_url, e.id


# ------------------------------------------------------------------ payloads
def req(entry_id, seconds=4, start=True, tmp=None, end=False):
    e = entry(entry_id)
    f = None
    if start:
        f = tmp / "s.png"
        f.write_bytes(b"\x89PNG")
    g = None
    if end:
        g = tmp / "e.png"
        g.write_bytes(b"\x89PNG")
    return VideoRequest(prompt="a lion", out=tmp / "o.mp4", model=e.model, seconds=seconds, aspect="16:9", resolution="1080p",
                        start_frame=f, end_frame=g, negative="blur", audio=bool(e.capabilities.get("native_audio")),
                        camera="slow push-in", params=dict(e.params))


def test_kling_uses_start_image_url_and_seedance_wan_use_image_url(tmp_path):
    kling = fal_video.build_payload(req("kling_3", 4, tmp=tmp_path, end=True))
    assert "start_image_url" in kling and "image_url" not in kling and "end_image_url" in kling
    assert kling["duration"] == "4" and kling["generate_audio"] is True and "tail_image_url" not in kling
    wan = fal_video.build_payload(req("wan_2_6", 4, tmp=tmp_path))
    assert "image_url" in wan and "start_image_url" not in wan and "end_image_url" not in wan
    assert wan["resolution"] == "720p" and "generate_audio" not in wan and "aspect_ratio" not in wan
    seed = fal_video.build_payload(req("seedance_2", 4, tmp=tmp_path, end=True))
    assert {"image_url", "end_image_url", "resolution", "aspect_ratio", "generate_audio"} <= set(seed)


def test_durations_are_snapped_up_to_what_the_model_accepts(tmp_path):
    assert fal_video.build_payload(req("wan_2_6", 4, tmp=tmp_path))["duration"] == "5"
    assert fal_video.build_payload(req("wan_2_6", 5, tmp=tmp_path))["duration"] == "5"
    assert fal_video.build_payload(req("wan_2_6", 6, tmp=tmp_path))["duration"] == "10"
    assert fal_video.build_payload(req("kling_3", 2, tmp=tmp_path))["duration"] == "3"
    assert fal_video.build_payload(req("seedance_2", 4, tmp=tmp_path))["duration"] == "4"


def test_empty_fields_are_not_sent(tmp_path):
    r = req("wan_2_6", 4, tmp=tmp_path)
    r.negative = ""
    assert "negative_prompt" not in fal_video.build_payload(r)
    r2 = req("kling_3", 4, start=False, tmp=tmp_path)
    assert "start_image_url" not in fal_video.build_payload(r2)


# ------------------------------------------------------------------ billing and estimate use the length the model makes
def test_billed_seconds():
    assert entry("wan_2_6").billed_seconds(4) == 5 and entry("wan_2_6").billed_seconds(11) == 15
    assert entry("kling_3").billed_seconds(4) == 4 and entry("seedance_2").billed_seconds(2) == 4
    assert entry("kling_avatar").billed_seconds(4.3) == 4.3                       # no list: billed as asked
    assert entry("wan_2_6").billed_seconds(40) == 15


def video_project(svc, mode="balanced"):
    p = svc.new_project("A lion walks", seconds=12, quality_mode=mode)
    p.settings.takes_other = 1
    p.settings.music = False
    p.settings.budget_usd = 3.0
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Walk", goal="walk", target_seconds=12))
    for i in range(3):
        c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"Shot {i + 1}", goal="a lion walks", target_seconds=4))
        c.script = ClipScript(shot_type=ShotType.wildlife, visual="a lion walks through grass", action_beats=["walks"])
    svc.save(p)
    return svc.load(p.id)


def test_estimate_bills_the_five_seconds_wan_really_makes(svc, monkeypatch):
    for k in ("FAL_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.setenv(k, "x")
    svc.reload()
    p = video_project(svc)
    s = svc.summary(p)
    leaf = leaves(p)[0]
    line = next(l for l in leaf.cost.lines if l.item.startswith("Video (wan_2_6)"))
    assert "5 s" in line.calc and "cut to 4 s" in line.calc and abs(line.cost - 0.5) < 0.01
    assert s["seconds"] == 12.0 and s["cost"] < 3.0 and not any("budget" in w.lower() for w in s["warnings"])


# ------------------------------------------------------------------ the fal queue
def patch_http(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(fal_common.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("FAL_KEY", "k")


def queue(handler_log, submit, status=None, result=None):
    def handler(r: httpx.Request):
        handler_log.append((r.method, r.url.path))
        if r.method == "POST":
            return httpx.Response(200, json=submit)
        if r.url.path.endswith("/status"):
            return status(r) if status else httpx.Response(200, json={"status": "COMPLETED"})
        return result(r) if result else httpx.Response(200, json={"video": {"url": "https://v3.fal.media/x.mp4"}})
    return handler


def test_queue_uses_the_urls_fal_returns(monkeypatch):
    log = []
    patch_http(monkeypatch, queue(log, {"request_id": "r1", "status_url": "https://queue.fal.run/wan/v2.6/requests/r1/status",
                                        "response_url": "https://queue.fal.run/wan/v2.6/requests/r1"}))
    out = asyncio.run(fal_common.run("wan/v2.6/image-to-video", {"prompt": "x"}))
    assert out["video"]["url"].endswith("x.mp4")
    assert log == [("POST", "/wan/v2.6/image-to-video"), ("GET", "/wan/v2.6/requests/r1/status"), ("GET", "/wan/v2.6/requests/r1")]


def test_without_urls_the_owner_and_app_only_address_is_built_never_the_path(monkeypatch):
    log = []
    patch_http(monkeypatch, queue(log, {"request_id": "r2"}))
    asyncio.run(fal_common.run("fal-ai/kling-video/v3/pro/image-to-video", {"prompt": "x"}))
    assert log[1:] == [("GET", "/fal-ai/kling-video/requests/r2/status"), ("GET", "/fal-ai/kling-video/requests/r2")]


def test_a_404_on_the_given_result_url_falls_back_to_the_app_only_address(monkeypatch):
    log = []

    def result(r):
        return httpx.Response(404, text="Not Found") if "/v3/" in r.url.path else httpx.Response(200, json={"video": {"url": "https://v3.fal.media/y.mp4"}})
    patch_http(monkeypatch, queue(log, {"request_id": "r3", "response_url": "https://queue.fal.run/fal-ai/kling-video/v3/pro/requests/r3"}, result=result))
    out = asyncio.run(fal_common.run("fal-ai/kling-video/v3/pro/image-to-video", {"prompt": "x"}))
    assert out["video"]["url"].endswith("y.mp4")


def test_unknown_model_path_gets_a_plain_message_and_is_retryable(monkeypatch):
    log = []
    patch_http(monkeypatch, queue(log, {"request_id": "r4"},
                                  result=lambda r: httpx.Response(404, json={"detail": "Path /v3/image-to-video not found"})))
    with pytest.raises(PluginError) as ei:
        asyncio.run(fal_common.run("fal-ai/wan/v3/image-to-video", {"prompt": "x"}))
    assert "no model called 'fal-ai/wan/v3/image-to-video'" in str(ei.value) and "Nothing was charged" in str(ei.value)
    assert ei.value.retry_other_model is True


def test_server_errors_are_not_retried_on_another_model(monkeypatch):
    patch_http(monkeypatch, queue([], {"request_id": "r5"}, result=lambda r: httpx.Response(500, text="boom")))
    with pytest.raises(PluginError) as ei:
        asyncio.run(fal_common.run("wan/v2.6/image-to-video", {"prompt": "x"}))
    assert "HTTP 500" in str(ei.value) and ei.value.retry_other_model is False


# ------------------------------------------------------------------ engine: next video model after a refusal
def setup_engine(svc, monkeypatch):
    for k in ("FAL_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.setenv(k, "x")
    svc.reload()
    p = svc.new_project("A lion walks", seconds=8)
    svc.save(p)
    calls = []
    return p, Engine(svc), calls


def alts(svc, first):
    return [e for e in svc.reg.candidates("video", "wildlife", {"start_frame": True}, "balanced") if e.id != first.id]


def vreq(tmp_path, first):
    s = tmp_path / "s.png"
    s.write_bytes(b"\x89PNG")
    return VideoRequest(prompt="x", out=tmp_path / "o.mp4", model=first.model, seconds=4, start_frame=s, params=dict(first.params))


def test_video_refused_before_work_moves_to_the_next_model_and_only_that_one_is_charged(svc, monkeypatch, tmp_path):
    p, eng, calls = setup_engine(svc, monkeypatch)
    first = svc.reg.choose("video", "wildlife", {"start_frame": True}, mode="balanced")
    assert first.id == "wan_2_6"

    async def gen(req):
        calls.append(req.model)
        if req.model == first.model:
            raise PluginError("fal.ai has no model called 'x'", retry_other_model=True)
        Path(req.out).write_bytes(b"MP4")
        return req.out, Usage()
    monkeypatch.setattr(svc.reg.plugin("fal"), "generate", gen)
    used = asyncio.run(eng._video_parts(p.id, first, vreq(tmp_path, first), "t1", alts(svc, first), None))
    assert used.id != first.id and calls[0] == first.model and len(calls) == 2
    rows = [r for r in ProjectStore.ledger(p.id) if r["kind"] == "video"]
    assert len(rows) == 1 and rows[0]["catalog_id"] == used.id and f"because {first.id} failed" in rows[0]["what"]
    assert abs(rows[0]["actual_usd"] - used.billed_seconds(4) * used.unit_price) < 1e-6


def test_a_server_error_or_timeout_is_not_sent_to_another_model(svc, monkeypatch, tmp_path):
    p, eng, calls = setup_engine(svc, monkeypatch)
    first = svc.reg.choose("video", "wildlife", {"start_frame": True}, mode="balanced")

    async def gen(req):
        calls.append(req.model)
        raise PluginError("fal result: HTTP 500: boom")                  # might already have been billed
    monkeypatch.setattr(svc.reg.plugin("fal"), "generate", gen)
    with pytest.raises(PluginError, match="HTTP 500"):
        asyncio.run(eng._video_parts(p.id, first, vreq(tmp_path, first), "t2", alts(svc, first), None))
    assert len(calls) == 1 and ProjectStore.ledger(p.id) == []


def test_a_free_preview_never_gets_a_paid_fallback(svc, monkeypatch, tmp_path):
    p, eng, calls = setup_engine(svc, monkeypatch)
    free = svc.reg.catalog.get("free_preview")

    async def gen(req):
        calls.append(req.model)
        raise PluginError("x", retry_other_model=True)
    monkeypatch.setattr(svc.reg.plugin("fake_video"), "generate", gen)
    with pytest.raises(PluginError):
        asyncio.run(eng._video_parts(p.id, free, vreq(tmp_path, free), "t3", alts(svc, free), None))
    assert calls == ["ken-burns"]


# ------------------------------------------------------------------ vg doctor
def test_doctor_checks_fal_model_names(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "k")

    def handler(r: httpx.Request):
        if r.url.host == "queue.fal.run":
            return httpx.Response(404, text="request not found")
        wanted = r.url.params.get("endpoint_id")
        if wanted == "wan/v2.6/image-to-video":
            return httpx.Response(200, json={"models": [{"endpoint_id": wanted}]})
        if wanted == "fal-ai/flux-2-pro/edit":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(500, text="oops")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    checks = {c.name: c for c in asyncio.run(doctor.run_checks(client=client, catalog=Catalog.load()))}
    assert checks["fal model wan_2_6"].status == doctor.OK
    assert checks["fal model flux_2"].status == doctor.WARN and "may be out of date" in checks["fal model flux_2"].message
    assert checks["fal model kling_3"].status == doctor.SKIP and "could not check" in checks["fal model kling_3"].message.lower()


def test_doctor_command_sees_keys_saved_in_the_gui(monkeypatch, tmp_path):
    """The GUI saves keys in ~/.video-generator/.env; vg doctor used to ignore them."""
    from typer.testing import CliRunner
    from video_generator.cli import app
    from video_generator.config import vg_home
    (vg_home() / ".env").write_text('OPENAI_API_KEY="sk-from-the-gui"\n')
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = []

    async def fake_run_checks(client=None, catalog=None):
        seen.append(__import__("os").environ.get("OPENAI_API_KEY"))
        return [doctor.Check("OpenAI key", doctor.OK, "Accepted.")]
    monkeypatch.setattr(doctor, "run_checks", fake_run_checks)
    out = CliRunner().invoke(app, ["doctor"])
    assert out.exit_code == 0 and seen == ["sk-from-the-gui"] and "No problems found" in out.output
