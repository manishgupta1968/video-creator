"""`vg doctor`: check your keys with FREE calls, before any money is spent.

Each check says in plain words what works, what does not, and what to do.
Nothing here creates a picture, video or voice, so nothing is charged."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import httpx

from .plugins.image.openai_image import DEFAULT_MODEL, pick_image_model

OK, WARN, BAD, SKIP = "ok", "warn", "bad", "skip"
BOGUS_REQUEST = "00000000-0000-0000-0000-000000000000"


@dataclass
class Check:
    name: str
    status: str          # ok | warn | bad | skip
    message: str


def _short(r: httpx.Response) -> str:
    return " ".join((r.text or "").split())[:160]


async def check_openai(client: httpx.AsyncClient, catalog_model: str = DEFAULT_MODEL) -> list[Check]:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return [Check("OpenAI", SKIP, "No OPENAI_API_KEY set. (Optional: used for the AI brain and for pictures.)")]
    try:
        r = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        return [Check("OpenAI", WARN, f"Could not reach OpenAI ({type(exc).__name__}). Check your internet connection.")]
    if r.status_code in (401, 403):
        return [Check("OpenAI", BAD, f"OpenAI rejected the key ({r.status_code}). Make a new key at platform.openai.com/api-keys and paste it in Settings.")]
    if r.status_code != 200:
        return [Check("OpenAI", WARN, f"OpenAI answered {r.status_code}: {_short(r)}")]
    ids = [m.get("id", "") for m in (r.json().get("data") or [])]
    out = [Check("OpenAI key", OK, f"Accepted. {len(ids)} models are open to this key.")]
    if catalog_model in ids:
        out.append(Check("OpenAI pictures", OK, f"Picture model '{catalog_model}' is available."))
    else:
        alt = pick_image_model(ids)
        if alt:
            out.append(Check("OpenAI pictures", OK, f"'{catalog_model}' is not available to your key, so '{alt}' will be used instead (automatic)."))
        else:
            out.append(Check("OpenAI pictures", WARN, f"No GPT Image model is open to your key (the name '{catalog_model}' is not listed). "
                             "The tool will use another picture model (fal.ai Flux or Gemini) instead. "
                             "If you want OpenAI pictures: platform.openai.com → Settings → Organization → Verify Organization."))
    return out


async def check_elevenlabs(client: httpx.AsyncClient, model: str = "eleven_v3") -> list[Check]:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        return [Check("ElevenLabs", SKIP, "No ELEVENLABS_API_KEY set. (Optional: natural voices and voice copying.)")]
    headers = {"xi-api-key": key}
    try:
        r = await client.get("https://api.elevenlabs.io/v1/user", headers=headers)
        m = await client.get("https://api.elevenlabs.io/v1/models", headers=headers)
    except httpx.HTTPError as exc:
        return [Check("ElevenLabs", WARN, f"Could not reach ElevenLabs ({type(exc).__name__}). Check your internet connection.")]
    out: list[Check] = []
    restricted = "missing_permissions" in (r.text or "")
    if r.status_code == 200:
        sub = (r.json().get("subscription") or {})
        used, limit = sub.get("character_count"), sub.get("character_limit")
        left = f" {max(int(limit) - int(used), 0):,} characters left this month." if isinstance(used, (int, float)) and isinstance(limit, (int, float)) else ""
        out.append(Check("ElevenLabs key", OK, f"Accepted. Plan: {sub.get('tier', 'unknown')}.{left}"))
        if str(sub.get("tier", "")).lower() in ("free", "") and left:
            out.append(Check("ElevenLabs voice copy", WARN, "Copying a voice from your recording needs a paid ElevenLabs plan. Normal voices work on the free plan."))
    elif r.status_code in (401, 403) and restricted:
        out.append(Check("ElevenLabs key", OK, "Accepted, but this key has limited permissions (it cannot read the account). That is fine if it may use text-to-speech."))
    elif r.status_code in (401, 403):
        out.append(Check("ElevenLabs key", BAD, f"ElevenLabs rejected the key ({r.status_code}). Make a new key at elevenlabs.io → Developers → API Keys."))
        return out
    else:
        out.append(Check("ElevenLabs key", WARN, f"ElevenLabs answered {r.status_code}: {_short(r)}"))
    if m.status_code == 200 and isinstance(m.json(), list):
        ids = [x.get("model_id", "") for x in m.json()]
        out.append(Check("ElevenLabs voice model", OK if model in ids else WARN,
                         f"Voice model '{model}' is available." if model in ids else
                         f"'{model}' is not in your model list. Voice models you have: {', '.join(ids[:6]) or 'none'}."))
    return out


async def check_fal(client: httpx.AsyncClient) -> list[Check]:
    key = os.environ.get("FAL_KEY", "")
    if not key:
        return [Check("fal.ai", SKIP, "No FAL_KEY set. (Needed for real video: Kling, Seedance, Wan, talking animals.)")]
    try:
        r = await client.get(f"https://queue.fal.run/fal-ai/flux/dev/requests/{BOGUS_REQUEST}/status",
                             headers={"Authorization": f"Key {key}"})
    except httpx.HTTPError as exc:
        return [Check("fal.ai", WARN, f"Could not reach fal.ai ({type(exc).__name__}). Check your internet connection.")]
    text = _short(r)
    if r.status_code in (401, 403):
        if "balance" in text.lower() or "locked" in text.lower():
            return [Check("fal.ai key", BAD, f"fal.ai accepted the key but says: {text}. Add credit at fal.ai/dashboard/billing.")]
        return [Check("fal.ai key", BAD, f"fal.ai rejected the key ({r.status_code}): {text}. Make a new key at fal.ai/dashboard/keys.")]
    if r.status_code >= 500:
        return [Check("fal.ai key", WARN, f"fal.ai answered {r.status_code}. Try again in a minute.")]
    return [Check("fal.ai key", OK, "Accepted. (Model names can only be fully checked by making a clip; if one fails, the message names it.)")]


async def check_fal_models(client: httpx.AsyncClient, catalog) -> list[Check]:
    """Ask fal.ai whether each fal model in the catalogue exists. A model name that is wrong only shows up when a clip is
    made, so this looks ahead. Anything unclear is reported as 'could not check', never as 'broken'."""
    key = os.environ.get("FAL_KEY", "")
    if not key or catalog is None:
        return []
    out: list[Check] = []
    entries = [e for e in catalog.entries if e.vendor == "fal" and e.enabled and e.model]
    for e in entries:
        try:
            r = await client.get("https://api.fal.ai/v1/models", params={"endpoint_id": e.model}, headers={"Authorization": f"Key {key}"})
        except httpx.HTTPError:
            return out + [Check("fal.ai models", WARN, "Could not reach fal.ai to check the model names.")]
        label = f"fal model {e.id}"
        try:
            data = r.json() if r.status_code == 200 else None
        except ValueError:
            data = None
        models = data.get("models") if isinstance(data, dict) else None
        if isinstance(models, list):
            ids = {m.get("endpoint_id") for m in models if isinstance(m, dict)}
            if e.model in ids:
                out.append(Check(label, OK, f"'{e.model}' is listed by fal.ai."))
            elif not models:
                out.append(Check(label, WARN, f"fal.ai did not list '{e.model}'. The name may be out of date. "
                                 "Check the model name on fal.ai/models and correct it in catalog.yaml."))
            else:
                out.append(Check(label, SKIP, f"Could not check '{e.model}' (unexpected answer from fal.ai)."))
        else:
            out.append(Check(label, SKIP, f"Could not check '{e.model}' (fal.ai answered {r.status_code})."))
    return out


async def run_checks(client: Optional[httpx.AsyncClient] = None, catalog=None) -> list[Check]:
    own = client is None
    client = client or httpx.AsyncClient(timeout=20, follow_redirects=True)
    try:
        image_model = DEFAULT_MODEL
        voice_model = "eleven_v3"
        if catalog is not None:
            try:
                image_model = catalog.get("gpt_image").model
                voice_model = catalog.get("eleven_v3").model
            except KeyError:
                pass
        out: list[Check] = []
        for part in (check_openai(client, image_model), check_elevenlabs(client, voice_model), check_fal(client),
                     check_fal_models(client, catalog)):
            out += await part
        return out
    finally:
        if own:
            await client.aclose()
