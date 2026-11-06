"""Google Gemini brain plugin (REST generateContent). Can watch short videos."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Optional, Type

import httpx
from pydantic import BaseModel

from ..base import LLM, PluginError, Usage, b64, raise_for
from .common import MAX_IMAGES, repair_prompt, schema_instruction, validate

API = "https://generativelanguage.googleapis.com/v1beta"


def media_parts(video: Optional[Path], images: Optional[list[Path]], keep_images: int = 0) -> list[dict]:
    """The pictures and video sent with a request. A short video is sent INSTEAD of the sampled frames (it already holds them); but the last
    `keep_images` pictures are evidence that is not in the video (for example the last picture of the clip BEFORE this one), so they are always sent."""
    def image(p) -> dict:
        return {"inline_data": {"mime_type": mimetypes.guess_type(str(p))[0] or "image/jpeg", "data": b64(p)}}
    if video and Path(video).exists() and Path(video).stat().st_size < 18_000_000:
        extra = list(images or [])[-keep_images:] if keep_images > 0 else []
        return [{"inline_data": {"mime_type": "video/mp4", "data": b64(video)}}] + [image(p) for p in extra]
    return [image(p) for p in (images or [])[:MAX_IMAGES]]


class GeminiLLM(LLM):
    name = "gemini"
    env_keys = ["GEMINI_API_KEY"]
    description = "Gemini via the Google Gemini API (can watch whole clips)"
    licence = "commercial"

    async def generate_json(self, *, system: str, user: str, schema: Type[BaseModel], model: str,
                            images: Optional[list[Path]] = None, video: Optional[Path] = None,
                            max_tokens: int = 16000, meta: Optional[dict] = None):
        model = model or "gemini-2.5-pro"
        parts = media_parts(video, images, int((meta or {}).get("keep_images", 0) or 0))
        parts.append({"text": user + schema_instruction(schema)})
        contents = [{"role": "user", "parts": parts}]
        usage = Usage()
        last_error = ""
        async with httpx.AsyncClient(timeout=600) as client:
            for _ in range(2):
                body = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents,
                        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens}}
                r = await client.post(f"{API}/models/{model}:generateContent",
                                      headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")}, json=body)
                raise_for(r, "Gemini")
                data = r.json()
                meta_u = data.get("usageMetadata", {})
                usage.input_tokens += meta_u.get("promptTokenCount", 0)
                usage.output_tokens += meta_u.get("candidatesTokenCount", 0)
                try:
                    text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
                except (KeyError, IndexError):
                    raise PluginError(f"Gemini returned no answer: {str(data)[:300]}")
                try:
                    return validate(schema, text), usage
                except PluginError as exc:
                    last_error = str(exc)
                    contents = contents + [{"role": "model", "parts": [{"text": text}]},
                                           {"role": "user", "parts": [{"text": repair_prompt(last_error)}]}]
        raise PluginError(last_error or "Gemini returned an unusable answer")
