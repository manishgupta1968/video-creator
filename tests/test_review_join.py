"""Drop 4, part 1 (v3.12): the Review Agent judges the stitch between a clip and the clip before it.
It is shown the last picture of the clip before and the first picture of this take, the plan's join kind, and a measured difference;
a continuing shot that does not start where the one before ended is capped by a rule no AI opinion can overrule."""
import asyncio

import pytest

from video_generator import media
from video_generator import policy as policy_mod
from video_generator.brain import IssueDraft, ReviewDraft, Scores, join_block
from video_generator.models import Review, ReviewJoin
from video_generator.project import ProjectStore
from video_generator.reviewer import Reviewer, apply_quality_rules
from video_generator.runner import Engine
from video_generator.tree import leaves, numbering

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors
from .test_scenarios import build, clip, run_all


def draft(**scores):
    return ReviewDraft(verdict="meets_goal", scores=Scores(**{"goal": 5, "script": 5, "actors": 5, "behaviour": 5, "realism": 5, "motion": 5, "consistency": 5,
                                                              "fidelity": 5, "audio": 5, "continuity": 5, "timing": 5, "lipsync": 5, "join": 5, **scores}))


def judged(kind="continues", difference=0.4, limit=0.15, previous="1.1"):
    return ReviewJoin(judged=True, previous=previous, kind=kind, difference=difference, limit=limit)


GOOD = {"motion": 2.0, "static_ratio": 0.1, "sharpness_vs_start": 1.0, "has_audio": 1, "lufs": -20, "peak_db": -6, "silence_ratio": 0.1}


# ------------------------------------------------------------------ the rule no AI opinion can overrule
def test_a_continuing_shot_that_does_not_start_where_the_last_ended_is_capped_whatever_the_ai_says():
    out = apply_quality_rules(draft(), GOOD, False, False, join=judged("continues", difference=0.4))
    assert out.scores.join == 2 and out.verdict == "does_not_meet_goal"
    bad = [i for i in out.issues if i.check == "join"]
    assert bad and bad[0].severity == "major" and "0.40" in bad[0].text and "clip 1.1" in bad[0].text
    assert any("hand-over picture" in s for s in out.suggestions)


def test_a_continuing_shot_within_the_limit_keeps_the_ai_score():
    out = apply_quality_rules(draft(), GOOD, False, False, join=judged("continues", difference=0.05))
    assert out.scores.join == 5 and out.verdict == "meets_goal" and not [i for i in out.issues if i.check == "join"]


def test_a_new_angle_or_a_cut_has_no_hard_picture_rule_they_are_left_to_the_ai():
    for kind in ("same_scene", "cut"):
        out = apply_quality_rules(draft(join=4), GOOD, False, False, join=judged(kind, difference=0.9))
        assert out.scores.join == 4 and not [i for i in out.issues if i.check == "join"]


def test_without_evidence_the_ai_may_not_invent_a_stitch_score():
    for j in (None, ReviewJoin(judged=False, why_not="this is the first clip")):
        assert apply_quality_rules(draft(join=5), GOOD, False, False, join=j).scores.join == 0
    old = apply_quality_rules(draft(join=5), GOOD, False, False)                           # a caller that knows nothing about joins (older code)
    assert old.scores.join == 0


def test_the_words_the_reviewer_reads_follow_the_kind_of_join():
    text = join_block("1.1", "continues", "the same shot goes on", "crossfade", 0.31, 0.15, "she is at the door", "she opens the door")
    assert "CONTINUES the same shot" in text and "0.31" in text and "limit for a continuing shot is 0.15" in text
    assert "she is at the door" in text and "should not dissolve or fade" in text and "LAST TWO attached images" in text
    cut = join_block("1.2", "cut", "a new place", "cut", 0.8, 0.15, "", "")
    assert "deliberate CUT" in cut and "ACCIDENT" in cut and "limit for a continuing shot" not in cut
    assert "SAME SCENE" in join_block("1.2", "same_scene", "", "cut", None, 0.15, "", "")


def test_the_new_score_is_named_and_a_weak_stitch_makes_the_verdict_worse_not_better():
    out = apply_quality_rules(draft(join=2), GOOD, False, False, join=judged("same_scene", difference=0.5))
    assert out.verdict == "does_not_meet_goal"                                                 # join 2 or less: does not meet the goal
    assert apply_quality_rules(draft(join=3), GOOD, False, False, join=judged("same_scene")).verdict == "minor_issues"


