"""ElevenLabs Music API (licensed training data)."""
from __future__ import annotations

import os

import httpx

from ..base import MusicGenerator, Usage, raise_for


class ElevenLabsMusic(MusicGenerator):
    name = "elevenlabs_music"
    env_keys = ["ELEVENLABS_API_KEY"]
    description = "ElevenLabs Music"

    async def generate(self, prompt, seconds, out, model: str = "", reference=None):
        body = {"prompt": f"{prompt}. Instrumental background score, no vocals.",
                "music_length_ms": int(max(min(seconds, 300), 10) * 1000)}
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post("https://api.elevenlabs.io/v1/music",
                                  headers={"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", "")}, json=body)
            raise_for(r, "ElevenLabs Music")
            out.write_bytes(r.content)
        return out, Usage(seconds=seconds)
