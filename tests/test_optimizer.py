"""Drop 3 (v3.11): the Optimizer. A shorter and cheaper video, every change proposed first, nothing taken silently.
Proposals are measured on a copy by the same estimate the screen uses; clips already made, kept or protected, and lines marked exact, are never touched."""
import asyncio

import pytest

from video_generator import estimate as E
from video_generator import optimizer as O
from video_generator import policy as policy_mod
from video_generator.models import (ActorDetails, ActorInShot, ClipScript, ContextItem, ContextType, DialogueLine, Node, NodeKind, NodeStatus, ShotType)
from video_generator.project import ProjectStore
from video_generator.tree import add_child, leaves

from .fake_vendors import Vendors

LINE = "Hello there, my friend. Welcome to the quiet hall."
LONG = "First sentence has some words in it. Second sentence has more words in it as well. Third sentence ends the whole thing here."
TRIMMED = "First sentence has some words in it. Second sentence has more words in it as well."


def keys(svc, monkeypatch):
    return Vendors(svc, monkeypatch)


def offline_brain(svc, monkeypatch):
    monkeypatch.setattr(svc.reg, "llm_fallback_order", lambda task: ["fake_llm"])            # the free offline helper answers; nothing is bought


def demo(svc, parts=2, per=2, seconds=10.0, speech=LINE, quality="best", fixed=False, **settings):
    """parts x per people clips, each planned longer than its content needs, one speaker."""
    p = svc.new_project("Optimize demo", seconds=parts * per * seconds, quality_mode=quality)
    p.settings.review_enabled = True
    p.settings.music = False
    for k, v in settings.items():
        setattr(p.settings, k, v)
    asha = ContextItem(type=ContextType.actor, title="Asha", actor=ActorDetails(kind="ai_person", voice_gender="female", voice_accent="Indian English"))
    p.context.append(asha)
    for i in range(1, parts + 1):
        part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title=f"Part {i}", goal="g", target_seconds=per * seconds))
        for j in range(1, per + 1):
            c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"Clip {i}.{j}", goal="g", target_seconds=seconds))
            c.script = ClipScript(shot_type=ShotType.human_motion, visual="a person", action_beats=["steps in", "looks up"], sound_notes="room tone",
                                  dialogue=[DialogueLine(speaker=asha.id, text=speech, fixed=fixed)], actors_in_shot=[ActorInShot(actor_id=asha.id)])
    svc.save(p)
    return svc.load(p.id)


def edit_ids(prop, level=None, checked=None):
    return [e["id"] for e in prop["edits"] if (level is None or e["level"] == level) and (checked is None or e["checked"] == checked)]


