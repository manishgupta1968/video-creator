"""Video through fal.ai — Kling, Seedance, Wan, and any other fal video model.
The catalogue row's `model` is the fal endpoint id; its `params` say how that model's API is spelled:

  image_field             name of the start-picture field (default image_url; Kling 3 uses start_image_url)
  end_image_field         name of the end-picture field (omit when the model has none)
  reference_images_field  name of the LIST of reference pictures (reference-to-video models, e.g. image_urls)
  reference_video_field   name of the LIST of reference videos (e.g. video_urls)
  tag_format              how the prompt names a reference: "@{kind}{n}" -> @Image1, @Video1 (the default)
  durations               lengths the model accepts, in seconds (a 4 s clip is asked for as the next one up)
  resolution              a fixed resolution to ask for, e.g. 720p
  fields                  the only fields to send (a safe list); leave out to send the usual set
"""
from __future__ import annotations

from ..base import Usage, VideoGenerator, VideoRequest
from .. import fal_common as fal

USUAL = ["prompt", "image_field", "end_image_field", "negative_prompt", "duration", "aspect_ratio", "resolution", "generate_audio"]
DEFAULT_TAG = "@{kind}{n}"       # fal's reference-to-video models name inputs @Image1, @Video1 in the prompt


def snap_duration(seconds: float, allowed) -> str:
    """The length to ask for: the next allowed length at or above `seconds` (the clip is cut back afterwards)."""
    if allowed:
        lengths = sorted(float(a) for a in allowed)
        best = next((a for a in lengths if a >= seconds - 1e-6), lengths[-1])
        return str(int(best)) if float(best).is_integer() else str(best)
    return str(int(round(max(seconds, 1))))


def tag(kind: str, n: int, fmt: str = DEFAULT_TAG) -> str:
    return fmt.format(kind=kind, n=n)


def reference_guide(req: VideoRequest) -> str:
    """The sentences that tell a reference-to-video model what each reference is for. Empty when nothing is sent.
    The reference video only gives the camera and the movement: its plain blocks must never be copied as the look."""
    prm = req.params or {}
    fmt = prm.get("tag_format") or DEFAULT_TAG
    parts: list[str] = []
    if req.reference_video and prm.get("reference_video_field"):
        parts.append(f"{tag('Video', 1, fmt)} is the camera and movement reference: follow its camera path, framing, timing "
                     f"and where each figure moves, exactly. Do not copy its look: its plain coloured shapes only stand for "
                     f"the people, animals and things described here and shown in the pictures.")
    if req.references and prm.get("reference_images_field"):
        for i, _ in enumerate(req.references, 1):
            label = req.reference_labels[i - 1] if i - 1 < len(req.reference_labels) and req.reference_labels[i - 1] else "a reference picture"
            parts.append(f"{tag('Image', i, fmt)} is {label}.")
    return " ".join(parts)


def build_payload(req: VideoRequest) -> dict:
    """The JSON for this model. Only fields the model is known to have are sent; empty ones are dropped."""
    prm = req.params or {}
    image_field = prm.get("image_field", "image_url")
    end_field = prm.get("end_image_field")
    guide = reference_guide(req)
    values = {
        "prompt": (guide + " " if guide else "") + req.prompt + (f" Camera: {req.camera}." if req.camera else ""),
        "image_field": fal.file_input(req.start_frame),
        "end_image_field": fal.file_input(req.end_frame) if end_field else None,
        "reference_images_field": [fal.file_input(p) for p in req.references] if prm.get("reference_images_field") else None,
        "reference_video_field": ([fal.file_input(req.reference_video)]
                                  if req.reference_video and prm.get("reference_video_field") else None),
        "negative_prompt": req.negative,
        "duration": snap_duration(req.seconds, prm.get("durations")),
        "aspect_ratio": req.aspect,
        "resolution": prm.get("resolution") or req.resolution,
        "generate_audio": req.audio,
    }
    wanted = prm.get("fields") or USUAL
    names = {"image_field": image_field, "end_image_field": end_field or "end_image_url",
             "reference_images_field": prm.get("reference_images_field") or "image_urls",
             "reference_video_field": prm.get("reference_video_field") or "video_urls"}
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
