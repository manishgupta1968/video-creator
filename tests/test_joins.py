"""Step 7A (v3.10): how a clip joins the clip before it. The plan DECIDES it (before any script exists), the tool ENFORCES it when making,
and then MEASURES it: the first picture of a clip is compared with the last picture of the clip it continues from."""
import asyncio

import pytest
from PIL import Image

from video_generator import estimate as E
from video_generator import media
from video_generator import policy as policy_mod
from video_generator.brain import ActorDraft, ClipDraft, PartDraft, ProjectDraft, StyleDraft
from video_generator.models import ClipScript, DependencyType, Node, NodeKind, NodeStatus, ShotType
from video_generator.project import ProjectStore
from video_generator.runner import Engine
from video_generator.tree import add_child, leaves

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors
from .test_scenarios import build, clip, run_all


def two_clips(svc, join="continues", **kw):
    p, ids = build(svc, "Two shots", [], [
        clip("human_motion", "A person stands at a door", end="the person is at the door, facing the camera", seconds=4),
        clip("human_motion", "The person opens the door", start="the person is at the door, facing the camera", seconds=4)])
    if join:
        svc.set_join(p.id, ids[1], join)
    return svc.load(p.id), ids


def link_types(p, a, b):
    return {d.type for d in p.dependencies if d.from_id == a and d.to_id == b}


# ------------------------------------------------------------------ the plan decides, before any script is written
def test_the_plan_states_a_join_for_every_clip_and_the_links_follow(svc, monkeypatch):
    def c(title, join, reason="", end=""):
        return ClipDraft(title=title, goal=f"{title} goal", seconds=4, join=join, join_reason=reason, place="a room", present=["Asha"],
                         start_state=f"{title} starts", end_state=end or f"{title} ends")

    async def fake_draft(project):
        return ProjectDraft(title="Joins", style=StyleDraft(), actors=[ActorDraft(name="Asha", kind="ai_person")], parts=[
            PartDraft(title="One", goal="g", seconds=8, clips=[c("A", "", ""), c("B", "continues", "the same shot goes on", end="Asha at the window")]),
            PartDraft(title="Two", goal="g", seconds=8, clips=[c("C", "cut", "a new place"), c("D", "same scene", "a new angle")])])
    monkeypatch.setattr(svc.brain, "draft_project", fake_draft)
    p = asyncio.run(svc.draft(svc.new_project("Joins").id, write_scripts=False))
    a, b, c3, d = leaves(p)
    assert [x.continuity.join for x in (a, b, c3, d)] == ["", "continues", "cut", "same_scene"]      # "same scene" is understood as same_scene
    assert b.continuity.join_reason == "the same shot goes on"
    assert link_types(p, a.id, b.id) == {DependencyType.continues_from}
    assert link_types(p, b.id, c3.id) == set()                                                        # a cut across the part boundary: no link
    assert link_types(p, c3.id, d.id) == {DependencyType.same_location}
    assert b.transition_in == "cut"                                                                    # a continuing shot is a hard cut
    assert b.continuity.start_state == a.continuity.end_state                                          # the tool copied it


def test_a_join_left_blank_is_not_invented_and_old_links_stay(svc):
    p, ids = build(svc, "Old project", [], [clip("landscape", "a lamp"), clip("landscape", "a lamp, closer")], links=[(0, 1, "continues_from")])
    b = leaves(p)[1]
    assert b.continuity.join == "" and link_types(p, ids[0], ids[1]) == {DependencyType.continues_from}


def test_changing_a_join_to_continues_copies_the_end_and_marks_a_made_clip_out_of_date(svc):
    p, ids = two_clips(svc, join="cut")
    q = svc.load(p.id)
    first, second = leaves(q)
    second.script.start_state = "something else"
    second.status = NodeStatus.done
    svc.save(q)
    q = svc.set_join(p.id, ids[1], "continues")
    first, second = leaves(q)
    assert second.continuity.join == "continues" and link_types(q, ids[0], ids[1]) == {DependencyType.continues_from}
    assert second.script.start_state == first.script.end_state == "the person is at the door, facing the camera"
    assert second.status == NodeStatus.stale                    # it must be made again, from the hand-over picture
    assert second.transition_in == "cut"
    q = svc.set_join(p.id, ids[1], "cut")
    assert link_types(q, ids[0], ids[1]) == set()
    with pytest.raises(ValueError):
        svc.set_join(p.id, ids[0], "continues")                 # the very first clip has nothing before it
    with pytest.raises(ValueError):
        svc.set_join(p.id, ids[1], "dissolve")


