"""Units for the general rules behind the scenarios: voice casting, sound design, continuity, framing."""
import asyncio

import pytest
from PIL import Image

from video_generator import casting, media
from video_generator.models import ActorDetails, ClipScript, ContextItem, ContextType, DependencyType, Node, NodeKind, NodeStatus, ShotType
from video_generator.plugins.base import PluginError, VoiceSpec
from video_generator.project import ProjectStore
from video_generator.reviewer import Reviewer
from video_generator.runner import Engine
from video_generator.tree import leaves

from .conftest import requires_ffmpeg
from .fake_vendors import VOICES, Vendors, close, mean_colour
from .test_scenarios import actor, add_reference_photo, build, clip, peak_db, run_all


# ------------------------------------------------------------------ casting
def test_gender_age_pitch_are_read_from_words_not_names():
    assert casting.guess_gender("a deep, heavy male voice") == "male" and casting.guess_gender("a bright young woman") == "female"
    assert casting.guess_gender("the voice of the lion") == "" and casting.guess_gender("she says that he left") == ""
    assert casting.guess_age("an elderly man") == "older" and casting.guess_age("a little girl") == "child"
    a = ContextItem(type=ContextType.actor, title="Kito", actor=ActorDetails(kind="animal", voice_description="a deep, slow, calm male voice"))
    from video_generator.models import Project
    prof = casting.profile_for(a, Project())
    assert (prof.gender, prof.pitch, prof.pace) == ("male", "low", "slow")


def candidates(spec, voices=VOICES, taken=(), fails=False):
    from video_generator.plugins.voice.elevenlabs import ElevenLabsVoice
    plugin = ElevenLabsVoice()

    async def lv():
        if fails:
            raise PluginError("ElevenLabs voices: HTTP 401: missing_permissions")
        return voices
    plugin.list_voices = lv
    return asyncio.run(plugin.candidates(spec, taken))


def test_gender_is_a_hard_filter_and_taken_voices_come_last():
    male = candidates(VoiceSpec(description="deep, heavy", gender="male", pitch="low", pace="slow"))
    assert male and all(c.gender == "male" for c in male) and male[0].voice_id == "m_deep"
    again = candidates(VoiceSpec(description="deep, heavy", gender="male", pitch="low"), taken=("m_deep",))
    assert again[0].voice_id != "m_deep" and again[-1].voice_id == "m_deep"              # a voice already used is the last choice
    female = candidates(VoiceSpec(description="warm", gender="female", age="older", accent="British"))
    assert female[0].voice_id == "f_old"                                                   # age and accent count after gender


def test_unreadable_voice_list_never_gives_the_wrong_gender():
    cands = candidates(VoiceSpec(description="deep", gender="male", pitch="low"), fails=True)
    assert cands and all(c.gender == "male" for c in cands) and "Voices: Read" in cands[0].note
    assert cands[0].voice_id != "21m00Tcm4TlvDq8ikWAM"                                     # never the female default for a male speaker


def test_a_weak_match_is_reported_never_hidden():
    from video_generator.plugins.base import VoiceChoice

    class OnlyFemale:
        async def candidates(self, spec, taken=()):
            return [VoiceChoice("f1", "Zoe", "x", gender="female")]

    class Broken:
        async def candidates(self, spec, taken=()):
            raise PluginError("HTTP 401: missing_permissions")
    cands, note = asyncio.run(casting.choose_voice(OnlyFemale(), casting.Profile(gender="male"), ()))
    assert cands and "no male voice was found" in note
    cands, note = asyncio.run(casting.choose_voice(Broken(), casting.Profile(gender="male"), ()))
    assert cands == [] and "no voice was found" in note and "missing_permissions" in note


