"""Step 5 (v3.10): numbers you can trust (any script, the speaker's real pace), edits that cascade (a part's length moves its clips,
never below what a clip needs, never touching clips that are made or kept), and lines marked "say exactly this"."""
import pytest

from video_generator import estimate as E
from video_generator import policy as policy_mod
from video_generator import scaling
from video_generator.brain import ActorDraft, ClipScriptDraft, Line, ProjectDraft, StyleDraft, draft_to_script, preserve_fixed
from video_generator.models import (ActorDetails, ClipScript, ContextItem, ContextType, DialogueLine, Node, NodeKind, NodeStatus,
                                    ShotType)
from video_generator.tree import add_child, leaves

from .fake_vendors import Vendors

HINDI = "श्री गुरु चरन सरोज रज, निज मनु मुकुर सुधारि"          # nine words


# ------------------------------------------------------------------ words in any script
def test_words_are_counted_the_same_in_any_script():
    assert E._words("Shri guru charan saroj raj") == 5
    assert E._words(HINDI) == 9                                  # a letters-only pattern counted 17: vowel signs are marks, not letters
    assert E._words("don't stop well-known 2025") == 4
    assert E._words("— । ,") == 0 and E._words("") == 0 and E._words(None) == 0   # a lone dash or danda is not a word
    assert E._words("你好世界 hello") == 3                         # unspaced script: 2 characters per word, and one Latin word


def test_a_hindi_line_is_timed_as_nine_words_not_seventeen(svc):
    p = svc.new_project("Hindi timing", seconds=10)
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="P", goal="g"))
    c = add_child(p, part.id, Node(kind=NodeKind.clip, title="C", goal="g"))
    c.script = ClipScript(shot_type=ShotType.landscape, visual="a lamp", narration=HINDI)
    svc.save(p)
    q = svc.load(p.id)
    secs = leaves(q)[0].duration.likely_s
    expected = 9 / q.settings.default_wpm * 60 + 2 * policy_mod.current().edge_pad
    assert secs == pytest.approx(max(expected, 3.0), abs=0.2) and secs < 17 / q.settings.default_wpm * 60 + 1


def test_the_planner_can_set_how_fast_a_speaker_really_speaks(svc, monkeypatch):
    async def fake_draft(project):
        return ProjectDraft(title="Slow", style=StyleDraft(), actors=[ActorDraft(name="Chanter", kind="ai_person", speaking_wpm=60)], parts=[])
    monkeypatch.setattr(svc.brain, "draft_project", fake_draft)
    import asyncio
    p = svc.new_project("A slow chant")
    p = asyncio.run(svc.draft(p.id, write_scripts=False))
    chanter = next(c for c in p.context if c.title == "Chanter")
    assert chanter.actor.speaking_wpm == 60
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="P", goal="g"))
    c = add_child(p, part.id, Node(kind=NodeKind.clip, title="C", goal="g"))
    c.script = ClipScript(shot_type=ShotType.landscape, visual="v", dialogue=[DialogueLine(speaker=chanter.id, text="one two three four five six")])
    assert E.speaking_wpm(p, c, chanter.id) == 60
    assert E.speech_need(p, c) == pytest.approx(6 / 60 * 60 + 2 * policy_mod.current().edge_pad)       # 6 s at 60 words a minute, plus the quiet at both ends


# ------------------------------------------------------------------ named settings
def test_the_new_settings_are_named_and_the_budget_threshold_is_no_longer_hidden(svc, monkeypatch):
    names = {n: why for n, _, why in policy_mod.describe()}
    for n in ("min_clip_s", "min_action_seconds", "unspaced_chars_per_word", "budget_min_strength"):
        assert names[n]
    Vendors(svc, monkeypatch)
    cheap = [e.strength("human_motion") for e in svc.reg.candidates("video", "human_motion", mode="budget")]
    policy_mod.use(policy_mod.Policy(budget_min_strength=5))
    try:
        strict = [e.strength("human_motion") for e in svc.reg.candidates("video", "human_motion", mode="budget")]
    finally:
        policy_mod.use(policy_mod.Policy())
    assert strict and all(x >= 5 for x in strict) and len(strict) <= len(cheap)


