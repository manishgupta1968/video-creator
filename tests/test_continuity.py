"""Steps 7B and 7C (v3.10): characters stay in sync (language, accent, voice) and a free rule check finds what would break the feeling of one video."""
import asyncio

import pytest

from video_generator import casting, languages
from video_generator import continuity as C
from video_generator import estimate as E
from video_generator import policy as policy_mod
from video_generator import routes
from video_generator.brain import render
from video_generator.models import ActorDetails, ActorInShot, ClipScript, ContextItem, ContextType, DialogueLine, Node, NodeKind, NodeStatus, ShotType
from video_generator.plugins.base import VoiceSpec
from video_generator.project import ProjectStore
from video_generator.tree import add_child, leaves

from .conftest import requires_ffmpeg
from .fake_vendors import VOICES, Vendors
from .test_scenarios import actor, build, clip, run_all
from .test_voice_sound_frame import candidates as candidates_for


def by_code(found, code):
    return [f for f in found if f["code"] == code]


def two_clips_with_places(svc, join="cut", **kw):
    p, ids = build(svc, "Two shots", [], [clip("human_motion", "A person stands at a door", end="at the door", seconds=4),
                                         clip("human_motion", "The person opens the door", start="at the door", seconds=4)])
    q = svc.load(p.id)
    a, b = leaves(q)
    for c in (a, b):
        c.continuity.place, c.continuity.present = "a quiet hall, evening", ["Asha"]
    svc.save(q)
    if join:
        svc.set_join(p.id, ids[1], join)
    return svc.load(p.id), ids


# ------------------------------------------------------------------ 7B: characters
def test_the_draft_prompt_makes_the_accent_and_language_of_every_speaker_required():
    text = render("draft", goal="g", length_block="L", length_rules="r", language_block="LANG", routes="R", aspect="16:9", context="c")
    assert "voice_accent is REQUIRED" in text and "never empty" in text and "`language`" in text
    assert "(Example only:" in text                                                       # an example, marked as one


def test_the_offline_planner_gives_each_speaker_the_videos_language_and_accent(svc):
    p = svc.new_project("A presenter explains the lamp", seconds=20, language="hi")
    q = asyncio.run(svc.draft(p.id, write_scripts=False))
    presenter = next(c for c in q.context if c.title == "Presenter")
    assert presenter.actor.language == "hi" and presenter.actor.voice_accent == "Hindi"


def test_an_actor_can_speak_another_language_than_the_video(svc):
    p = svc.new_project("Two speakers", language="en")
    item = ContextItem(type=ContextType.actor, title="Asha", actor=ActorDetails(language="hi", voice_gender="female"))
    p.context.append(item)
    assert casting.profile_for(item, p).language == "hi"
    plain = ContextItem(type=ContextType.actor, title="Ben", actor=ActorDetails(voice_gender="male"))
    assert casting.profile_for(plain, p).language == "en"                                  # no language of their own: the video's


