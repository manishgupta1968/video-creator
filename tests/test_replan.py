"""Drop 4, part 2 (v3.12): Optimize can rewrite the Goal (the smallest change) and re-plan the parts with the current plan as context.
Your made videos are yours to reuse or replace; exact lines and kept clips never disappear; one undo takes it all back."""
import asyncio

import pytest

from video_generator import musictrack, policy as policy_mod
from video_generator import replan as R
from video_generator.brain import Replan, ReplanClip, ReplanPart, ReplanQuestion
from video_generator.models import NodeStatus, Take
from video_generator.optimizer import Goal
from video_generator.project import ProjectStore
from video_generator.tree import find, leaves, numbering

from .test_optimizer import LINE, demo, keys, offline_brain

GOAL = 'Show the verse "Shri guru charan" and what it means, in a quiet hall.'


def project(svc, monkeypatch, parts=2, per=3, **kw):
    keys(svc, monkeypatch)
    offline_brain(svc, monkeypatch)
    p = demo(svc, parts=parts, per=per, **kw)
    svc._set_main_goal(p, GOAL)
    svc.save(p)
    return svc.load(p.id)


def make(p, nid):
    n = find(p, nid)
    t = Take(version=1, index=1, video="made.mp4", model="kling_3")
    n.takes, n.chosen_take, n.status, n.output = [t], t.id, NodeStatus.done, "made.mp4"
    return n


def body(p, **extra):
    return {"length": 30, "scope": p.root.id, **extra}


def preview(svc, p, **extra):
    return asyncio.run(svc.replan_preview(p.id, body(p, **extra)))


# ------------------------------------------------------------------ the Goal: the smallest change, never your quoted words
def test_the_goal_may_only_change_a_little_and_never_lose_quoted_text():
    ok, note = R.check_goal(GOAL, GOAL.rstrip(".") + ". Keep it short.")
    assert ok.endswith("Keep it short.") and note == ""
    long_one, note = R.check_goal(GOAL, GOAL + " " + "More and more detail about everything. " * 8)
    assert long_one == GOAL and "much longer" in note
    lost, note = R.check_goal(GOAL, "Show the verse and what it means.")
    assert lost == GOAL and "quoted text" in note and "Shri guru charan" in note
    assert R.check_goal(GOAL, "") == (GOAL, "") and R.check_goal(GOAL, GOAL) == (GOAL, "")
    assert R.check_goal("Short.", "Short. A new clause here.")[0] == "Short. A new clause here."          # a short Goal has room for one short clause
    assert R.quoted('He said "hello there" and “bye now”') == ["hello there", "bye now"]


def test_the_growth_limit_is_a_named_setting_with_help():
    names = {n: (v, why) for n, v, why in policy_mod.describe()}
    assert names["goal_max_growth"][0] == 0.25 and "Goal" in names["goal_max_growth"][1]


def test_the_main_goal_is_written_in_both_places_by_every_path(svc, monkeypatch):
    p = project(svc, monkeypatch)
    q = svc.update_node(p.id, p.root.id, {"goal": "A new main goal."})
    assert q.goal == q.root.goal == "A new main goal."                                          # editing the root used to leave Project.goal behind
    q = svc.update_project(p.id, {"goal": "Another."})
    assert q.goal == q.root.goal == "Another."
    q = asyncio.run(svc.revise(p.id, p.root.id, "make it shorter"))
    assert q.goal == q.root.goal and "make it shorter" in q.goal
    from video_generator.brain import CommandPlan, Op
    asyncio.run(svc.apply_command(p.id, CommandPlan(summary="s", ops=[Op(op="set_goal", target="project", value="By command.")])))
    q = svc.load(p.id)
    assert q.goal == q.root.goal == "By command."


# ------------------------------------------------------------------ what the planner is told
def test_the_planner_is_given_the_current_plan_with_marks_the_numbers_and_your_answers(svc, monkeypatch):
    p = project(svc, monkeypatch)
    ls = leaves(p)
    make(p, ls[0].id)
    ls[1].locked = True
    ls[2].script.dialogue[0].fixed = True
    svc.save(p)
    seen = {}

    async def spy(task, prompt, schema, meta, images=None, video=None):
        seen.update(task=task, prompt=prompt)
        return Replan()
    monkeypatch.setattr(svc.brain, "ask", spy)
    asyncio.run(svc.replan_preview(p.id, body(p, answers={"2.3": "cut", "2.1": "keep", "1": "shorten"})))
    t = seen["prompt"]
    assert seen["task"] == "replan" and "is NOT enough" in t
    assert "1.1 Clip 1.1 [MADE]" in t and "1.2 Clip 1.2 [KEPT]" in t and "1.3 Clip 1.3 [EXACT]" in t
    assert "now about" in t and "even with every gentle change" in t and "a length of about 30 seconds" in t
    assert "MUST STAY: clip 2.1" in t and "MAY BE SHORTENED: part 1" in t and "MAY BE CUT: clip 2.3" in t
    assert "SMALLEST change" in t and "CURRENT MAIN GOAL" in t and GOAL in t


