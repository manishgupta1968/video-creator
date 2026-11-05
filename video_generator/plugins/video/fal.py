"""Video through fal.ai — Kling, Seedance, Wan, and any other fal video model.
The catalogue row's `model` is the fal endpoint id; its `params` say how that model's API is spelled:

  image_field      name of the start-picture field (default image_url; Kling 3 uses start_image_url)
  end_image_field  name of the end-picture field (omit when the model has none)
  durations        lengths the model accepts, in seconds (a 4 s clip is asked for as the next one up)
  resolution       a fixed resolution to ask for, e.g. 720p
  fields           the only fields to send (a safe list); leave out to send the usual set
"""
from __future__ import annotations

from ..base import Usage, VideoGenerator, VideoRequest
from .. import fal_common as fal

USUAL = ["prompt", "image_field", "end_image_field", "negative_prompt", "duration", "aspect_ratio", "resolution", "generate_audio"]


def snap_duration(seconds: float, allowed) -> str:
    """The length to ask for: the next allowed length at or above `seconds` (the clip is cut back afterwards)."""
    if allowed:
        lengths = sorted(float(a) for a in allowed)
        best = next((a for a in lengths if a >= seconds - 1e-6), lengths[-1])
        return str(int(best)) if float(best).is_integer() else str(best)
    return str(int(round(max(seconds, 1))))


def build_payload(req: VideoRequest) -> dict:
    """The JSON for this model. Only fields the model is known to have are sent; empty ones are dropped."""
    prm = req.params or {}
    image_field = prm.get("image_field", "image_url")
    end_field = prm.get("end_image_field")
    values = {
        "prompt": req.prompt + (f" Camera: {req.camera}." if req.camera else ""),
        "image_field": fal.file_input(req.start_frame),
        "end_image_field": fal.file_input(req.end_frame) if end_field else None,
        "negative_prompt": req.negative,
        "duration": snap_duration(req.seconds, prm.get("durations")),
        "aspect_ratio": req.aspect,
        "resolution": prm.get("resolution") or req.resolution,
        "generate_audio": req.audio,
    }
    wanted = prm.get("fields") or USUAL
    names = {"image_field": image_field, "end_image_field": end_field or "end_image_url"}
    payload = {names.get(k, k): values[k] for k in wanted if k in values}
    return {k: v for k, v in payload.items() if v not in (None, "", [])}


class FalVideo(VideoGenerator):
    name = "fal"
    env_keys = ["FAL_KEY"]
    description = "Many video models through one fal.ai key"

    async def generate(self, req: VideoRequest):
        result = await fal.run(req.model, build_payload(req))
        await fal.save(result, req.out, "video", "videos", "output")
        return req.out, Usage(seconds=req.seconds, raw={"model": req.model})