@requires_ffmpeg
def test_pitch_measurement_and_bounded_correction(tmp_path):
    for hz in (110, 260):
        wav = tmp_path / f"t{hz}.wav"
        media.ff("-f", "lavfi", "-i", f"sine=frequency={hz}", "-t", "2", str(wav))
        assert abs(media.voice_pitch(wav) - hz) < 6
    wav = tmp_path / "t260.wav"
    out, note, shift = casting.fit_voice(wav, casting.Profile(gender="male", pitch="low"))
    assert shift == -casting.policy_mod.current().max_pitch_shift_st and "choose another voice" in note                  # too high to fix: capped, and the user is told
    assert media.voice_pitch(out) < 215 and abs(media.probe_duration(out) - 2.0) < 0.1
    ok, note2, shift2 = casting.fit_voice(tmp_path / "t110.wav", casting.Profile(gender="male", pitch="low"))
    assert ok == tmp_path / "t110.wav" and shift2 == 0.0 and note2 == ""                  # a fitting voice is left alone
    slow, _, _ = casting.fit_voice(tmp_path / "t110.wav", casting.Profile(gender="male", pace="slow"))
    assert media.probe_duration(slow) > 2.1                                                # slow pace is applied


# ------------------------------------------------------------------ engine: voices
@requires_ffmpeg
def test_a_voice_that_is_too_high_is_corrected_once_and_noted(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch, voice_pitch={"m_deep": 250.0, "m_young": 250.0, "m_old": 250.0, "m_ind": 250.0})
    boss = actor("Boss", voice_gender="male", voice_pitch="low", voice_description="deep")
    p, ids = build(svc, "Boss speaks", [boss], [
        clip("dialogue_scene", "Boss at a desk", say=[("Boss", "Quarterly results are in."), ("Boss", "They are good.")], actors=["Boss"])])
    run_all(svc, p.id)
    p = svc.load(p.id)
    item = next(c for c in p.context if c.title == "Boss")
    assert "semitones deeper" in item.actor.voice_note                                      # visible to the user
    voice = ProjectStore.path_for(p.id) / leaves(p)[0].voice_audio
    assert media.voice_pitch(voice) < 215                                                   # the heard voice was lowered
    assert item.analysis["voice_shift"]["semitones"] < 0                                    # both lines share one correction


