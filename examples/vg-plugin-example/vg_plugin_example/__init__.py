"""Example plugin: a free local 'video model' that turns the keyframe into a
pencil-sketch style clip with a slow pan. Shows every piece a real plugin needs."""
from __future__ import annotations

from PIL import Image, ImageFilter, ImageOps

from video_generator import media
from video_generator.plugins.base import Usage, VideoGenerator, VideoRequest


class SketchVideo(VideoGenerator):
    name = "sketch_video"            # referenced by catalog.yaml rows (plugin: sketch_video)
    env_keys: list[str] = []         # API keys it needs, e.g. ["MYVENDOR_API_KEY"]
    description = "Example plugin: pencil-sketch clip from the keyframe (free)"
    licence = "MIT"

    async def generate(self, req: VideoRequest):
        size = media.frame_size(req.aspect, "720p")
        src = req.start_frame
        sketch = req.out.with_suffix(".sketch.png")
        if src:
            img = Image.open(src).convert("L").filter(ImageFilter.CONTOUR)
            ImageOps.autocontrast(img).convert("RGB").save(sketch)
        else:
            media.placeholder_image(req.prompt[:200], sketch, size)
        media.still_to_clip(sketch, req.out, req.seconds, size, 24, zoom=True)
        return req.out, Usage(seconds=req.seconds)
