"""Cartesia Sonic voices: speech and instant cloning."""
from __future__ import annotations

import os

import httpx

from ..base import PluginError, Usage, VoiceSpec, VoiceSynth, raise_for

API = "https://api.cartesia.ai"
VERSION = os.environ.get("CARTESIA_VERSION", "2025-04-16")


class CartesiaVoice(VoiceSynth):
    name = "cartesia"
    env_keys = ["CARTESIA_API_KEY"]
    description = "Cartesia Sonic voices and cloning"
    can_clone = True

    def _h(self) -> dict:
        return {"X-API-Key": os.environ.get("CARTESIA_API_KEY", ""), "Cartesia-Version": VERSION}

    async def synthesize(self, text: str, voice: VoiceSpec, out, model: str = ""):
        vid = voice.voice_id or await self.match(voice.description)
        if not vid:
            raise PluginError("Cartesia: no voice selected")
        body = {"model_id": model or "sonic-3", "transcript": text, "voice": {"mode": "id", "id": vid},
                "language": voice.language or "en",
                "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100}}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{API}/tts/bytes", headers=self._h(), json=body)
            raise_for(r, "Cartesia")
        out.write_bytes(r.content)
        return out, Usage(raw={"chars": len(text)})

    async def clone(self, sample, name: str) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            with open(sample, "rb") as f:
                r = await client.post(f"{API}/voices/clone", headers=self._h(), data={"name": name[:60], "language": "en"},
                                      files={"clip": (sample.name, f, "audio/wav")})
            raise_for(r, "Cartesia clone")
        return r.json()["id"]

    async def match(self, description: str, language: str = "en"):
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{API}/voices", headers=self._h())
            if r.status_code >= 400:
                return None
            data = r.json()
        voices = data.get("data", data) if isinstance(data, dict) else data
        words = set((description or "").lower().split())
        best, score = None, -1
        for v in voices or []:
            text = f"{v.get('name', '')} {v.get('description', '')}".lower()
            s = sum(1 for w in words if w in text)
            if s > score:
                best, score = v.get("id"), s
        return best
