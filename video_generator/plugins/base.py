"""Plugin interfaces. The core only talks to these; never to a vendor SDK.

To add a tool: subclass one interface, set `name`/`job`/`env_keys`, register
it under the `video_generator.plugins` entry-point group, and add a row to
catalog.yaml that names the plugin.
"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Type

import httpx
from pydantic import BaseModel


class PluginError(RuntimeError):
    """A provider call failed; message is shown to the user.

    retry_other_model: the request was refused before any work was done (wrong model name, bad input),
    so nothing was charged and another model of the same kind can safely be tried."""

    def __init__(self, message: str = "", retry_other_model: bool = False):
        super().__init__(message)
        self.retry_other_model = retry_other_model


class NotConfigured(PluginError):
    pass


@dataclass
class Usage:
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    raw: dict = field(default_factory=dict)


class Plugin:
    name: str = ""
    job: str = ""
    env_keys: list[str] = []
    description: str = ""
    licence: str = ""

    def __init__(self, config: Any = None):
        self.config = config

    def is_configured(self) -> tuple[bool, str]:
        missing = [k for k in self.env_keys if not os.environ.get(k)]
        if missing:
            return False, f"set {', '.join(missing)}"
        return True, "ok"

    def key(self, name: Optional[str] = None) -> str:
        k = name or (self.env_keys[0] if self.env_keys else "")
        val = os.environ.get(k, "")
        if not val:
            raise NotConfigured(f"{self.name}: missing {k}")
        return val

    async def price_lookup(self, model: str) -> Optional[float]:
        """Return a live unit price if the vendor exposes one; else None."""
        return None


# ----------------------------------------------------------------------- jobs
class LLM(Plugin):
    job = "llm"

    async def generate_json(self, *, system: str, user: str, schema: Type[BaseModel], model: str,
                            images: Optional[list[Path]] = None, video: Optional[Path] = None,
                            max_tokens: int = 16000, meta: Optional[dict] = None) -> tuple[BaseModel, Usage]:
        """Return a validated `schema` instance. `meta` carries structured inputs
        (used by the offline brain; real LLMs read the prompt)."""
        raise NotImplementedError


@dataclass
class ImageRequest:
    prompt: str
    out: Path
    model: str = ""
    references: list[Path] = field(default_factory=list)
    aspect: str = "16:9"
    negative: str = ""
    label: str = ""              # e.g. "Clip 2.1 · The Greeting" (shown on free preview cards)


class ImageGenerator(Plugin):
    job = "image"

    async def generate(self, req: ImageRequest) -> tuple[Path, Usage]:
        raise NotImplementedError


@dataclass
class VideoRequest:
    prompt: str
    out: Path
    model: str = ""
    seconds: float = 5
    aspect: str = "16:9"
    resolution: str = "1080p"
    start_frame: Optional[Path] = None
    end_frame: Optional[Path] = None
    references: list[Path] = field(default_factory=list)
    negative: str = ""
    audio: bool = True
    camera: str = ""
    label: str = ""
    params: dict = field(default_factory=dict)      # the catalogue row's `params` (field names, allowed lengths …)


class VideoGenerator(Plugin):
    job = "video"

    async def generate(self, req: VideoRequest) -> tuple[Path, Usage]:
        raise NotImplementedError


@dataclass
class AvatarRequest:
    photo: Optional[Path]
    audio: Path
    out: Path
    model: str = ""
    prompt: str = ""
    avatar_id: Optional[str] = None
    aspect: str = "16:9"
    label: str = ""


class AvatarGenerator(Plugin):
    job = "avatar"

    async def generate(self, req: AvatarRequest) -> tuple[Path, Usage]:
        raise NotImplementedError


@dataclass
class VoiceSpec:
    voice_id: Optional[str] = None
    description: str = ""
    language: str = "en"
    emotion: str = ""
    speed: float = 1.0
    # the voice profile (decided by the planner, editable by the user); "" = not decided
    gender: str = ""            # male | female | neutral
    age: str = ""               # child | teen | young | adult | older
    pitch: str = ""             # low | medium | high
    pace: str = ""              # slow | normal | fast
    accent: str = ""


@dataclass
class VoiceChoice:
    """One voice a vendor can offer for a profile."""
    voice_id: str
    name: str = ""
    provider: str = ""
    score: float = 0.0
    gender: str = ""
    note: str = ""              # e.g. "stock voice (the voice list could not be read)"


class VoiceSynth(Plugin):
    job = "voice"
    can_clone = False

    async def candidates(self, spec: "VoiceSpec", taken: tuple = ()) -> list["VoiceChoice"]:
        """Voices that fit `spec`, best first. `taken` = voice ids already used by other speakers (used last).
        Default: the vendor's old text match, if it has one."""
        vid = await self.match(spec.description, spec.language)
        return [VoiceChoice(vid, "", self.name)] if vid else []

    async def synthesize(self, text: str, voice: VoiceSpec, out: Path, model: str = "") -> tuple[Path, Usage]:
        raise NotImplementedError

    async def clone(self, sample: Path, name: str) -> str:
        raise PluginError(f"{self.name} cannot clone voices")

    async def match(self, description: str, language: str = "en") -> Optional[str]:
        """Pick a stock voice id matching a text description."""
        return None

    async def list_voices(self) -> list[dict]:
        return []