# ------------------------------------------------------------------ evidence from real clips
def two_clips(svc, join="continues", **settings):
    p, ids = build(svc, "Two shots", [], [clip("landscape", "A road", sound="wind", end="a straight road at noon"),
                                         clip("landscape", "The same road", sound="wind", start="a straight road at noon")],
                   review_enabled=True, **settings)
    if join != "cut":
        svc.set_join(p.id, ids[1], join)
    return svc.load(p.id), ids


@requires_ffmpeg
def test_the_reviewer_is_shown_the_two_pictures_and_the_measured_difference(svc, monkeypatch, tmp_path):
    Vendors(svc, monkeypatch)
    p, ids = two_clips(svc)
    run_all(svc, p.id)
    p = svc.load(p.id)
    second = leaves(p)[1]
    base = ProjectStore.path_for(p.id)
    take = next(t for t in second.takes if t.id == second.chosen_take)
    work = base / "clips" / second.id / "review" / take.id
    info, text, images = Reviewer(svc)._join_evidence(p, second, take, base, work, base / take.video, [], False)
    assert info.judged and info.previous == "1.1" and info.kind == "continues" and info.difference is not None and info.difference <= policy_mod.current().join_max_difference
    assert len(images) == 2 and all(x.exists() for x in images) and info.previous_frame and info.this_frame
    assert (base / info.previous_frame).exists() and (base / info.this_frame).exists()          # kept inside the project so the screen can show them
    assert "clip 1.1" in text and "CONTINUES the same shot" in text


@requires_ffmpeg
def test_the_first_clip_a_missing_clip_and_a_placeholder_before_are_not_judged_with_a_plain_reason(svc, monkeypatch, tmp_path):
    p, ids = two_clips(svc)                                                                     # no keys: every clip is a free placeholder
    run_all(svc, p.id)
    p = svc.load(p.id)
    first, second = leaves(p)
    base = ProjectStore.path_for(p.id)
    rv = Reviewer(svc)
    t1 = next(t for t in first.takes if t.id == first.chosen_take)
    info, text, images = rv._join_evidence(p, first, t1, base, tmp_path / "a", base / t1.video, [], False)
    assert not info.judged and "first clip" in info.why_not and not images and text == ""
    t2 = next(t for t in second.takes if t.id == second.chosen_take)
    info, text, images = rv._join_evidence(p, second, t2, base, tmp_path / "b", base / t2.video, [], False)
    assert not info.judged and "placeholder" in info.why_not and info.previous == "1.1" and not images
    first.output = None
    info, _t, _i = rv._join_evidence(p, second, t2, base, tmp_path / "c", base / t2.video, [], False)
    assert not info.judged and "not made yet" in info.why_not


