"""The language a video is spoken in: a short code (en, hi, ta …) kept in `Settings.language`.

"auto" means "the planner decides from the goal"; it only lives until the first draft is made.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from functools import lru_cache
from importlib import resources

import yaml

AUTO = "auto"


@lru_cache(maxsize=1)
def names() -> dict[str, str]:
    """code -> name, from data/languages.yaml (the list offered on the Start screen)."""
    data = yaml.safe_load(resources.files("video_generator.data").joinpath("languages.yaml").read_text()) or {}
    return {str(k): str(v) for k, v in data.items()}


def name_of(code: str) -> str:
    return names().get((code or "").lower(), code or "")


def normalise(value: str) -> str:
    """A short lowercase code from what the planner or a person wrote ('Hindi', 'hi-IN', 'HI' all give 'hi'); '' when unclear."""
    v = (value or "").strip().lower()
    if not v or v == AUTO:
        return ""
    for code, name in names().items():
        if v == name.lower():
            return code
    m = re.fullmatch(r"([a-z]{2,3})(?:[-_][a-z0-9]{2,8})*", v)
    return m.group(1) if m else ""


def effective(language: str) -> str:
    """The code the voice and speech-to-text services get: never 'auto' (they cannot use it)."""
    return normalise(language) or "en"


@lru_cache(maxsize=1)
def scripts() -> dict[str, tuple[str, ...]]:
    """code -> the writing system(s) the language is normally written in, from data/language_scripts.yaml."""
    data = yaml.safe_load(resources.files("video_generator.data").joinpath("language_scripts.yaml").read_text()) or {}
    return {str(k): tuple(str(x) for x in (v if isinstance(v, list) else [v])) for k, v in data.items()}


def script_of(text: str) -> tuple[str, float, int]:
    """The writing system most of the letters of `text` are in: (name, share of the letters, number of letters). ('', 0, 0) when there are no letters."""
    counts: Counter = Counter()
    for ch in text or "":
        if ch.isalpha():
            try:
                counts[unicodedata.name(ch).split()[0]] += 1
            except ValueError:
                continue
    total = sum(counts.values())
    if not total:
        return "", 0.0, 0
    top, n = counts.most_common(1)[0]
    return top, n / total, total
