"""OpenAI GPT Image (generate, or edit with reference images).

Model names change often. If the name in the catalogue is not available to this key
("does not exist" / no access), we ask OpenAI which image models the key can really use,
pick the newest GPT Image model, and remember it for the rest of the run."""
from __future__ import annotations

import base64
import re

from ..base import ImageGenerator, ImageRequest, PluginError, Usage

SIZES = {"16:9": "1536x1024", "9:16": "1024x1536", "1:1": "1024x1024"}


def size_for(aspect: str) -> str:
    """The nearest size OpenAI makes for any aspect: landscape, portrait or square. The engine then crops to the exact shape."""
    if aspect in SIZES:
        return SIZES[aspect]
    try:
        a, b = (float(x) for x in aspect.split(":"))
        r = a / b
    except (ValueError, ZeroDivisionError):
        return "1536x1024"
    return "1536x1024" if r >= 1.2 else "1024x1536" if r <= 0.83 else "1024x1024"
DEFAULT_MODEL = "gpt-image-1"
_WORKS: dict[str, str] = {}          # the model we asked for -> the model that really works for this key

MISSING_WORDS = ("does not exist", "model_not_found", "not have access", "do not have access", "not found")
VERIFY_WORDS = ("must be verified", "verify organization", "verification")


def _text(exc) -> str:
    body = getattr(exc, "body", None)
    msg = ""
    if isinstance(body, dict):
        msg = str((body.get("error") or {}).get("message") or "")
    return (msg or str(exc)).lower()


def model_missing(exc) -> bool:
    return getattr(exc, "status_code", 0) in (400, 403, 404) and any(w in _text(exc) for w in MISSING_WORDS)


def needs_verification(exc) -> bool:
    return any(w in _text(exc) for w in VERIFY_WORDS)


def _rank(model_id: str):
    """Newest first: gpt-image-2 beats gpt-image-1.5 beats gpt-image-1; plain names beat dated copies and 'mini'."""
    base = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model_id)
    nums = tuple(int(n) for n in re.findall(r"\d+", base.replace("gpt-image", "")))
    return (not ("mini" in base), nums, base == model_id, -len(model_id))


def pick_image_model(ids: list[str], avoid: str = "") -> str:
    """The best GPT Image model in `ids` (never `avoid`), or ''."""
    good = [i for i in ids if i.startswith("gpt-image") and i != avoid]
    return max(good, key=_rank) if good else ""


class OpenAIImage(ImageGenerator):
    name = "gpt_image"
    env_keys = ["OPENAI_API_KEY"]
    description = "OpenAI GPT Image"

    async def _call(self, client, model: str, req: ImageRequest, prompt: str, size: str):
        if req.references:
            files = [open(p, "rb") for p in req.references[:4]]
            try:
                return await client.images.edit(model=model, image=files, prompt=prompt, size=size)
            finally:
                for f in files:
                    f.close()
        return await client.images.generate(model=model, prompt=prompt, size=size)

    async def generate(self, req: ImageRequest):
        import openai
        client = openai.AsyncOpenAI()
        size = size_for(req.aspect)
        prompt = req.prompt + (f"\nAvoid: {req.negative}" if req.negative else "")
        asked = req.model or DEFAULT_MODEL
        model = _WORKS.get(asked, asked)
        try:
            try:
                resp = await self._call(client, model, req, prompt, size)
            except openai.APIStatusError as exc:
                if needs_verification(exc):
                    raise PluginError("OpenAI says your organisation must be verified before it can use image models. "
                                      "Open platform.openai.com → Settings → Organization → General → Verify Organization "
                                      "(a few minutes), then try again.") from exc
                if not model_missing(exc):
                    raise
                ids = [m.id async for m in client.models.list()]                # which models can THIS key use?
                alt = pick_image_model(ids, avoid=model)
                if not alt:
                    raise PluginError(f"OpenAI says the picture model '{model}' is not available to your key, and no other GPT Image "
                                      f"model is listed for it. Another picture model will be tried instead.") from exc
                _WORKS[asked] = alt
                resp = await self._call(client, alt, req, prompt, size)
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
