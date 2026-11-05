"""Scenario matrix: the tool must work for ANY kind of video, not one example.

Each scenario builds a different kind of project, runs the whole engine (plan -> estimate -> make -> join) with pretend
vendors, and then the same general rules are checked on the result:
  every speaker has a profile and a DIFFERENT voice, and each voice fits the profile (gender, age, accent)
  every AI clip has sound (its own, made natural sound, or a planned silence)
  a clip that continues another starts from the previous clip's last frame, on every route
  no black bars at the sides or top/bottom of AI clips, in any aspect ratio
  the cost window has a natural-sound line when sound is made, and nothing raises
"""
import asyncio

import pytest

from video_generator import casting, media
from video_generator import estimate as E
from video_generator.models import (ActorDetails, ActorInShot, ClipScript, Consent, ContextItem, ContextRole, ContextType,
                                    DialogueLine, Node, NodeKind, NodeStatus, ShotType)
from video_generator.project import ProjectStore
from video_generator.runner import Engine
from video_generator.tree import add_child, leaves

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors, close, colour_for, mean_colour, pitch_of_id

pytestmark = requires_ffmpeg

REFERENCE_COLOUR = (20, 60, 200)        # the colour of the reference photo given to the engine: it must NOT leak into continuing clips


# ------------------------------------------------------------------ building blocks
def actor(title, kind="ai_person", role=ContextRole.must_appear, **kw) -> ContextItem:
    prof = {k: kw.pop(k) for k in list(kw) if k.startswith("voice_")}
    return ContextItem(type=ContextType.actor, title=title, role=role, actor=ActorDetails(
        kind=kind, description=kw.pop("description", f"{title}, photoreal"), clothing=kw.pop("clothing", ""), **prof), **kw)


def clip(shot, visual, say=(), narration="", sound="light ambience", start="", end="", actors=(), speech_on_camera=None, seconds=4) -> dict:
    return dict(shot=shot, visual=visual, say=list(say), narration=narration, sound=sound, start=start, end=end,
                actors=list(actors), seconds=seconds, on_camera=bool(say) if speech_on_camera is None else speech_on_camera)


def build(svc, goal, actors, clips, aspect="16:9", links=(), language="en", **settings):
    p = svc.new_project(goal, seconds=4 * len(clips), aspect=aspect, quality_mode="balanced")
    p.settings.music = False
    p.settings.review_enabled = False
    p.settings.auto_photo = False
    p.settings.takes_people = 1
    p.settings.takes_other = 1
    p.settings.language = language
    p.settings.budget_usd = 20
    for k, v in settings.items():
        setattr(p.settings, k, v)
    for a in actors:
        p.context.append(a)
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Story", goal=goal, target_seconds=4.0 * len(clips)))
    ids = []
    for i, c in enumerate(clips):
        node = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"Shot {i + 1}", goal=c["visual"], target_seconds=float(c["seconds"])))
        speakers = {a.title: a.id for a in actors}
        node.script = ClipScript(
            shot_type=ShotType(c["shot"]), visual=c["visual"], sound_notes=c["sound"], start_state=c["start"], end_state=c["end"],
            narration=c["narration"], on_camera_speech=c["on_camera"],
            actors_in_shot=[ActorInShot(actor_id=speakers[n]) for n in c["actors"]],
            dialogue=[DialogueLine(speaker=speakers[who], text=text) for who, text in c["say"]])
        ids.append(node.id)
    svc.save(p)
    p = svc.load(p.id)
    for a, b, typ in links:
        svc.add_dependency(p.id, ids[a], ids[b], typ)
    return svc.load(p.id), ids


def add_reference_photo(svc, p, item, tmp_path, size=(900, 675), name="ref.png"):
    from PIL import Image
    path = tmp_path / name
    Image.new("RGB", size, REFERENCE_COLOUR).save(path)
    svc.add_context_file(svc.load(p.id), path, ctx_id=item.id)


def run_all(svc, pid, mode="all"):
    eng = Engine(svc, stop_when_waiting=True)

    async def go():
        await eng.start(pid, mode, None, auto_pick=True)
        await eng.runs[pid].task
    asyncio.run(go())
    return eng