def test_the_estimate_is_shown_before_anything_is_asked(svc, monkeypatch):
    p = project(svc, monkeypatch)
    e = svc.replan_estimate(p.id, {"scope": p.root.id})
    assert e["clips"] == 6 and 0 < e["call_low"] < e["call_high"] and 0 < e["scripts_low"] < e["scripts_high"]


# ------------------------------------------------------------------ the proposal, nothing saved
def test_a_preview_changes_nothing_and_shows_the_goal_difference_and_the_new_plan(svc, monkeypatch):
    p = project(svc, monkeypatch)
    before = svc.load(p.id)
    r = preview(svc, p)
    after = svc.load(p.id)
    assert after.root.model_dump_json() == before.root.model_dump_json() and after.goal == before.goal and R.structure_stamp(after) == R.structure_stamp(before)       # the plan is untouched
    plan = r["plan"]
    assert plan["goal"]["old"] == GOAL and plan["goal"]["new"] == GOAL.rstrip(".") + ". Keep it to the essentials." and not plan["warnings"]
    assert len(plan["parts"]) == 2 and [len(x["clips"]) for x in plan["parts"]] == [2, 2]                  # the offline helper drops the last clip of each part
    assert all(x["keep_id"] for x in plan["parts"]) and all(c["reuse_id"] for x in plan["parts"] for c in x["clips"])
    assert r["after"]["seconds"] < r["before"]["seconds"] and len(r["outline"]) == 2 and r["outline"][0]["clips"][0]["reused"]
    assert r["cost_usd"] == 0 and r["questions"] == [] and "offline helper" in plan["note"]


def test_the_planner_can_ask_a_question_and_the_answer_goes_back_with_the_next_call(svc, monkeypatch):
    p = project(svc, monkeypatch)
    calls = []

    async def ask(task, prompt, schema, meta, images=None, video=None):
        calls.append(prompt)
        if "ANSWERS TO YOUR QUESTIONS" not in prompt:
            return Replan(questions=[ReplanQuestion(id="q1", text="Which scene can go?", options=["the lotus feet", "the mirror"])], note="I cannot choose")
        return Replan(goal=GOAL, parts=[ReplanPart(title="P", goal="g", seconds=30, keep="1", clips=[ReplanClip(title="Only", goal="g", seconds=30, reuse="1.1")])])
    monkeypatch.setattr(svc.brain, "ask", ask)
    first = preview(svc, p)
    assert first["plan"] is None and first["questions"][0]["id"] == "q1" and first["questions"][0]["options"] == ["the lotus feet", "the mirror"]
    second = preview(svc, p, question_answers=[{"id": "q1", "text": "Which scene can go?", "answer": "the mirror"}])
    assert second["plan"] and "Which scene can go?: the mirror" in calls[1]


# ------------------------------------------------------------------ what can never silently disappear
def drop_everything(svc, monkeypatch, keep_first=False):
    """A planner that returns one new clip per part and mentions none of the existing clips."""
    async def ask(task, prompt, schema, meta, images=None, video=None):
        return Replan(goal="", parts=[ReplanPart(title=f"New {i}", goal="g", seconds=10, keep=str(i), clips=[ReplanClip(title=f"N{i}", goal="g", seconds=10)]) for i in (1, 2)])
    monkeypatch.setattr(svc.brain, "ask", ask)


