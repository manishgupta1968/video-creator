"""Plugin discovery (entry points) and routing (catalogue + shot type)."""
from __future__ import annotations

import importlib
import json
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Optional

from . import policy as policy_mod
from .catalog import Catalog, CatalogEntry
from .config import Config, vg_home
from .plugins.base import Plugin

GROUP = "video_generator.plugins"

# Used when running from a source checkout without `pip install -e .`
BUILTINS = {
    "fake_llm": "video_generator.plugins.fake.fake_llm:FakeLLM",
    "fake_image": "video_generator.plugins.fake.fake_media:FakeImage",
    "fake_video": "video_generator.plugins.fake.fake_media:FakeVideo",
    "fake_avatar": "video_generator.plugins.fake.fake_media:FakeAvatar",
    "fake_lipsync": "video_generator.plugins.fake.fake_media:FakeLipSync",
    "fake_music": "video_generator.plugins.fake.fake_media:FakeMusic",
    "fake_transcribe": "video_generator.plugins.fake.fake_media:FakeTranscriber",
    "anthropic": "video_generator.plugins.llm.anthropic_llm:AnthropicLLM",
    "openai": "video_generator.plugins.llm.openai_llm:OpenAILLM",
    "gemini": "video_generator.plugins.llm.gemini_llm:GeminiLLM",
    "fal": "video_generator.plugins.video.fal:FalVideo",
    "fal_image": "video_generator.plugins.image.fal_image:FalImage",
    "fal_avatar": "video_generator.plugins.avatar.fal_avatar:FalAvatar",
    "fal_lipsync": "video_generator.plugins.lipsync.fal_lipsync:FalLipSync",
    "fal_music": "video_generator.plugins.music.fal_music:FalMusic",
    "replicate": "video_generator.plugins.video.replicate:ReplicateVideo",
    "veo": "video_generator.plugins.video.veo:VeoVideo",
    "runway": "video_generator.plugins.video.runway:RunwayVideo",
    "luma": "video_generator.plugins.video.luma:LumaVideo",
    "kling": "video_generator.plugins.video.kling:KlingVideo",
    "gpt_image": "video_generator.plugins.image.openai_image:OpenAIImage",
    "nano_banana": "video_generator.plugins.image.gemini_image:GeminiImage",
    "heygen": "video_generator.plugins.avatar.heygen:HeyGenAvatar",
    "elevenlabs": "video_generator.plugins.voice.elevenlabs:ElevenLabsVoice",
    "cartesia": "video_generator.plugins.voice.cartesia:CartesiaVoice",
    "kokoro": "video_generator.plugins.voice.local_voice:KokoroVoice",
    "flite": "video_generator.plugins.voice.local_voice:FliteVoice",
    "system_voice": "video_generator.plugins.voice.local_voice:SystemVoice",
    "fal_mmaudio": "video_generator.plugins.sfx.fal_mmaudio:FalMMAudio",
    "elevenlabs_sfx": "video_generator.plugins.sfx.elevenlabs_sfx:ElevenLabsSfx",
    "local_ambience": "video_generator.plugins.sfx.local_ambience:LocalAmbience",
    "elevenlabs_music": "video_generator.plugins.music.elevenlabs_music:ElevenLabsMusic",
    "local_music": "video_generator.plugins.music.local_music:LocalMusic",
    "faster_whisper": "video_generator.plugins.transcribe.whisper:FasterWhisper",
    "openai_transcribe": "video_generator.plugins.transcribe.whisper:OpenAITranscribe",
    "flicker": "video_generator.plugins.quality.scorers:FlickerScorer",
    "face_similarity": "video_generator.plugins.quality.scorers:FaceSimilarityScorer",
    "ffmpeg": "video_generator.plugins.assemble.ffmpeg_assembler:FFmpegAssembler",
}


def _load(target: str):
    mod, _, attr = target.partition(":")
    return getattr(importlib.import_module(mod), attr)


@lru_cache(maxsize=1)
def plugin_classes() -> dict[str, type]:
    found: dict[str, str] = dict(BUILTINS)
    try:
        for ep in entry_points(group=GROUP):
            found[ep.name] = ep.value
    except Exception:  # pragma: no cover
        pass
    classes: dict[str, type] = {}
    for name, target in found.items():
        try:
            cls = _load(target)
            cls.name = cls.name or name
            classes[name] = cls
        except Exception as exc:  # broken third-party plugin must not break the app
            classes[name] = type(f"Broken_{name}", (Plugin,), {"name": name, "broken": str(exc),
                                                              "is_configured": lambda self: (False, f"failed to load: {exc}")})
    return classes


