"""Voices: Google and OpenAI voices that follow the accent asked for, the 'Voice made by' choice, who speaks a clip's
narration, and your own recording placed on a clip exactly as it is. Voice services are replaced by stand-ins."""
import asyncio
import base64
import json

import httpx
import pytest

from video_generator import media
from video_generator.estimate import speech_need
from video_generator.models import ContextType
from video_generator.plugins.base import VoiceSpec
from video_generator.plugins.voice.instructed_voices import GeminiVoice, OpenAIVoice, instruction
from video_generator.project import ProjectStore
from video_generator.runner import Engine
from video_generator.scene3d import film
from video_generator.tree import find, leaves

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors
from .test_language_mix import two_speakers

SPEC = VoiceSpec(language="hi", accent="Indian English", gender="male", age="older", pace="slow", emotion="devotional")


def test_the_accent_and_manner_are_asked_for_in_words():
    text = instruction(SPEC)
    assert text.startswith("Speak with an Indian English accent, in Hindi") and "an older male voice" in text and "slowly" in text
    g = GeminiVoice().body("shri guru charan", SPEC)
    assert g["contents"][0]["parts"][0]["text"] == text + "\nshri guru charan"
    assert g["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert g["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Puck"      # a male voice
    o = OpenAIVoice().body("shri guru charan", SPEC, "")
    assert o["instructions"] == text and o["model"] == "gpt-4o-mini-tts" and o["voice"] in ("ballad", "onyx", "echo", "ash", "verse", "cedar")


@requires_ffmpeg
def test_google_voice_turns_its_sound_into_a_wav(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    pcm = (b"\x00\x10" * 24000)                                                    # one second of 24 kHz sound
    seen = {}

    async def post(self, url, params=None, json=None, **k):
        seen.update(url=url, body=json)
        data = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000",
                                                                       "data": base64.b64encode(pcm).decode()}}]}}]}
        return httpx.Response(200, json=data, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    out, _ = asyncio.run(GeminiVoice().synthesize("namaste", SPEC, tmp_path / "v.wav"))
    assert abs(media.probe_duration(out) - 1.0) < 0.1 and "gemini-2.5-flash-preview-tts:generateContent" in seen["url"]
    assert seen["body"]["contents"][0]["parts"][0]["text"].endswith("namaste")


def test_voice_made_by_your_choice(svc, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    svc.reload()
    svc.config.preferred_models = {"voice": "gemini_tts"}
    assert svc.reg.choose("voice").id == "gemini_tts"
    svc.config.preferred_models = {"voice": "openai_tts"}
    assert svc.reg.choose("voice").id == "openai_tts"


def test_a_clips_narration_can_be_spoken_by_any_character(svc, monkeypatch):
    v = Vendors(svc, monkeypatch)
    p, _ = two_speakers(svc)
    ravi = next(c for c in p.context if c.title == "Ravi")
    node = leaves(p)[0]
    node.script.dialogue = []
    node.script.narration, node.script.narration_by = "Once upon a time", ravi.id
    svc.save(p)
    asyncio.run(Engine(svc)._make_voice(p.id, node.id))
    call = v.calls["voice"][-1]
    assert call["text"] == "Once upon a time" and call["spec"].gender == "male" and call["spec"].accent == "Indian English"
    assert not any(c.title == "Narrator" for c in svc.load(p.id).context)            # no Narrator card was needed
    assert film._lines(svc.load(p.id), find(svc.load(p.id), node.id))[0][0] == ravi.id


@requires_ffmpeg
def test_your_own_recording_is_placed_exactly_as_it_is(svc, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    v = Vendors(svc, monkeypatch)
    monkeypatch.setattr(appmod, "svc", svc)
    p, _ = two_speakers(svc)
    node = leaves(p)[0]
    node.script.dialogue = []
    node.script.narration = "shri guru charan saroj raj"
    svc.save(p)
    rec = tmp_path / "me.m4a"
    media.ff("-f", "lavfi", "-i", "sine=frequency=330:duration=3", str(rec))
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/nodes/{node.id}/narration-recording", files={"file": ("me.m4a", rec.read_bytes(), "audio/mp4")})
        assert r.status_code == 200
    s = find(svc.load(p.id), node.id).script
    assert s.narration_audio.startswith("clips/") and abs(s.narration_seconds - 3.0) < 0.2
    assert abs(speech_need(svc.load(p.id), find(svc.load(p.id), node.id)) - (3.0 + 2 * 0.5)) < 0.3    # the clip follows the recording
    asyncio.run(Engine(svc)._make_voice(p.id, node.id))
    assert v.calls["voice"] == []                                                   # no voice service was used
    n = find(svc.load(p.id), node.id)
    assert n.voice_audio and abs(n.voice_seconds - 4.0) < 0.4                       # your 3 s, with the quiet at both ends
    saved = json.loads((ProjectStore.path_for(p.id) / "clips" / node.id / "voice_lines.json").read_text())
    assert saved["lines"][0]["recorded"] and saved["lines"][0]["text"] == "shri guru charan saroj raj"
    asyncio.run(Engine(svc)._make_voice(p.id, node.id))
    assert v.calls["voice"] == []                                                   # not made again
    q = svc.load(p.id)
    find(q, node.id).voice_audio = None                                             # the 3D film also uses your recording
    svc.save(q)
    voice, note = asyncio.run(film.clip_voice(svc, p.id, find(svc.load(p.id), node.id), "free"))
    assert voice.exists() and note == "your own recording"
    with TestClient(appmod.app) as client:
        assert client.delete(f"/api/projects/{p.id}/nodes/{node.id}/narration-recording").status_code == 200
    s = find(svc.load(p.id), node.id).script
    assert s.narration_audio == "" and s.narration_seconds is None


def test_an_empty_or_unreadable_recording_is_refused(svc, monkeypatch):
    p, _ = two_speakers(svc)
    node = leaves(p)[0]
    with pytest.raises(ValueError, match="empty"):
        svc.set_narration_recording(p.id, node.id, b"", "x.webm")
    with pytest.raises(ValueError, match="could not be read"):
        svc.set_narration_recording(p.id, node.id, b"not audio at all", "x.webm")
