"""Voices that follow a spoken instruction: the accent, age, pitch, pace and mood are ASKED FOR, not only matched.

  gemini_tts   Google's Gemini text-to-speech (GEMINI_API_KEY): generateContent with responseModalities AUDIO and a
               prebuilt voice; the text is preceded by an instruction such as "Say in a warm Indian English accent,
               slowly:". It returns 24 kHz 16-bit PCM, turned into a wav file. Speaks Hindi and many other languages.
  openai_tts   OpenAI's text-to-speech (OPENAI_API_KEY): /v1/audio/speech with `instructions` (gpt-4o-mini-tts).

Neither copies a voice from a sample: for your own (or someone else's, with permission) voice, use ElevenLabs or
Cartesia. Claude Code and Codex cannot make sound.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import httpx

from ... import media
from ..base import PluginError, Usage, VoiceChoice, VoiceSpec, VoiceSynth, raise_for

LANGUAGE_WORDS = {"hi": "Hindi", "en": "English", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "mr": "Marathi",
                  "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "ur": "Urdu", "sa": "Sanskrit",
                  "es": "Spanish", "fr": "French", "de": "German", "ja": "Japanese", "zh": "Chinese", "ar": "Arabic"}


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def instruction(spec: VoiceSpec) -> str:
    """How the line must sound, in words: accent, language, age, gender, pitch, pace, mood and the voice's character."""
    bits = []
    if spec.accent:
        bits.append(f"with {_a(spec.accent)} accent")
    lang = (spec.language or "").split("-")[0].lower()
    if lang and lang != "en":
        bits.append(f"in {LANGUAGE_WORDS.get(lang, lang)}, pronounced naturally as a native speaker would")
    who = " ".join(x for x in (spec.age if spec.age not in ("", "adult") else "", spec.gender if spec.gender != "neutral" else "") if x)
    if who:
        bits.append(f"as {_a(who)} voice")
    if spec.pitch and spec.pitch != "medium":
        bits.append(f"with {_a(spec.pitch)} pitch")
    if spec.pace and spec.pace != "normal":
        bits.append("slowly" if spec.pace == "slow" else "briskly")
    if spec.emotion:
        bits.append(f"sounding {spec.emotion}")
    if spec.description:
        bits.append(f"({spec.description})")
    return ("Speak " + ", ".join(bits) + ".") if bits else ""


# prebuilt Gemini voices, with the gender they sound (used to pick one for a profile)
GEMINI_VOICES = {"Kore": "female", "Aoede": "female", "Leda": "female", "Zephyr": "female", "Autonoe": "female",
                 "Callirrhoe": "female", "Despina": "female", "Erinome": "female", "Laomedeia": "female",
                 "Pulcherrima": "female", "Vindemiatrix": "female", "Sulafat": "female", "Achernar": "female",
                 "Gacrux": "female", "Puck": "male", "Charon": "male", "Fenrir": "male", "Orus": "male",
                 "Enceladus": "male", "Iapetus": "male", "Umbriel": "male", "Algieba": "male", "Algenib": "male",
                 "Rasalgethi": "male", "Alnilam": "male", "Schedar": "male", "Achird": "male", "Zubenelgenubi": "male",
                 "Sadachbia": "male", "Sadaltager": "male"}
OPENAI_VOICES = {"coral": "female", "nova": "female", "shimmer": "female", "sage": "female", "marin": "female",
                 "ballad": "male", "onyx": "male", "echo": "male", "ash": "male", "verse": "male", "cedar": "male",
                 "alloy": "neutral", "fable": "neutral"}


def _choices(table: dict, spec: VoiceSpec, taken: tuple, provider: str) -> list[VoiceChoice]:
    out = []
    for name, gender in table.items():
        score = 1.0 if not spec.gender or spec.gender == gender else 0.2 if gender == "neutral" else 0.0
        if name in taken:
            score -= 0.5
        out.append(VoiceChoice(name, name, provider, score=score, gender=gender,
                               note="the accent and manner are asked for in words with every line"))
    return sorted(out, key=lambda c: -c.score)


class GeminiVoice(VoiceSynth):
    name = "gemini_tts"
    env_keys = ["GEMINI_API_KEY"]
    description = "Google Gemini text-to-speech (accent and manner asked for in words)"
    licence = "commercial (Google terms)"

    async def candidates(self, spec: VoiceSpec, taken: tuple = ()) -> list[VoiceChoice]:
        return _choices(GEMINI_VOICES, spec, taken, self.name)

    def body(self, text: str, spec: VoiceSpec) -> dict:
        how = instruction(spec)
        voice = spec.voice_id if spec.voice_id in GEMINI_VOICES else next(
            (c.voice_id for c in _choices(GEMINI_VOICES, spec, (), self.name)), "Kore")
        return {"contents": [{"parts": [{"text": (how + "\n" if how else "") + text}]}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                                     "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}

    async def synthesize(self, text: str, voice: VoiceSpec, out: Path, model: str = ""):
        model = model or "gemini-2.5-flash-preview-tts"
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  params={"key": self.key()}, json=self.body(text, voice))
            raise_for(r, "Google Gemini voice")
        try:
            part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            pcm = base64.b64decode(part["data"])
        except (KeyError, IndexError, ValueError) as exc:
            raise PluginError(f"Google Gemini voice gave no sound: {str(r.text)[:300]}") from exc
        rate = 24000
        mime = part.get("mimeType", "")
        if "rate=" in mime:
            try:
                rate = int(mime.split("rate=")[1].split(";")[0])
            except ValueError:
                pass
        raw = out.with_suffix(".pcm")
        raw.write_bytes(pcm)
        media.ff("-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", str(raw), "-ar", "44100", "-ac", "1", str(out))
        raw.unlink(missing_ok=True)
        return out, Usage(raw={"chars": len(text)})


class OpenAIVoice(VoiceSynth):
    name = "openai_tts"
    env_keys = ["OPENAI_API_KEY"]
    description = "OpenAI text-to-speech (accent and manner asked for in words)"
    licence = "commercial (OpenAI terms)"

    async def candidates(self, spec: VoiceSpec, taken: tuple = ()) -> list[VoiceChoice]:
        return _choices(OPENAI_VOICES, spec, taken, self.name)

    def body(self, text: str, spec: VoiceSpec, model: str) -> dict:
        voice = spec.voice_id if spec.voice_id in OPENAI_VOICES else next(
            (c.voice_id for c in _choices(OPENAI_VOICES, spec, (), self.name)), "coral")
        body = {"model": model or "gpt-4o-mini-tts", "voice": voice, "input": text, "response_format": "wav"}
        how = instruction(spec)
        if how:
            body["instructions"] = how
        return body

    async def synthesize(self, text: str, voice: VoiceSpec, out: Path, model: str = ""):
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post("https://api.openai.com/v1/audio/speech",
                                  headers={"Authorization": f"Bearer {self.key()}"}, json=self.body(text, voice, model))
            raise_for(r, "OpenAI voice")
        raw = out.with_suffix(".src.wav")
        raw.write_bytes(r.content)
        media.ff("-i", str(raw), "-ar", "44100", "-ac", "1", str(out))
        raw.unlink(missing_ok=True)
        return out, Usage(raw={"chars": len(text)})