SIMPLE_TASKS = ("photo_query", "pick_photo", "explain", "command", "suggest_dependencies", "optimize")      # brain tasks a cheaper AI can do

MOTION_LEVELS = ("face", "body", "scene")      # what a model can animate, from least to most; a higher level covers a lower one


def capability_covers(job: str, caps: dict, cap: str, want) -> bool:
    """Does a catalogue row's capabilities meet one need? Purely data-driven: booleans must be true, numbers must be at
    least the wanted number, `animates` is ordered (scene covers body covers face), other words must match or be
    listed. A row that does not declare `animates` is assumed to animate a whole scene (video) or only a face (avatar)."""
    have = caps.get(cap)
    if cap == "animates":
        have = have or ("face" if job == "avatar" else "scene")
        return MOTION_LEVELS.index(have) >= MOTION_LEVELS.index(want) if have in MOTION_LEVELS and want in MOTION_LEVELS else have == want
    if isinstance(want, bool):
        return bool(have) or not want
    if isinstance(want, (int, float)):
        return (have or 0) >= want
    if isinstance(want, str):
        return have == want or (isinstance(have, (list, tuple, set)) and want in have)
    return True


class Registry:
    def __init__(self, config: Config, catalog: Optional[Catalog] = None):
        self.config = config
        self.catalog = catalog or Catalog.load()
        self._instances: dict[str, Plugin] = {}

    # ------------------------------------------------------------ plugins
    def plugin(self, name: str) -> Plugin:
        if name not in self._instances:
            classes = plugin_classes()
            if name not in classes:
                raise KeyError(f"unknown plugin: {name}")
            self._instances[name] = classes[name](self.config)
        return self._instances[name]

    def configured(self, name: str) -> bool:
        try:
            ok, _ = self.plugin(name).is_configured()
            return ok
        except KeyError:
            return False

    def entry_usable(self, e: CatalogEntry) -> bool:
        return e.enabled and e.id not in self.config.disabled_models and self.configured(e.plugin)

    # ------------------------------------------------------------ routing
    def candidates(self, job: str, shot_type: str = "other", need: Optional[dict] = None,
                   mode: Optional[str] = None) -> list[CatalogEntry]:
        """Usable catalogue entries for a job, best first.

        mode: best (quality first), balanced (quality per dollar), budget
        (the cheapest REAL model that is good enough), free (free local tools only).
        Free placeholders are only used in free mode, or as a last resort when no real model is usable."""
        mode = mode or self.config.quality_mode
        need = need or {}
        out = []
        for e in self.catalog.for_job(job):
            if not self.entry_usable(e):
                continue
            if mode == "free" and not e.is_free:
                continue
            if all(capability_covers(job, e.capabilities, cap, want) for cap, want in need.items()):
                out.append(e)

        def level(e: CatalogEntry) -> int:
            return e.strength(shot_type) if job == "video" else e.quality

        if mode != "free":
            real = [e for e in out if not e.is_free]
            if real:
                out = real                                   # a placeholder card is never "cheaper" than real footage
            if mode == "budget":
                decent = [e for e in out if level(e) >= policy_mod.current().budget_min_strength]   # cheapest, but not a model that is poor for this kind of shot
                if decent:
                    out = decent

        def score(e: CatalogEntry) -> tuple:
            strength = e.strength(shot_type) if job == "video" else e.quality
            free_penalty = 0 if mode in ("free", "budget") else (-10 if e.is_free else 0)
            if mode == "best":
                return (free_penalty + strength, -e.unit_price)
            if mode == "budget":
                return (-e.unit_price, strength)
            if mode == "free":
                return (strength,)
            # balanced: quality first, but a cheaper model within one point wins
            return (free_penalty + strength * 2 - min(e.unit_price * 5, 3), -e.unit_price)

        out.sort(key=score, reverse=True)
        pref = self.config.preferred_models.get(shot_type) or self.config.preferred_models.get(job)
        if pref:
            out.sort(key=lambda e: 0 if e.id == pref else 1)
        return out

    def choose(self, job: str, shot_type: str = "other", need: Optional[dict] = None,
               override: Optional[str] = None, mode: Optional[str] = None, strict: bool = False) -> CatalogEntry:
        """Best usable model. strict=True: never relax `need` (raises LookupError instead)."""
        if override:
            try:
                e = self.catalog.get(override)
                if self.entry_usable(e):
                    return e
            except KeyError:
                pass
        c = self.candidates(job, shot_type, need, mode)
        if not c and need and strict:
            raise LookupError(f"no usable {job} model with {need}")
        if not c and need:
            c = self.candidates(job, shot_type, None, mode)  # relax capabilities, warn upstream
        if not c:
            c = self.candidates(job, shot_type, None, "free")
        if not c:
            raise LookupError(f"no usable model for {job}")
        return c[0]

    # ------------------------------------------------------------ time history
    def _timings_path(self):
        return vg_home() / "timings.json"

    def time_factor(self, entry_id: str) -> float:
        """Real job time / catalogue estimate, learned from your recent jobs."""
        if not hasattr(self, "_timings"):
            try:
                self._timings = json.loads(self._timings_path().read_text())
            except Exception:
                self._timings = {}
        return float(self._timings.get(entry_id, 1.0))

    def record_time(self, entry_id: str, wall_s: float, expected_s: float) -> None:
        if expected_s <= 0:
            return
        ratio = max(0.2, min(wall_s / expected_s, 5.0))
        old = self.time_factor(entry_id)
        self._timings[entry_id] = round(old * 0.7 + ratio * 0.3, 3)
        try:
            self._timings_path().write_text(json.dumps(self._timings))
        except OSError:
            pass

    # ------------------------------------------------------------ why a model cannot be used (shown in every list of choices)
    def unusable_reason(self, e: CatalogEntry) -> str:
        """'' when the model can be used; otherwise the exact cause in plain words."""
        if not e.enabled or e.id in self.config.disabled_models:
            return "switched off (Settings > Model catalogue)"
        try:
            ok, why = self.plugin(e.plugin).is_configured()
        except KeyError:
            return f"the {e.plugin} plugin is not installed"
        return "" if ok else why

    # ------------------------------------------------------------ AI brain
    def llm_group(self, task: str) -> str:
        """The kind of work a brain task belongs to: review | simple | default (planning and scripts)."""
        return "review" if task == "review" else "simple" if task in SIMPLE_TASKS else "default"

    def _picked(self, task: str) -> Optional[tuple[str, str]]:
        """The (plugin, model) chosen in Settings for this kind of work, when that plugin is connected."""
        key = self.config.llm.per_task_model.get(self.llm_group(task), "")
        plugin, _, model = key.partition(":")
        return (plugin, model) if plugin and model and self.configured(plugin) else None

    def llm_plugin_name(self, task: str = "default") -> str:
        picked = self._picked(task)
        if picked:
            return picked[0]
        llm = self.config.llm
        if task == "review" and llm.reviewer not in ("", "same"):
            name = llm.reviewer
        else:
            name = llm.per_task.get(task) or llm.default
        if name and name != "auto" and self.configured(name):
            return name
        for candidate in ("anthropic", "openai", "gemini"):
            if self.configured(candidate):
                return candidate
        return "fake_llm"

    def llm_model(self, task: str, plugin_name: str) -> str:
        """The model id to use on `plugin_name` for this task: the one chosen for this kind of work, else the plugin's usual."""
        picked = self._picked(task)
        if picked and picked[0] == plugin_name:
            return picked[1]
        return self.config.llm.models.get(plugin_name, "")

    def llm(self, task: str = "default") -> tuple[Plugin, str]:
        name = self.llm_plugin_name(task)
        return self.plugin(name), self.llm_model(task, name)

    def llm_entry(self, task: str = "default", plugin_name: Optional[str] = None) -> Optional[CatalogEntry]:
        """The catalogue row (price!) of the AI model a task really uses: matched by plugin AND model id, so two models of one
        vendor are priced separately. Falls back to the plugin's first row when the model id is not in the catalogue."""
        name = plugin_name or self.llm_plugin_name(task)
        model = self.llm_model(task, name)
        rows = [e for e in self.catalog.for_job("llm") if e.plugin == name]
        return next((e for e in rows if e.model == model), None) or (rows[0] if rows else None)

    def llm_fallback_order(self, task: str) -> list[str]:
        first = self.llm_plugin_name(task)
        rest = [n for n in ("anthropic", "openai", "gemini") if n != first and self.configured(n)]
        return [first] + rest + (["fake_llm"] if first != "fake_llm" else [])
