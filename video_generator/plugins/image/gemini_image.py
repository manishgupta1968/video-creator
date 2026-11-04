"""Google Nano Banana (Gemini image models) with up to several reference images."""
from __future__ import annotations

import base64
import mimetypes
import os

import httpx

from ..base import ImageGenerator, ImageRequest, PluginError, Usage, b64, raise_for

API = "https://generativelanguage.googleapis.com/v1beta"


class GeminiImage(ImageGenerator):
    name = "nano_banana"
    env_keys = ["GEMINI_API_KEY"]
    description = "Google Nano Banana image models"

    async def generate(self, req: ImageRequest):
        parts: list[dict] = []
        for p in req.references[:5]:
            parts.append({"inline_data": {"mime_type": mimetypes.guess_type(str(p))[0] or "image/jpeg", "data": b64(p)}})
        text = req.prompt + f"\nAspect ratio {req.aspect}. Photoreal." + (f" Avoid: {req.negative}" if req.negative else "")
        if req.references:
            text += " Keep the exact identity, face and clothing of the people/objects in the reference images."
        parts.append({"text": text})
        body = {"contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": req.aspect}}}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{API}/models/{req.model}:generateContent",
                                  headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")}, json=body)
            raise_for(r, "Nano Banana")
            data = r.json()
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inline_data") or part.get("inlineData")
                if inline and inline.get("data"):
                    req.out.write_bytes(base64.b64decode(inline["data"]))
                    return req.out, Usage()
        raise PluginError(f"Nano Banana returned no image: {str(data)[:300]}")
