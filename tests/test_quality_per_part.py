"""Step 6 (v3.10): cheapest or best, for the whole video or any part. A part's quality changes video, picture and natural sound only:
a character's voice, the narrator, the reference look and the music are chosen ONCE, by the whole video's quality."""
import pytest

from video_generator import estimate as E
from video_generator.models import ActorDetails, ClipScript, ContextItem, ContextType, DialogueLine, Node, NodeKind, NodeStatus, ShotType
from video_generator.tree import add_child, leaves

from .fake_vendors import Vendors
from .test_scenarios import actor, build, clip, run_all


def keys(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    monkeypatch.setenv("CARTESIA_API_KEY", "x")             # a second voice service, so that "the cast one" can differ from "the cheapest one"
    svc.reload()
    v.__init__(svc, monkeypatch)
    return v


def two_parts(svc, shot="human_motion", quality="balanced"):
    p = svc.new_project("Two parts", seconds=8, quality_mode=quality)
    p.settings.music = False
    p.settings.review_enabled = False
    parts = []
    for i in (1, 2):
        part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title=f"Part {i}", goal="g", target_seconds=4.0))
        c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"Clip {i}", goal="g", target_seconds=4.0))
        c.script = ClipScript(shot_type=ShotType(shot), visual="a person walks", sound_notes="room tone", motion="scene")
        parts.append(part)
    svc.save(p)
    return svc.load(p.id)


# ------------------------------------------------------------------ the nearest choice wins
def test_a_node_uses_its_own_quality_else_the_part_above_else_the_video(svc):
    p = svc.new_project("Inherit", quality_mode="balanced")
    a = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="A", goal="g", quality_mode="best"))
    inner = add_child(p, a.id, Node(kind=NodeKind.goal, title="Inner", goal="g"))
    c1 = add_child(p, inner.id, Node(kind=NodeKind.clip, title="c1", goal="g"))
    c2 = add_child(p, a.id, Node(kind=NodeKind.clip, title="c2", goal="g", quality_mode="budget"))
    b = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="B", goal="g"))
    c3 = add_child(p, b.id, Node(kind=NodeKind.clip, title="c3", goal="g"))
    assert [E.mode_for(p, n) for n in (a, inner, c1, c2, b, c3, p.root)] == ["best", "best", "best", "budget", "balanced", "balanced", "balanced"]