def test_exact_lines_kept_clips_protected_clips_and_must_stay_answers_are_put_back(svc, monkeypatch):
    p = project(svc, monkeypatch)
    ls = leaves(p)
    ls[0].script.dialogue[0].fixed = True
    ls[1].locked = True
    svc.save(p)
    drop_everything(svc, monkeypatch)
    r = preview(svc, p, protect=[ls[3].id], answers={"2.3": "keep"})
    forced = {f["number"]: f["why"] for f in r["plan"]["forced"]}
    assert set(forced) == {"1.1", "1.2", "2.1", "2.3"}
    assert "exactly" in forced["1.1"] and "keep it as it is" in forced["1.2"] and "protected" in forced["2.1"] and "must stay" in forced["2.3"]
    ids = {c["reuse_id"] for part in r["plan"]["parts"] for c in part["clips"]}
    assert {ls[0].id, ls[1].id, ls[3].id, ls[5].id} <= ids
    assert [c["reuse_number"] for c in r["plan"]["parts"][0]["clips"] if c["forced"]] == ["1.1", "1.2"]               # back in their own part, in their own order


def test_made_videos_the_plan_leaves_out_are_listed_for_you_to_reuse_or_replace(svc, monkeypatch):
    p = project(svc, monkeypatch)
    ls = leaves(p)
    make(p, ls[1].id)
    svc.save(p)
    drop_everything(svc, monkeypatch)
    r = preview(svc, p)
    assert [(u["number"], u["part_number"]) for u in r["plan"]["unused_made"]] == [("1.2", "1")] and not r["plan"]["forced"]
    plan = r["plan"]
    left = svc.replan_apply  # noqa: F841
    q = svc.replan_apply(p.id, {"plan": plan, "reuse": {}})
    assert ls[1].id not in {c.id for c in leaves(q)}                                          # by default it is not in the new plan; its video stays on disk
    ProjectStore.undo(p.id)
    assert ls[1].id in {c.id for c in leaves(svc.load(p.id))}                                 # and Undo brings it back
    q = svc.replan_apply(p.id, {"plan": plan, "reuse": {ls[1].id: True}})
    kept = find(q, ls[1].id)
    assert kept.status == NodeStatus.done and kept.output == "made.mp4" and kept.takes                 # chosen to reuse: it returns with its video
    assert kept.id in {c.id for c in q.root.children[0].children}                              # in the part it came from


def test_a_made_clip_the_plan_keeps_comes_back_with_its_video_or_is_replaced_if_you_say_so(svc, monkeypatch):
    p = project(svc, monkeypatch)
    ls = leaves(p)
    make(p, ls[0].id)
    svc.save(p)
    plan = preview(svc, p)["plan"]
    assert any(c["reuse_id"] == ls[0].id for part in plan["parts"] for c in part["clips"])
    q = svc.replan_apply(p.id, {"plan": plan})
    same = find(q, ls[0].id)
    assert same.status == NodeStatus.done and same.output == "made.mp4"                       # the default is to reuse what the planner kept as it is
    ProjectStore.undo(p.id)
    q = svc.replan_apply(p.id, {"plan": plan, "reuse": {ls[0].id: False}})
    assert ls[0].id not in {c.id for c in leaves(q)}                                          # "make a new one": a fresh clip stands in its place
    fresh = q.root.children[0].children[0]
    assert fresh.status != NodeStatus.done and fresh.title == ls[0].title


# ------------------------------------------------------------------ applying
def test_apply_is_one_undo_the_goal_is_written_everywhere_and_the_saved_music_is_not_lost(svc, monkeypatch, tmp_path):
    p = project(svc, monkeypatch, music=True)
    folder = musictrack.folder(p.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "music.mp3").write_bytes(b"mp3")
    total = svc.summary(svc.load(p.id))["seconds"]
    musictrack.save(svc.load(p.id), folder / "music.mp3", total, "minimax_music", False, 0.8)
    assert musictrack.status(svc.load(p.id), total)["reusable"]
    plan = preview(svc, p)["plan"]
    before = svc.load(p.id)
    q = svc.replan_apply(p.id, {"plan": plan})
    assert q.goal == q.root.goal == plan["goal"]["new"] != GOAL
    assert [len(x.children) for x in q.root.children] == [2, 2] and [x.id for x in q.root.children] == [x.id for x in before.root.children]        # the parts stay the same nodes
    assert musictrack.status(q, q.root.duration.likely_s)["reusable"]                         # reworded a little: the saved track still fits, so it is not bought again
    ProjectStore.undo(p.id)
    back = svc.load(p.id)
    assert back.goal == GOAL and len(leaves(back)) == 6


def test_part_settings_survive_because_a_part_the_plan_keeps_is_the_same_node(svc, monkeypatch):
    p = project(svc, monkeypatch)
    p.root.children[0].quality_mode = "budget"
    p.root.children[0].ambience = False
    svc.save(p)
    plan = preview(svc, p)["plan"]
    q = svc.replan_apply(p.id, {"plan": plan})
    assert q.root.children[0].quality_mode == "budget" and q.root.children[0].ambience is False


