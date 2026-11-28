"""The spoken words (narration and dialogue) in the whole 3D film: the computer's own voice in the line's language (free,
shows the timing), the voice made for the real video when it exists, the voice service on request (made once and reused
by the video), a timing note when the words are longer than the clip, and sound strips in the Blender film."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from video_generator import media
from video_generator.plugins.base import Usage
from video_generator.plugins.voice.local_voice import SystemVoice
from video_generator.project import ProjectStore
from video_generator.scene3d import film
from video_generator.tree import find

from .conftest import requires_ffmpeg
from .test_scene3d_change import project


class Spoken:
    """A stand-in voice: a tone as long as the words (0.4 s per word), and it records what it was asked."""
    def __init__(self):
        self.calls = []

    async def synthesize(self, text, voice, out, model=""):
        self.calls.append((text, voice.language))
        secs = 0.4 * max(len(text.split()), 1)
        media.ff("-f", "lavfi", "-i", f"sine=frequency=440:duration={secs:.2f}", "-ar", "44100", "-ac", "1", str(out))
        return out, Usage()


def _fix(project, nid, seconds=4.0):
    find(project, nid).duration.likely_s = seconds
    return project


def narrate(svc, pid, nid, words, lang="hi"):
    p = svc.load(pid)
    sc = find(p, nid).script
    sc.narration, sc.narration_language = words, lang
    svc.save(p)


@requires_ffmpeg
def test_the_3d_film_speaks_the_narration_in_its_language_and_notes_the_timing(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    spoken = Spoken()
    monkeypatch.setattr(film, "_free_voice", lambda svc_, lang: spoken)
    narrate(svc, p.id, ids[0], "shri guru charan saroj raj nij manu mukuru sudhar baranau raghubar bimal jasu")
    f = asyncio.run(film.make_film(svc, p.id, prepare=True))
    assert f.parts[0].seconds > 4                       # a clip grows to fit its words, so nothing is cut ...
    assert not any("spoken words take" in n for n in f.notes)
    spoken.calls.clear()
    monkeypatch.setattr(film, "_lines", lambda project, node: [("narrator", "shri guru charan saroj raj nij manu mukuru sudhar baranau raghubar bimal jasu shri", "hi")]
                        if node.id == ids[0] else [])
    q = svc.load(p.id)
    find(q, ids[0]).duration.likely_s = 4.0             # ... but when a clip's length is fixed, the film says so
    monkeypatch.setattr(svc, "load", lambda pid, _l=svc.load: _fix(_l(pid), ids[0]))
    f = asyncio.run(film.make_film(svc, p.id, prepare=False))
    assert spoken.calls == [("shri guru charan saroj raj nij manu mukuru sudhar baranau raghubar bimal jasu shri", "hi")]
    base = ProjectStore.path_for(p.id)
    assert media.has_audio(base / f.video)
    assert any("Spoken words:" in n and "your computer's own voice" in n for n in f.notes)
    assert any(n.startswith("Clip 1.1: the spoken words take") and "Shorten the words" in n for n in f.notes)   # 13 words > 4 s
    again = asyncio.run(film.make_film(svc, p.id, prepare=False))
    assert len(spoken.calls) == 1 and media.has_audio(base / again.video)       # the same words are not spoken again


@requires_ffmpeg
def test_new_words_make_the_film_out_of_date(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    monkeypatch.setattr(film, "_free_voice", lambda svc_, lang: Spoken())
    narrate(svc, p.id, ids[0], "hello there")
    asyncio.run(film.make_film(svc, p.id, prepare=True))
    assert not film.stale_reason(svc.load(p.id))
    narrate(svc, p.id, ids[0], "a different line")
    assert film.stale_reason(svc.load(p.id))


@requires_ffmpeg
def test_the_voice_made_for_the_video_is_used_when_it_exists(svc, monkeypatch, tmp_path):
    p, ids = project(svc, monkeypatch)
    narrate(svc, p.id, ids[0], "hello there")
    base = ProjectStore.path_for(p.id)
    voice = base / "clips" / ids[0] / "voice.wav"
    voice.parent.mkdir(parents=True, exist_ok=True)
    media.ff("-f", "lavfi", "-i", "sine=frequency=300:duration=1", str(voice))
    q = svc.load(p.id)
    find(q, ids[0]).voice_audio = str(voice.relative_to(base))
    svc.save(q)
    monkeypatch.setattr(film, "_free_voice", lambda svc_, lang: pytest.fail("the free voice must not be used"))
    f = asyncio.run(film.make_film(svc, p.id, prepare=True))
    assert any("the voice made for the video" in n for n in f.notes)


@requires_ffmpeg
def test_the_voice_service_option_makes_the_videos_voice_once(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    narrate(svc, p.id, ids[0], "hello there")
    q = svc.load(p.id)
    q.settings.scene3d.film_voice = "service"
    svc.save(q)
    made = []

    class Eng:
        async def _make_voice(self, pid, nid):
            made.append(nid)
            base = ProjectStore.path_for(pid)
            v = base / "clips" / nid / "voice.wav"
            v.parent.mkdir(parents=True, exist_ok=True)
            media.ff("-f", "lavfi", "-i", "sine=frequency=500:duration=1", str(v))
            pr = svc.load(pid)
            find(pr, nid).voice_audio = str(v.relative_to(base))
            svc.save(pr)
    monkeypatch.setattr(svc, "engine", Eng(), raising=False)
    f = asyncio.run(film.make_film(svc, p.id, prepare=True, allow_paid=True))
    assert made == [ids[0]] and any("your voice service (the video will reuse it)" in n for n in f.notes)
    asyncio.run(film.make_film(svc, p.id, prepare=True, allow_paid=True))
    assert made == [ids[0]]                                                        # made once, then reused


@requires_ffmpeg
def test_no_sound_when_switched_off(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    narrate(svc, p.id, ids[0], "hello there")
    q = svc.load(p.id)
    q.settings.scene3d.film_voice = "off"
    svc.save(q)
    monkeypatch.setattr(film, "_free_voice", lambda svc_, lang: pytest.fail("no voice when off"))
    f = asyncio.run(film.make_film(svc, p.id, prepare=True))
    assert not any("Spoken words" in n for n in f.notes)


def test_the_computers_voice_picks_a_voice_for_the_language(monkeypatch):
    listing = "Alex                en_US    # Most people recognize me by my voice.\nLekha               hi_IN    # नमस्ते\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": listing})())
    assert SystemVoice.say_voice("hi") == "Lekha" and SystemVoice.say_voice("en") == "" and SystemVoice.say_voice("ta") == ""


def test_the_blender_film_gets_sound_strips():
    text = (Path(film.__file__).with_name("blender_film.py")).read_text()
    assert "strips.new_sound(" in text and 'clip.get("audio")' in text


@requires_ffmpeg
def test_the_real_voice_is_made_first_so_no_clip_becomes_a_blank_card(svc, monkeypatch):
    """The voice service made the voice AFTER the previews, the clip's length changed, and its fresh preview was shown
    as a blank card; the next update planned it again (it looked endless). Now the voice comes first."""
    from .fake_vendors import Vendors
    p, ids = project(svc, monkeypatch)
    first = asyncio.run(film.make_film(svc, p.id, prepare=True))
    v = Vendors(svc, monkeypatch)
    q = svc.load(p.id)
    find(q, ids[0]).script.narration = "shri guru charan saroj raj nij manu mukuru sudhar baranau raghubar bimal jasu jo dayaku phal chari"
    q.settings.scene3d.film_voice = "service"
    svc.save(q)
    f = asyncio.run(film.make_film(svc, p.id, prepare=True, allow_paid=True))      # you agreed to the voice service
    assert [pt.source for pt in f.parts] == ["3d", "3d"] and f.parts[0].seconds > 4
    assert not film.stale_reason(svc.load(p.id)) and len(v.calls["voice"]) == 1
    assert f.previous_video == first.video and (ProjectStore.path_for(p.id) / first.video).exists()   # the film before is kept
    again = asyncio.run(film.make_film(svc, p.id, prepare=True, allow_paid=True))
    assert any("Nothing had changed" in n for n in again.notes) and len(v.calls["voice"]) == 1


@requires_ffmpeg
def test_a_film_that_fails_half_way_leaves_your_film_as_it_was(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    good = asyncio.run(film.make_film(svc, p.id, prepare=True))

    def broken(*a, **k):
        raise media.MediaError("stopped half-way")
    monkeypatch.setattr(media, "join_clips", broken)
    with pytest.raises(film.FilmError):
        asyncio.run(film.make_film(svc, p.id, prepare=False))
    kept = svc.load(p.id).scene3d_film
    assert kept.video == good.video and (ProjectStore.path_for(p.id) / kept.video).exists()


def test_only_one_film_is_made_at_a_time(svc, monkeypatch):
    p, _ = project(svc, monkeypatch)
    film._MAKING.add(p.id)
    try:
        with pytest.raises(film.FilmError, match="already being made"):
            asyncio.run(film.make_film(svc, p.id, prepare=False))
    finally:
        film._MAKING.discard(p.id)