def test_each_part_chooses_its_own_models(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = two_parts(svc, "human_motion", "balanced")
    p.root.children[0].quality_mode = "best"
    p.root.children[1].quality_mode = "budget"
    svc.save(p)
    q = svc.load(p.id)
    a, b = leaves(q)
    assert E.plan_clip(q, a, svc.reg).video.id == svc.reg.choose("video", "human_motion", mode="best").id == "kling_3"
    assert E.plan_clip(q, b, svc.reg).video.id == svc.reg.choose("video", "human_motion", mode="budget").id == "wan_2_6"
    assert q.root.children[1].cost.likely_usd < q.root.children[0].cost.likely_usd       # the cheaper part costs less


def test_a_part_on_free_preview_only_makes_placeholders_and_the_banner_says_why(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = two_parts(svc)
    p.root.children[0].quality_mode = "free"
    svc.save(p)
    q = svc.load(p.id)
    info = svc.summary(q)["preview"]
    a, b = leaves(q)
    assert info["causes"][a.id]["video"] == "free_mode" and b.id not in info["clips"]
    assert not info["chosen_free_mode"] and E.plan_clip(q, a, svc.reg).video.is_free and not E.plan_clip(q, b, svc.reg).video.is_free


def test_the_cost_table_shows_each_parts_own_quality(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = two_parts(svc)
    p.root.children[1].quality_mode = "budget"
    svc.save(p)
    rows = {r["number"]: r for r in svc.summary(svc.load(p.id))["parts"]}
    assert rows["1"]["quality"] == "balanced" and not rows["1"]["quality_own"]
    assert rows["2"]["quality"] == "budget" and rows["2"]["quality_own"] and rows["2.1"]["quality"] == "budget"


# ------------------------------------------------------------------ voices, narrator, looks and music: once for the whole video
def spoken_project(svc, provider, mode_of_part):
    cast = ContextItem(type=ContextType.actor, title="Rahul", actor=ActorDetails(kind="ai_person", description="a man", voice_gender="male",
                                                                              voice_id="v1", voice_provider=provider, voice_name="Cast voice"))
    p = svc.new_project("Pinned voice", seconds=4, quality_mode="best")
    p.context.append(cast)
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="P", goal="g", quality_mode=mode_of_part))
    c = add_child(p, part.id, Node(kind=NodeKind.clip, title="C", goal="g", target_seconds=4.0))
    c.script = ClipScript(shot_type=ShotType.dialogue_scene, visual="v", dialogue=[DialogueLine(speaker=cast.id, text="hello there")])
    svc.save(p)
    return svc.load(p.id)


def test_a_cheaper_part_never_recasts_a_character_with_another_voice_service(svc, monkeypatch):
    keys(svc, monkeypatch)
    default_service = svc.reg.choose("voice", mode="best").plugin
    cast_service = next(e.plugin for e in svc.catalog.for_job("voice") if svc.reg.entry_usable(e) and not e.is_free and e.plugin != default_service)
    for part_mode in ("budget", "free", "best"):
        q = spoken_project(svc, cast_service, part_mode)
        assert E.plan_clip(q, leaves(q)[0], svc.reg).voice.plugin == cast_service, part_mode           # the service that cast the voice keeps it


def test_a_new_voice_is_chosen_by_the_quality_of_the_whole_video_not_the_part(svc, monkeypatch):
    keys(svc, monkeypatch)
    q = spoken_project(svc, "", "budget")                                  # nobody is cast yet; the part says budget, the video says best
    c = leaves(q)[0]
    for card in q.context:
        card.actor.voice_id, card.actor.voice_provider = None, None
    assert E.plan_clip(q, c, svc.reg).voice.id == svc.reg.choose("voice", mode="best").id


def test_free_quality_for_the_whole_video_does_not_keep_a_paid_voice(svc, monkeypatch):
    keys(svc, monkeypatch)
    q = spoken_project(svc, "elevenlabs", None)
    q.settings.quality_mode = "free"
    assert E.plan_clip(q, leaves(q)[0], svc.reg).voice.is_free


def test_a_characters_reference_picture_follows_the_whole_video_not_the_part(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = two_parts(svc, "human_motion", "best")
    p.root.children[0].quality_mode = "budget"
    svc.save(p)
    q = svc.load(p.id)
    assert E.plan_clip(q, leaves(q)[0], svc.reg).image.id == "flux_2"           # the clip's own picture follows the part
    assert E.sheet_image(svc.reg, q).id == "gpt_image"                           # the look sheet follows the video


# ------------------------------------------------------------------ the engine really uses the part's quality
def test_the_engine_makes_each_clip_with_its_own_parts_model(svc, monkeypatch):
    v = keys(svc, monkeypatch)
    p, ids = build(svc, "Two qualities", [], [clip("human_motion", "A person walks"), clip("human_motion", "A person runs")])
    q = svc.load(p.id)
    a, b = leaves(q)
    a.quality_mode, b.quality_mode = "best", "budget"
    svc.save(q)
    run_all(svc, p.id)
    made = {r.model for r in v.calls["video"]}
    assert made == {"fal-ai/kling-video/v3/pro/image-to-video", svc.catalog.get("wan_2_6").model}


# ------------------------------------------------------------------ what each quality would cost, before you choose
def test_each_quality_is_priced_on_a_copy_and_nothing_is_saved(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = two_parts(svc, "human_motion", "balanced")
    part = p.root.children[0]
    r = svc.mode_costs(p.id, part.id)
    m = r["modes"]
    assert set(m) == {"best", "balanced", "budget", "free"} and r["current"] == "" and r["effective"] == "balanced" and not r["is_whole_video"]
    assert m["budget"]["cost_todo"] < m["best"]["cost_todo"] and m["free"]["cost_todo"] <= m["budget"]["cost_todo"]
    assert m["best"]["models"] == ["kling_3"] and m["budget"]["models"] == ["wan_2_6"] and m["free"]["models"] == ["free_preview"]
    assert svc.load(p.id).root.children[0].quality_mode is None                     # asking does not change anything
    assert svc.mode_costs(p.id, p.root.id)["is_whole_video"]


def test_only_clips_not_made_yet_count_in_what_a_quality_would_cost(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = two_parts(svc)
    first = leaves(p)[0]
    first.status = NodeStatus.done
    svc.save(p)
    r = svc.mode_costs(p.id, p.root.id)["modes"]["balanced"]
    assert r["clips"] == 2 and r["to_make"] == 1 and r["cost_todo"] < r["cost"]


def test_a_part_inherits_the_part_above_and_reports_it(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = two_parts(svc)
    p.root.children[0].quality_mode = "best"
    svc.save(p)
    q = svc.load(p.id)
    inner = leaves(q)[0]
    r = svc.mode_costs(q.id, inner.id)
    assert r["current"] == "" and r["effective"] == "best" and r["inherits"] == "best"


# ------------------------------------------------------------------ saving the choice
def test_the_quality_of_a_part_can_be_set_changed_and_cleared(svc):
    p = two_parts(svc)
    part = p.root.children[0]
    assert svc.update_node(p.id, part.id, {"quality_mode": "budget"}).root.children[0].quality_mode == "budget"
    assert svc.update_node(p.id, part.id, {"quality_mode": ""}).root.children[0].quality_mode is None
    with pytest.raises(ValueError, match="best, balanced, budget or free"):
        svc.update_node(p.id, part.id, {"quality_mode": "cheap"})


def test_api_prices_each_quality_and_saves_the_choice(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    keys(svc, monkeypatch)
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p = two_parts(svc)
    part = p.root.children[1]
    with TestClient(appmod.app) as client:
        r = client.get(f"/api/projects/{p.id}/nodes/{part.id}/mode-costs").json()
        assert r["modes"]["budget"]["cost_todo"] < r["modes"]["best"]["cost_todo"]
        v = client.patch(f"/api/projects/{p.id}/nodes/{part.id}", json={"quality_mode": "budget"}).json()
        assert next(x for x in v["summary"]["parts"] if x["id"] == part.id)["quality"] == "budget"
        assert client.patch(f"/api/projects/{p.id}/nodes/{part.id}", json={"quality_mode": "cheap"}).status_code == 400
