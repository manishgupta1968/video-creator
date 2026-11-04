"""Talking-presenter video from a photo + audio via fal.ai (VEED Fabric, Kling Avatar)."""
from __future__ import annotations

from ..base import AvatarGenerator, AvatarRequest, PluginError, Usage
from .. import fal_common as fal
from ... import media


class FalAvatar(AvatarGenerator):
    name = "fal_avatar"
    env_keys = ["FAL_KEY"]
    description = "Photo + voice → talking presenter (fal.ai)"

    async def generate(self, req: AvatarRequest):
        if not req.photo:
            raise PluginError("a presenter photo (or generated reference sheet) is needed")
        payload = {"image_url": fal.file_input(req.photo), "audio_url": fal.file_input(req.audio),
                   "prompt": req.prompt, "resolution": "720p"}
        result = await fal.run(req.model, payload)
        await fal.save(result, req.out, "video", "output")
        return req.out, Usage(seconds=media.probe_duration(req.audio))