def pretend_real(svc, pid):
    """Pretend nothing is a free preview, so hand-off frames are real (the fake vendors produce 'real' clips anyway)."""
    return svc.load(pid)


# ------------------------------------------------------------------ the general rules
def peak_db(path) -> float:
    """Loudest point of the sound in dB; digital silence has no measurable peak, so it counts as -120."""
    return media.audio_stats(path).get("peak_db", -120.0)


def speakers_of(p):
    names = {}
    for c in p.context:
        if c.type == ContextType.actor and c.actor and c.actor.voice_id:
            names[c.id] = c
    return names


def check_rules(svc, pid, vendors, aspect="16:9", expect_sound=True, silent_ok=()):
    p = svc.load(pid)
    ls = leaves(p)
    # nothing raised: every clip is done and none carries a failure
    assert all(l.status == NodeStatus.done for l in ls), [(l.title, l.status, l.warnings) for l in ls]
    assert not any(w.startswith("failed") for l in ls for w in l.warnings)
    # every speaker has a profile and a DIFFERENT voice
    voiced = speakers_of(p)
    ids = [c.actor.voice_id for c in voiced.values()]
    assert len(ids) == len(set(ids)), f"two speakers share a voice: {[(c.title, c.actor.voice_id) for c in voiced.values()]}"
    for c in voiced.values():
        a = c.actor
        if a.voice_provider == "elevenlabs" and a.voice_id != "cloned_voice":
            prof = casting.profile_for(c, p)
            if prof.gender in ("male", "female"):
                assert pitch_of_id(a.voice_id) == (115.0 if prof.gender == "male" else 225.0), (c.title, prof.gender, a.voice_id)
    # every AI clip has sound unless the plan asked for silence
    for l in ls:
        if l.kind != NodeKind.clip:
            continue
        out = ProjectStore.path_for(pid) / l.output
        assert media.has_audio(out), l.title
        if expect_sound and l.id not in silent_ok:
            assert peak_db(out) > -50, f"{l.title} is silent"
        # no black bars: the picture fills the frame
        b = media.bars(out, at=min(1.0, l.takes[0].seconds / 2 if l.takes else 1.0))
        assert max(b.values()) < 0.02, f"{l.title}: black bars {b}"
    return p


