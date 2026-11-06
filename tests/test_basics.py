"""Step 2 (v3.9): the basics a person looks at first: length (Auto), language, cost by part, a price ballpark."""
import asyncio

import pytest

from video_generator import casting, languages, policy as policy_mod
from video_generator.models import ClipScript, DialogueLine, Node, NodeKind, NodeStatus, ShotType
from video_generator.tree import add_child, leaves

from .fake_vendors import Vendors


# ------------------------------------------------------------------ language codes
def test_language_codes_are_normalised_and_auto_never_reaches_a_voice_service(svc):
    assert languages.normalise("Hindi") == "hi" and languages.normalise("hi-IN") == "hi" and languages.normalise("HI") == "hi"
    assert languages.normalise("auto") == "" and languages.normalise("") == "" and languages.normalise("not a language!") == ""
    assert languages.effective("auto") == "en" and languages.effective("ta") == "ta"
    p = svc.new_project("A video", language="auto")
    assert casting.profile_for(None, p).language == "en"            # the voice vendors cannot use "auto"
    p.settings.language = "hi"
    assert casting.profile_for(None, p).language == "hi"


# ------------------------------------------------------------------ the planner is told about length and language
def test_the_draft_prompt_says_whether_a_length_was_asked_for(svc):
    fixed = svc.new_project("A video", seconds=45)
    line, rules = svc.brain.length_blocks(fixed)
    assert "TARGET LENGTH: 45 seconds" in line and "MUST add up" in rules
    auto = svc.new_project("A video", length_mode="auto")
    line, rules = svc.brain.length_blocks(auto)
    assert "none was given" in line and "as short as the story allows" in line and "every spoken line is heard in full" in rules


def test_the_language_line_is_decided_by_the_plan_or_fixed_by_you(svc):
    auto = svc.new_project("A video", language="auto")
    assert "Decide from the goal" in svc.brain.language_block(auto)
    hindi = svc.new_project("A video", language="hi")
    assert "Hindi (hi)" in svc.brain.language_block(hindi) and "own script" in svc.brain.language_block(hindi)
    assert "Hindi (hi)" in svc.brain.language_line(hindi)


# ------------------------------------------------------------------ Auto length
def test_auto_length_makes_the_plans_own_total_the_length(svc):
    p = svc.new_project("A calm product demo", length_mode="auto", language="auto")
    assert p.settings.length_mode == "auto" and p.settings.language == "auto"
    p = asyncio.run(svc.draft(p.id, write_scripts=False))
    clips_total = sum(n.target_seconds or 0 for n in leaves(p))
    assert p.settings.length_mode == "auto"
    assert p.settings.target_seconds == pytest.approx(clips_total, abs=0.2) and p.root.target_seconds == p.settings.target_seconds
    assert p.settings.language == "en"                               # the offline brain did not decide: English
    s = svc.summary(p)
    assert s["length_mode"] == "auto" and not any("vs target" in w for w in s["warnings"])


def test_a_fixed_length_still_warns_when_the_plan_is_far_from_it(svc):
    p = svc.new_project("A calm product demo", seconds=60)
    p = asyncio.run(svc.draft(p.id, write_scripts=False))
    assert p.settings.length_mode == "fixed"
    first = leaves(p)[0]
    first.target_seconds = 40                                          # push the plan far from the 60 s asked for
    svc.save(p)
    assert any("vs target" in w for w in svc.summary(svc.load(p.id))["warnings"])


def test_asking_for_a_length_ends_auto_mode_but_other_settings_do_not(svc):
    p = svc.new_project("A video", length_mode="auto")
    p = svc.update_project(p.id, {"settings": {"budget_usd": 5}})
    assert p.settings.length_mode == "auto" and p.settings.budget_usd == 5
    p = svc.update_node(p.id, p.root.id, {"target_seconds": 90})
    assert p.settings.length_mode == "fixed" and p.settings.target_seconds == 90
    q = svc.new_project("Another", length_mode="auto")
    q = svc.update_project(q.id, {"settings": {"target_seconds": 45}})
    assert q.settings.length_mode == "fixed" and q.settings.target_seconds == 45


