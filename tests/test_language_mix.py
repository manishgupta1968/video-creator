"""v3.13: everything the tool writes is English; only the SPOKEN words follow the language you choose, and a video may mix languages.
The real AI's obedience, a real voice and a real subtitle font cannot be tested here: these tests check what the tool SENDS, STORES and DOES."""
import asyncio
import json

import pytest

from video_generator import brain as brain_mod
from video_generator import casting, languages
from video_generator import policy as policy_mod
from video_generator.brain import ClipScriptDraft, Line, draft_to_script, render
from video_generator.continuity import check
from video_generator.models import ActorDetails, ClipScript, ContextItem, ContextType, DialogueLine, Project, Settings
from video_generator.project import ProjectStore
from video_generator.reviewer import Reviewer
from video_generator.runner import Engine, subtitle_text
from video_generator.tree import leaves

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors
from .test_scenarios import actor, build, clip, run_all

DEVANAGARI = "श्री गुरु चरन सरोज रज"
ENGLISH = "Hello there, my friend"


def two_speakers(svc, language="hi", also=("en",)):
    asha = actor("Asha", voice_gender="female", voice_accent="Hindi")
    asha.actor.language = "hi"
    ravi = actor("Ravi", voice_gender="male", voice_accent="Indian English")
    ravi.actor.language = "en"
    p, ids = build(svc, "A sage and a child", [asha, ravi], [clip("dialogue_scene", "They talk", say=[("Asha", DEVANAGARI), ("Ravi", ENGLISH)], actors=["Asha", "Ravi"])],
                   language=language, also_languages=list(also))
    return svc.load(p.id), ids


# ------------------------------------------------------------------ 1. English is the working language
TEXT_TASKS = ["decompose", "split_clip", "revise_goal", "replan", "optimize", "command", "review", "node_review"]


def test_the_english_rule_is_written_once_and_every_ai_task_gets_it():
    rule = brain_mod.english_rule()
    assert "Write in English" in rule and "ONLY text that may be in another language is a spoken line" in rule and "word for word" in rule
    assert rule in brain_mod.system_prompt() and "{{english_rule}}" not in brain_mod.system_prompt()          # every task sends the system prompt
    for name in TEXT_TASKS:
        assert "{{english_line}}" in brain_mod.template(name), name                                           # the text-writing tasks repeat it in one line
        rendered = render(name)
        assert brain_mod.ENGLISH_LINE in rendered and "{{english_line}}" not in rendered, name


def test_the_draft_and_script_prompts_say_only_the_spoken_words_use_the_language(svc):
    hindi = svc.new_project("Hanuman Chalisa verse", language="hi")
    block = svc.brain.language_block(hindi)
    assert "SPOKEN WORDS" in block and "Hindi (hi)" in block and "every other word you write" in block and "English" in block
    assert "`translation`" in block                                                                           # the English meaning is asked for in the same call
    line = svc.brain.language_line(hindi)
    assert "Every other word you write" in line and "Hindi (hi)" in line and "own script" in line
    assert "not a translation" in line                                                                        # a quote in English letters: same words, spoken script
    auto = svc.new_project("Hanuman Chalisa verse", language="auto")
    assert "Decide from the goal" in svc.brain.language_block(auto) and "English" in svc.brain.language_block(auto)


def test_a_mixed_video_names_the_other_languages_in_both_prompts(svc):
    p = svc.new_project("A sage teaches a child", language="hi", also_languages=["en", "ta", "hi"])
    assert p.settings.also_languages == ["en", "ta"]                                                          # the main language is never repeated
    block, line = svc.brain.language_block(p), svc.brain.language_line(p)
    for text in (block, line):
        assert "English (en)" in text and "Tamil (ta)" in text and "`narration_language`" in text
    assert "`narration_language`" not in svc.brain.language_block(svc.new_project("x", language="hi"))      # a single-language video is not told about mixing


