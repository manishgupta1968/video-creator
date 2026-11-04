"""Lip-sync a clip to our voice track via fal.ai (Sync Labs lipsync-2-pro)."""
from __future__ import annotations

from ..base import LipSync, Usage
from .. import fal_common as fal
from ... import media


class FalLipSync(LipSync):
    name = "fal_lipsync"
    env_keys = ["FAL_KEY"]
    description = "Sync lip-sync through fal.ai"

    async def sync(self, video, audio, out, model: str = ""):
        result = await fal.run(model or "fal-ai/sync-lipsync/v2/pro",
                               {"video_url": fal.file_input(video), "audio_url": fal.file_input(audio),
                                "sync_mode": "cut_off"})
        await fal.save(result, out, "video", "output")
        return out, Usage(seconds=media.probe_duration(out))