# ------------------------------------------------------------------ the scenarios
def test_1_female_presenter_in_indian_english(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    meera = actor("Meera", voice_gender="female", voice_age="adult", voice_pitch="medium", voice_accent="Indian English",
                  voice_description="warm, clear", consent=Consent(confirmed=True, statement="self"))
    p, ids = build(svc, "A presenter explains a new app", [meera], [
        clip("talking_head", "Meera in a bright office speaks to camera", say=[("Meera", "Welcome. Let me show you the app.")], actors=["Meera"])])
    add_reference_photo(svc, p, meera, tmp_path)
    run_all(svc, p.id)
    p = check_rules(svc, p.id, v)
    assert next(c for c in p.context if c.title == "Meera").actor.voice_id == "f_ind"          # woman + Indian accent
    assert v.calls["avatar"] and v.calls["sfx"]                                                  # talking-picture clip got natural sound


def test_2_man_and_woman_talking(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    arun = actor("Arun", voice_gender="male", voice_age="adult", voice_pitch="medium", voice_description="calm")
    sara = actor("Sara", voice_gender="female", voice_age="young", voice_description="cheerful")
    p, _ = build(svc, "Two colleagues talk in a cafe", [arun, sara], [
        clip("dialogue_scene", "Arun and Sara talk at a cafe table", say=[("Arun", "Did you see the numbers?"), ("Sara", "Yes, they look great!")],
             actors=["Arun", "Sara"], sound="cafe murmur, cups")])
    run_all(svc, p.id)
    p = check_rules(svc, p.id, v)
    voices = {c.title: c.actor.voice_id for c in p.context if c.actor}
    assert voices["Arun"].startswith("m_") and voices["Sara"].startswith("f_") and voices["Arun"] != voices["Sara"]
    assert voices["Sara"] == "f_young"                                                           # young woman -> young female voice
    assert {c["voice_id"] for c in v.calls["voice"]} == {voices["Arun"], voices["Sara"]}         # each line spoken with its own voice


def test_3_talking_animal_continues_from_the_walk(svc, monkeypatch, tmp_path):
    """The original example, and the continuity rule on the talking route."""
    v = Vendors(svc, monkeypatch)
    lion = actor("Kito", kind="animal", voice_gender="male", voice_pitch="low", voice_pace="slow", voice_age="adult",
                 voice_description="deep, heavy, slow")
    p, ids = build(svc, "A lion walks up and says hello", [lion], [
        clip("wildlife", "Kito walks through grass toward the camera", actors=["Kito"], sound="light wind, soft footsteps",
             end="Kito stops, facing the camera, looking into the lens"),
        clip("talking_head", "Kito looks into the lens and speaks", say=[("Kito", "Hello, how are you?")], actors=["Kito"],
             start="Kito stops, facing the camera, looking into the lens", sound="light wind")],
        links=[(0, 1, "continues_from")])
    add_reference_photo(svc, p, next(c for c in p.context if c.title == "Kito"), tmp_path)
    run_all(svc, p.id)
    p = check_rules(svc, p.id, v)
    kito = next(c for c in p.context if c.title == "Kito")
    assert kito.actor.voice_id.startswith("m_") and kito.actor.voice_name                       # a male voice, and the user can see its name
    # continuity on the talking route: the speaking picture is the LAST FRAME of clip 1, not the reference photo
    first = ProjectStore.path_for(p.id) / leaves(p)[0].output
    last = tmp_path / "last.png"
    media.last_frame(first, last)
    speaker_photo = v.calls["avatar"][0].photo
    assert close(mean_colour(speaker_photo), mean_colour(last), 40) and not close(mean_colour(speaker_photo), REFERENCE_COLOUR, 60)
    # the clip prompt carries the planned states
    assert "The clip ends as: Kito stops, facing the camera" in v.calls["video"][0].prompt       # the planned end state reaches the video model


def test_4_silent_nature_montage_gets_natural_sound(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    p, ids = build(svc, "A calm morning in the hills", [], [
        clip("landscape", "Mist over green hills at dawn", sound="soft wind, distant birds"),
        clip("landscape", "A river runs through the valley", sound="flowing water"),
        clip("landscape", "Sunlight reaches a village", sound="silence")])
    run_all(svc, p.id)
    p = check_rules(svc, p.id, v, silent_ok={ids[2]})
    prompts = [c["prompt"] for c in v.calls["sfx"]]
    assert prompts == ["soft wind, distant birds", "flowing water"]                              # planned sound, and none for "silence"
    third = leaves(p)[2]
    assert peak_db(ProjectStore.path_for(p.id) / third.output) < -50                            # the planner chose silence: respected


def test_5_product_advert_with_narrator_and_no_people(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    bag = actor("AquaBag", kind="product", description="a blue waterproof backpack")
    p, _ = build(svc, "Advert for a waterproof backpack", [bag], [
        clip("product", "The blue backpack on a rock in the rain", narration="Meet AquaBag. Built for every storm.", actors=["AquaBag"],
             sound="rain on rock", speech_on_camera=False),
        clip("product", "Water beads off the fabric", narration="Stay dry. Go further.", actors=["AquaBag"], sound="rain, light drips",
             speech_on_camera=False)])
    add_reference_photo(svc, p, next(c for c in p.context if c.title == "AquaBag"), tmp_path, size=(800, 800))
    run_all(svc, p.id)
    p = check_rules(svc, p.id, v)
    narr = [c for c in p.context if c.title == "Narrator"]
    assert narr and narr[0].actor.voice_id, "a narrator card (voice only) must exist so the user can see and change the voice"
    assert {c["voice_id"] for c in v.calls["voice"]} == {narr[0].actor.voice_id}                 # one narrator voice across both clips


def test_6_slides_with_narration(svc, monkeypatch, tmp_path, sample_pdf):
    v = Vendors(svc, monkeypatch)
    p = svc.new_project("Features of the app", seconds=8, quality_mode="balanced")
    p.settings.music = False
    p.settings.review_enabled = False
    svc.save(p)
    p = svc.load(p.id)
    svc.add_context_file(p, sample_pdf)
    p = svc.load(p.id)
    slides = [n for n in leaves(p) if n.kind == NodeKind.slides]
    if not slides:
        p = asyncio.run(svc.draft(p.id))
        slides = [n for n in leaves(p) if n.kind == NodeKind.slides]
    assert slides
    svc.update_node(p.id, slides[0].id, {"script": {"narration": "Two simple features. Light and strong."}})
    run_all(svc, p.id)
    p = svc.load(p.id)
    out = ProjectStore.path_for(p.id) / next(l for l in leaves(p) if l.kind == NodeKind.slides).output
    assert media.has_audio(out) and peak_db(out) > -50                                            # the narration is there
    assert not v.calls["sfx"]                                                                     # slides are never given made-up ambience


def test_7_vertical_social_clip_with_a_4_3_photo(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    nina = actor("Nina", voice_gender="female", voice_age="young", voice_description="energetic, bright", voice_pace="fast",
                 consent=Consent(confirmed=True, statement="self"))
    p, _ = build(svc, "A vertical tip video", [nina], [
        clip("talking_head", "Nina talks to camera in her kitchen", say=[("Nina", "Quick tip: salt the water first.")], actors=["Nina"]),
        clip("product", "A pot of boiling water, close up", sound="boiling water")], aspect="9:16")
    add_reference_photo(svc, p, next(c for c in p.context if c.title == "Nina"), tmp_path, size=(1200, 900))       # 4:3 photo in a 9:16 video
    run_all(svc, p.id)
    p = check_rules(svc, p.id, v, aspect="9:16")
    first = ProjectStore.path_for(p.id) / leaves(p)[0].output
    w, h = media.video_size(first)
    assert h > w and abs(w / h - 9 / 16) < 0.02                                                   # really vertical
    sent = v.calls["avatar"][0].photo
    from PIL import Image
    sw, sh = Image.open(sent).size
    assert abs(sw / sh - 9 / 16) < 0.02                                                           # the 4:3 photo was fitted before it was animated


def test_8_users_own_voice_sample_wins_over_the_profile(svc, monkeypatch, tmp_path, sample_voice):
    v = Vendors(svc, monkeypatch)
    me = actor("Priya", kind="digital_twin", voice_gender="male", voice_description="deep",           # profile says male on purpose
               consent=Consent(confirmed=True, statement="self"))
    me.actor.voice_sample = "inputs/voice.wav"
    p, _ = build(svc, "Priya introduces herself", [me], [
        clip("talking_head", "Priya speaks to camera", say=[("Priya", "Hi, I am Priya.")], actors=["Priya"])])
    (ProjectStore.path_for(p.id) / "inputs").mkdir(exist_ok=True)
    (ProjectStore.path_for(p.id) / "inputs" / "voice.wav").write_bytes(sample_voice.read_bytes())
    add_reference_photo(svc, p, next(c for c in p.context if c.title == "Priya"), tmp_path)
    run_all(svc, p.id)
    p = svc.load(p.id)
    pri = next(c for c in p.context if c.title == "Priya")
    assert v.calls["clone"] and pri.actor.voice_id == "cloned_voice"                               # the cloned voice is used
    assert not [s for s in v.calls["candidates"]]                                                  # the profile was never consulted
    assert all(l.status == NodeStatus.done for l in leaves(p))


def test_9_child_and_elderly_characters(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    kid = actor("Tia", voice_gender="female", voice_age="child", voice_description="small, cheerful")
    grandpa = actor("Grandpa", voice_gender="male", voice_age="older", voice_description="warm, gravelly")
    p, _ = build(svc, "A girl asks her grandfather a question", [kid, grandpa], [
        clip("dialogue_scene", "Tia and Grandpa on a porch", say=[("Tia", "Grandpa, why is the sky red?"), ("Grandpa", "Because the day is saying goodnight.")],
             actors=["Tia", "Grandpa"], sound="evening crickets, porch creak")])
    run_all(svc, p.id)
    p = check_rules(svc, p.id, v)
    voices = {c.title: c.actor.voice_id for c in p.context if c.actor}
    assert voices["Grandpa"] == "m_old" and voices["Tia"] == "f_young"                              # age is respected on both


def test_10_hindi_narration_uses_language_and_accent(svc, monkeypatch, tmp_path):
    v = Vendors(svc, monkeypatch)
    narrator = actor("Narrator", role=ContextRole.voice, description="the voice-over (never seen)", voice_gender="female",
                     voice_age="adult", voice_accent="Indian", voice_description="warm, clear")
    p, _ = build(svc, "A short film about monsoon in Hindi", [narrator], [
        clip("landscape", "Rain over a city skyline", narration="बारिश आ गई है।", sound="rain, distant thunder", actors=[]),
        clip("landscape", "People with umbrellas", narration="शहर भीग गया है।", sound="rain, street", actors=[])], language="hi")
    run_all(svc, p.id)
    p = check_rules(svc, p.id, v)
    assert v.calls["voice"] and all(c["language"] == "hi" for c in v.calls["voice"])                 # the language reaches the voice vendor
    assert svc.load(p.id).context[0].actor.voice_id == "f_ind"                                       # female + Indian accent


def test_11_user_clip_mixed_with_ai_clips(svc, monkeypatch, tmp_path, sample_clip):
    v = Vendors(svc, monkeypatch)
    p, ids = build(svc, "Our trip", [], [
        clip("landscape", "A road through mountains", sound="wind and a distant engine"),
        clip("landscape", "A lake at sunset", sound="gentle water")])
    p = svc.load(p.id)
    part = p.root.children[0]
    user = Node(kind=NodeKind.user_clip, title="My own clip", goal="the user's footage")
    part.children.insert(1, user)
    svc.save(p)
    p = svc.load(p.id)
    svc.add_context_file(p, sample_clip, node_id=next(n for n in leaves(p) if n.kind == NodeKind.user_clip).id) if False else None
    uc = next(n for n in leaves(p) if n.kind == NodeKind.user_clip)
    dst = ProjectStore.path_for(p.id) / "inputs"
    dst.mkdir(exist_ok=True)
    (dst / "mine.mp4").write_bytes(sample_clip.read_bytes())
    uc.media = "inputs/mine.mp4"
    uc.voice_seconds = 3
    svc.save(p)
    run_all(svc, p.id)
    p = svc.load(p.id)
    assert all(l.status == NodeStatus.done for l in leaves(p)), [(l.title, l.status, l.warnings) for l in leaves(p)]
    assert p.final_output and media.has_video(ProjectStore.path_for(p.id) / p.final_output)
    ai = [l for l in leaves(p) if l.kind == NodeKind.clip]
    for l in ai:
        assert max(media.bars(ProjectStore.path_for(p.id) / l.output).values()) < 0.02
    assert len(v.calls["sfx"]) == 2                                                                  # sound only for the two AI clips


# ------------------------------------------------------------------ the cost window knows about the sound
def test_cost_window_has_a_natural_sound_line_only_when_sound_is_made(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p, ids = build(svc, "Hills", [], [clip("landscape", "Hills at dawn", sound="wind"), clip("landscape", "A river", sound="silence")])
    svc.refresh(p)
    p = svc.load(p.id)
    lines = {l.title: [x.item for x in l.cost.lines] for l in leaves(p)}
    assert any("Natural sound" in i for i in lines["Shot 1"]) and not any("Natural sound" in i for i in lines["Shot 2"])
    s = svc.summary(p)
    p.settings.ambience = False
    svc.save(p)
    p2 = svc.load(p.id)
    svc.refresh(p2)
    assert not any("Natural sound" in x.item for l in leaves(p2) for x in l.cost.lines)               # the switch turns it off
