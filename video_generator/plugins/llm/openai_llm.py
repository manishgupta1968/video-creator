"""OpenAI (GPT) brain plugin — official `openai` SDK, Chat Completions with JSON mode."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional, Type

from pydantic import BaseModel

from ..base import LLM, PluginError, Usage, b64
from .common import MAX_IMAGES, repair_prompt, schema_instruction, validate


class OpenAILLM(LLM):
    name = "openai"
    env_keys = ["OPENAI_API_KEY"]
    description = "GPT models via the OpenAI API"
    licence = "commercial"

    async def generate_json(self, *, system: str, user: str, schema: Type[BaseModel], model: str,
                            images: Optional[list[Path]] = None, video: Optional[Path] = None,
                            max_tokens: int = 16000, meta: Optional[dict] = None):
        import openai

        client = openai.AsyncOpenAI()
        model = model or "gpt-5"
        parts: list[dict] = [{"type": "text", "text": user + schema_instruction(schema)}]
        for p in (images or [])[:MAX_IMAGES]:
            mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64(p)}"}})
        messages = [{"role": "system", "content": system}, {"role": "user", "content": parts}]
        usage = Usage()
        last_error = ""
        for _ in range(2):
            try:
                resp = await client.chat.completions.create(model=model, messages=messages,
                                                            response_format={"type": "json_object"},
                                                            max_completion_tokens=max_tokens)
            except openai.AuthenticationError as exc:
                raise PluginError("OpenAI API key is invalid") from exc
            except openai.RateLimitError as exc:
                raise PluginError("OpenAI rate limit or quota reached") from exc
            except openai.APIStatusError as exc:
                raise PluginError(f"OpenAI API error {exc.status_code}: {str(exc)[:200]}") from exc
            except openai.APIConnectionError as exc:
                raise PluginError("cannot reach the OpenAI API (network)") from exc
            if resp.usage:
                usage.input_tokens += resp.usage.prompt_tokens or 0
                usage.output_tokens += resp.usage.completion_tokens or 0
            text = resp.choices[0].message.content or ""
            try:
                return validate(schema, text), usage
            except PluginError as exc:
                last_error = str(exc)
                messages = messages + [{"role": "assistant", "content": text or "{}"},
                                       {"role": "user", "content": repair_prompt(last_error)}]
        raise PluginError(last_error or "GPT returned an unusable answer")
