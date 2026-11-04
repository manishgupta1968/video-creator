"""Anthropic (Claude) brain plugin — official `anthropic` SDK.

Defaults: model claude-opus-5-5, adaptive thinking (always on for this
model), effort from config (default "medium"), server-side refusal
fallbacks enabled (`fallbacks: "default"` with the 2026-07-01 beta).
"""
from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Optional, Type

from pydantic import BaseModel

from ..base import LLM, PluginError, Usage, b64
from .common import MAX_IMAGES, repair_prompt, schema_instruction, validate


class AnthropicLLM(LLM):
    name = "anthropic"
    env_keys = ["ANTHROPIC_API_KEY"]
    description = "Claude via the Anthropic API"
    licence = "commercial"

    def is_configured(self):
        import os
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return True, "ok"
        return False, "set ANTHROPIC_API_KEY"

    def _client(self):
        import anthropic
        return anthropic.AsyncAnthropic()

    async def generate_json(self, *, system: str, user: str, schema: Type[BaseModel], model: str,
                            images: Optional[list[Path]] = None, video: Optional[Path] = None,
                            max_tokens: int = 16000, meta: Optional[dict] = None):
        import anthropic

        model = model or "claude-opus-5-5"
        content: list[dict] = []
        for p in (images or [])[:MAX_IMAGES]:
            mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64(p)}})
        content.append({"type": "text", "text": user + schema_instruction(schema)})
        messages: list[dict] = [{"role": "user", "content": content}]
        cfg = self.config.llm if self.config else None
        effort = getattr(cfg, "anthropic_effort", "medium") or "medium"
        use_fallbacks = getattr(cfg, "anthropic_fallbacks", True)
        client = self._client()
        usage = Usage()
        last_error = ""
        for attempt in range(2):
            kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages,
                          output_config={"effort": effort})
            try:
                if use_fallbacks:
                    resp = await client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                             fallbacks="default", **kwargs)
                else:
                    resp = await client.messages.create(**kwargs)
            except anthropic.BadRequestError as exc:
                if use_fallbacks and attempt == 0 and "fallback" in str(exc).lower():
                    use_fallbacks = False
                    continue
                raise PluginError(f"Claude rejected the request: {exc.message}") from exc
            except anthropic.AuthenticationError as exc:
                raise PluginError("Anthropic API key is invalid") from exc
            except anthropic.RateLimitError as exc:
                await asyncio.sleep(5)
                raise PluginError("Anthropic rate limit; try again shortly") from exc
            except anthropic.APIStatusError as exc:
                raise PluginError(f"Anthropic API error {exc.status_code}") from exc
            except anthropic.APIConnectionError as exc:
                raise PluginError("cannot reach the Anthropic API (network)") from exc
            usage.input_tokens += getattr(resp.usage, "input_tokens", 0) or 0
            usage.output_tokens += getattr(resp.usage, "output_tokens", 0) or 0
            if resp.stop_reason == "refusal":
                raise PluginError("Claude declined this request")
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            try:
                return validate(schema, text), usage
            except PluginError as exc:
                last_error = str(exc)
                messages = messages + [{"role": "assistant", "content": text or "{}"},
                                       {"role": "user", "content": repair_prompt(last_error)}]
        raise PluginError(last_error or "Claude returned an unusable answer")
