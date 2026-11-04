"""OpenAI GPT Image (generate, or edit with reference images)."""
from __future__ import annotations

import base64

from ..base import ImageGenerator, ImageRequest, PluginError, Usage

SIZES = {"16:9": "1536x1024", "9:16": "1024x1536", "1:1": "1024x1024"}


class OpenAIImage(ImageGenerator):
    name = "gpt_image"
    env_keys = ["OPENAI_API_KEY"]
    description = "OpenAI GPT Image"

    async def generate(self, req: ImageRequest):
        import openai
        client = openai.AsyncOpenAI()
        size = SIZES.get(req.aspect, "1536x1024")
        prompt = req.prompt + (f"\nAvoid: {req.negative}" if req.negative else "")
        try:
            if req.references:
                files = [open(p, "rb") for p in req.references[:4]]
                try:
                    resp = await client.images.edit(model=req.model or "gpt-image-1", image=files, prompt=prompt, size=size)
                finally:
                    for f in files:
                        f.close()
            else:
                resp = await client.images.generate(model=req.model or "gpt-image-1", prompt=prompt, size=size)
        except openai.APIStatusError as exc:
            raise PluginError(f"OpenAI image error {exc.status_code}: {str(exc)[:200]}") from exc
        data = resp.data[0]
        if getattr(data, "b64_json", None):
            req.out.write_bytes(base64.b64decode(data.b64_json))
        elif getattr(data, "url", None):
            from ..base import download
            await download(data.url, req.out)
        else:
            raise PluginError("OpenAI returned no image")
        return req.out, Usage()