def test_the_drafted_prompt_really_carries_the_words(svc):
    seen = {}

    async def spy(task, prompt, schema, meta, images=None, video=None):
        seen[task] = prompt
        raise RuntimeError("stop")
    svc.brain.ask = spy
    p = svc.new_project("Hanuman Chalisa verse", language="hi", also_languages=["en"])
    with pytest.raises(RuntimeError):
        asyncio.run(svc.brain.draft_project(p))
    assert "SPOKEN WORDS" in seen["draft"] and "English (en)" in seen["draft"] and "title, goals, descriptions, notes" in seen["draft"]
    n = p.root
    n.script = None
    with pytest.raises(RuntimeError):
        asyncio.run(svc.brain.write_clip_script(p, n))
    assert "LANGUAGE: the spoken words are in Hindi (hi)" in seen["write_clip_script"] and "Every other word you write" in seen["write_clip_script"]


# ------------------------------------------------------------------ 2. one language, many, or decided
def test_a_line_and_the_narration_keep_their_own_language_and_meaning(svc):
    p, _ = two_speakers(svc)
    asha, ravi = [c.id for c in p.context if c.type == ContextType.actor]
    d = ClipScriptDraft(visual="v", dialogue=[
        Line(speaker_name="Asha", text=DEVANAGARI, translation="Respect to the guru's feet"),             # Asha speaks Hindi: nothing to record, the meaning is kept
        Line(speaker_name="Asha", text=ENGLISH, language="en", translation="should be dropped"),           # one line in another allowed language, English: no meaning kept
        Line(speaker_name="Ravi", text=ENGLISH, language="en"),                                            # the same as his own language: nothing to record
        Line(speaker_name="Ravi", text="வணக்கம்", language="ta"),                                         # Tamil is not allowed in this video: dropped
    ], narration="गुरुदेव कहते हैं", narration_language="hi", narration_translation="Gurudev says")
    s = draft_to_script(p, d)
    assert [(x.speaker, x.language, x.translation) for x in s.dialogue] == [
        (asha, "", "Respect to the guru's feet"), (asha, "en", ""), (ravi, "", ""), (ravi, "", "")]
    assert s.narration_language == "" and s.narration_translation == "Gurudev says"                         # hi is the video's language: nothing to record, the meaning is kept
    english = draft_to_script(p, ClipScriptDraft(visual="v", narration="Gurudev says", narration_language="en", narration_translation="repeated"))
    assert english.narration_language == "en" and english.narration_translation == ""                       # English narration in a Hindi video: no meaning needed
    d2 = ClipScriptDraft(visual="v", narration=DEVANAGARI, narration_language="hi", narration_translation="Respect to the guru")
    p.settings.language = "en"
    p.settings.also_languages = ["hi"]
    s2 = draft_to_script(p, d2)
    assert s2.narration_language == "hi" and s2.narration_translation == "Respect to the guru"


def test_when_no_language_is_decided_yet_any_real_code_is_kept_and_unknown_ones_are_not():
    p = Project(name="n", goal="g", settings=Settings(language="auto"))
    d = ClipScriptDraft(visual="v", dialogue=[Line(speaker_name="narrator", text="x", language="Hindi"), Line(speaker_name="narrator", text="y", language="zz!")])
    s = draft_to_script(p, d)
    assert [x.language for x in s.dialogue] == ["hi", ""]


def test_old_projects_and_scripts_without_the_new_fields_load_and_behave_as_before(svc):
    p = svc.new_project("old", language="hi")
    data = json.loads(p.model_dump_json())
    for k in ("also_languages", "subtitle_language"):
        data["settings"].pop(k)
    data["root"]["script"] = {"dialogue": [{"speaker": "narrator", "text": "x"}], "narration": "y"}
    q = Project.model_validate(data)
    assert q.settings.also_languages == [] and q.settings.subtitle_language == "spoken"
    assert q.root.script.dialogue[0].language == "" and q.root.script.narration_language == "" and q.root.script.dialogue[0].translation == ""
    assert casting.clip_languages(q, q.root.script) == ["hi"]                                                # every line is the video's language