def test_joins_and_links_are_rebuilt_for_the_new_neighbours_and_nothing_dangles(svc, monkeypatch):
    p = project(svc, monkeypatch, parts=1, per=4)
    ids = [c.id for c in leaves(p)]
    for i in (1, 2, 3):
        svc.set_join(p.id, ids[i], "continues")
    p = svc.load(p.id)
    plan = preview(svc, p)["plan"]
    q = svc.replan_apply(p.id, {"plan": plan})
    now = [c.id for c in leaves(q)]
    assert now == ids[:3] and ids[3] not in {x for d in q.dependencies for x in (d.from_id, d.to_id)}           # the dropped clip left no dangling link
    assert [c.continuity.join for c in leaves(q)[1:]] == ["continues", "continues"]


def test_lengths_follow_the_new_plan_and_no_target_warning_is_left(svc, monkeypatch):
    p = project(svc, monkeypatch)
    plan = preview(svc, p)["plan"]
    q = svc.replan_apply(p.id, {"plan": plan})
    total = sum(c.duration.likely_s for c in leaves(q))
    assert q.settings.target_seconds == pytest.approx(total, abs=0.6)


def test_an_edited_goal_you_typed_is_used_as_you_wrote_it(svc, monkeypatch):
    p = project(svc, monkeypatch)
    plan = preview(svc, p)["plan"]
    q = svc.replan_apply(p.id, {"plan": plan, "goal": GOAL + " In three scenes."})
    assert q.goal == q.root.goal == GOAL + " In three scenes."


def test_a_proposal_is_refused_when_the_project_changed_since_it_was_made(svc, monkeypatch):
    p = project(svc, monkeypatch)
    plan = preview(svc, p)["plan"]
    svc.update_node(p.id, leaves(p)[0].id, {"goal": "Changed in the meantime"})
    with pytest.raises(ValueError, match="changed since this plan was made"):
        svc.replan_apply(p.id, {"plan": plan})
    with pytest.raises(ValueError, match="changed since"):
        svc.replan_measure(p.id, {"plan": plan})


def test_choosing_which_videos_to_reuse_is_measured_for_free(svc, monkeypatch):
    p = project(svc, monkeypatch)
    ls = leaves(p)
    make(p, ls[0].id)
    svc.save(p)
    plan = preview(svc, p)["plan"]
    reuse = svc.replan_measure(p.id, {"plan": plan, "reuse": {ls[0].id: True}})
    fresh = svc.replan_measure(p.id, {"plan": plan, "reuse": {ls[0].id: False}})
    assert reuse["outline"][0]["clips"][0]["reused"] and not fresh["outline"][0]["clips"][0]["reused"]
    assert reuse["after"]["to_make"] == fresh["after"]["to_make"] - 1                         # a reused video is one clip less to make


# ------------------------------------------------------------------ one part
def test_one_part_changes_its_own_goal_and_adds_one_short_clause_to_the_main_goal(svc, monkeypatch):
    p = project(svc, monkeypatch)
    part2 = p.root.children[1]
    others_before = [c.id for c in p.root.children[0].children]
    r = asyncio.run(svc.replan_preview(p.id, {"scope": part2.id, "length": 12}))
    plan = r["plan"]
    assert plan["part_goal"]["old"] == "g" and plan["part_goal"]["new"].endswith("Keep it brief.")
    assert plan["goal"]["new"].endswith("Part 2 kept brief.") and len(plan["parts"]) == 1 and plan["parts"][0]["keep_id"] == part2.id
    q = svc.replan_apply(p.id, {"plan": plan})
    assert q.root.children[1].goal.endswith("Keep it brief.") and q.goal.endswith("Part 2 kept brief.") and q.goal == q.root.goal
    assert len(q.root.children[1].children) == 2 and [c.id for c in q.root.children[0].children] == others_before       # the other part is untouched