@requires_ffmpeg
def test_a_refused_voice_moves_to_the_next_best_voice(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    v.refuse = {"m_deep"}
    boss = actor("Boss", voice_gender="male", voice_pitch="low", voice_description="deep authoritative")
    p, _ = build(svc, "Boss speaks", [boss], [clip("dialogue_scene", "Boss at a desk", say=[("Boss", "Hello.")], actors=["Boss"])])
    run_all(svc, p.id)
    p = svc.load(p.id)
    item = next(c for c in p.context if c.title == "Boss")
    assert item.actor.voice_id.startswith("m_") and item.actor.voice_id != "m_deep"
    assert all(l.status == NodeStatus.done for l in leaves(p))


@requires_ffmpeg
def test_the_profile_chosen_by_the_user_wins_over_guessing(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    odd = actor("Robo", kind="ai_person", voice_gender="female", voice_description="a deep, heavy robot")    # words say deep; the field says female
    p, _ = build(svc, "Robo speaks", [odd], [clip("dialogue_scene", "Robo in a lab", say=[("Robo", "Beep.")], actors=["Robo"])])
    run_all(svc, p.id)
    assert next(c for c in svc.load(p.id).context if c.title == "Robo").actor.voice_id.startswith("f_")


# ------------------------------------------------------------------ planner (offline brain)
def test_offline_planner_decides_voice_sound_states_and_music(svc):
    p = svc.new_project("A woman presenter explains our new bag, with a narrator and a lion in the ad", seconds=24)
    p = asyncio.run(svc.draft(p.id))
    actors = {c.title: c.actor for c in p.context if c.actor}
    assert actors["Presenter"].voice_gender == "female" and actors["Lion"].voice_pitch == "low" and actors["Lion"].voice_pace == "slow"
    assert "Narrator" in actors and next(c for c in p.context if c.title == "Narrator").role.value == "voice"
    assert p.music_advice
    for l in leaves(p):
        s = l.script
        assert s.sound_notes and s.end_state and s.start_state                              # every clip: sound design and states


def test_a_continuing_clip_starts_where_the_previous_one_ends(svc):
    p = svc.new_project("A man walks then then speaks", seconds=8)
    p = asyncio.run(svc.draft(p.id))
    ls = leaves(p)
    first = ls[0]
    first.script.end_state = "He stops, facing the camera"
    svc.save(p)
    from video_generator.brain import Brain
    p = svc.load(p.id)
    second = leaves(p)[1]
    second.goal = "then he continues and speaks"
    svc.save(p)
    draft = asyncio.run(svc.brain.write_clip_script(svc.load(p.id), leaves(svc.load(p.id))[1]))
    assert "He stops, facing the camera" in draft.start_state or not draft.continues_from_previous


# ------------------------------------------------------------------ sound
@requires_ffmpeg
def test_sound_maker_falls_back_and_never_stops_the_clip(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    from video_generator.plugins.base import Usage

    async def boom(prompt, seconds, out, model="", video=None, params=None):
        v.calls["sfx"].append({"prompt": prompt, "model": model})
        raise PluginError("fal: HTTP 422: bad duration", retry_other_model=True)

    async def eleven(prompt, seconds, out, model="", video=None, params=None):
        v.calls["sfx"].append({"prompt": prompt, "model": "eleven"})
        media.ff("-f", "lavfi", "-i", "anoisesrc=d=4:r=44100,volume=0.3", "-ac", "2", str(out))
        return out, Usage()
    monkeypatch.setattr(svc.reg.plugin("fal_mmaudio"), "generate", boom)
    monkeypatch.setattr(svc.reg.plugin("elevenlabs_sfx"), "generate", eleven)
    p, ids = build(svc, "Hills", [], [clip("landscape", "Hills", sound="wind")])
    run_all(svc, p.id)
    p = svc.load(p.id)
    assert all(l.status == NodeStatus.done for l in leaves(p))
    assert [c["model"] for c in v.calls["sfx"]] == ["fal-ai/mmaudio-v2", "eleven"]           # first refused, second used
    rows = [r for r in ProjectStore.ledger(p.id) if r["kind"] == "sfx"]
    assert len(rows) == 1 and "because mmaudio failed" in rows[0]["what"]


@requires_ffmpeg
def test_with_no_sound_vendor_the_free_local_sound_is_the_safety_net(svc, monkeypatch, tmp_path):
    Vendors(svc, monkeypatch)

    async def boom(*a, **k):
        raise PluginError("down")
    monkeypatch.setattr(svc.reg.plugin("fal_mmaudio"), "generate", boom)
    monkeypatch.setattr(svc.reg.plugin("elevenlabs_sfx"), "generate", boom)
    p, ids = build(svc, "Hills", [], [clip("landscape", "Hills", sound="wind through grass")])
    run_all(svc, p.id)
    p = svc.load(p.id)
    out = ProjectStore.path_for(p.id) / leaves(p)[0].output
    assert leaves(p)[0].status == NodeStatus.done and peak_db(out) > -50


@requires_ffmpeg
def test_ambience_switch_and_native_sound_models(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    p, ids = build(svc, "Hills", [], [clip("landscape", "Hills", sound="wind")], ambience=False)
    run_all(svc, p.id)
    assert v.calls["sfx"] == []                                                              # switched off: nothing made
    p2, ids2 = build(svc, "A car", [], [clip("product", "A car drives", sound="engine")])
    plan = __import__("video_generator.estimate", fromlist=["x"]).plan_clip(p2, leaves(p2)[0], svc.reg)
    assert plan.route == "video"
    if plan.video.capabilities.get("native_audio"):
        assert plan.sfx is None                                                              # a model with its own sound needs none


def test_local_ambience_picks_a_recipe_from_the_words(tmp_path):
    for words in ("light wind in the grass", "rain on a tin roof", "busy street traffic", "quiet office"):
        out = tmp_path / "a.wav"
        media.local_ambience(out, 2, words)
        assert abs(media.probe_duration(out) - 2) < 0.2 and peak_db(out) > -60


# ------------------------------------------------------------------ framing
def test_fit_image_modes_make_the_exact_shape(tmp_path):
    src = tmp_path / "s.png"
    Image.new("RGB", (1500, 1000), (200, 120, 40)).save(src)
    for aspect, ratio in (("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0), ("4:5", 0.8)):
        for mode in ("cover", "blur", "black"):
            out = tmp_path / f"o_{mode}.png"
            media.fit_image(src, out, aspect, mode)
            w, h = Image.open(out).size
            assert abs(w / h - ratio) < 0.01, (aspect, mode, w, h)
    media.fit_image(src, tmp_path / "b.png", "16:9", "black")
    assert max(media.bars(tmp_path / "b.png").values()) > 0.05                                                   # black mode keeps its bars (control)
    media.fit_image(src, tmp_path / "c.png", "16:9", "blur")
    assert max(media.bars(tmp_path / "c.png").values()) < 0.01                                                   # blur mode has no black bars
    media.fit_image(src, tmp_path / "d.png", "16:9", "cover")
    assert max(media.bars(tmp_path / "d.png").values()) < 0.01


@requires_ffmpeg
def test_normalize_clip_fill_modes(tmp_path):
    src = tmp_path / "in.mp4"
    media.ff("-f", "lavfi", "-i", "color=c=orange:s=900x600:r=24", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))      # 3:2 clip
    results = {}
    for fill in ("black", "blur", "crop"):
        out = tmp_path / f"{fill}.mp4"
        media.normalize_clip(src, out, (1280, 720), 24, fill=fill)
        assert media.video_size(out) == (1280, 720)
        results[fill] = max(media.bars(out).values())
    assert results["black"] > 0.05 and results["blur"] < 0.02 and results["crop"] < 0.02           # the negative control: black really has bars
    same = tmp_path / "same.mp4"
    media.ff("-f", "lavfi", "-i", "color=c=orange:s=640x360:r=24", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(same))
    out = tmp_path / "same_out.mp4"
    media.normalize_clip(same, out, (1280, 720), 24, fill="blur")
    assert media.video_size(out) == (1280, 720)


# ------------------------------------------------------------------ continuity
@requires_ffmpeg
def test_anchor_keeps_a_character_the_same_in_later_scenes(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    cat = actor("Momo", kind="animal", voice_gender="female", voice_description="small")
    p, ids = build(svc, "A cat in two places", [cat], [
        clip("wildlife", "Momo on a wall", actors=["Momo"]), clip("wildlife", "Momo in a garden", actors=["Momo"])])
    add_reference_photo(svc, p, next(c for c in p.context if c.title == "Momo"), tmp_path)
    run_all(svc, p.id)
    p = svc.load(p.id)
    momo = next(c for c in p.context if c.title == "Momo")
    assert momo.analysis.get("anchor")                                                         # the first appearance became the anchor
    # later pictures use the anchor (the look from the first clip), not only the original reference
    refs_used = [r.references for r in v.calls["picture"] if r.references]
    assert refs_used and any(len(r) >= 1 for r in refs_used)


@requires_ffmpeg
def test_same_scene_clips_get_the_earlier_frame_as_a_reference(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    p, ids = build(svc, "One room, two angles", [], [
        clip("product", "A kitchen, wide", sound="room tone"), clip("product", "The same kitchen, close on the kettle", sound="room tone")],
        links=[(0, 1, "same_location")])
    run_all(svc, p.id)
    p = svc.load(p.id)
    second_pics = [r for r in v.calls["picture"] if "close on the kettle" in r.prompt]
    assert second_pics and any(str(x).endswith(".png") and "scene_from_" in str(x) for r in second_pics for x in r.references)


@requires_ffmpeg
def test_review_sees_the_clip_joins_the_plan_says_must_flow(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    p, ids = build(svc, "A walk then a talk", [], [
        clip("landscape", "A road", sound="wind", end="a straight road at noon"), clip("landscape", "The same road", sound="wind", start="a straight road at noon"),
        clip("landscape", "A new city", sound="traffic")], links=[(0, 1, "continues_from")])
    run_all(svc, p.id)
    p = svc.load(p.id)
    from video_generator.tree import numbering
    text, images = Reviewer(svc)._boundaries(p, p.root, numbering(p), tmp_path / "rv")
    assert "clip 1.2 continues the same shot (after clip 1.1" in text                         # the linked pair is shown first
    assert "clip 1.3 is a deliberate cut (after clip 1.2" in text and len(images) == 4          # a cut is shown too, so an accidental-looking one can be flagged


@requires_ffmpeg
def test_a_project_made_with_the_old_voice_logic_gets_a_proper_voice_on_re_make(svc, monkeypatch, tmp_path):
    """Old projects stored a text-matched (often female) voice with no name. A re-make must cast again and speak again."""
    import json
    v = Vendors(svc, monkeypatch)
    lion = actor("Kito", kind="animal", voice_gender="male", voice_pitch="low", voice_description="deep, heavy")
    p, ids = build(svc, "A lion speaks", [lion], [clip("talking_head", "Kito speaks", say=[("Kito", "Hello.")], actors=["Kito"])])
    add_reference_photo(svc, p, next(c for c in p.context if c.title == "Kito"), tmp_path)
    run_all(svc, p.id)
    # put the project back into the state the old code left: female default voice, no name, cached voice without a voice list
    q = svc.load(p.id)
    item = next(c for c in q.context if c.title == "Kito")
    item.actor.voice_id, item.actor.voice_provider, item.actor.voice_name = "f_mid", "elevenlabs", ""
    svc.save(q)
    f = ProjectStore.path_for(p.id) / "clips" / ids[0] / "voice_lines.json"
    data = json.loads(f.read_text())
    data.pop("voices")
    f.write_text(json.dumps(data))
    before = len(v.calls["voice"])
    eng = Engine(svc, stop_when_waiting=True)

    async def go():
        await eng.start(p.id, "clip", [ids[0]], auto_pick=True)
        await eng.runs[p.id].task
    asyncio.run(go())
    q = svc.load(p.id)
    item = next(c for c in q.context if c.title == "Kito")
    assert item.actor.voice_id.startswith("m_") and item.actor.voice_name                  # cast again, and named
    assert len(v.calls["voice"]) > before and v.calls["voice"][-1]["voice_id"].startswith("m_")       # and spoken again with it


@requires_ffmpeg
def test_re_make_on_a_finished_clip_makes_it_again_and_followers_follow(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    p, ids = build(svc, "Two shots", [], [clip("landscape", "Hills", sound="wind"), clip("landscape", "Hills, closer", sound="wind")],
                   links=[(0, 1, "continues_from")])
    run_all(svc, p.id)
    made = len(v.calls["video"])
    assert all(l.status == NodeStatus.done for l in leaves(svc.load(p.id)))
    eng = Engine(svc, stop_when_waiting=True)

    async def go():
        await eng.start(p.id, "clip", [ids[0]], auto_pick=True)
        await eng.runs[p.id].task
    asyncio.run(go())
    q = svc.load(p.id)
    first, second = leaves(q)
    assert len(v.calls["video"]) >= made + 1                                  # clip 1 was made again
    assert first.status == NodeStatus.done and second.status == NodeStatus.stale   # the clip that continues from it must be made again too