def test_the_language_of_a_line_is_the_lines_then_the_speakers_then_the_videos(svc):
    p, _ = two_speakers(svc)
    asha, ravi = [c.id for c in p.context if c.type == ContextType.actor]
    assert casting.line_language(p, asha) == "hi" and casting.line_language(p, ravi) == "en"
    assert casting.line_language(p, asha, "en") == "en"                                                      # one speaker switching language
    assert casting.line_language(p, "narrator") == "hi" and casting.line_language(p, "someone else", "") == "hi"
    p.settings.language = "auto"
    assert casting.line_language(p, "narrator") == "en"                                                      # never "auto": no service can use it
    s = ClipScript(dialogue=[DialogueLine(speaker=asha, text="a"), DialogueLine(speaker=ravi, text="b"), DialogueLine(speaker=asha, text="c", language="en")],
                   narration="n", narration_language="ta")
    assert casting.clip_languages(p, s) == ["hi", "en", "ta"] and casting.clip_languages(p, None) == []


def test_settings_keep_also_spoken_clean_and_the_main_language_out_of_it(svc):
    p = svc.new_project("x", language="hi")
    svc.update_project(p.id, {"settings": {"also_languages": ["Hindi", "en", "English", "zz!", "ta"]}})
    assert svc.load(p.id).settings.also_languages == ["en", "ta"]
    svc.update_project(p.id, {"settings": {"language": "en"}})
    assert svc.load(p.id).settings.also_languages == ["ta"]                                                  # en became the main language: it leaves the list
    assert svc.new_project("y", subtitle_language="nonsense").settings.subtitle_language == "spoken"