@requires_ffmpeg
def test_a_take_review_sends_the_two_join_pictures_last_and_stays_within_eighteen_pictures(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p, ids = two_clips(svc)
    run_all(svc, p.id)
    seen = {}

    async def spy(task, prompt, schema, meta, images=None, video=None):
        seen.update(task=task, prompt=prompt, meta=meta, images=list(images or []))
        return draft(join=4)
    monkeypatch.setattr(svc.brain, "ask", spy)
    q = svc.load(p.id)
    second = leaves(q)[1]
    asyncio.run(Reviewer(svc).review_take(p.id, second.id, second.chosen_take))
    assert seen["task"] == "review" and len(seen["images"]) <= 18
    assert [x.name for x in seen["images"][-2:]] == ["join_prev_last.jpg", "join_this_first.jpg"]          # the evidence comes last, so a cap would never cut it
    assert "HOW THIS CLIP IS STITCHED" in seen["prompt"] and "Clip 1.1 is the clip before this one" in seen["prompt"]
    assert seen["meta"]["keep_images"] == 2 and seen["meta"]["join"]["kind"] == "continues" and seen["meta"]["join"]["judged"]
    r = next(x for x in svc.load(p.id).reviews if x.target == second.chosen_take)
    assert r.join and r.join.judged and r.scores["join"] in (4, 2) and "join_difference" in r.measurements


@requires_ffmpeg
def test_the_offline_reviewer_scores_the_stitch_from_the_measured_difference(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    monkeypatch.setattr(svc.reg, "llm_fallback_order", lambda task: ["fake_llm"])
    p, ids = two_clips(svc)
    run_all(svc, p.id)
    q = svc.load(p.id)
    first, second = leaves(q)
    r2 = asyncio.run(Reviewer(svc).review_take(p.id, second.id, second.chosen_take))
    assert r2.join.judged and r2.scores["join"] == 4 and r2.verdict in ("meets_goal", "minor_issues")
    r1 = asyncio.run(Reviewer(svc).review_take(p.id, first.id, first.chosen_take))
    assert not r1.join.judged and r1.scores["join"] == 0
    # the clip before is made again as something else: this clip no longer starts where it ended
    base = ProjectStore.path_for(p.id)
    media.ff("-f", "lavfi", "-i", "color=c=black:s=640x360:r=24", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base / first.output))
    r3 = asyncio.run(Reviewer(svc).review_take(p.id, second.id, second.chosen_take))
    assert r3.scores["join"] == 2 and r3.verdict == "does_not_meet_goal" and any(i.check == "join" and i.frame for i in r3.issues)


def test_the_take_with_the_better_stitch_is_the_one_picked(svc):
    from video_generator.models import Take
    p = svc.new_project("Pick")
    from video_generator.models import Node, NodeKind
    from video_generator.tree import add_child
    c = add_child(p, p.root.id, Node(kind=NodeKind.clip, title="C", goal="g"))
    a, b = Take(version=1, index=1, video="a.mp4"), Take(version=1, index=2, video="b.mp4")
    base = {"goal": 4, "script": 4, "realism": 4, "motion": 4}
    a.review_id, b.review_id = "ra", "rb"
    p.reviews = [Review(id="ra", target=a.id, scores={**base, "join": 2}), Review(id="rb", target=b.id, scores={**base, "join": 5})]
    c.takes, c.version = [a, b], 1
    assert Engine(svc)._best_take(p, c, 1).id == b.id


# ------------------------------------------------------------------ the part and whole-video review
def test_seam_times_follow_the_same_arithmetic_as_the_join():
    assert media.seam_times([4.0, 3.0, 5.0], ["", "cut", "cut"]) == [(4.0, 0.0), (7.0, 0.0)]
    t = media.seam_times([4.0, 3.0, 5.0], ["", "crossfade", "cut"], tdur=0.5)
    assert t[0] == (pytest.approx(3.75), 0.5) and t[1][1] == 0.0 and t[1][0] == pytest.approx(3.5 + 3.0 - media.cut_fade(24) + media.cut_fade(24) / 2, abs=0.01)


def coloured_clips(tmp_path, n=4):
    from PIL import Image
    colours = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))[:n]
    paths = []
    for i, colour in enumerate(colours):
        img = tmp_path / f"c{i}.png"
        Image.new("RGB", (320, 180), colour).save(img)
        out = tmp_path / f"c{i}.mp4"
        media.ff("-loop", "1", "-i", str(img), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "2", "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", str(out))
        paths.append(out)
    return paths, colours


@requires_ffmpeg
def test_a_cut_and_a_crossfade_in_one_video_never_lose_a_clip(tmp_path):
    """A hard cut inside a chain with other transitions used a fade shorter than one picture, and ffmpeg dropped the clip after it."""
    paths, _ = coloured_clips(tmp_path)
    for trans in (["", "cut", "crossfade", "cut"], ["", "crossfade", "cut", "crossfade"], ["", "crossfade", "cut", "cut"]):
        joined = tmp_path / "j.mp4"
        media.join_clips(paths, trans, joined, (320, 180), 24)
        expected = 8.0 - 0.5 * sum(1 for t in trans[1:] if t != "cut") - media.cut_fade(24) * sum(1 for t in trans[1:] if t == "cut")
        assert media.probe_duration(joined) == pytest.approx(expected, abs=0.15), trans
    assert media.cut_fade(24) >= 1 / 24 and media.cut_fade(60) >= 1 / 60 and media.cut_fade(12) >= 1 / 12


