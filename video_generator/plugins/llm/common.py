"""Shared JSON handling for every LLM plugin (vendor-neutral)."""
from __future__ import annotations

import json
import re
from typing import Type

from pydantic import BaseModel, ValidationError

from ..base import PluginError

MAX_IMAGES = 18


def schema_instruction(schema: Type[BaseModel]) -> str:
    return ("\n\nRespond with ONLY a JSON object (no markdown) that validates against this JSON schema:\n"
            + json.dumps(schema.model_json_schema(), separators=(",", ":")))


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the reply")
    return json.loads(text[start:end + 1])


def validate(schema: Type[BaseModel], text: str) -> BaseModel:
    try:
        return schema.model_validate(extract_json(text))
    except (ValueError, ValidationError) as exc:
        raise PluginError(f"reply did not match the expected format: {str(exc)[:300]}") from exc


def repair_prompt(error: str) -> str:
    return (f"Your previous reply was not valid: {error}\n"
            "Reply again with ONLY the corrected JSON object.")
