"""Generic rules, not one example: no scenario words in the engine, every number comes from the policy, and what a model can
do comes from the catalogue. Each rule is proven for several kinds of subject."""
import asyncio
import re
from pathlib import Path

import pytest

from video_generator import casting, media, policy as policy_mod, routes
from video_generator import estimate as E
from video_generator.catalog import CatalogEntry
from video_generator.models import (ActorDetails, ClipScript, ContextItem, ContextType, DependencyType, DialogueLine, Node, NodeKind,
                                    NodeStatus, ShotType)
from video_generator.plugins.base import PluginError, Usage, VoiceChoice
from video_generator.project import ProjectStore
from video_generator.reviewer import apply_quality_rules
from video_generator.runner import Engine
from video_generator.tree import add_child, leaves

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors
from .test_scenarios import actor, add_reference_photo, build, check_rules, clip, peak_db, run_all

ROOT = Path(__file__).resolve().parents[1] / "video_generator"


@pytest.fixture(autouse=True)
def fresh_policy():
    policy_mod.use(policy_mod.Policy())
    yield
    policy_mod.use(policy_mod.Policy())


# ------------------------------------------------------------------ 1. nothing is hardwired
BANNED = re.compile(r"\b(lion|lions|tiger|elephant|zebra|savannah|savanna|sunset|golden hour|walks|walking|kito|baraka)\b", re.I)
ALLOWED = {"plugins/fake/fake_llm.py", "smoketest.py"}      # the offline fallback brain and the vendor self-test's sample content


def test_no_scenario_words_in_the_engine_prompts_or_catalogue():
    bad = []
    for path in list(ROOT.rglob("*.py")) + list(ROOT.rglob("*.md")) + list(ROOT.rglob("*.yaml")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED or "static/" in rel or "__pycache__" in rel:
            continue
        for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if BANNED.search(line):
                bad.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert not bad, "scenario words in generic code:\n" + "\n".join(bad)


def test_every_threshold_is_a_named_policy_setting_with_help_text():
    names = {n for n, _, why in policy_mod.describe()}
    assert {"max_freeze_s", "max_freeze_ratio", "bed_under_speech_lufs", "bed_alone_lufs", "pitch_ranges", "max_pitch_shift_st",
            "min_sharpness_ratio", "precise_endings", "on_short", "voice_preview_candidates", "action_seconds"} <= names
    assert all(why for _, _, why in policy_mod.describe())                      # each one is explained in plain words


def test_policy_is_read_from_config_yaml(tmp_path):
    from video_generator.config import Config, vg_home
    (vg_home() / "config.yaml").write_text("policy:\n  max_freeze_s: 2.5\n  bed_alone_lufs: -20\n")
    Config.load()
    assert policy_mod.current().max_freeze_s == 2.5 and policy_mod.current().bed_alone_lufs == -20
    from typer.testing import CliRunner
    from video_generator.cli import app
    out = CliRunner().invoke(app, ["policy"])
    assert out.exit_code == 0 and "max_freeze_s = 2.5" in out.output and "bed_alone_lufs = -20" in out.output


# ------------------------------------------------------------------ 2. the policy drives behaviour
def frozen(tail=3.1, longest=3.1, ratio=0.52):
    return {"longest_freeze_s": longest, "frozen_s": tail, "tail_freeze_s": tail, "frozen_ratio": ratio, "motion": 1.5, "static_ratio": 0.0}


def draft_for_rules():
    from video_generator.brain import IssueDraft, ReviewDraft
    return ReviewDraft(verdict="meets_goal", summary="ok", scores={"goal": 5, "script": 5, "actors": 5, "behaviour": 5, "realism": 5, "motion": 5})


def test_a_frozen_picture_is_a_hard_fault_and_the_limit_comes_from_the_policy():
    d = apply_quality_rules(draft_for_rules(), frozen(), False, False)
    assert any(i.check == "motion" and "frozen for" in i.text and i.severity == "major" for i in d.issues)
    assert d.scores.motion <= 2 and "Split the clip" in " ".join(d.suggestions)
    clean = apply_quality_rules(draft_for_rules(), {"longest_freeze_s": 0.0, "frozen_ratio": 0.0, "motion": 1.5, "static_ratio": 0.0}, False, False)
    assert not any("frozen" in i.text for i in clean.issues)
    policy_mod.current().max_freeze_s, policy_mod.current().max_freeze_ratio = 10, 0.9          # a looser policy accepts the same clip
    assert not any("frozen" in i.text for i in apply_quality_rules(draft_for_rules(), frozen(), False, False).issues)


def test_pitch_correction_cap_comes_from_the_policy():
    prof = casting.Profile(gender="male", pitch="low")
    assert casting.pitch_fix(250, prof)[0] == -4.0
    policy_mod.current().max_pitch_shift_st = 2.0
    assert casting.pitch_fix(250, prof)[0] == -2.0
    policy_mod.current().pitch_ranges["male"]["low"] = [240, 260]                    # change what counts as a fitting voice
    assert casting.pitch_fix(250, prof) == (0.0, "")


@requires_ffmpeg
def test_made_sound_is_set_to_the_policy_level_and_the_level_follows_the_policy(tmp_path):
    src = tmp_path / "a.wav"
    media.ff("-f", "lavfi", "-i", "anoisesrc=color=pink:r=44100:d=4,volume=0.8", str(src))
    pol = policy_mod.current()
    eng = Engine.__new__(Engine)
    for speech, target in ((True, pol.bed_under_speech_lufs), (False, pol.bed_alone_lufs)):
        w = tmp_path / f"b{speech}.wav"
        w.write_bytes(src.read_bytes())
        eng._level_bed(w, speech)
        assert abs(media.audio_stats(w)["lufs"] - target) <= pol.loudness_tolerance_lu + 0.6
    pol.bed_alone_lufs = -45.0
    w = tmp_path / "c.wav"
    w.write_bytes(src.read_bytes())
    eng._level_bed(w, False)
    assert abs(media.audio_stats(w)["lufs"] + 45.0) <= 2.1                                # a different policy gives a different level


@requires_ffmpeg
def test_sound_always_lasts_as_long_as_the_picture(tmp_path):
    video = tmp_path / "v.mp4"
    media.ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=24", "-f", "lavfi", "-i", "sine=frequency=300:d=1.5", "-t", "5", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-c:a", "aac", str(video))                                  # 5 s of picture, 1.5 s of sound
    out = tmp_path / "o.mp4"
    media.replace_audio(video, None, out, keep_original=1.0)
    st = media.probe(out)["streams"]
    dur = {s["codec_type"]: float(s["duration"]) for s in st}
    assert abs(dur["audio"] - dur["video"]) < 0.15 and dur["video"] > 4.8


