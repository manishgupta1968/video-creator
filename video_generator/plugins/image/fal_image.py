"""Images through fal.ai (e.g. Flux 2 with reference images)."""
from __future__ import annotations

from ..base import ImageGenerator, ImageRequest, Usage
from .. import fal_common as fal

SIZES = {"16:9": "landscape_16_9", "9:16": "portrait_16_9", "1:1": "square_hd", "4:3": "landscape_4_3", "3:4": "portrait_4_3"}


def size_for(aspect: str) -> str:
    if aspect in SIZES:
        return SIZES[aspect]
    try:
        a, b = (float(x) for x in aspect.split(":"))
        r = a / b
    except (ValueError, ZeroDivisionError):
        return "landscape_16_9"
    return "landscape_16_9" if r >= 1.5 else "landscape_4_3" if r >= 1.2 else "portrait_16_9" if r <= 0.65 else "portrait_4_3" if r <= 0.83 else "square_hd"


class FalImage(ImageGenerator):
    name = "fal_image"
    env_keys = ["FAL_KEY"]
    description = "Image models through fal.ai"

    async def generate(self, req: ImageRequest):
        payload = {"prompt": req.prompt, "image_size": size_for(req.aspect),
                   "negative_prompt": req.negative, "num_images": 1}
        if req.references:
            payload["image_urls"] = [fal.file_input(p) for p in req.references[:4]]
        model = req.model if req.references else req.model.replace("/edit", "")
        result = await fal.run(model, payload)
        await fal.save(result, req.out, "images", "image")
        return req.out, Usage()
