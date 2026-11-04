"""Video through fal.ai — Kling, Seedance, Wan, and any other fal video model.
The catalogue row's `model` is the fal endpoint id."""
from __future__ import annotations

from ..base import Usage, VideoGenerator, VideoRequest
from .. import fal_common as fal


def snap_duration(seconds: float, allowed) -> str:
    if allowed:
        best = min(allowed, key=lambda a: abs(float(a) - seconds) if float(a) >= seconds - 0.5 else 999 + float(a))
        return str(best)
    return str(int(round(max(seconds, 1))))


class FalVideo(VideoGenerator):
    name = "fal"
    env_keys = ["FAL_KEY"]
    description = "Many video models through one fal.ai key"

    async def generate(self, req: VideoRequest):
        allowed = None
        payload = {
            "prompt": req.prompt + (f" Camera: {req.camera}." if req.camera else ""),
            "image_url": fal.file_input(req.start_frame),
            "end_image_url": fal.file_input(req.end_frame),
            "tail_image_url": fal.file_input(req.end_frame),
            "negative_prompt": req.negative,
            "duration": snap_duration(req.seconds, allowed),
            "aspect_ratio": req.aspect,
            "resolution": req.resolution,
            "generate_audio": req.audio,
        }
        if req.references and not req.start_frame:
            payload["image_urls"] = [fal.file_input(p) for p in req.references[:4]]
        result = await fal.run(req.model, payload)
        await fal.save(result, req.out, "video", "videos", "output")
        return req.out, Usage(seconds=req.seconds, raw={"model": req.model})