def test_a_changed_end_state_moves_on_to_the_clip_that_continues_from_it(svc):
    p, ids = two_clips(svc)
    q = svc.load(p.id)
    leaves(q)[1].status = NodeStatus.done
    svc.save(q)
    q = svc.update_node(p.id, ids[0], {"script": {"end_state": "the person has stepped back from the door"}})
    first, second = leaves(q)
    assert second.script.start_state == "the person has stepped back from the door" and second.status == NodeStatus.stale


def test_taking_out_the_clip_before_turns_the_join_into_a_cut(svc):
    p, ids = two_clips(svc)
    q = svc.remove_node(p.id, ids[0])
    only = leaves(q)[0]
    assert only.continuity.join == "" and not q.dependencies


# ------------------------------------------------------------------ enforced: a continuing clip must start from a picture
def keys(svc, monkeypatch):
    return Vendors(svc, monkeypatch)


def no_model_starts_from_a_picture(svc, monkeypatch):
    for e in svc.catalog.for_job("video"):
        monkeypatch.setitem(e.capabilities, "start_frame", False)


def test_a_continuing_clip_is_blocked_when_no_connected_model_can_start_from_a_picture(svc, monkeypatch):
    keys(svc, monkeypatch)
    no_model_starts_from_a_picture(svc, monkeypatch)
    p, ids = two_clips(svc)
    first, second = leaves(p)
    plan = E.plan_clip(p, second, svc.reg)
    assert plan.blocked and "last picture" in plan.blocked and "change the join to a cut" in plan.blocked
    assert second.blocked == plan.blocked and not first.blocked
    info = svc.estimate_targets(p.id, [ids[1]])
    assert [b["id"] for b in info["blocked"]] == [ids[1]] and info["blocked"][0]["number"] == "1.2"
    with pytest.raises(ValueError, match="Cannot start yet"):
        asyncio.run(Engine(svc, stop_when_waiting=True).start(p.id, "all", None, auto_pick=True))
    q = svc.set_join(p.id, ids[1], "cut")                                  # the way out: a cut needs no hand-over picture
    assert not leaves(q)[1].blocked


def test_a_cut_or_a_new_angle_is_never_blocked(svc, monkeypatch):
    keys(svc, monkeypatch)
    no_model_starts_from_a_picture(svc, monkeypatch)
    for join in ("cut", "same_scene"):
        p, ids = two_clips(svc, join=join)
        assert not E.plan_clip(p, leaves(p)[1], svc.reg).blocked, join


def test_free_preview_has_nothing_to_enforce(svc, monkeypatch):
    p, ids = two_clips(svc)                                               # no keys at all: every clip is a placeholder
    assert not E.plan_clip(p, leaves(p)[1], svc.reg).blocked


def test_the_part_quality_cannot_remove_the_hand_over_rule_it_ranks_only_models_that_can_start_from_a_picture(svc, monkeypatch):
    keys(svc, monkeypatch)
    cheapest = svc.reg.choose("video", "human_motion", mode="budget")
    monkeypatch.setitem(cheapest.capabilities, "start_frame", False)       # the budget choice cannot start from a picture; others can
    p, ids = two_clips(svc)
    p.root.children[0].quality_mode = "budget"
    svc.save(p)
    q = svc.load(p.id)
    plan = E.plan_clip(q, leaves(q)[1], svc.reg)
    assert not plan.blocked and plan.video.capabilities.get("start_frame") and plan.video.id != cheapest.id
    assert any(plan.video.id in w and "start from the last picture" in w for w in plan.warnings)       # and the screen says so