def test_the_planner_is_told_no_connected_voice_can_sing(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    text = routes.describe(svc.reg)
    assert "none can sing" in text and "never 'sung'" in text
    for e in svc.catalog.for_job("voice"):
        if e.id == "elevenlabs_v3" or e.plugin == "elevenlabs":
            monkeypatch.setitem(e.capabilities, "sing", True)
    assert "models that can sing" in routes.describe(svc.reg)                              # it follows the catalogue, not the code


def test_the_accent_the_plan_asks_for_counts_strongly_when_a_voice_is_chosen(svc):
    spec = VoiceSpec(description="clear", gender="female", age="young", accent="Indian English")
    assert candidates_for(spec)[0].voice_id == "f_ind"                                    # the Indian voice beats the young American one
    assert policy_mod.current().voice_accent_weight > 4 > 2                                # stronger than the old fixed 2
    names = {n: why for n, _, why in policy_mod.describe()}
    assert "accent" in names["voice_accent_weight"]


def test_a_voice_labelled_with_another_accent_is_said_plainly_never_hidden():
    assert casting.accent_mismatch("american", "Indian English")
    assert "labelled 'american'" in casting.accent_mismatch("american", "Indian English") and "Indian English" in casting.accent_mismatch("american", "Indian English")
    assert casting.accent_mismatch("indian", "Indian English") == ""
    assert casting.accent_mismatch("", "Indian English") == "" and casting.accent_mismatch("american", "") == ""


@requires_ffmpeg
def test_the_accent_label_of_the_chosen_voice_is_kept_and_a_mismatch_is_noted(svc, monkeypatch):
    Vendors(svc, monkeypatch, voices=[v for v in VOICES if v["voice_id"] in ("f_mid", "f_young")])        # only American women in this library
    meera = actor("Meera", voice_gender="female", voice_age="adult", voice_accent="Indian English", voice_description="warm")
    p, ids = build(svc, "Meera speaks", [meera], [clip("talking_head", "Meera speaks to the camera", say=[("Meera", "Hello there")], actors=["Meera"])])
    run_all(svc, p.id)
    q = svc.load(p.id)
    card = next(c for c in q.context if c.title == "Meera")
    assert card.actor.voice_accent_label == "american" and "labelled 'american'" in card.actor.voice_note
    found = C.check(q, svc.reg, ProjectStore.path_for(q.id))
    assert by_code(found, "accent_label") and by_code(found, "accent_label")[0]["fixes"][0]["action"] == "open_actor"


# ------------------------------------------------------------------ 7C: the free checks
def test_a_join_left_undecided_is_listed_once_and_one_click_marks_cuts(svc):
    p, ids = two_clips_with_places(svc, join="")
    f = by_code(C.check(p, svc.reg), "join_undecided")
    assert len(f) == 1 and "1.2" in f[0]["text"] and f[0]["fixes"][0]["action"] == "joins_as_cuts"
    q = svc.fix_continuity(p.id, "joins_as_cuts")
    assert leaves(q)[1].continuity.join == "cut" and not by_code(C.check(q, svc.reg), "join_undecided")


def test_a_continuing_clip_that_does_not_start_where_the_last_ends_is_a_problem_with_a_fix(svc):
    p, ids = two_clips_with_places(svc, join="continues")
    q = svc.load(p.id)
    leaves(q)[1].script.start_state = "somewhere quite different"
    svc.save(q)
    found = by_code(C.check(svc.load(p.id), svc.reg), "start_not_end")
    assert found and found[0]["severity"] == "problem" and found[0]["number"] == "1.2"
    fixed = svc.fix_continuity(p.id, found[0]["fixes"][0]["action"], found[0]["fixes"][0]["node"])
    assert leaves(fixed)[1].script.start_state == leaves(fixed)[0].script.end_state
    assert not by_code(C.check(fixed, svc.reg), "start_not_end")


def test_the_same_place_and_people_joined_as_a_cut_offers_a_same_scene_join(svc):
    p, ids = two_clips_with_places(svc, join="cut")
    f = by_code(C.check(p, svc.reg), "same_place_cut")
    assert f and f[0]["fixes"][0] == {"action": "set_join", "label": "Make it a same-scene join", "node": ids[1], "join": "same_scene"}
    q = svc.fix_continuity(p.id, "set_join", ids[1], "same_scene")
    assert not by_code(C.check(q, svc.reg), "same_place_cut")
    other = svc.load(p.id)
    leaves(other)[1].continuity.place = "a busy market, noon"
    assert not by_code(C.check(other, svc.reg), "same_place_cut")                          # a different place: a cut is right


def test_clothing_that_changes_inside_one_scene_is_noted_but_a_reworded_outfit_is_not(svc):
    asha = actor("Asha", clothing="a red silk sari")
    p, ids = build(svc, "Asha", [asha], [clip("human_motion", "Asha stands", actors=["Asha"]), clip("human_motion", "Asha turns", actors=["Asha"])])
    svc.set_join(p.id, ids[1], "same_scene")
    q = svc.load(p.id)
    a, b = leaves(q)
    a.script.actors_in_shot[0].clothing, b.script.actors_in_shot[0].clothing = "a red silk sari with gold edges", "a blue denim jacket and jeans"
    assert by_code(C.check(q, svc.reg), "clothing_changes")
    b.script.actors_in_shot[0].clothing = "the red silk sari, gold edges"
    assert not by_code(C.check(q, svc.reg), "clothing_changes")
    b.script.actors_in_shot[0].clothing = "a blue denim jacket and jeans"
    svc.set_join(p.id, ids[1], "cut")
    assert not by_code(C.check(svc.load(p.id), svc.reg), "clothing_changes")               # a new place or time: new clothes are fine


def test_a_line_written_in_another_script_than_its_speakers_language_is_noted(svc):
    meera = actor("Meera", voice_gender="female", voice_accent="Indian English")
    meera.actor.language = "hi"
    p, ids = build(svc, "Meera", [meera], [clip("talking_head", "Meera speaks", say=[("Meera", "Shri guru charan saroj raj")], actors=["Meera"]),
                                          clip("talking_head", "Meera speaks again", say=[("Meera", "श्री गुरु चरन सरोज रज")], actors=["Meera"]),
                                          clip("talking_head", "Meera says a name", say=[("Meera", "Om")], actors=["Meera"])])
    found = by_code(C.check(p, svc.reg), "script_differs")
    assert [f["number"] for f in found] == ["1.1"]                                         # Latin letters for Hindi: noted; Devanagari: fine; a very short line: not judged
    assert "Hindi" in found[0]["text"] and "Devanagari" in found[0]["text"]
    assert languages.script_of("श्री गुरु")[0] == "DEVANAGARI" and languages.script_of("")[2] == 0


def test_a_speaker_with_no_accent_is_found_and_a_complete_one_is_not(svc):
    bare = actor("Bare", voice_gender="male")
    full = actor("Full", voice_gender="female", voice_accent="British English")
    p, ids = build(svc, "Two", [bare, full], [clip("dialogue_scene", "Two talk", say=[("Bare", "Hello"), ("Full", "Hi")], actors=["Bare", "Full"])])
    found = by_code(C.check(p, svc.reg), "speaker_incomplete")
    assert len(found) == 1 and "Bare" in found[0]["text"] and "an accent" in found[0]["text"] and found[0]["fixes"][0]["action"] == "open_actor"


@requires_ffmpeg
def test_a_clip_made_with_a_voice_that_has_changed_since_is_a_problem(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    meera = actor("Meera", voice_gender="female", voice_accent="Indian English", voice_description="warm")
    p, ids = build(svc, "Meera", [meera], [clip("talking_head", "Meera speaks", say=[("Meera", "Hello there")], actors=["Meera"])])
    run_all(svc, p.id)
    q = svc.load(p.id)
    assert not by_code(C.check(q, svc.reg, ProjectStore.path_for(q.id)), "voice_changed")
    next(c for c in q.context if c.title == "Meera").actor.voice_id = "someone_else"
    found = by_code(C.check(q, svc.reg, ProjectStore.path_for(q.id)), "voice_changed")
    assert found and found[0]["severity"] == "problem" and found[0]["fixes"][0]["action"] == "remake"


def test_parts_made_with_different_video_models_are_noted_where_they_meet(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p = svc.new_project("Two parts", seconds=8, quality_mode="balanced")
    for i in (1, 2):
        part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title=f"Part {i}", goal="g", target_seconds=4.0))
        c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"Clip {i}", goal="g", target_seconds=4.0))
        c.script = ClipScript(shot_type=ShotType.human_motion, visual="a person", sound_notes="room tone")
    p.root.children[0].quality_mode, p.root.children[1].quality_mode = "best", "budget"
    svc.save(p)
    q = svc.load(p.id)
    f = by_code(C.check(q, svc.reg), "parts_differ")
    assert f and "look may differ" in f[0]["text"] and f[0]["number"] == "2.1"
    q.root.children[1].quality_mode = "best"
    assert not by_code(C.check(q, svc.reg), "parts_differ")


