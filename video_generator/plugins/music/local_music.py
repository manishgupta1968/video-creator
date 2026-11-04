"""Free music: your own file (context item with role 'sound'/'music') or an ambient pad."""
from __future__ import annotations

import shutil

from ..base import MusicGenerator, Usage
from ... import media


class LocalMusic(MusicGenerator):
    name = "local_music"
    env_keys: list[str] = []
    description = "Your music file, or a free ambient pad"

    async def generate(self, prompt, seconds, out, model: str = "", reference=None):
        if reference and reference.exists():
            shutil.copy(reference, out.with_suffix(reference.suffix))
            media.ff("-i", str(out.with_suffix(reference.suffix)), "-t", f"{seconds:.2f}", str(out))
        else:
            media.ambient_pad(out, seconds, prompt.lower())
        return out, Usage(seconds=seconds)
