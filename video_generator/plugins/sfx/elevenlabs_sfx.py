"""Natural sound from a text description (ElevenLabs sound effects)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from ..base import PluginError, SoundEffect, Usage, raise_for
from ... import media

API = "https://api.elevenlabs.io/v1"


class ElevenLabsSfx(SoundEffect):
    name = "elevenlabs_sfx"
    env_keys = ["ELEVENLABS_API_KEY"]
    description = "Sound effects and ambience from a text description (ElevenLabs)"

    async def generate(self, prompt, seconds, out, model: str = "", video: Optional[Path] = None, params: Optional[dict] = None):
        body = {"text": prompt[:400], "duration_seconds": round(min(max(seconds, 0.5), 22.0), 1), "prompt_influence": 0.4}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{API}/sound-generation", params={"output_format": "mp3_44100_128"},
                                  headers={"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", "")}, json=body)
        raise_for(r, "ElevenLabs sound effects")
        mp3 = Path(tempfile.mkdtemp()) / "sfx.mp3"
        mp3.write_bytes(r.content)
        # the sound can be shorter than the clip: loop it to the length we need
        media.ff("-stream_loop", "-1", "-i", str(mp3), "-t", f"{seconds:.2f}", "-ac", "2", "-ar", "44100", str(out))
        return out, Usage(seconds=seconds)