def test_the_summary_and_the_next_step_guide_show_the_findings(svc):
    p, ids = two_clips_with_places(svc, join="cut")
    s = svc.summary(svc.load(p.id))
    assert any(f["code"] == "same_place_cut" for f in s["continuity"])
    assert any("same place" in i["text"] for i in s["guide"]["issues"])


@requires_ffmpeg
def test_the_confirm_dialog_lists_what_a_part_reuses_from_the_rest_of_the_video(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    meera = actor("Meera", voice_gender="female", voice_accent="Indian English", voice_description="warm")
    p, ids = build(svc, "Meera", [meera], [clip("talking_head", "Meera speaks", say=[("Meera", "Hello there")], actors=["Meera"]),
                                          clip("talking_head", "Meera speaks again", say=[("Meera", "Good to see you")], actors=["Meera"])])
    svc.set_join(p.id, ids[1], "continues")
    run_all(svc, p.id, "next")                                                              # only clip 1.1 is made
    info = svc.estimate_targets(p.id, [ids[1]])
    assert any("Meera's voice" in r for r in info["reuses"]) and any("last picture of clip 1.1" in r for r in info["reuses"])
    assert info["extra_upstream"] == [] and info["blocked"] == []


def test_the_api_runs_a_continuity_fix(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p, ids = two_clips_with_places(svc, join="")
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/continuity/fix", json={"action": "joins_as_cuts"}).json()
        assert not any(f["code"] == "join_undecided" for f in r["summary"]["continuity"])
        assert client.post(f"/api/projects/{p.id}/continuity/fix", json={"action": "remake"}).status_code == 400


# ------------------------------------------------------------------ after a goal edit: an offer, never a forced rewrite
def three_clips(svc):
    p, ids = build(svc, "Three", [], [clip("landscape", "a lamp one"), clip("landscape", "a lamp two"), clip("landscape", "a lamp three")])
    q = svc.load(p.id)
    a, b, c = leaves(q)
    a.status = NodeStatus.done                                   # made
    b.locked = True                                              # kept by you
    c.goal = "A completely different scene about a river"
    svc.save(q)
    return svc.load(p.id), ids


def test_the_rewrite_offer_counts_only_clips_that_may_change_and_prices_the_ai(svc):
    p, ids = three_clips(svc)
    r = svc.rewrite_offer(p.id, p.root.children[0].id)
    assert r["clips"] == 1 and r["numbers"] == ["1.3"] and r["kept"] == ["1.1", "1.2"] and r["cost_usd"] >= 0


def test_rewriting_scripts_after_a_goal_edit_never_touches_made_or_kept_clips(svc):
    p, ids = three_clips(svc)
    before = [l.script.visual for l in leaves(p)]
    q = asyncio.run(svc.write_all_scripts(p.id, p.root.children[0].id, overwrite=True))
    a, b, c = leaves(q)
    assert (a.script.visual, b.script.visual) == (before[0], before[1])                    # made and kept: left exactly as they were
    assert "river" in c.script.visual.lower() and c.script.visual != before[2]               # the clip that may change follows its new goal


def test_the_api_offers_the_rewrite(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p, ids = three_clips(svc)
    with TestClient(appmod.app) as client:
        r = client.get(f"/api/projects/{p.id}/nodes/{p.root.children[0].id}/rewrite-offer").json()
        assert r["clips"] == 1 and r["kept"] == ["1.1", "1.2"]
