"""Step 3 (v3.9): every model is shown so a person can choose: price in words, abilities, and the exact reason a model cannot be used.
Also: choose the AI model per kind of work, price each AI call by the model that really answered, and find models at the vendor."""
import asyncio
import re

import httpx
import pytest

from video_generator import estimate as E
from video_generator import models_list
from video_generator.models import ClipScript, Node, NodeKind, ShotType
from video_generator.plugins.base import Usage
from video_generator.tree import add_child, leaves

from .fake_vendors import Vendors


def row(svc, model_id):
    return next(r for r in svc.model_rows() if r["id"] == model_id)


# ------------------------------------------------------------------ every model, with the reason it cannot be used
def test_every_catalogue_model_is_listed_with_the_exact_reason_it_cannot_be_used(svc, monkeypatch):
    rows = svc.model_rows()
    assert {r["job"] for r in rows} >= {"video", "image", "voice", "avatar", "music", "llm"}
    assert len(rows) == len(svc.catalog.entries)
    kling = row(svc, "kling_3")
    assert not kling["usable"] and kling["why_not"] == "set FAL_KEY"
    assert row(svc, "free_preview")["usable"] and row(svc, "free_preview")["why_not"] == ""
    monkeypatch.setenv("FAL_KEY", "x")
    svc.reload()
    assert row(svc, "kling_3")["usable"] and row(svc, "kling_3")["why_not"] == ""
    svc.config.disabled_models = ["kling_3"]
    assert "switched off" in row(svc, "kling_3")["why_not"]


def test_rows_say_the_price_and_the_abilities_in_plain_words(svc):
    kling = row(svc, "kling_3")
    assert kling["price_text"] == "$0.168 per second"
    assert "starts from a picture" in kling["abilities"] and "can end on a picture" in kling["abilities"] and "clips up to 15 s" in kling["abilities"]
    assert row(svc, "claude_opus")["price_text"] == "$4 in / $20 out per 1M tokens"
    assert "sees pictures" in row(svc, "claude_opus")["abilities"] and "watches whole videos" in row(svc, "gemini")["abilities"]
    assert row(svc, "local_music")["price_text"] == "free"


def test_prices_are_written_with_cents_and_without_useless_zeros(svc):
    assert row(svc, "claude_haiku")["price_text"] == "$0.10 in / $0.50 out per 1M tokens"
    assert row(svc, "gemini_flash")["price_text"] == "$0.30 in / $2.50 out per 1M tokens"
    assert row(svc, "gpt")["price_text"] == "$1.25 in / $10 out per 1M tokens"
    assert row(svc, "wan_2_6")["price_text"].endswith("per second") and "$0.1 " not in row(svc, "wan_2_6")["price_text"]


def test_the_brain_list_has_the_claude_family_at_the_vendors_prices_and_a_draft_cost_for_each(svc):
    prices = {r["id"]: (r["price"]["usd_in"], r["price"]["usd_out"]) for r in svc.model_rows() if r["job"] == "llm"}
    assert prices["claude_fable"] == (10.0, 50.0) and prices["claude_opus"] == (4.0, 20.0)
    assert prices["claude_sonnet"] == (2.0, 10.0) and prices["claude_haiku"] == (0.10, 0.50)
    assert {"gpt", "gpt_mini", "gemini", "gemini_flash", "offline_brain"} <= set(prices)
    cost = {i: row(svc, i)["draft_cost_usd"] for i in ("claude_fable", "claude_opus", "claude_sonnet", "claude_haiku", "offline_brain")}
    assert cost["claude_fable"] > cost["claude_opus"] > cost["claude_sonnet"] > cost["claude_haiku"] > cost["offline_brain"] == 0
    assert all("draft_cost_usd" not in r for r in svc.model_rows() if r["job"] != "llm")
    assert row(svc, "claude_opus")["note"] and row(svc, "claude_haiku")["note"]


def test_a_price_not_checked_with_the_vendor_is_marked_as_unverified(svc):
    assert row(svc, "gpt_mini")["price_verified"] is False and row(svc, "gemini_flash")["price_verified"] is False
    assert row(svc, "claude_sonnet")["price_verified"] is True