@requires_ffmpeg
def test_the_seam_times_match_a_real_join(tmp_path):
    from PIL import Image
    paths, colours = coloured_clips(tmp_path)
    for trans in (["", "cut", "cut", "cut"], ["", "crossfade", "crossfade", "crossfade"], ["", "crossfade", "cut", "crossfade"]):
        joined = tmp_path / "j.mp4"
        media.join_clips(paths, trans, joined, (320, 180), 24)
        seams = media.seam_times([media.probe_duration(x) for x in paths], trans)
        for (t, d), expect_after in zip(seams, colours[1:]):
            shot = tmp_path / "s.png"
            media.extract_frame(joined, shot, t + d / 2 + 0.2)
            px = Image.open(shot).convert("RGB").getpixel((160, 90))
            assert all(abs(px[k] - expect_after[k]) < 60 for k in range(3)), (trans, t, px, expect_after)            # the clip after the seam is what shows there
            media.extract_frame(joined, shot, max(t - d / 2 - 0.2, 0.0))
            before = Image.open(shot).convert("RGB").getpixel((160, 90))
            assert before != px


@requires_ffmpeg
def test_the_part_review_shows_every_seam_cuts_included_from_the_stitched_video(svc, monkeypatch, tmp_path):
    Vendors(svc, monkeypatch)
    p, ids = build(svc, "Three shots", [], [clip("landscape", "A road", sound="wind", end="a road"), clip("landscape", "The same road", sound="wind", start="a road"),
                                           clip("landscape", "A new city", sound="traffic")], links=[(0, 1, "continues_from")])
    run_all(svc, p.id)
    p = svc.load(p.id)
    base = ProjectStore.path_for(p.id)
    stitched = tmp_path / "stitched.mp4"
    outs = [base / c.output for c in leaves(p)]
    media.join_clips(outs, ["", "cut", "cut"], stitched, (640, 360), 24)
    text, images = Reviewer(svc)._boundaries(p, p.root, numbering(p), tmp_path / "rv", stitched=stitched)
    lines = text.splitlines()
    assert lines[0].startswith("clip 1.2 continues the same shot") and "just BEFORE and just AFTER the seam" in lines[0] and " s of the video" in lines[0]
    assert lines[1].startswith("clip 1.3 is a deliberate cut") and len(images) == 4 and all(x.exists() for x in images)
    plain, pics = Reviewer(svc)._boundaries(p, p.root, numbering(p), tmp_path / "rv2")                       # no stitched video: the single clip files are used
    assert "LAST frame of clip 1.1" in plain.splitlines()[0] and len(pics) == 4


@requires_ffmpeg
def test_a_long_video_keeps_the_most_demanding_seams_and_never_passes_eighteen_pictures(svc, monkeypatch, tmp_path):
    Vendors(svc, monkeypatch)
    n = 9
    p, ids = build(svc, "Many", [], [clip("landscape", f"Shot {i}", sound="wind", seconds=2) for i in range(n)], links=[(7, 8, "continues_from")])
    run_all(svc, p.id)
    p = svc.load(p.id)
    text, images = Reviewer(svc)._boundaries(p, p.root, numbering(p), tmp_path / "rv")
    assert len(images) == 2 * Reviewer.MAX_SEAMS and "more seams are not shown" in text
    assert f"clip 1.{n} continues the same shot" in text                                              # the continuing shot is kept although it is the last seam


@requires_ffmpeg
def test_a_picture_past_the_end_of_a_video_is_never_handed_back_as_a_missing_file(tmp_path):
    clip_path = tmp_path / "v.mp4"
    media.ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=24", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip_path))
    out = tmp_path / "f.jpg"
    assert media.extract_frame(clip_path, out, at=1.0).exists()
    near_end = media.extract_frame(clip_path, tmp_path / "e.jpg", at=media.probe_duration(clip_path) + 0.05)         # a little past the last picture
    assert near_end.exists() and near_end.stat().st_size > 0
    with pytest.raises(media.MediaError, match="no picture could be read"):
        media.extract_frame(clip_path, tmp_path / "x.jpg", at=60.0)


