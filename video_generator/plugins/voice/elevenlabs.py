"""ElevenLabs voices: speech, instant voice cloning, stock-voice matching."""
from __future__ import annotations

import os

import httpx

from ..base import PluginError, Usage, VoiceSpec, VoiceSynth, raise_for
from ... import media

API = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"   # "Rachel" stock voice


class ElevenLabsVoice(VoiceSynth):
    name = "elevenlabs"
    env_keys = ["ELEVENLABS_API_KEY"]
    description = "ElevenLabs voices and cloning"
    can_clone = True
    _voices: list[dict] | None = None

    def _h(self) -> dict:
        return {"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", "")}

    async def synthesize(self, text: str, voice: VoiceSpec, out, model: str = ""):
        vid = voice.voice_id or await self.match(voice.description) or DEFAULT_VOICE
        body = {"text": text, "model_id": model or "eleven_v3"}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{API}/text-to-speech/{vid}", params={"output_format": "mp3_44100_128"},
                                  headers=self._h(), json=body)
            if r.status_code == 400 and "model" in r.text.lower():
                body["model_id"] = "eleven_multilingual_v2"
                r = await client.post(f"{API}/text-to-speech/{vid}", params={"output_format": "mp3_44100_128"},
                                      headers=self._h(), json=body)
            raise_for(r, "ElevenLabs")
        mp3 = out.with_suffix(".mp3")
        mp3.write_bytes(r.content)
        media.ff("-i", str(mp3), "-ar", "44100", "-ac", "1", str(out))
        mp3.unlink(missing_ok=True)
        return out, Usage(raw={"chars": len(text)})

    async def clone(self, sample, name: str) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            with open(sample, "rb") as f:
                r = await client.post(f"{API}/voices/add", headers=self._h(), data={"name": name[:60]},
                                      files={"files": (sample.name, f, "audio/mpeg")})
            raise_for(r, "ElevenLabs clone")
            vid = r.json().get("voice_id")
        if not vid:
            raise PluginError("ElevenLabs returned no voice id")
        return vid

    async def list_voices(self) -> list[dict]:
        if self._voices is None:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(f"{API}/voices", headers=self._h())
                raise_for(r, "ElevenLabs voices")
                self._voices = r.json().get("voices", [])
        return self._voices

    async def match(self, description: str, language: str = "en"):
        if not description:
            return None
        try:
            voices = await self.list_voices()
        except PluginError:
            return None
        words = set(description.lower().replace(",", " ").split())
        best, best_score = None, -1
        for v in voices:
            labels = " ".join(str(x) for x in (v.get("labels") or {}).values()).lower() + " " + (v.get("description") or "").lower()
            score = sum(1 for w in words if w in labels)
            if score > best_score:
                best, best_score = v.get("voice_id"), score
        return best