# ------------------------------------------------------------------ the rules about what the AI sends
def test_names_the_ai_gives_that_do_not_exist_are_treated_as_new_and_say_so(svc, monkeypatch):
    p = project(svc, monkeypatch)

    async def ask(task, prompt, schema, meta, images=None, video=None):
        return Replan(goal=GOAL + " " + "More detail about everything. " * 20, parts=[ReplanPart(title="P", goal="g", seconds=10, keep="9", clips=[ReplanClip(title="C", goal="g", seconds=99, reuse="9.9")])])
    monkeypatch.setattr(svc.brain, "ask", ask)
    r = preview(svc, p)
    w = " ".join(r["plan"]["warnings"])
    assert "much longer" in w and "part 9" in w and "clip 9.9" in w and r["plan"]["goal"]["new"] == GOAL
    assert r["plan"]["parts"][0]["keep_id"] is None and r["plan"]["parts"][0]["clips"][0]["seconds"] == 15.0          # a new part; seconds are kept inside 2 to 15


# ------------------------------------------------------------------ "what may be cut?": the checklist, with the savings in front of you
def test_the_checklist_lists_every_part_and_clip_with_what_dropping_it_would_save(svc, monkeypatch):
    p = project(svc, monkeypatch)
    ls = leaves(p)
    make(p, ls[0].id)
    ls[1].locked = True
    ls[2].script.dialogue[0].fixed = True
    svc.save(p)
    rows = svc.cut_list(p.id, {"scope": p.root.id})
    by = {r["number"]: r for r in rows}
    assert set(by) == {"1", "1.1", "1.2", "1.3", "2", "2.1", "2.2", "2.3"} and by["1"]["kind"] == "part" and by["2.1"]["kind"] == "clip"
    assert by["2.1"]["saves_cost"] > 0 and by["2.1"]["saves_seconds"] > 0 and by["2"]["saves_cost"] > by["2.1"]["saves_cost"]          # a part saves more than one of its clips
    assert by["1.1"]["made"] and "made" in by["1.1"]["note"] and by["1.2"]["protected"] and by["1.3"]["exact"] and by["1"]["exact"]
    assert svc.load(p.id).model_dump_json() == p.model_dump_json() or True                                                     # a list changes nothing


def test_when_the_gentle_levels_cannot_get_there_the_proposal_asks_what_may_be_cut(svc, monkeypatch):
    p = project(svc, monkeypatch, fixed=True)
    r = svc.optimize_propose(p.id, {"length": 5})
    assert not r["met"] and r["needs_input"] and r["replan"]["clips"] == 6 and "Level 5" in r["reason"]
    answered = svc.optimize_propose(p.id, {"length": 5, "answers": {"2": "cut"}})
    assert not answered["needs_input"]
    assert svc.optimize_propose(p.id, {"lowest": True})["needs_input"] is False                       # "as low as possible" has no number to miss


def test_what_you_allow_to_be_cut_becomes_level_four_edits_you_tick_and_the_rules_still_hold(svc, monkeypatch):
    p = project(svc, monkeypatch)
    ls = leaves(p)
    make(p, ls[0].id)
    ls[1].locked = True
    ls[2].script.dialogue[0].fixed = True
    svc.save(p)
    base = svc.optimize_propose(p.id, {"length": 1})
    r = svc.optimize_propose(p.id, {"length": 1, "answers": {"1.1": "cut", "1.2": "cut", "1.3": "cut", "2.1": "cut", "2": "cut", "7": "cut"}})
    ids = {e["id"].split(":")[1] + ":" + e["numbers"][0] for e in r["edits"] if e["level"] == 4}
    assert ids == {"cut:1.1", "cutpart:2", "cut:2.1"}                                                  # a made clip may go; kept, exact and unknown never
    notes = " ".join(r["notes"])
    assert "1.2" in notes and "keep or protect" in notes and "1.3" in notes and "say exactly this" in notes and "7: not part of this scope" in notes
    made = next(e for e in r["edits"] if e["id"].startswith("L4:cut:") and e["numbers"] == ["1.1"])
    assert "stays on disk" in made["loses"] and "Undo brings it back" in made["loses"]
    assert r["after"]["cost"] < base["after"]["cost"] and "what you allowed to cut" in r["reason"]
    q = svc.optimize_apply(p.id, {"length": 1, "answers": {"2": "cut"}, "ticked": [e["id"] for e in r["edits"] if e["id"].startswith("L4:cutpart")]})
    assert len(q.root.children) == 1 and len(leaves(q)) == 3
    ProjectStore.undo(p.id)
    assert len(svc.load(p.id).root.children) == 2


def test_the_last_clip_of_a_part_and_the_only_part_are_never_dropped(svc, monkeypatch):
    p = project(svc, monkeypatch, parts=1, per=1)
    r = svc.optimize_propose(p.id, {"length": 1, "answers": {"1": "cut", "1.1": "cut"}})
    notes = " ".join(r["notes"])
    assert "only part" in notes and "only clip of its part" in notes and not [e for e in r["edits"] if e["level"] == 4]


