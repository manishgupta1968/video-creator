"""The Review Agent judges VIDEO quality, not only the goal: measured numbers + rules AI cannot override."""
import asyncio

import pytest

from video_generator import media
from video_generator.brain import IssueDraft, ReviewDraft, Scores
from video_generator.models import NodeStatus
from video_generator.reviewer import apply_quality_rules
from video_generator.tree import leaves

from .conftest import requires_ffmpeg


def good_draft(**scores):
    base = dict(goal=5, script=5, actors=5, behaviour=5, realism=5, motion=5, consistency=5, fidelity=5, audio=5,
                continuity=5, timing=5, lipsync=5)
    base.update(scores)
    return ReviewDraft(verdict="meets_goal", scores=Scores(**base), issues=[], suggestions=[], summary="looks great")


GOOD = {"motion": 2.1, "static_ratio": 0.0, "sharpness_vs_start": 0.95, "has_audio": 1, "lufs": -18.0, "peak_db": -4.0, "silence_ratio": 0.1}


# ------------------------------------------------------------------ measurements
@requires_ffmpeg
def test_motion_and_sharpness_measurements_tell_clips_apart(tmp_path):
    moving, still, zoom, blurry = (tmp_path / n for n in ("moving.mp4", "still.mp4", "zoom.mp4", "blurry.mp4"))
    media.ff("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(moving))
    card = media.placeholder_image("A lion", tmp_path / "card.png", (1280, 720))
    media.still_to_clip(card, still, 3, (1280, 720), 24, zoom=False)
    media.still_to_clip(card, zoom, 3, (1280, 720), 24, zoom=True)
    media.ff("-i", str(moving), "-vf", "gblur=sigma=8", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(blurry))
    assert media.motion_stats(moving)["motion"] > 1.5
    assert media.motion_stats(still)["static_ratio"] > 0.9 and media.motion_stats(still)["motion"] < 0.05
    assert 0.1 < media.motion_stats(zoom)["motion"] < 1.0                    # a slow zoom is not real movement
    assert media.sharpness_ratio(blurry, None, tmp_path / "s1")["sharpness"] < media.sharpness_ratio(moving, None, tmp_path / "s2")["sharpness"] * 0.5
    assert media.sharpness_ratio(zoom, card, tmp_path / "s3")["sharpness_vs_start"] > 0.8


@requires_ffmpeg
def test_audio_and_pair_sampling(tmp_path):
    quiet = tmp_path / "q.wav"
    media.ff("-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-af", "volume=0.02", str(quiet))
    stats = media.audio_stats(quiet)
    assert stats["has_audio"] == 1 and stats["lufs"] < -35
    vid = tmp_path / "v.mp4"
    media.ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid))
    assert media.audio_stats(vid) == {"has_audio": 0}
    pairs = media.sample_pairs(vid, tmp_path / "pairs")
    assert len(pairs) == 6 and abs(pairs[1][0] - pairs[0][0] - 0.25) < 0.01


# ------------------------------------------------------------------ rules the AI cannot override
def test_clean_clip_can_pass():
    d = apply_quality_rules(good_draft(), GOOD, placeholder=False, speech_expected=True)
    assert d.verdict == "meets_goal" and not d.issues


def test_placeholder_never_passes_as_real_animation():
    d = apply_quality_rules(good_draft(), GOOD, placeholder=True, speech_expected=True)    # the AI said "great"
    assert d.verdict == "does_not_meet_goal"
    assert d.scores.realism == 1 and d.scores.motion == 1 and d.scores.fidelity == 1
    assert "not real animation" in d.issues[0].text and "Connect a video model" in d.suggestions[0]


def test_still_image_fails_motion_with_the_number_quoted():
    d = apply_quality_rules(good_draft(), {**GOOD, "motion": 0.04, "static_ratio": 0.95}, False, True)
    assert d.scores.motion == 1 and d.verdict == "does_not_meet_goal"
    assert any("0.04" in i.text and i.check == "motion" for i in d.issues)
    assert any("movement" in s for s in d.suggestions)


def test_low_movement_is_a_warning_not_a_failure():
    d = apply_quality_rules(good_draft(), {**GOOD, "motion": 0.55}, False, True)
    assert d.scores.motion == 3 and d.verdict == "minor_issues"


def test_blur_quiet_and_clipping_are_caught():
    d = apply_quality_rules(good_draft(), {**GOOD, "sharpness_vs_start": 0.3, "lufs": -48, "peak_db": -0.2}, False, True)
    assert d.scores.fidelity == 2 and d.scores.audio == 2
    assert {i.check for i in d.issues} == {"fidelity", "audio"}


def test_no_audio_when_speech_expected():
    d = apply_quality_rules(good_draft(), {**GOOD, "has_audio": 0}, False, True)
    assert d.scores.audio == 1
    d2 = apply_quality_rules(good_draft(), {**GOOD, "has_audio": 0}, False, False)          # no speech expected: fine
    assert d2.scores.audio == 5


def test_not_checked_stays_zero_but_a_measured_failure_still_counts():
    d = apply_quality_rules(good_draft(motion=0, fidelity=0, audio=0), GOOD, False, True)
    assert d.scores.motion == 0 and d.verdict == "meets_goal"                                # unknown is not a failure
    d = apply_quality_rules(good_draft(motion=0), {**GOOD, "motion": 0.02, "static_ratio": 1.0}, False, True)
    assert d.scores.motion == 1 and d.verdict == "does_not_meet_goal"


def test_ai_verdict_can_only_get_worse_never_better():
    draft = good_draft()
    draft.verdict = "does_not_meet_goal"
    assert apply_quality_rules(draft, GOOD, False, True).verdict == "does_not_meet_goal"


# ------------------------------------------------------------------ end to end with the free preview
@requires_ffmpeg
def test_review_of_a_free_preview_take_is_honest_and_best_take_ignores_unchecked(svc):
    from video_generator.runner import Engine
    p = svc.new_project("A presenter explains our bag", seconds=8, quality_mode="free")
    p = asyncio.run(svc.draft(p.id))
    clip = leaves(p)[0]
    eng = Engine(svc, stop_when_waiting=True)

    async def go():
        await eng.start(p.id, "clip", [clip.id])
        await eng.runs[p.id].task
    asyncio.run(go())
    p = svc.load(p.id)
    n = next(l for l in leaves(p) if l.id == clip.id)
    review = next(r for r in p.reviews if r.id == n.takes[0].review_id)
    assert review.verdict == "does_not_meet_goal"
    assert review.scores["realism"] == 1 and review.scores["motion"] == 1
    assert any("not real animation" in i.text for i in review.issues)
    assert {"motion", "static_ratio", "sharpness", "has_audio"} <= set(review.measurements)
    # the "not checked" zeros are ignored when comparing takes
    best = eng._best_take(p, n, n.version)
    assert best.id in {t.id for t in n.takes}