# ------------------------------------------------------------------ the extras: Gemini and the Continuity list
def test_gemini_still_gets_the_join_pictures_when_it_is_sent_the_video_itself(tmp_path):
    from video_generator.plugins.llm.gemini_llm import media_parts
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    pics = []
    for name in ("f1", "f2", "join_prev_last", "join_this_first"):
        f = tmp_path / f"{name}.jpg"
        f.write_bytes(b"jpg")
        pics.append(f)
    with_video = media_parts(video, pics, keep_images=2)
    assert len(with_video) == 3 and "video/mp4" in with_video[0]["inline_data"]["mime_type"]      # the video, then ONLY the evidence that is not in it
    assert len(media_parts(video, pics, keep_images=0)) == 1                                       # nothing extra when there is none
    assert len(media_parts(None, pics, keep_images=2)) == 4                                        # no video: every picture
    assert len(media_parts(video, pics)) == 1


def stitched_project(svc, score, kind="continues", with_measured=False):
    from video_generator.models import Take
    p, ids = build(svc, "Two", [], [clip("landscape", "A road", end="a road"), clip("landscape", "The same road", start="a road")])
    if kind != "cut":
        svc.set_join(p.id, ids[1], kind)
    p = svc.load(p.id)
    a, b = leaves(p)
    t = Take(version=1, index=1, video="b.mp4", model="kling_3")
    t.review_id = "rv_join"
    b.takes, b.chosen_take, b.status, b.output = [t], t.id, __import__("video_generator.models", fromlist=["NodeStatus"]).NodeStatus.done, "b.mp4"
    p.reviews = [Review(id="rv_join", target=t.id, scores={"goal": 4, "join": score},
                        issues=[__import__("video_generator.models", fromlist=["ReviewIssue"]).ReviewIssue(check="join", text="She is at the door in one picture and at the window in the next.", severity="major")],
                        join=ReviewJoin(judged=True, previous="1.1", kind=kind, difference=0.5 if with_measured else None, limit=0.15))]
    if with_measured:
        b.continuity.difference = 0.5
    return p, b


def test_a_weak_stitch_the_reviewer_found_is_listed_under_continuity_with_fixes(svc):
    from video_generator import continuity as C
    p, b = stitched_project(svc, score=2)
    found = [f for f in C.check(p, svc.reg) if f["code"] == "join_review"]
    assert len(found) == 1 and found[0]["severity"] == "problem" and found[0]["number"] == "1.2"
    assert "does not stitch well to clip 1.1" in found[0]["text"] and "window" in found[0]["text"]
    assert [f["action"] for f in found[0]["fixes"]] == ["remake", "set_join"] and found[0]["fixes"][1]["join"] == "cut"
    note = [f for f in C.check(stitched_project(svc, score=3)[0], svc.reg) if f["code"] == "join_review"]
    assert note and note[0]["severity"] == "note"
    assert not [f for f in C.check(stitched_project(svc, score=4)[0], svc.reg) if f["code"] == "join_review"]
    assert not [f for f in C.check(stitched_project(svc, score=0)[0], svc.reg) if f["code"] == "join_review"]           # 0 = not judged


def test_a_cut_that_looks_accidental_can_only_be_re_made_and_a_clip_waiting_to_be_made_again_is_not_judged(svc):
    from video_generator import continuity as C
    from video_generator.models import NodeStatus
    p, b = stitched_project(svc, score=2, kind="cut")
    f = [x for x in C.check(p, svc.reg) if x["code"] == "join_review"]
    assert f and [x["action"] for x in f[0]["fixes"]] == ["remake"]
    b.status = NodeStatus.stale
    assert not [x for x in C.check(p, svc.reg) if x["code"] == "join_review"]                       # the review is out of date: the clip must be made again first


def test_the_measured_difference_and_the_reviewers_opinion_are_not_listed_twice(svc):
    from video_generator import continuity as C
    p, b = stitched_project(svc, score=2, with_measured=True)
    codes = [f["code"] for f in C.check(p, svc.reg) if f["node"] == b.id]
    assert "join_measured" in codes and "join_review" not in codes


def test_the_review_with_its_stitch_travels_to_the_screen(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p, b = stitched_project(svc, score=2)
    svc.save(p)
    with TestClient(appmod.app) as client:
        v = client.get(f"/api/projects/{p.id}").json()
        r = next(x for x in v["project"]["reviews"] if x["id"] == "rv_join")
        assert r["join"]["judged"] and r["join"]["previous"] == "1.1" and r["scores"]["join"] == 2
        assert any(f["code"] == "join_review" for f in v["summary"]["continuity"])