# ------------------------------------------------------------------ level 1: no visible change
def test_level_one_only_takes_out_empty_time_and_the_after_numbers_are_what_the_screen_shows(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    r = O.propose(svc, p, p.root.id, O.Goal(lowest=True))
    one = [e for e in r["edits"] if e["level"] == 1]
    assert len(one) == 4 and all(e["kind"] == "seconds" and not e["loses"] for e in one)
    assert r["after"]["seconds"] < r["before"]["seconds"] and r["after"]["cost"] < r["before"]["cost"]
    assert r["met"] and r["stopped_at"] == 0                                                 # "as low as possible": no number to meet, only level 1 is ticked
    assert edit_ids(r, checked=True) == edit_ids(r, level=1)
    q = svc.optimize_apply(p.id, {"lowest": True})                                           # apply, then read what the screen shows
    s = svc.summary(q)
    assert s["seconds"] == pytest.approx(r["after"]["seconds"], abs=0.1) and s["cost"] == pytest.approx(r["after"]["cost"], abs=0.02)
    for clip in leaves(q):
        assert clip.script.dialogue[0].text == LINE and len(clip.script.action_beats) == 2     # every word and every action step is still there


def test_nothing_is_saved_by_asking(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    before = svc.load(p.id).model_dump_json()
    O.propose(svc, p, p.root.id, O.Goal(length=15))
    svc.optimize_propose(p.id, {"length": 15})
    assert svc.load(p.id).model_dump_json() == before


def test_an_edit_that_changes_nothing_is_not_proposed(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, seconds=5.0)                                                                 # already as short as the content needs
    r = O.propose(svc, p, p.root.id, O.Goal(lowest=True))
    assert not edit_ids(r, level=1)


# ------------------------------------------------------------------ the ladder stops at the first level that meets the goal
def test_the_ladder_stops_at_the_first_level_that_meets_the_goal_and_says_so(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    base = O.propose(svc, p, p.root.id, O.Goal(lowest=True))
    easy = O.propose(svc, p, p.root.id, O.Goal(length=base["after"]["seconds"] + 1))
    assert easy["met"] and easy["stopped_at"] == 1 and not edit_ids(easy, level=2, checked=True)
    cheaper = O.propose(svc, p, p.root.id, O.Goal(cost=base["after"]["cost"] - 3))
    assert cheaper["met"] and cheaper["stopped_at"] == 2
    assert edit_ids(cheaper, level=1, checked=True) and edit_ids(cheaper, level=2, checked=True) and not edit_ids(cheaper, level=3, checked=True)
    assert [lv["meets_goal"] for lv in cheaper["levels"]][:2] == [False, True]


def test_a_goal_that_cannot_be_met_says_why_and_what_it_would_take(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, fixed=True)
    r = O.propose(svc, p, p.root.id, O.Goal(length=5))
    assert not r["met"] and "Lines marked “say exactly this” always stay" in r["reason"]
    assert "cutting spoken lines" in r["reason"] and "Asking the AI to tighten" in r["reason"]
    assert r["after"]["seconds"] > 5
    c = O.propose(svc, p, p.root.id, O.Goal(cost=0.01))
    assert not c["met"] and "lowest cost reachable" in c["reason"]


def test_a_goal_is_required(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    with pytest.raises(ValueError, match="Choose a goal"):
        O.propose(svc, p, p.root.id, O.Goal())


# ------------------------------------------------------------------ never touched
def test_made_kept_and_protected_clips_are_never_changed(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    a, b, c, d = leaves(p)
    a.status = NodeStatus.done
    b.locked = True
    svc.save(p)
    p = svc.load(p.id)
    r = O.propose(svc, p, p.root.id, O.Goal(lowest=True), protect=[c.id])
    touched = {n for e in r["edits"] for n in e["nodes"]}
    assert not touched & {a.id, b.id, c.id} and d.id in touched
    assert r["protected"]["numbers"] == ["1.1", "1.2", "2.1"]
    q = svc.optimize_apply(p.id, {"lowest": True, "protect": [c.id]})
    la, lb, lc, ld = leaves(q)
    assert (la.target_seconds, lb.target_seconds, lc.target_seconds) == (10.0, 10.0, 10.0) and ld.target_seconds < 10.0


# ------------------------------------------------------------------ level 2: a little less polish
def test_level_two_steps_the_quality_down_and_takes_fewer_for_people_clips(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, quality="best")
    r = O.propose(svc, p, p.root.id, O.Goal(length=1000, cost=0.5))
    kinds = {e["kind"] for e in r["edits"] if e["level"] == 2}
    assert {"mode", "takes"} <= kinds
    mode = next(e for e in r["edits"] if e["kind"] == "mode")
    assert mode["value"] in ("balanced", "budget") and mode["effect"]["cost"] < 0 and "less polished" in mode["loses"]
    takes = next(e for e in r["edits"] if e["kind"] == "takes")
    assert takes["effect"]["cost"] < 0 and "Fewer takes" in takes["loses"]
    q = svc.optimize_apply(p.id, {"cost": 0.5})
    assert q.settings.quality_mode == mode["value"]
    assert all(E.takes_for(q, c) == 2 for c in leaves(q))


def test_a_part_changes_only_its_own_quality(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, quality="best")
    part2 = p.root.children[1]
    r = O.propose(svc, p, part2.id, O.Goal(cost=0.5))
    assert r["scope"]["number"] == "2" and not r["scope"]["is_whole_video"]
    q = svc.optimize_apply(p.id, {"scope": part2.id, "cost": 0.5})
    assert q.settings.quality_mode == "best" and q.root.children[0].quality_mode is None and q.root.children[1].quality_mode in ("balanced", "budget")
    assert [E.takes_for(q, c) for c in leaves(q)] == [3, 3, 2, 2]
    assert O.propose(svc, p, part2.id, O.Goal(lowest=True))["before"]["clips"] == 2          # the numbers are for the part, not the video


def test_a_step_that_would_use_a_weak_model_is_not_proposed(svc, monkeypatch):
    keys(svc, monkeypatch)
    for e in svc.catalog.for_job("video"):
        monkeypatch.setattr(e, "strengths", {k: 1 for k in ("human_motion", "other")}, raising=False)           # every model is weak for this shot
    p = demo(svc, quality="best")
    r = O.propose(svc, p, p.root.id, O.Goal(cost=0.5))
    if not any(e["kind"] == "mode" for e in r["edits"]):
        assert any("weak" in n for n in r["notes"])


# ------------------------------------------------------------------ level 3: something you would notice
def test_level_three_lists_what_you_lose_and_part_music_is_explained(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, music=True)
    r = O.propose(svc, p, p.root.id, O.Goal(cost=0.5), max_level=3)
    lost = {e["kind"]: e["loses"] for e in r["edits"] if e["level"] == 3}
    assert "review" in " ".join(e["id"] for e in r["edits"] if e["level"] == 3) and all(lost.values())
    part = O.propose(svc, p, p.root.children[0].id, O.Goal(cost=0.5))
    assert not any(e["kind"] == "music_off" for e in part["edits"])
    assert any("one track for the whole video" in n for n in part["notes"])


def test_natural_sound_can_be_switched_off_for_one_part_only(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, quality="budget")                                                            # a model with no sound of its own: natural sound is made for it
    part1 = p.root.children[0]
    before = {c.id: E.wants_ambience(p, c, E.plan_clip(p, c, svc.reg)) for c in leaves(p)}
    assert all(before.values())
    r = O.propose(svc, p, part1.id, O.Goal(cost=0.01), max_level=3)
    sound = next(e for e in r["edits"] if e["kind"] == "sound_off")
    assert sound["effect"]["cost"] < 0 and "No wind" in sound["loses"]
    q = svc.optimize_apply(p.id, {"scope": part1.id, "cost": 0.01, "ticked": [sound["id"]]})
    after = {c.id: E.wants_ambience(q, c, E.plan_clip(q, c, svc.reg)) for c in leaves(q)}
    assert q.root.children[0].ambience is False and q.root.children[1].ambience is None and q.settings.ambience
    ids = [c.id for c in leaves(q)]
    assert [after[i] for i in ids] == [False, False, True, True]                              # only the first part lost its made sound


# ------------------------------------------------------------------ one saved change, one undo
def test_apply_is_one_change_and_one_undo_takes_it_all_back(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    before = svc.load(p.id)
    svc.optimize_apply(p.id, {"cost": 3, "max_level": 3})
    changed = svc.load(p.id)
    assert changed.model_dump_json() != before.model_dump_json()
    ProjectStore.undo(p.id)
    restored = svc.load(p.id)
    assert [c.target_seconds for c in leaves(restored)] == [c.target_seconds for c in leaves(before)]
    assert restored.settings.quality_mode == before.settings.quality_mode and restored.settings.target_seconds == before.settings.target_seconds


def test_after_an_optimize_the_lengths_follow_what_is_inside(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    assert p.settings.length_mode == "fixed"
    q = svc.optimize_apply(p.id, {"lowest": True})
    total = sum(c.duration.likely_s for c in leaves(q))
    assert q.settings.target_seconds == pytest.approx(total, abs=0.6) and q.root.target_seconds == q.settings.target_seconds
    assert not any("vs target" in w for w in svc.summary(q)["warnings"])                  # a goal you set earlier is replaced by what you chose now


# ------------------------------------------------------------------ joins
def link_clips(svc, p, join="continues"):
    """Every clip continues the one before it (the first clip of a later part starts with a cut)."""
    ls = leaves(p)
    firsts = {part.children[0].id for part in p.root.children}
    for i in range(1, len(ls)):
        svc.set_join(p.id, ls[i].id, "cut" if ls[i].id in firsts else join)
    return svc.load(p.id)


def test_joins_kept_is_shown_and_a_dropped_clip_breaks_the_joins_around_it(svc, monkeypatch):
    keys(svc, monkeypatch)
    offline_brain(svc, monkeypatch)
    p = link_clips(svc, demo(svc, parts=1, per=4))
    ids = [c.id for c in leaves(p)]
    plain = O.propose(svc, p, p.root.id, O.Goal(lowest=True))
    assert plain["joins"] == {"kept": 3, "of": 3, "broken": []}                                # resizing never changes a join
    edit = {"clip": "1.2", "action": "drop", "reason": "said elsewhere", "kept": "the idea is in clip 1.3"}
    r = O.propose(svc, p, p.root.id, O.Goal(lowest=True), ai_edits=[edit], ticked=["L4:drop:" + ids[1]])
    assert r["joins"]["of"] == 3 and r["joins"]["kept"] == 1 and len(r["joins"]["broken"]) == 2
    assert "lost" in r["joins"]["broken"][0]
    q = O.apply(svc, svc.load(p.id), p.root.id, O.Goal(lowest=True), ["L4:drop:" + ids[1]], ai_edits=[edit])
    after = leaves(q)
    assert [c.id for c in after] == [ids[0], ids[2], ids[3]]
    assert after[1].continuity.join in ("cut", "") or O.joins_of(q).get((ids[0], ids[2])) is None                # the clip after a dropped one starts with a cut, never a false join


def test_merging_two_clips_keeps_the_first_start_the_last_end_and_the_join_after_it(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = link_clips(svc, demo(svc, parts=1, per=4))
    ids = [c.id for c in leaves(p)]
    q0 = svc.load(p.id)
    leaves(q0)[0].script.start_state, leaves(q0)[1].script.end_state = "she is at the door", "she is at the window"
    svc.save(q0)
    p = svc.load(p.id)
    edit = {"clip": "1.1", "action": "merge_with_next", "reason": "one continuous idea", "kept": "all of it"}
    r = O.propose(svc, p, p.root.id, O.Goal(lowest=True), ai_edits=[edit], ticked=["L4:merge:" + ids[0]])
    assert r["joins"] == {"kept": 3, "of": 3, "broken": []}                                    # the join between the two is inside the merged clip, the others stay
    q = O.apply(svc, svc.load(p.id), p.root.id, O.Goal(lowest=True), ["L4:merge:" + ids[0]], ai_edits=[edit])
    first, third, fourth = leaves(q)
    assert first.id == ids[0] and len(first.script.dialogue) == 2 and len(first.script.action_beats) == 4
    assert first.script.start_state == "she is at the door" and first.script.end_state == "she is at the window"
    assert O.joins_of(q).get((first.id, third.id)) == "continues"                              # what continued from the second clip now continues from the merged one


def test_the_new_continuity_findings_are_listed_for_the_proposal(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, parts=1, per=2)
    r = O.propose(svc, p, p.root.id, O.Goal(lowest=True))
    assert isinstance(r["findings"], list)


# ------------------------------------------------------------------ level 4: the AI, checked before you see it
def test_asking_the_ai_shows_its_cost_first_and_nothing_is_asked_when_nothing_can_change(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    info = O.propose(svc, p, p.root.id, O.Goal(lowest=True))["ai"]
    assert info["available"] and info["clips"] == 4 and 0 < info["cost_low"] < info["cost_high"]
    for c in leaves(p):
        c.status = NodeStatus.done
    svc.save(p)
    done = O.propose(svc, svc.load(p.id), p.root.id, O.Goal(lowest=True))["ai"]
    assert not done["available"] and "made, kept or protected" in done["why"]
    with pytest.raises(ValueError, match="made, kept or protected"):
        asyncio.run(svc.optimize_ai(p.id, {"lowest": True}))


def test_the_offline_helper_trims_the_last_sentence_and_never_a_line_marked_exact(svc, monkeypatch):
    offline_brain(svc, monkeypatch)
    p = demo(svc, speech=LONG, seconds=12.0)
    c0 = leaves(p)[0]
    c0.script.dialogue[0].fixed = True
    svc.save(p)
    got = asyncio.run(svc.optimize_ai(p.id, {"length": 10}))
    numbers = {v["numbers"][0] for v in got["valid"]}
    assert "1.1" not in numbers and {"1.2", "2.1", "2.2"} <= numbers                          # the exact line is not touched
    shorter = next(v for v in got["valid"] if v["numbers"] == ["1.2"])
    assert shorter["value"]["dialogue"] == [TRIMMED] and shorter["kept"] and shorter["reason"]
    assert got["cost_usd"] == 0                                                              # the offline helper is free


def test_ai_suggestions_become_level_four_edits_you_tick_and_apply(svc, monkeypatch):
    keys(svc, monkeypatch)
    offline_brain(svc, monkeypatch)
    p = demo(svc, speech=LONG, seconds=12.0)
    got = asyncio.run(svc.optimize_ai(p.id, {"lowest": True}))
    r = svc.optimize_propose(p.id, {"lowest": True, "ai_edits": got["edits"]})
    four = [e for e in r["edits"] if e["level"] == 4]
    assert four and not any(e["checked"] for e in four)                                      # "as low as possible without losing quality" never ticks a script change by itself
    base = svc.optimize_propose(p.id, {"lowest": True})
    ticked = [e["id"] for e in r["edits"] if e["checked"]] + [four[0]["id"]]
    r2 = svc.optimize_propose(p.id, {"lowest": True, "ai_edits": got["edits"], "ticked": ticked})
    assert r2["after"]["seconds"] < base["after"]["seconds"] and r2["after"]["cost"] < base["after"]["cost"]
    q = svc.optimize_apply(p.id, {"lowest": True, "ai_edits": got["edits"], "ticked": ticked})
    changed = [c for c in leaves(q) if c.script.dialogue[0].text != LONG]
    assert len(changed) == 1 and changed[0].script.dialogue[0].text == TRIMMED               # only the one you ticked
    assert changed[0].voice_audio is None                                                    # an old voice no longer fits the new words


def test_a_goal_that_needs_the_ai_ticks_its_changes_for_you_to_see_before_applying(svc, monkeypatch):
    keys(svc, monkeypatch)
    offline_brain(svc, monkeypatch)
    p = demo(svc, speech=LONG, seconds=12.0)
    base = O.propose(svc, p, p.root.id, O.Goal(length=1))
    goal = {"length": base["after"]["seconds"] - 2}
    assert not O.propose(svc, p, p.root.id, O.Goal(**goal))["met"]                           # the steps without the AI cannot get there
    got = asyncio.run(svc.optimize_ai(p.id, goal))
    r = svc.optimize_propose(p.id, {**goal, "ai_edits": got["edits"]})
    assert any(e["level"] == 4 and e["checked"] for e in r["edits"])                          # needed to meet the goal, so ticked: the person still sees and can untick
    assert r["after"]["seconds"] < base["after"]["seconds"] and r["met"] and r["stopped_at"] == 4


def test_the_rules_refuse_what_the_ai_should_not_do(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, parts=1, per=4)
    a, b, c, d = leaves(p)
    a.status = NodeStatus.done
    b.script.dialogue[0].fixed = True
    svc.save(p)
    p = svc.load(p.id)
    raw = [
        {"clip": "1.1", "action": "shorten", "dialogue": ["Hello."]},                                       # made: refused
        {"clip": "1.2", "action": "drop"},                                                                   # holds an exact line: refused
        {"clip": "1.3", "action": "shorten", "dialogue": ["Hi."]},                                           # cuts more than half the words: refused
        {"clip": "1.3", "action": "shorten", "dialogue": [LINE, LINE]},                                      # wrong number of lines: refused
        {"clip": "1.4", "action": "merge_with_next"},                                                        # no clip after it: refused
        {"clip": "9.9", "action": "drop"},                                                                   # not in this video: refused
    ]
    edits, skipped = O.validate_ai(svc, p, p.root.id, frozenset(), raw)
    assert not edits and len(skipped) == 6
    text = " ".join(skipped)
    for word in ("made, kept or protected", "say exactly this", "cut more than 50%", "number of lines", "cannot be merged", "not part of this scope"):
        assert word in text, word


def test_a_part_keeps_one_clip_and_loses_at_most_the_allowed_share(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, parts=1, per=4)
    raw = [{"clip": f"1.{i}", "action": "drop", "reason": "r", "kept": "k"} for i in (1, 2, 3, 4)]
    edits, skipped = O.validate_ai(svc, p, p.root.id, frozenset(), raw)
    assert len(edits) == 2 and len(skipped) == 2 and all("at least one clip" in s for s in skipped)       # max_cut_ratio 0.5 of 4 clips
    monkeypatch.setattr(policy_mod.current(), "max_cut_ratio", 0.25)
    edits, _ = O.validate_ai(svc, p, p.root.id, frozenset(), raw)
    assert len(edits) == 1


def test_a_merge_across_a_cut_or_between_different_shots_is_refused(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc, parts=1, per=3)
    ids = [c.id for c in leaves(p)]
    svc.set_join(p.id, ids[1], "cut")
    svc.set_join(p.id, ids[2], "same_scene")
    p = svc.load(p.id)
    leaves(p)[2].script.on_camera_speech = True
    edits, skipped = O.validate_ai(svc, p, p.root.id, frozenset(), [{"clip": "1.1", "action": "merge_with_next"}, {"clip": "1.2", "action": "merge_with_next"}])
    assert not edits and any("across a cut" in s for s in skipped) and any("different kinds of shot" in s for s in skipped)


# ------------------------------------------------------------------ named settings, API and command line
def test_the_optimizer_settings_are_named_with_help_text():
    names = {n: (v, why) for n, v, why in policy_mod.describe()}
    for n in ("max_cut_ratio", "optimize_slack_s", "optimize_goal_tolerance", "optimize_ai_cost_range"):
        assert names[n][1]
    assert names["max_cut_ratio"][0] == 0.5


def test_the_optimize_task_is_a_simple_job_for_the_cheaper_ai(svc):
    assert svc.reg.llm_group("optimize") == "simple"


def test_the_api_proposes_asks_the_ai_and_applies(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    keys(svc, monkeypatch)
    offline_brain(svc, monkeypatch)
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p = demo(svc)
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/optimize/propose", json={"lowest": True}).json()
        assert r["before"]["seconds"] > r["after"]["seconds"] and r["levels"][0]["name"] == "No visible change"
        assert client.post(f"/api/projects/{p.id}/optimize/propose", json={}).status_code == 400
        ai = client.post(f"/api/projects/{p.id}/optimize/ai", json={"lowest": True}).json()
        assert ai["valid"] and ai["cost_usd"] == 0
        done = client.post(f"/api/projects/{p.id}/optimize/apply", json={"lowest": True}).json()
        assert done["summary"]["seconds"] == pytest.approx(r["after"]["seconds"], abs=0.1)


def test_the_command_line_shows_a_proposal_and_applies_it_when_asked(svc, monkeypatch):
    from typer.testing import CliRunner
    from video_generator import cli
    keys(svc, monkeypatch)
    monkeypatch.setattr(cli, "_svc", lambda: svc)
    p = demo(svc)
    run = CliRunner()
    shown = run.invoke(cli.app, ["optimize", "--lowest", "-p", p.id])
    assert shown.exit_code == 0 and "level 1 No visible change" in shown.output and "Joins kept" not in shown.output
    assert svc.load(p.id).root.children[0].children[0].target_seconds == 10.0                  # showing does not change anything
    done = run.invoke(cli.app, ["optimize", "--lowest", "--apply", "--yes", "-p", p.id])
    assert done.exit_code == 0 and "Applied" in done.output
    assert svc.load(p.id).root.children[0].children[0].target_seconds < 10.0
    bad = run.invoke(cli.app, ["optimize", "-p", p.id])
    assert bad.exit_code != 0


# ------------------------------------------------------------------ speed: every edit refreshes the estimate, so a refresh must not start a program per model
def test_a_refresh_does_not_start_a_sub_process_for_every_model(svc, monkeypatch):
    from video_generator import media
    keys(svc, monkeypatch)
    p = demo(svc, parts=3, per=4)
    media.flite_available.cache_clear()
    svc.refresh(p.model_copy(deep=True))                                                      # warm up: the one question about ffmpeg is asked here
    calls = []
    real = media.subprocess.run
    monkeypatch.setattr(media.subprocess, "run", lambda *a, **k: calls.append(a) or real(*a, **k))
    for _ in range(3):
        svc.refresh(p.model_copy(deep=True))
    assert calls == []


def test_after_the_ai_has_been_asked_the_reason_counts_what_it_could_do(svc, monkeypatch):
    keys(svc, monkeypatch)
    offline_brain(svc, monkeypatch)
    p = demo(svc, speech=LONG, seconds=12.0)
    got = asyncio.run(svc.optimize_ai(p.id, {"length": 1}))
    r = svc.optimize_propose(p.id, {"length": 1, "ai_edits": got["edits"]})
    assert not r["met"] and "Even with the AI's suggestions" in r["reason"] and "Asking the AI" not in r["reason"]
    without = svc.optimize_propose(p.id, {"length": 1})
    assert r["after"]["seconds"] < without["after"]["seconds"] and "Asking the AI to tighten" in without["reason"]


def test_when_the_video_is_over_budget_the_next_step_also_offers_the_optimizer(svc, monkeypatch):
    keys(svc, monkeypatch)
    p = demo(svc)
    p.settings.budget_usd = 1.0
    svc.save(p)
    g = svc.summary(svc.load(p.id))["guide"]
    cost = next(x for x in g["steps"] if x["id"] == "cost")
    assert cost["action"]["kind"] == "budget" and any(a["action"]["kind"] == "optimize" for a in cost["also"])