# ------------------------------------------------------------------ the AI model per kind of work
def two_brains(svc, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    svc.reload()


def test_a_model_can_be_chosen_per_kind_of_work(svc, monkeypatch):
    two_brains(svc, monkeypatch)
    reg = svc.reg
    assert reg.llm_plugin_name("draft") == "anthropic" and reg.llm_entry("draft").id == "claude_opus"
    svc.config.llm.per_task_model = {"review": "openai:gpt-5-mini", "simple": "anthropic:claude-haiku-5-5"}
    assert reg.llm_plugin_name("review") == "openai" and reg.llm_model("review", "openai") == "gpt-5-mini"
    assert reg.llm_entry("review").id == "gpt_mini"
    assert reg.llm_entry("explain").id == "claude_haiku" and reg.llm_entry("command").id == "claude_haiku"
    assert reg.llm_entry("draft").id == "claude_opus" and reg.llm_entry("write_clip_script").id == "claude_opus"    # planning is untouched


def test_a_chosen_model_of_a_vendor_that_is_not_connected_is_ignored_not_fatal(svc, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    svc.reload()
    svc.config.llm.per_task_model = {"default": "gemini:gemini-2.5-flash"}
    assert svc.reg.llm_plugin_name("draft") == "openai" and svc.reg.llm_entry("draft").id == "gpt"


def test_every_ai_call_is_priced_by_the_model_that_really_answered(svc, monkeypatch):
    two_brains(svc, monkeypatch)
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert svc.brain._cost("draft", "anthropic", usage) == pytest.approx(24.0)            # Opus: 4 + 20
    svc.config.llm.per_task_model = {"default": "anthropic:claude-sonnet-5-5"}
    assert svc.brain._cost("draft", "anthropic", usage) == pytest.approx(12.0)            # Sonnet: 2 + 10
    svc.config.llm.models["anthropic"] = "claude-haiku-5-5"
    svc.config.llm.per_task_model = {}
    assert svc.brain._cost("draft", "anthropic", usage) == pytest.approx(0.6)             # Haiku: 0.1 + 0.5
    svc.config.llm.models["anthropic"] = "a-model-not-in-the-catalogue"
    assert svc.reg.llm_entry("draft").plugin == "anthropic"                               # falls back to the vendor's first row


def test_the_review_estimate_follows_the_model_chosen_for_reviews(svc, monkeypatch):
    Vendors(svc, monkeypatch)                                                              # (OpenAI key only: the brain is gpt-5)
    p = svc.new_project("Review price", seconds=8, quality_mode="balanced")
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="P", goal="g", target_seconds=8))
    c = add_child(p, part.id, Node(kind=NodeKind.clip, title="C", goal="g", target_seconds=8))
    c.script = ClipScript(shot_type=ShotType.landscape, visual="hills", sound_notes="wind")
    svc.save(p)

    def review_cost():
        line = next(l for l in leaves(svc.load(p.id))[0].cost.lines if l.item == "Review agent")
        return line.cost
    before = review_cost()
    svc.config.llm.per_task_model = {"review": "openai:gpt-5-mini"}
    svc.save(svc.load(p.id))
    assert 0 < review_cost() < before


# ------------------------------------------------------------------ the vendor's own list of models
def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_reading_a_vendors_model_list_uses_the_keys_and_filters_from_the_data(svc):
    from video_generator.catalog import load_vendors
    specs = {v["id"]: v["models_list"] for v in load_vendors() if v.get("models_list")}
    assert {"anthropic", "openai", "google"} <= set(specs)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = (dict(request.headers), str(request.url))
        if request.url.host == "api.anthropic.com":
            return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5"}, {"id": "claude-new-9", "display_name": "Claude New 9"}]})
        if request.url.host == "api.openai.com":
            return httpx.Response(200, json={"data": [{"id": i} for i in ("gpt-5", "gpt-5-mini", "text-embedding-3-large", "whisper-1", "dall-e-3", "gpt-4o-realtime-preview", "o4-mini")]})
        return httpx.Response(200, json={"models": [
            {"name": "models/gemini-2.5-pro", "displayName": "Gemini 2.5 Pro", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-embedding-001", "displayName": "Embedding", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/imagen-4", "displayName": "Imagen", "supportedGenerationMethods": ["predict"]}]})
    a = run(models_list.fetch(specs["anthropic"], "KEY1", mock_client(handler)))
    o = run(models_list.fetch(specs["openai"], "KEY2", mock_client(handler)))
    g = run(models_list.fetch(specs["google"], "KEY3", mock_client(handler)))
    assert [m["id"] for m in a] == ["claude-sonnet-5-5", "claude-new-9"] and a[1]["name"] == "Claude New 9"
    assert [m["id"] for m in o] == ["gpt-5", "gpt-5-mini", "o4-mini"]                      # embeddings, speech, pictures, live audio left out
    assert [m["id"] for m in g] == ["gemini-2.5-pro"]                                      # only models that can write; "models/" removed
    assert seen["api.anthropic.com"][0]["x-api-key"] == "KEY1" and seen["api.openai.com"][0]["authorization"] == "Bearer KEY2"
    assert "key=KEY3" in seen["generativelanguage.googleapis.com"][1]