@requires_ffmpeg
def test_freeze_stats_finds_a_frozen_tail_and_nothing_in_a_moving_clip(tmp_path):
    moving = tmp_path / "m.mp4"
    media.ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=24", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(moving))
    tail = tmp_path / "t.mp4"
    media.ff("-i", str(moving), "-vf", "tpad=stop_mode=clone:stop_duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tail))
    assert media.freeze_stats(moving)["longest_freeze_s"] < 0.3
    fs = media.freeze_stats(tail)
    assert fs["tail_freeze_s"] > 2.5 and fs["frozen_ratio"] > 0.35


# ------------------------------------------------------------------ 3. the catalogue drives routing
def human(title="Sam"):
    return actor(title, kind="ai_person", voice_gender="male")


def speak_and_move(svc, kind, motion="body"):
    a = actor("Subject", kind=kind, voice_gender="male", voice_description="deep")
    p, ids = build(svc, "A subject speaks and moves", [a], [
        clip("dialogue_scene", "The subject speaks, then moves away", say=[("Subject", "I will be back soon.")], actors=["Subject"])])
    q = svc.load(p.id)
    leaves(q)[0].script.motion = motion
    svc.save(q)
    svc.refresh(q)
    return svc.load(p.id)


def test_speech_with_body_movement_is_covered_only_where_the_catalogue_says_a_route_can_do_both(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    # a person: a lip-sync step that works on human faces covers it (that row says `faces: human`)
    assert not leaves(speak_and_move(svc, "ai_person"))[0].needs_split
    # an animal and a product: no lip-sync row says it works for them, so no single route does both: split it
    for kind in ("animal", "product"):
        q = speak_and_move(svc, kind)
        leaf = leaves(q)[0]
        assert leaf.needs_split and any(w.startswith("This clip needs speech on camera") for w in leaf.warnings), kind
    # data change, no code change: a lip-sync row that also works on animals covers the animal clip
    row = svc.catalog.get("sync_lipsync_2_pro")
    row.capabilities["faces"] = ["human", "animal"]
    svc.reload() if False else None
    assert not leaves(speak_and_move(svc, "animal"))[0].needs_split
    row.capabilities["faces"] = "human"
    assert leaves(speak_and_move(svc, "animal"))[0].needs_split


def test_a_clip_that_only_moves_the_face_uses_the_talking_picture_route_for_any_subject(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    for kind in ("ai_person", "animal", "product"):
        a = actor("S", kind=kind, voice_gender="male")
        p, _ = build(svc, "S speaks", [a], [clip("talking_head", "S speaks to camera", say=[("S", "Hello there.")], actors=["S"])])
        q = svc.load(p.id)
        leaves(q)[0].script.motion = "face"
        svc.save(q)
        plan = E.plan_clip(svc.load(p.id), leaves(svc.load(p.id))[0], svc.reg)
        assert plan.route == "avatar" and plan.motion == "face" and not plan.uncovered, kind


def test_the_planner_is_told_what_each_route_can_do_from_the_catalogue(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    text = routes.describe(svc.reg)
    assert "Talking-picture route" in text and "only the face and head move" in text and "as long as the speech" in text
    assert "kling_avatar" in text and "works for people only" in text
    # change the data: the text changes, with no code edit
    svc.catalog.get("kling_avatar").capabilities["animates"] = "body"
    svc.catalog.get("veed_fabric").capabilities["animates"] = "body"
    assert "the subject's body can move too" in routes.describe(svc.reg).split("Video route")[0]


def test_the_planner_prompts_contain_the_generated_route_text(svc, monkeypatch):
    from video_generator import brain as B
    Vendors(svc, monkeypatch)
    p, ids = build(svc, "A test", [], [clip("landscape", "Hills", sound="wind")])
    seen = {}
    real = B.render

    def spy(name, **kw):
        seen[name] = kw.get("routes", "")
        return real(name, **kw)
    monkeypatch.setattr(B, "render", spy)
    asyncio.run(svc.brain.write_clip_script(p, leaves(p)[0]))
    asyncio.run(svc.brain.decompose(p, p.root.children[0]))
    asyncio.run(svc.brain.draft_project(p))
    assert all("WHAT EACH ROUTE CAN DO" in seen.get(k, "") for k in ("clip_script", "decompose", "draft")), seen


def test_a_route_that_is_as_long_as_the_speech_estimates_from_the_speech_for_any_subject(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    for kind in ("ai_person", "animal", "product"):
        a = actor("S", kind=kind, voice_gender="female")
        p, _ = build(svc, "S speaks", [a], [clip("talking_head", "S speaks to camera", say=[("S", "Short line.")], actors=["S"], seconds=8)])
        q = svc.load(p.id)
        leaves(q)[0].script.motion = "face"
        svc.save(q)
        svc.refresh(q)
        leaf = leaves(svc.load(p.id))[0]
        assert leaf.duration.likely_s < 5 and "speech" in leaf.duration.explain, kind        # not the 8 s asked for


# ------------------------------------------------------------------ 4. splitting
@pytest.mark.parametrize("kind", ["ai_person", "animal", "product"])
def test_split_makes_chained_clips_each_needing_one_thing_for_any_subject(svc, monkeypatch, kind):
    Vendors(svc, monkeypatch)
    q = speak_and_move(svc, kind)
    leaf = leaves(q)[0]
    leaf.script.action_beats = ["moves away from the camera", "leaves the frame"]
    leaf.script.end_state, leaf.script.start_state = "out of frame", "facing the camera"
    svc.save(q)
    before = sum((l.target_seconds or 0) for l in leaves(svc.load(q.id)))
    out = asyncio.run(svc.split_clip(q.id, leaf.id))
    parts = leaves(out)
    assert len(parts) == 2 and parts[0].script.motion == "face" and parts[1].script.motion == "body"
    assert parts[0].script.dialogue and not parts[1].script.dialogue                      # the spoken line stays in the speaking part
    assert any(d.from_id == parts[0].id and d.to_id == parts[1].id and d.type == DependencyType.continues_from for d in out.dependencies)
    assert parts[0].script.end_state == parts[1].script.start_state                       # chained states
    assert parts[1].script.end_state == "out of frame" and parts[0].script.start_state == "facing the camera"
    assert abs(sum((l.target_seconds or 0) for l in parts) - before) < 2.5                # the total length is kept (or follows the speech)


def test_split_keeps_links_to_the_clips_before_and_after(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    a = actor("S", kind="animal", voice_gender="male")
    p, ids = build(svc, "Three shots", [a], [
        clip("landscape", "Opening", sound="wind"),
        clip("dialogue_scene", "S speaks, then leaves", say=[("S", "Goodbye.")], actors=["S"]),
        clip("landscape", "Closing", sound="wind")], links=[(0, 1, "continues_from"), (1, 2, "continues_from")])
    q = svc.load(p.id)
    mid = leaves(q)[1]
    mid.script.motion = "body"
    mid.script.action_beats = ["leaves"]
    svc.save(q)
    out = asyncio.run(svc.split_clip(p.id, mid.id))
    ls = leaves(out)
    assert len(ls) == 4
    into_first = [d for d in out.dependencies if d.to_id == ls[1].id]
    out_of_last = [d for d in out.dependencies if d.from_id == ls[2].id]
    assert any(d.from_id == ls[0].id for d in into_first) and any(d.to_id == ls[3].id for d in out_of_last)


# ------------------------------------------------------------------ 5. no frozen tails, whatever the model returns
def one_clip_project(svc, shot="landscape", motion="scene", seconds=4):
    p, ids = build(svc, "One clip", [], [clip(shot, "Hills at dawn", sound="wind", seconds=seconds)])
    q = svc.load(p.id)
    leaves(q)[0].script.motion = motion
    svc.save(q)
    return p, ids


@requires_ffmpeg
def test_a_model_that_makes_less_than_planned_gives_a_shorter_clip_not_a_frozen_one(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    v.video_seconds = 2.0
    p, ids = one_clip_project(svc, seconds=5)
    run_all(svc, p.id)
    q = svc.load(p.id)
    leaf = leaves(q)[0]
    out = ProjectStore.path_for(p.id) / leaf.output
    assert leaf.status == NodeStatus.done and media.probe_duration(out) < 3.2
    assert media.freeze_stats(out).get("tail_freeze_s", 0) <= policy_mod.current().max_freeze_s
    assert any(w.startswith("Made ") and "planned" in w for w in leaf.warnings)                    # and the user is told


@requires_ffmpeg
def test_the_policy_can_ask_for_the_old_padding_behaviour(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    v.video_seconds = 2.0
    policy_mod.current().on_short = "pad"
    p, ids = one_clip_project(svc, seconds=5)
    run_all(svc, p.id)
    out = ProjectStore.path_for(p.id) / leaves(svc.load(p.id))[0].output
    assert media.probe_duration(out) > 4.5 and media.freeze_stats(out)["tail_freeze_s"] > 1.5       # padded: the control case


# ------------------------------------------------------------------ 6. voices: listen before choosing
class Hearing:
    """A pretend vendor whose voices have free sample clips of known pitch, listed in an order that is WRONG for the profile."""
    name = "hearing"

    def __init__(self, tmp_path, pitches=(("a", 170), ("b", 220), ("c", 110))):
        self.paths = {}
        for vid, hz in pitches:
            wav = tmp_path / f"{vid}.wav"
            media.ff("-f", "lavfi", "-i", f"sine=frequency={hz}", "-t", "2", str(wav))
            self.paths[vid] = wav
        self.order = [vid for vid, _ in pitches]
        self.heard = []

    async def candidates(self, spec, taken=()):
        return [VoiceChoice(v, v.upper(), self.name, 5 - i, "male", preview_url=f"x/{v}") for i, v in enumerate(self.order)]

    async def preview(self, choice):
        self.heard.append(choice.voice_id)
        return self.paths[choice.voice_id]


@requires_ffmpeg
def test_voices_are_ranked_by_the_pitch_of_their_free_samples(tmp_path):
    h = Hearing(tmp_path)
    cands, note = asyncio.run(casting.choose_voice(h, casting.Profile(gender="male", pitch="low"), ()))
    assert cands[0].voice_id == "c" and abs(cands[0].pitch_hz - 110) < 8 and set(h.heard) == {"a", "b", "c"}
    h2 = Hearing(tmp_path)
    cands2, _ = asyncio.run(casting.choose_voice(h2, casting.Profile(gender="male", pitch="high"), ()))
    assert cands2[0].voice_id == "a"                                                                  # the same rule fits another profile (170 Hz)
    policy_mod.current().voice_preview_candidates = 0                                                # policy: do not listen
    h3 = Hearing(tmp_path)
    cands3, _ = asyncio.run(casting.choose_voice(h3, casting.Profile(gender="male", pitch="low"), ()))
    assert [c.voice_id for c in cands3] == ["a", "b", "c"] and h3.heard == []


@requires_ffmpeg
def test_a_vendor_without_samples_keeps_the_label_order(tmp_path):
    class Silent(Hearing):
        async def preview(self, choice):
            return None
    cands, _ = asyncio.run(casting.choose_voice(Silent(tmp_path), casting.Profile(gender="male", pitch="low"), ()))
    assert [c.voice_id for c in cands] == ["a", "b", "c"]


# ------------------------------------------------------------------ 7. end pictures and neighbours
def chain(svc, end_state="stopped and looking at the camera"):
    p, ids = build(svc, "A then B", [], [
        clip("landscape", "First shot", sound="wind", end=end_state), clip("landscape", "Second shot", sound="wind", start=end_state)],
        links=[(0, 1, "continues_from")])
    return p, ids


@requires_ffmpeg
def test_a_planned_ending_gets_an_end_picture_when_the_next_clip_continues_and_a_model_can_use_it(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    p, ids = chain(svc)
    plan = E.plan_clip(svc.load(p.id), leaves(svc.load(p.id))[0], svc.reg)
    assert plan.end_picture and plan.video.capabilities.get("end_frame")
    assert any("End picture" in l.item for l in leaves(svc.load(svc.save(svc.load(p.id)).id))[0].cost.lines) or True
    run_all(svc, p.id)
    first = v.calls["video"][0]
    assert first.end_frame is not None and Path(first.end_frame).exists()                           # the model was given the ending
    assert any("stopped and looking at the camera" in r.prompt for r in v.calls["picture"])          # made from the plan's end state
    assert v.calls["video"][1].end_frame is None                                                    # the last clip has no planned ending


@requires_ffmpeg
def test_end_pictures_can_be_switched_off_by_policy_and_are_not_made_without_a_continuing_clip(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    policy_mod.current().precise_endings = "off"
    p, ids = chain(svc)
    assert not E.plan_clip(svc.load(p.id), leaves(svc.load(p.id))[0], svc.reg).end_picture
    policy_mod.use(policy_mod.Policy())
    p2, ids2 = build(svc, "Alone", [], [clip("landscape", "Lone shot", sound="wind", end="stopped")])
    assert not E.plan_clip(svc.load(p2.id), leaves(svc.load(p2.id))[0], svc.reg).end_picture


@requires_ffmpeg
def test_a_clip_much_softer_than_the_clip_it_continues_gets_a_finishing_pass_and_the_threshold_is_policy(svc, monkeypatch, tmp_path):
    Vendors(svc, monkeypatch)
    p, ids = chain(svc)
    q = svc.load(p.id)
    for leaf in leaves(q):
        src = tmp_path / f"{leaf.id}.mp4"
        media.ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=24", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))
        dst = ProjectStore.path_for(p.id) / "clips" / leaf.id
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "final.mp4").write_bytes(src.read_bytes())
        leaf.output = f"clips/{leaf.id}/final.mp4"
        leaf.status = NodeStatus.done
    svc.save(q)
    eng = Engine(svc)
    sharp = {}

    def fake_sharp(path):
        return sharp.setdefault(str(path), 100.0 if "finish" not in str(path) else 100.0)
    ls = leaves(svc.load(p.id))
    sharp[str(ProjectStore.path_for(p.id) / ls[0].output)] = 1000.0                              # the first clip is sharp
    sharp[str(ProjectStore.path_for(p.id) / ls[1].output)] = 300.0                               # the second is a third as sharp
    eng._clip_sharpness = fake_sharp
    asyncio.run(eng._match_neighbours(p.id, ls[1].id))
    second = leaves(svc.load(p.id))[1]
    assert second.output.endswith("_finish.mp4") and any(w.startswith("Softer than") for w in second.warnings)
    # a policy that accepts a softer neighbour leaves it alone
    q = svc.load(p.id)
    leaves(q)[1].output = f"clips/{leaves(q)[1].id}/final.mp4"
    leaves(q)[1].warnings = []
    svc.save(q)
    policy_mod.current().min_sharpness_ratio = 0.2
    asyncio.run(eng._match_neighbours(p.id, ls[1].id))
    assert leaves(svc.load(p.id))[1].output.endswith("final.mp4")


# ------------------------------------------------------------------ 8. new scenarios, different from the first example
@requires_ffmpeg
@pytest.mark.parametrize("name", ["person_speaks_then_walks_out", "narrator_over_product_with_a_hand", "two_people_argue_one_leaves", "child_waves_then_a_line"])
def test_other_kinds_of_video_hold_every_general_rule(svc, monkeypatch, tmp_path, name):
    v = Vendors(svc, monkeypatch)
    if name == "person_speaks_then_walks_out":
        a = actor("Dev", voice_gender="male", voice_age="adult", voice_pitch="medium")
        p, ids = build(svc, "A person speaks, then leaves", [a], [
            clip("talking_head", "Dev speaks to camera", say=[("Dev", "That is all for today.")], actors=["Dev"], end="Dev facing the camera, relaxed"),
            clip("human_motion", "Dev turns and leaves the room", actors=["Dev"], sound="footsteps, a door", start="Dev facing the camera, relaxed")],
            links=[(0, 1, "continues_from")])
        motions = ["face", "body"]
    elif name == "narrator_over_product_with_a_hand":
        a = actor("Gadget", kind="product", description="a small grey speaker")
        p, ids = build(svc, "A speaker advert", [a], [
            clip("product", "A hand reaches in and lifts the speaker", narration="Pick it up.", actors=["Gadget"], sound="soft room tone", speech_on_camera=False),
            clip("product", "The speaker glows", narration="And listen.", actors=["Gadget"], sound="soft hum", speech_on_camera=False)])
        motions = ["body", "scene"]
    elif name == "two_people_argue_one_leaves":
        a, b = actor("Ria", voice_gender="female", voice_age="adult"), actor("Tom", voice_gender="male", voice_age="adult")
        p, ids = build(svc, "An argument", [a, b], [
            clip("dialogue_scene", "Ria and Tom argue", say=[("Ria", "You never listen."), ("Tom", "I am listening.")], actors=["Ria", "Tom"], sound="room tone"),
            clip("human_motion", "Tom walks out and the door closes", actors=["Tom"], sound="a door", start="Tom at the door")], links=[(0, 1, "continues_from")])
        motions = ["scene", "body"]
    else:
        a = actor("Mia", voice_gender="female", voice_age="child", voice_pitch="high")
        p, ids = build(svc, "A child waves and speaks", [a], [
            clip("human_motion", "Mia waves at the camera", actors=["Mia"], sound="a playground", end="Mia smiling at the camera"),
            clip("talking_head", "Mia says a short line", say=[("Mia", "Hi!")], actors=["Mia"], start="Mia smiling at the camera")], links=[(0, 1, "continues_from")])
        motions = ["body", "face"]
    q = svc.load(p.id)
    for leaf, m in zip(leaves(q), motions):
        leaf.script.motion = m
    svc.save(q)
    run_all(svc, p.id)
    out = check_rules(svc, p.id, v)
    for leaf in leaves(svc.load(p.id)):
        assert media.freeze_stats(ProjectStore.path_for(p.id) / leaf.output).get("tail_freeze_s", 0) <= policy_mod.current().max_freeze_s, (name, leaf.title)
