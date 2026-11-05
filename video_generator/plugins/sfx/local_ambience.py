"""Free natural sound made with ffmpeg noise filters (wind, rain, room tone, crowd ...). The safety net."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..base import SoundEffect, Usage
from ... import media


class LocalAmbience(SoundEffect):
    name = "local_ambience"
    env_keys: list[str] = []
    description = "Free simple natural sound (wind, rain, room tone ...)"

    async def generate(self, prompt, seconds, out, model: str = "", video: Optional[Path] = None, params: Optional[dict] = None):
        media.local_ambience(out, seconds, prompt)
        return out, Usage(seconds=seconds)
