"""Background music via fal.ai (e.g. MiniMax Music)."""
from __future__ import annotations

from ..base import MusicGenerator, Usage
from .. import fal_common as fal


class FalMusic(MusicGenerator):
    name = "fal_music"
    env_keys = ["FAL_KEY"]
    description = "Music models through fal.ai"

    async def generate(self, prompt, seconds, out, model: str = "", reference=None):
        payload = {"prompt": f"{prompt}. Instrumental background music, about {int(seconds)} seconds.",
                   "reference_audio_url": fal.file_input(reference) if reference else None}
        result = await fal.run(model, payload)
        await fal.save(result, out, "audio", "audio_file", "output")
        return out, Usage(seconds=seconds)