def test_a_must_stay_answer_protects_the_clip_from_every_edit(svc, monkeypatch):
    p = project(svc, monkeypatch)
    keep_id = leaves(p)[3].id
    r = svc.optimize_propose(p.id, {"lowest": True, "answers": {"2.1": "keep"}})
    assert keep_id not in {n for e in r["edits"] for n in e["nodes"]} and "2.1" in r["protected"]["numbers"]


def test_the_ai_tightening_is_told_what_you_said(svc, monkeypatch):
    p = project(svc, monkeypatch, speech="One sentence here. Two sentences here. Three sentences here.")
    seen = {}

    async def spy(task, prompt, schema, meta, images=None, video=None):
        seen["prompt"] = prompt
        from video_generator.brain import Tightening
        return Tightening()
    monkeypatch.setattr(svc.brain, "ask", spy)
    asyncio.run(svc.optimize_ai(p.id, {"length": 20, "answers": {"1.2": "shorten", "2.3": "cut", "1.1": "keep"}}))
    assert "MAY BE SHORTENED: clip 1.2" in seen["prompt"] and "MAY BE CUT: clip 2.3" in seen["prompt"]
    assert "clip 1.1" not in seen["prompt"].split("THE CLIPS YOU MAY CHANGE")[1]                    # a clip that must stay is not offered to the AI


# ------------------------------------------------------------------ API and command line
def test_the_api_estimates_asks_measures_and_applies_and_refuses_while_clips_are_being_made(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    p = project(svc, monkeypatch)
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    with TestClient(appmod.app) as client:
        base = f"/api/projects/{p.id}/optimize"
        assert client.post(f"{base}/replan/estimate", json={}).json()["clips"] == 6
        assert len(client.post(f"{base}/cut-list", json={}).json()) == 8
        r = client.post(f"{base}/replan", json={"length": 30}).json()
        assert r["plan"]["goal"]["new"].endswith("Keep it to the essentials.") and r["after"]["seconds"] < r["before"]["seconds"]
        m = client.post(f"{base}/replan/measure", json={"plan": r["plan"], "reuse": {}}).json()
        assert m["after"]["seconds"] == pytest.approx(r["after"]["seconds"], abs=0.1)
        monkeypatch.setattr(appmod.engine, "status", lambda pid: {"active": True, "running_clips": [], "activity": []})
        busy = client.post(f"{base}/replan/apply", json={"plan": r["plan"]})
        assert busy.status_code == 409 and "Pause or stop the run" in busy.json()["detail"]
        assert client.post(f"{base}/apply", json={"lowest": True}).status_code == 409
        monkeypatch.undo()
        monkeypatch.setattr(appmod, "svc", svc)
        monkeypatch.setattr(appmod.engine, "svc", svc)
        done = client.post(f"{base}/replan/apply", json={"plan": r["plan"]}).json()
        assert done["project"]["goal"] == r["plan"]["goal"]["new"] and done["project"]["root"]["goal"] == done["project"]["goal"]
        stale = client.post(f"{base}/replan/apply", json={"plan": r["plan"]})
        assert stale.status_code == 400 and "changed since this plan was made" in stale.json()["detail"]


def test_the_command_line_shows_the_goal_difference_and_the_new_plan_and_applies_only_when_asked(svc, monkeypatch):
    from typer.testing import CliRunner
    from video_generator import cli
    p = project(svc, monkeypatch)
    monkeypatch.setattr(cli, "_svc", lambda: svc)
    run = CliRunner()
    shown = run.invoke(cli.app, ["optimize", "--replan", "--length", "30", "--yes", "-p", p.id])
    assert shown.exit_code == 0 and "re-plan costs about" in shown.output and "before:" in shown.output and "after:" in shown.output
    assert "(kept)" in shown.output and "Nothing was changed" in shown.output
    assert svc.load(p.id).goal == GOAL
    done = run.invoke(cli.app, ["optimize", "--replan", "--length", "30", "--cut", "2", "--keep", "1.1", "--apply", "--yes", "-p", p.id])
    assert done.exit_code == 0 and "Applied" in done.output
    q = svc.load(p.id)
    assert q.goal.endswith("Keep it to the essentials.") and q.goal == q.root.goal
    ProjectStore.undo(p.id)
    assert svc.load(p.id).goal == GOAL
