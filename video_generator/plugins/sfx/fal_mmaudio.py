"""Natural sound that fits a finished clip, made by fal.ai's MMAudio (video + text in, sound out)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from ..base import PluginError, SoundEffect, Usage
from .. import fal_common as fal
from ... import media


class FalMMAudio(SoundEffect):
    name = "fal_mmaudio"
    env_keys = ["FAL_KEY"]
    description = "Sound made to fit your clip (fal.ai MMAudio, about $0.001 per second)"

    async def generate(self, prompt, seconds, out, model: str = "", video: Optional[Path] = None, params: Optional[dict] = None):
        if not video:
            raise PluginError("MMAudio needs the finished clip to listen to")
        tmp = Path(tempfile.mkdtemp())
        small = media.silent_proxy(video, tmp / "proxy.mp4", height=360)       # small and without sound: quick to upload
        prm = params or {}
        payload = {"video_url": fal.file_input(small), "prompt": prompt[:400]}
        if prm.get("send_duration", True):
            payload["duration"] = round(max(min(seconds, float(prm.get("max_seconds", 30))), 1.0), 1)
        if prm.get("negative_prompt"):
            payload["negative_prompt"] = prm["negative_prompt"]
        result = await fal.run(model or "fal-ai/mmaudio-v2", payload)
        got = await fal.save(result, tmp / "out.mp4", "video", "audio")
        if not media.has_audio(got):
            raise PluginError("fal returned a file without sound")
        media.ff("-i", str(got), "-vn", "-ac", "2", "-ar", "44100", str(out))
        return out, Usage(seconds=seconds, raw={"model": model})