@pytest.mark.parametrize("status,words", [(401, "refused the key"), (500, "error (500)")])
def test_a_vendor_that_refuses_or_fails_gives_a_plain_message(status, words):
    from video_generator.catalog import load_vendors
    spec = next(v["models_list"] for v in load_vendors() if v["id"] == "anthropic")
    with pytest.raises(models_list.ListError, match=re.escape(words)):
        run(models_list.fetch(spec, "k", mock_client(lambda r: httpx.Response(status, json={}))))


def test_discovery_reports_new_models_errors_and_vendors_without_a_key(svc, monkeypatch):
    two_brains(svc, monkeypatch)

    async def fake_fetch(spec, key, client=None):
        if "anthropic" in spec["url"]:
            return [{"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"}, {"id": "claude-brand-new", "name": "Brand New"}]
        raise models_list.ListError("the vendor refused the key (check it, or its permissions)")
    monkeypatch.setattr(models_list, "fetch", fake_fetch)
    r = run(svc.discover_models())
    by_id = {m["id"]: m for m in r["models"]}
    assert by_id["claude-sonnet-5-5"]["in_catalogue"] is True and by_id["claude-brand-new"]["in_catalogue"] is False
    assert by_id["claude-brand-new"]["plugin"] == "anthropic"
    assert "refused the key" in r["errors"]["OpenAI API"] and "Google Gemini API (AI Studio)" in r["skipped"]


def test_a_found_model_is_added_with_the_price_you_read_and_it_survives_a_restart(svc):
    r = svc.add_model("anthropic", "claude-brand-new", 3.0, 15.0)
    assert r["id"] == "anthropic_claude_brand_new" and r["price_text"] == "$3 in / $15 out per 1M tokens" and r["price_verified"] is True
    svc.reload()                                                                           # read from your own catalogue file
    again = row(svc, "anthropic_claude_brand_new")
    assert again["plugin"] == "anthropic" and again["model"] == "claude-brand-new" and again["draft_cost_usd"] > 0
    r2 = svc.add_model("anthropic", "claude-brand-new", 1.0, 5.0)                           # same model again: price changes, no duplicate
    assert r2["id"] == r["id"] and sum(1 for x in svc.model_rows() if x["model"] == "claude-brand-new") == 1
    assert svc.reg.llm_entry("draft") is not None


def test_adding_a_model_checks_its_inputs(svc):
    with pytest.raises(ValueError, match="negative"):
        svc.add_model("anthropic", "x", -1, 2)
    with pytest.raises(ValueError, match="unknown AI vendor"):
        svc.add_model("nobody", "x", 1, 2)


# ------------------------------------------------------------------ the web API
def test_api_lists_models_refreshes_adds_and_stores_the_choice(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    two_brains(svc, monkeypatch)
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)

    async def fake_fetch(spec, key, client=None):
        return [{"id": "claude-brand-new", "name": "Brand New"}]
    monkeypatch.setattr(models_list, "fetch", fake_fetch)
    with TestClient(appmod.app) as client:
        s = client.get("/api/settings").json()
        k = next(r for r in s["catalog"] if r["id"] == "kling_3")
        assert k["why_not"] == "set FAL_KEY" and k["price_text"] and k["abilities"]
        r = client.post("/api/models/llm/refresh").json()
        assert any(m["id"] == "claude-brand-new" and not m["in_catalogue"] for m in r["models"])
        added = client.post("/api/catalog/llm", json={"plugin": "anthropic", "model": "claude-brand-new", "usd_in": 3, "usd_out": 15}).json()
        assert any(x["model"] == "claude-brand-new" for x in added["catalog"])
        bad = client.post("/api/catalog/llm", json={"plugin": "anthropic", "model": "x", "usd_in": -1, "usd_out": 1})
        assert bad.status_code == 400
        patched = client.patch("/api/settings", json={"llm": {"per_task_model": {"review": "openai:gpt-5-mini"}}}).json()
        assert patched["config"]["llm"]["per_task_model"] == {"review": "openai:gpt-5-mini"}
        assert svc.reg.llm_entry("review").id == "gpt_mini"