# ------------------------------------------------------------------ the shortest a clip can honestly be
def clip_with(svc, **script):
    p = svc.new_project("Floors", seconds=10)
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="P", goal="g"))
    c = add_child(p, part.id, Node(kind=NodeKind.clip, title="C", goal="g"))
    c.script = ClipScript(shot_type=ShotType.landscape, visual="v", **script)
    return p, c


def test_a_clip_is_never_shorter_than_its_speech_its_action_steps_or_the_minimum(svc):
    p, c = clip_with(svc)
    assert E.clip_floor(p, c) == (3.0, "a clip is never shorter than 3 s")
    p, c = clip_with(svc, action_beats=["a", "b", "c", "d"])
    assert E.clip_floor(p, c) == (6.0, "4 action steps need 6 s")
    p, c = clip_with(svc, narration=" ".join(["word"] * 30))
    secs, why = E.clip_floor(p, c)
    assert secs == pytest.approx(30 / 150 * 60 + 1.0, abs=0.1) and "the speech needs" in why
    c.voice_seconds = 20.0                                       # once the real voice exists, its real length rules
    assert E.clip_floor(p, c)[0] == pytest.approx(20.5, abs=0.1)


# ------------------------------------------------------------------ resizing a part
def three_clips(svc, lengths=(6, 6, 6), **settings):
    p = svc.new_project("Resize", seconds=sum(lengths), quality_mode="balanced")
    for k, v in settings.items():
        setattr(p.settings, k, v)
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Part", goal="g", target_seconds=float(sum(lengths))))
    for i, secs in enumerate(lengths):
        c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"C{i + 1}", goal="g", target_seconds=float(secs)))
        c.script = ClipScript(shot_type=ShotType.landscape, visual="v", sound_notes="wind", target_seconds=float(secs))
    svc.save(p)
    return svc.load(p.id)


def lens(p):
    return [l.target_seconds for l in leaves(p)]


def test_a_part_length_change_moves_its_clips_in_proportion(svc):
    p = three_clips(svc, (6, 12))
    res = scaling.scale_node(p, p.root.children[0].id, 9)
    assert lens(p) == [3.0, 6.0] and res["achieved"] == 9 and res["note"] == "" and len(res["changed"]) == 2
    assert res["changed"][0] == {"id": leaves(p)[0].id, "number": "1.1", "from": 6.0, "to": 3.0}
    assert p.root.children[0].target_seconds == 9                # the part's own length follows what is inside it


def test_it_never_goes_below_what_the_clips_need_and_says_why(svc):
    p = three_clips(svc, (6, 6, 6))
    res = scaling.scale_node(p, p.root.children[0].id, 6)
    assert lens(p) == [3.0, 3.0, 3.0] and res["achieved"] == 9
    assert "cannot go below 9 s" in res["note"] and "never shorter than 3 s" in res["note"]
    q = three_clips(svc, (6, 6))
    leaves(q)[0].script.narration = " ".join(["word"] * 30)       # speech needs about 13 s: words cannot be squeezed
    res = scaling.scale_node(q, q.root.children[0].id, 8)
    assert lens(q)[0] >= 12.5 and "the speech needs" in res["note"]


def test_a_clip_that_is_made_or_kept_is_never_touched_and_the_others_take_the_change(svc):
    p = three_clips(svc, (6, 6, 6))
    a, b, c = leaves(p)
    a.status = NodeStatus.done
    a.duration.likely_s = 6.0
    b.locked = True
    res = scaling.scale_node(p, p.root.children[0].id, 12)
    assert a.target_seconds == 6.0 and b.target_seconds == 6.0 and c.target_seconds == 3.0 and a.status == NodeStatus.done
    assert res["kept"] == ["1.1", "1.2"] and res["achieved"] == 15 and "2 clips already made or kept" in res["note"]