def test_projects_made_before_the_setting_existed_stay_fixed(svc):
    from video_generator.models import Settings
    assert Settings.model_validate({"target_seconds": 30}).length_mode == "fixed"


# ------------------------------------------------------------------ cost by part
def two_part_project(svc):
    p = svc.new_project("Parts", seconds=24)
    a = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="First", goal="a", target_seconds=12))
    b = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Second", goal="b", target_seconds=12))
    for part, n in ((a, 2), (b, 1)):
        for i in range(n):
            c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"{part.title} clip {i + 1}", goal="g", target_seconds=6.0 * (2 if part is b else 1)))
            c.script = ClipScript(shot_type=ShotType.landscape, visual="hills", sound_notes="wind")
    leaves(p)[0].status = NodeStatus.done
    svc.save(p)
    return svc.load(p.id)


def test_cost_by_part_lists_every_part_and_clip_and_adds_up(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p = two_part_project(svc)
    rows = svc.summary(p)["parts"]
    assert [r["number"] for r in rows] == ["1", "1.1", "1.2", "2", "2.1"]
    assert [r["depth"] for r in rows] == [0, 1, 1, 0, 1]
    first, c1, c2 = rows[0], rows[1], rows[2]
    assert first["kind"] == "goal" and first["clips"] == 2 and first["done"] == 1
    assert first["cost"] == pytest.approx(c1["cost"] + c2["cost"], abs=0.011)
    assert first["seconds"] == pytest.approx(c1["seconds"] + c2["seconds"], abs=0.11)
    assert c1["models"] and rows[3]["quality"] == "balanced"
    total = sum(r["cost"] for r in rows if r["depth"] == 0)
    assert total == pytest.approx(svc.summary(p)["cost_total"], abs=0.02)


# ------------------------------------------------------------------ price ballpark
def test_ballpark_is_zero_when_only_free_tools_are_possible(svc):
    b = svc.ballpark(60, "balanced")
    assert not b["real"] and b["per_minute"]["high"] == 0 and b["total"]["high"] == 0


def test_ballpark_with_keys_gives_a_range_made_of_catalogue_prices(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    b = svc.ballpark(120, "balanced")
    assert b["real"] and 0 < b["per_minute"]["low"] < b["per_minute"]["high"]
    assert b["total"]["low"] == pytest.approx(b["per_minute"]["low"] * 2, abs=0.02)
    assert {"video", "image", "voice"} <= set(b["models"]) and any(l["item"].startswith("Video (") for l in b["lines"])
    assert sum(l["low"] for l in b["lines"]) == pytest.approx(b["per_minute"]["low"], abs=0.03)


def test_ballpark_budget_is_not_dearer_than_best(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    best, budget = svc.ballpark(60, "best"), svc.ballpark(60, "budget")
    assert budget["per_minute"]["low"] <= best["per_minute"]["low"] and budget["per_minute"]["high"] <= best["per_minute"]["high"]


def test_the_ballpark_assumptions_are_named_policy_settings_with_help_text():
    names = {n: why for n, _, why in policy_mod.describe()}
    assert names["ballpark_clip_seconds"] and names["ballpark_speech_share"]


# ------------------------------------------------------------------ the web API
def test_api_languages_ballpark_and_health_defaults(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    Vendors(svc, monkeypatch)
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    with TestClient(appmod.app) as client:
        langs = client.get("/api/languages").json()
        assert {"code": "hi", "name": "Hindi"} in langs and {"code": "en", "name": "English"} in langs
        b = client.get("/api/ballpark", params={"seconds": 60, "quality": "budget"}).json()
        assert b["mode"] == "budget" and b["total"]["high"] >= b["total"]["low"] > 0
        h = client.get("/api/health").json()
        assert h["default_budget"] == svc.config.budget_usd and h["default_quality"] == svc.config.quality_mode