# ------------------------------------------------------------------ 3. the language is used
def test_the_voice_is_asked_for_each_lines_language(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    p, ids = two_speakers(svc)
    asha, ravi = [c.id for c in p.context if c.type == ContextType.actor]
    node = leaves(p)[0]
    node.script.dialogue.append(DialogueLine(speaker=asha, text="Now in English", language="en"))
    svc.save(p)
    eng = Engine(svc)
    asyncio.run(eng._make_voice(p.id, node.id))
    assert [c["language"] for c in v.calls["voice"]] == ["hi", "en", "en"]                                   # her Hindi line, his English line, her switch to English
    saved = json.loads((ProjectStore.path_for(p.id) / "clips" / node.id / "voice_lines.json").read_text())
    assert saved["languages"] == ["hi", "en", "en"] and [l["language"] for l in saved["lines"]] == ["hi", "en", "en"]
    n = len(v.calls["voice"])
    asyncio.run(eng._make_voice(p.id, node.id))
    assert len(v.calls["voice"]) == n                                                                         # nothing changed: the voice is not bought again
    q = svc.load(p.id)
    leaves(q)[0].script.dialogue[2].language = "hi"                                                          # a line changes language: the voice is made again
    svc.save(q)
    asyncio.run(eng._make_voice(p.id, node.id))
    assert len(v.calls["voice"]) == n + 3 and v.calls["voice"][-1]["language"] == "hi"


def test_a_voice_file_made_before_languages_were_stored_is_not_remade(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    p, ids = two_speakers(svc)
    node = leaves(p)[0]
    eng = Engine(svc)
    asyncio.run(eng._make_voice(p.id, node.id))
    n = len(v.calls["voice"])
    f = ProjectStore.path_for(p.id) / "clips" / node.id / "voice_lines.json"
    data = json.loads(f.read_text())
    data.pop("languages")
    f.write_text(json.dumps(data))
    asyncio.run(eng._make_voice(p.id, node.id))
    assert len(v.calls["voice"]) == n


def test_the_voice_spec_takes_the_lines_language_first(svc):
    p, _ = two_speakers(svc)
    asha = next(c for c in p.context if c.title == "Asha")
    eng = Engine(svc)
    assert eng._voice_spec(p, asha.id, "elevenlabs", "").language == "hi"
    assert eng._voice_spec(p, asha.id, "elevenlabs", "", "en").language == "en"
    assert eng._voice_spec(p, asha.id, "elevenlabs", "", "not a language!").language == "hi"


class Listener:
    def __init__(self):
        self.heard = []

    async def transcribe(self, media_path, language="en", hint=""):
        self.heard.append(language)
        return []


def test_the_reviewer_listens_in_the_clips_language_and_works_it_out_when_two_are_spoken(svc):
    p, _ = two_speakers(svc)
    asha, ravi = [c.id for c in p.context if c.type == ContextType.actor]
    node = leaves(p)[0]
    only_hindi = ClipScript(dialogue=[DialogueLine(speaker=asha, text=DEVANAGARI)])
    node.script = only_hindi
    assert Reviewer._listen_language(p, node) == "hi"
    node.script = ClipScript(dialogue=[DialogueLine(speaker=asha, text=DEVANAGARI), DialogueLine(speaker=ravi, text=ENGLISH)])
    assert Reviewer._listen_language(p, node) == ""                                                          # mixed: the service works it out
    policy_mod.current().mixed_language_detection = False
    try:
        assert Reviewer._listen_language(p, node) == "hi"                                                    # switched off: the first language only
    finally:
        policy_mod.current().mixed_language_detection = True
    node.script = ClipScript(visual="no speech")
    p.settings.language = "ta"
    assert Reviewer._listen_language(p, node) == "ta"                                                        # nothing scripted: the video's language


@requires_ffmpeg
def test_a_take_review_gives_the_transcriber_the_clips_language(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p, ids = two_speakers(svc)
    q = svc.load(p.id)
    q.settings.review_enabled = True
    svc.save(q)
    run_all(svc, p.id)
    q = svc.load(p.id)
    node = leaves(q)[0]
    ear = Listener()
    rv = Reviewer(svc)
    monkeypatch.setattr(rv, "transcriber", lambda: ear)

    async def spy(task, prompt, schema, meta, images=None, video=None):
        from .test_review_join import draft
        return draft()
    monkeypatch.setattr(svc.brain, "ask", spy)
    asyncio.run(rv.review_take(p.id, node.id, node.chosen_take))
    assert ear.heard == [""]                                                                                  # Hindi and English in one clip: auto-detect


def test_each_line_is_checked_against_its_own_languages_script(svc):
    asha = actor("Asha", voice_gender="female", voice_accent="Hindi")
    asha.actor.language = "hi"
    p, ids = build(svc, "Asha", [asha], [clip("talking_head", "Asha speaks", say=[("Asha", DEVANAGARI)], actors=["Asha"]),
                                         clip("talking_head", "Asha switches to English", say=[("Asha", ENGLISH)], actors=["Asha"]),
                                         clip("talking_head", "Asha says it in English letters", say=[("Asha", "Shri guru charan saroj raj")], actors=["Asha"])],
                   language="hi")
    q = svc.load(p.id)
    second = leaves(q)[1]
    second.script.dialogue[0].language = "en"                                                                # this line IS English: Latin letters are right
    svc.save(q)
    found = [f for f in check(svc.load(p.id), svc.reg) if f["code"] == "script_differs"]
    assert [f["number"] for f in found] == ["1.3"]                                                           # only the Hindi line written in English letters


def test_the_subtitle_text_is_spoken_english_or_both_and_never_empty():
    line = {"text": DEVANAGARI, "translation": "Respect to the guru's feet"}
    assert subtitle_text(line, "spoken") == DEVANAGARI
    assert subtitle_text(line, "english") == "Respect to the guru's feet"
    assert subtitle_text(line, "both") == DEVANAGARI + "\nRespect to the guru's feet"
    assert subtitle_text({"text": ENGLISH, "translation": ""}, "english") == ENGLISH                         # no meaning written: shows as spoken
    assert subtitle_text({"text": ENGLISH, "translation": ENGLISH}, "both") == ENGLISH                       # same words: not shown twice
    assert subtitle_text({"text": "x"}, "both") == "x"                                                       # an older file has no meaning at all


@requires_ffmpeg
def test_the_subtitle_file_follows_the_setting(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p, ids = two_speakers(svc)
    q = svc.load(p.id)
    leaves(q)[0].script.dialogue[0].translation = "Respect to the guru's feet"
    svc.save(q)
    eng = Engine(svc)
    asyncio.run(eng._make_voice(p.id, leaves(q)[0].id))
    base = ProjectStore.path_for(p.id)
    meta = base / "clips" / leaves(q)[0].id / "voice_lines.json"
    lines = json.loads(meta.read_text())["lines"]
    assert lines[0]["translation"] == "Respect to the guru's feet" and lines[1]["translation"] == ""
    for mode, first in (("spoken", DEVANAGARI), ("english", "Respect to the guru's feet"), ("both", DEVANAGARI + "\nRespect to the guru's feet")):
        q = svc.load(p.id)
        q.settings.subtitle_language = mode
        entries = eng._subtitle_entries(q)
        assert entries[0][2] == first and entries[1][2] == ENGLISH, mode


def test_changing_the_subtitle_language_makes_a_finished_video_out_of_date_but_the_default_does_not(svc):
    p = svc.new_project("x")
    before = ProjectStore.final_signature(p)
    p.settings.subtitle_language = "spoken"
    assert ProjectStore.final_signature(p) == before                                                         # videos finished before this setting stay current
    p.settings.subtitle_language = "english"
    assert ProjectStore.final_signature(p) != before


def test_a_missing_subtitle_font_is_noted_but_only_when_the_subtitles_show_the_spoken_words(svc, monkeypatch):
    p, ids = two_speakers(svc, language="hi", also=())
    monkeypatch.setattr("video_generator.media.font_for_language", lambda code: False if code == "hi" else True)
    found = [f for f in check(p, svc.reg) if f["code"] == "subtitle_font"]
    assert len(found) == 1 and "Hindi" in found[0]["text"] and "empty boxes" in found[0]["text"]
    p.settings.subtitle_language = "english"
    assert not [f for f in check(p, svc.reg) if f["code"] == "subtitle_font"]                                # English subtitles need no Hindi font
    p.settings.subtitle_language = "both"
    p.settings.subtitles = False
    assert not [f for f in check(p, svc.reg) if f["code"] == "subtitle_font"]                                # no subtitles at all
    monkeypatch.setattr("video_generator.media.font_for_language", lambda code: None)                        # this computer cannot say: not guessed
    p.settings.subtitles = True
    assert not [f for f in check(p, svc.reg) if f["code"] == "subtitle_font"]


def test_the_split_of_a_clip_keeps_each_lines_language_and_meaning(svc, monkeypatch):
    from .test_generic_rules import speak_and_move
    Vendors(svc, monkeypatch)
    q = speak_and_move(svc, "ai_person")
    leaf = leaves(q)[0]
    leaf.script.action_beats = ["moves away from the camera", "leaves the frame"]
    leaf.script.end_state, leaf.script.start_state = "out of frame", "facing the camera"
    leaf.script.dialogue[0].language = "hi"
    leaf.script.dialogue[0].translation = "Respect to the guru's feet"
    svc.save(q)
    parts = leaves(asyncio.run(svc.split_clip(q.id, leaf.id)))
    spoken = parts[0].script.dialogue[0]
    assert spoken.language == "hi" and spoken.translation == "Respect to the guru's feet"


# ------------------------------------------------------------------ API and command line
def test_the_api_and_the_command_line_accept_the_new_choices(svc):
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from video_generator.cli import app as cli_app
    from video_generator.web.app import app as web_app
    client = TestClient(web_app)
    r = client.post("/api/projects", data={"goal": "A sage teaches a child", "seconds": "20", "language": "hi", "also_languages": "en,ta", "subtitle_language": "both"})
    assert r.status_code == 200
    pid = r.json()["id"]
    s = ProjectStore.load(pid).settings
    assert s.language == "hi" and s.also_languages == ["en", "ta"] and s.subtitle_language == "both"
    client.patch(f"/api/projects/{pid}", json={"settings": {"also_languages": ["ta", "hi", "en"], "subtitle_language": "english"}})
    s = ProjectStore.load(pid).settings
    assert s.also_languages == ["ta", "en"] and s.subtitle_language == "english"
    run = CliRunner()
    out = run.invoke(cli_app, ["new", "A sage teaches a child", "--no-draft", "--language", "hi", "--also-language", "en", "--subtitles", "english"])
    assert out.exit_code == 0, out.output
    pid2 = next(p["id"] for p in ProjectStore.list() if p["id"] in out.output)
    s2 = ProjectStore.load(pid2).settings
    assert s2.language == "hi" and s2.also_languages == ["en"] and s2.subtitle_language == "english"
    bad = run.invoke(cli_app, ["new", "x", "--no-draft", "--subtitles", "loud"])
    assert bad.exit_code != 0


def test_the_new_policy_setting_has_help_text():
    f = policy_mod.Policy.model_fields["mixed_language_detection"]
    assert f.default is True and "language" in (f.description or "")