class LipSync(Plugin):
    job = "lipsync"

    async def sync(self, video: Path, audio: Path, out: Path, model: str = "") -> tuple[Path, Usage]:
        raise NotImplementedError


class MusicGenerator(Plugin):
    job = "music"

    async def generate(self, prompt: str, seconds: float, out: Path, model: str = "",
                       reference: Optional[Path] = None) -> tuple[Path, Usage]:
        raise NotImplementedError


class SoundEffect(Plugin):
    """Natural sound for a clip: ambience of the place and effects tied to the action (not music, not speech)."""
    job = "sfx"

    async def generate(self, prompt: str, seconds: float, out: Path, model: str = "",
                       video: Optional[Path] = None, params: Optional[dict] = None) -> tuple[Path, Usage]:
        """Write an audio file of about `seconds` to `out`. `video` is the finished (silent) clip: a model that
        can listen to the pictures uses it so the sound fits what happens."""
        raise NotImplementedError


@dataclass
class Segment:
    start: float
    end: float
    text: str


class Transcriber(Plugin):
    job = "transcribe"

    async def transcribe(self, media: Path, language: str = "en", hint: str = "") -> list[Segment]:
        raise NotImplementedError


class QualityScorer(Plugin):
    job = "quality"

    def score(self, video: Path, references: list[Path]) -> dict[str, float]:
        raise NotImplementedError


# ----------------------------------------------------------------------- helpers
def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode()}"


def b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


async def download(url: str, out: Path, headers: Optional[dict] = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers or {}) as r:
            r.raise_for_status()
            with open(out, "wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)
    return out


async def poll(fetch: Callable[[], Awaitable[dict]], done: Callable[[dict], Optional[bool]],
               interval: float = 5, timeout: float = 1800) -> dict:
    """Generic submit->poll loop. `done` returns True (finished), False (failed) or None (wait)."""
    start = time.monotonic()
    while True:
        data = await fetch()
        state = done(data)
        if state is True:
            return data
        if state is False:
            raise PluginError(f"provider reported failure: {str(data)[:500]}")
        if time.monotonic() - start > timeout:
            raise PluginError("provider timed out")
        await asyncio.sleep(interval)


def raise_for(r: httpx.Response, who: str) -> None:
    if r.status_code >= 400:
        raise PluginError(f"{who}: HTTP {r.status_code}: {r.text[:500]}",
                          retry_other_model=r.status_code in (400, 404, 405, 409, 410, 413, 415, 422))