def test_changing_a_part_or_the_whole_video_through_the_service_moves_the_clips(svc):
    p = three_clips(svc, (6, 6, 6))
    part = p.root.children[0]
    q = svc.update_node(p.id, part.id, {"target_seconds": 12})
    assert lens(q) == [4.0, 4.0, 4.0] and svc.last_scale[p.id]["achieved"] == 12 and q.root.children[0].target_seconds == 12
    assert svc.summary(svc.load(p.id))["seconds"] == pytest.approx(12, abs=1.5)
    svc.last_scale.clear()
    q = svc.update_project(p.id, {"settings": {"target_seconds": 9}})        # the whole video
    assert lens(q) == [3.0, 3.0, 3.0] and q.settings.length_mode == "fixed" and svc.last_scale[p.id]["changed"]
    svc.last_scale.clear()
    q = svc.update_node(p.id, leaves(q)[0].id, {"target_seconds": 5})        # one clip: it just changes
    assert leaves(q)[0].target_seconds == 5 and p.id not in svc.last_scale


def test_the_patch_routes_say_what_a_length_change_did_once(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p = three_clips(svc, (6, 6))
    with TestClient(appmod.app) as client:
        r = client.patch(f"/api/projects/{p.id}/nodes/{p.root.children[0].id}", json={"target_seconds": 6}).json()
        assert r["scale"]["achieved"] == 6 and len(r["scale"]["changed"]) == 2
        assert "scale" not in client.get(f"/api/projects/{p.id}").json()      # shown once
        r = client.patch(f"/api/projects/{p.id}", json={"settings": {"target_seconds": 6}}).json()
        assert r["scale"]["requested"] == 6


# ------------------------------------------------------------------ "say exactly this"
def test_the_planner_can_mark_a_line_as_fixed(svc):
    d = ClipScriptDraft(visual="v", dialogue=[Line(speaker_name="narrator", text="exact words", fixed=True), Line(speaker_name="narrator", text="loose")],
                        narration="a quote", narration_fixed=True)
    s = draft_to_script(svc.new_project("x"), d)
    assert [l.fixed for l in s.dialogue] == [True, False] and s.narration_fixed


def test_a_rewritten_script_still_holds_every_fixed_line():
    old = ClipScript(visual="v", dialogue=[DialogueLine(speaker="a", text="line one"), DialogueLine(speaker="a", text="EXACT TEXT", fixed=True)],
                     narration="the quote", narration_fixed=True)
    new = ClipScript(visual="w", dialogue=[DialogueLine(speaker="a", text="something else"), DialogueLine(speaker="a", text="Exact text, reworded")],
                     narration="a different narration")
    restored = preserve_fixed(old, new)
    assert [l.text for l in new.dialogue] == ["something else", "EXACT TEXT", "Exact text, reworded"] and new.dialogue[1].fixed
    assert new.narration == "the quote" and new.narration_fixed and set(restored) == {"EXACT TEXT", "the quote"}
    kept = ClipScript(visual="w", dialogue=[DialogueLine(speaker="a", text="EXACT TEXT")])
    assert preserve_fixed(old, kept) == ["the quote"]                      # the line was already there: only the narration comes back
    assert kept.dialogue[0].fixed and sum(1 for l in kept.dialogue if l.text == "EXACT TEXT") == 1        # never doubled


def test_rewriting_a_clip_with_ai_cannot_lose_a_fixed_line(svc):
    import asyncio
    p, c = clip_with(svc, dialogue=[DialogueLine(speaker="narrator", text="Say exactly this sentence.", fixed=True)])
    svc.save(p)
    q = asyncio.run(svc.revise(p.id, c.id, "make it shorter and punchier"))
    s = leaves(q)[0].script
    assert any(l.text == "Say exactly this sentence." and l.fixed for l in s.dialogue)


def test_a_split_keeps_the_fixed_mark_of_every_line(svc):
    import asyncio
    p, c = clip_with(svc, dialogue=[DialogueLine(speaker="narrator", text="Keep this exactly.", fixed=True)], action_beats=["walks", "leaves"],
                     start_state="a", end_state="b")
    c.script.on_camera_speech = False
    svc.save(p)
    q = asyncio.run(svc.split_clip(p.id, c.id))
    lines = [l for x in leaves(q) for l in x.script.dialogue]
    assert lines and all(l.fixed for l in lines)


def test_a_clip_can_be_kept_as_it_is(svc):
    p = three_clips(svc, (6, 6))
    q = svc.update_node(p.id, leaves(p)[0].id, {"locked": True})
    assert leaves(q)[0].locked is True
    assert scaling.protected(leaves(q)[0]) and not scaling.protected(leaves(q)[1])