def test_a_model_you_pinned_that_cannot_start_from_a_picture_blocks_the_clip(svc, monkeypatch):
    keys(svc, monkeypatch)
    pinned = svc.reg.choose("video", "human_motion", mode="budget")
    monkeypatch.setitem(pinned.capabilities, "start_frame", False)
    p, ids = two_clips(svc)
    q = svc.load(p.id)
    leaves(q)[1].provider_override = pinned.id
    svc.save(q)
    plan = E.plan_clip(svc.load(p.id), leaves(svc.load(p.id))[1], svc.reg)
    assert plan.blocked and pinned.id in plan.blocked


def test_a_placeholder_before_it_means_waiting_for_a_real_clip_not_a_fresh_start(svc, monkeypatch):
    keys(svc, monkeypatch)
    p, ids = two_clips(svc)
    q = svc.load(p.id)
    leaves(q)[0].provider_override = "free_preview"                        # the first clip will only be a placeholder card
    svc.save(q)
    q = svc.load(p.id)
    second = leaves(q)[1]
    assert second.blocked and "free placeholder" in second.blocked and "1.1" in second.blocked
    q = svc.update_node(p.id, ids[0], {"provider_override": ""})            # use the best model again
    assert not leaves(q)[1].blocked


def test_a_talking_picture_clip_never_starts_fresh_after_a_placeholder(svc, monkeypatch):
    from .test_scenarios import actor
    keys(svc, monkeypatch)
    meera = actor("Meera", voice_gender="female", voice_accent="Indian English")
    p, ids = build(svc, "Meera", [meera], [clip("landscape", "a hall at dusk", end="Meera at the door", seconds=4),
                                          clip("talking_head", "Meera speaks", say=[("Meera", "Hello there")], actors=["Meera"], start="Meera at the door")])
    svc.set_join(p.id, ids[1], "continues")
    q = svc.load(p.id)
    plan = E.plan_clip(q, leaves(q)[1], svc.reg)
    assert plan.route == "avatar" and not plan.blocked                       # the first clip will be real footage: its last picture can be the speaker
    leaves(q)[0].provider_override = "free_preview"
    svc.save(q)
    q = svc.load(p.id)
    plan = E.plan_clip(q, leaves(q)[1], svc.reg)
    assert plan.route == "avatar" and "free placeholder" in plan.blocked and leaves(q)[1].blocked == plan.blocked


# ------------------------------------------------------------------ measured: the first picture against the last picture
@requires_ffmpeg
def test_picture_difference_is_zero_for_the_same_and_high_for_a_different_picture(tmp_path):
    a, b, c = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png"
    Image.new("RGB", (640, 360), (200, 60, 60)).save(a)
    Image.new("RGB", (640, 360), (202, 58, 61)).save(b)               # the same picture, a little noise
    Image.new("RGB", (640, 360), (10, 10, 10)).save(c)
    assert media.frame_difference(a, a) == 0 and media.frame_difference(a, b) < policy_mod.current().join_max_difference
    assert media.frame_difference(a, c) > 0.3 > media.frame_difference(a, b)
    clip_path = tmp_path / "v.mp4"
    media.ff("-loop", "1", "-i", str(a), "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip_path))
    assert media.frame_difference(clip_path, a, a_last=True) < 0.05 and media.frame_difference(clip_path, c, a_last=True) > 0.3


def test_the_difference_limit_is_a_named_setting_with_help():
    names = {n: (v, why) for n, v, why in policy_mod.describe()}
    assert names["join_max_difference"][0] == 0.15 and "first picture" in names["join_max_difference"][1]


@requires_ffmpeg
def test_a_continuing_clip_really_starts_where_the_last_one_ended_and_is_measured(svc, monkeypatch):
    keys(svc, monkeypatch)
    p, ids = two_clips(svc)
    run_all(svc, p.id)
    q = svc.load(p.id)
    first, second = leaves(q)
    assert all(l.status == NodeStatus.done for l in (first, second))
    assert second.continuity.difference is not None and second.continuity.difference <= policy_mod.current().join_max_difference
    assert not any("does not start where" in w for w in second.warnings)


@requires_ffmpeg
def test_a_clip_that_does_not_start_where_the_last_ended_is_flagged_and_the_limit_is_live(svc, monkeypatch, tmp_path):
    keys(svc, monkeypatch)
    p, ids = two_clips(svc)
    eng = run_all(svc, p.id)
    q = svc.load(p.id)
    second = leaves(q)[1]
    other = ProjectStore.path_for(p.id) / second.output
    media.ff("-f", "lavfi", "-i", "color=c=black:s=640x360:r=24", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(other))   # a different picture
    asyncio.run(eng._check_joins(p.id, ids[1]))
    q = svc.load(p.id)
    svc.refresh(q)
    second = leaves(q)[1]
    assert second.continuity.difference > policy_mod.current().join_max_difference
    miss = [w for w in second.warnings if "does not start where clip 1.1 ended" in w]
    assert miss and "Re-make it from the hand-over picture" in miss[0] and "change this join to a cut" in miss[0]
    monkeypatch.setattr(policy_mod.current(), "join_max_difference", 0.99)         # the limit is read live
    svc.refresh(q)
    assert not any("does not start where" in w for w in leaves(q)[1].warnings)


@requires_ffmpeg
def test_making_the_earlier_clip_again_measures_the_pair_again(svc, monkeypatch):
    keys(svc, monkeypatch)
    p, ids = two_clips(svc)
    eng = run_all(svc, p.id)
    q = svc.load(p.id)
    first = leaves(q)[0]
    first_file = ProjectStore.path_for(p.id) / first.output
    media.ff("-f", "lavfi", "-i", "color=c=white:s=640x360:r=24", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(first_file))   # clip 1 changed
    asyncio.run(eng._check_joins(p.id, ids[0]))                                      # runs when EITHER clip finishes
    assert svc.load(p.id).root.children[0].children[1].continuity.difference > policy_mod.current().join_max_difference


@requires_ffmpeg
def test_a_placeholder_is_never_compared(svc, monkeypatch):
    p, ids = two_clips(svc)                                                          # no keys: both clips are free previews
    eng = run_all(svc, p.id)
    assert leaves(svc.load(p.id))[1].continuity.difference is None                   # a placeholder card has no real picture to compare


def test_making_a_part_alone_includes_the_clip_it_continues_from_when_that_is_not_made(svc, monkeypatch):
    keys(svc, monkeypatch)
    p, ids = two_clips(svc)
    info = svc.estimate_targets(p.id, [ids[1]])
    assert info["extra_upstream"] == [ids[0]] and info["clips"] == [ids[0], ids[1]]           # the earlier clip comes first, and is counted in the cost
    assert not any("last picture of clip" in r for r in info["reuses"])                         # it is made in this very run, so nothing is reused from it yet


def test_the_command_line_can_set_and_list_joins(svc, monkeypatch):
    from typer.testing import CliRunner
    from video_generator import cli
    monkeypatch.setattr(cli, "_svc", lambda: svc)
    p, ids = two_clips(svc, join="cut")
    runner = CliRunner()
    out = runner.invoke(cli.app, ["join", "1.2", "continues", "-p", p.id])
    assert out.exit_code == 0 and "continues" in out.output
    assert svc.load(p.id).root.children[0].children[1].continuity.join == "continues"
    bad = runner.invoke(cli.app, ["join", "1.2", "dissolve", "-p", p.id])
    assert bad.exit_code != 0
    listing = runner.invoke(cli.app, ["continuity", "-p", p.id])
    assert listing.exit_code == 0


# ------------------------------------------------------------------ the screen can change a join
def test_the_api_changes_a_join(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p, ids = two_clips(svc, join="cut")
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/nodes/{ids[1]}/join", json={"join": "continues", "reason": "same shot"}).json()
        second = r["project"]["root"]["children"][0]["children"][1]
        assert second["continuity"]["join"] == "continues" and second["continuity"]["join_reason"] == "same shot"
        assert client.post(f"/api/projects/{p.id}/nodes/{ids[1]}/join", json={"join": "dissolve"}).status_code == 400
