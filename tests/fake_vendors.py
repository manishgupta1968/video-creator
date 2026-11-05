"""Pretend vendors for whole-pipeline tests: they behave like the real ones (shapes, sizes, sound, voices) but are
instant and free. Used by the scenario matrix and the voice / sound / continuity tests."""
from __future__ import annotations

import colorsys
import hashlib
import json
from pathlib import Path

from PIL import Image

from video_generator import media
from video_generator.plugins.base import PluginError, Usage

# ElevenLabs-style voice list (labels as the real API gives them)
VOICES = [
    {"voice_id": "m_deep", "name": "Marcus", "labels": {"gender": "male", "age": "middle_aged", "accent": "american", "description": "deep authoritative", "use_case": "narration"}},
    {"voice_id": "m_young", "name": "Jay", "labels": {"gender": "male", "age": "young", "accent": "american", "description": "casual friendly"}},
    {"voice_id": "m_old", "name": "Walter", "labels": {"gender": "male", "age": "old", "accent": "british", "description": "warm gravelly"}},
    {"voice_id": "m_ind", "name": "Raj", "labels": {"gender": "male", "age": "middle_aged", "accent": "indian", "description": "clear"}},
    {"voice_id": "f_young", "name": "Zoe", "labels": {"gender": "female", "age": "young", "accent": "american", "description": "bright cheerful"}},
    {"voice_id": "f_mid", "name": "Anna", "labels": {"gender": "female", "age": "middle_aged", "accent": "american", "description": "warm calm narration"}},
    {"voice_id": "f_old", "name": "Edna", "labels": {"gender": "female", "age": "old", "accent": "british", "description": "kind"}},
    {"voice_id": "f_ind", "name": "Priya", "labels": {"gender": "female", "age": "middle_aged", "accent": "indian", "description": "warm clear"}},
]
PITCH = {"m": 115.0, "f": 225.0}          # the pitch of each fake voice, by the first letter of its id


def colour_for(text: str) -> tuple[int, int, int]:
    """A bright colour from a text: every picture/clip gets its own colour, so tests can tell which picture a clip came from."""
    h = int(hashlib.md5(text.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.7, 0.9)
    return int(r * 255), int(g * 255), int(b * 255)


def mean_colour(path: Path) -> tuple[float, float, float]:
    img = Image.open(path).convert("RGB").resize((16, 16))
    px = list(img.get_flattened_data()) if hasattr(img, 'get_flattened_data') else list(img.getdata())
    return tuple(sum(p[i] for p in px) / len(px) for i in range(3))


def close(a, b, tol=60.0) -> bool:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 < tol


class Vendors:
    """Install the pretend vendors on a Service. Records every call in `.calls`."""

    def __init__(self, svc, monkeypatch, voices=None, voice_pitch: dict | None = None, list_voices_fails: bool = False):
        for k in ("FAL_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.setenv(k, "x")
        svc.reload()
        self.svc = svc
        self.calls: dict[str, list] = {k: [] for k in ("voice", "clone", "picture", "video", "avatar", "sfx", "lipsync", "candidates")}
        self.voices = voices or VOICES
        self.pitch = voice_pitch or {}
        self.refuse: set[str] = set()          # voice ids the vendor refuses ("voice not found")
        self.video_seconds: float = 4.0         # how long the pretend video model's clips are (real models make fixed lengths)
        reg = svc.reg
        eleven = reg.plugin("elevenlabs")
        vendors = self

        async def list_voices():
            if list_voices_fails:
                raise PluginError("ElevenLabs voices: HTTP 401: missing_permissions voices_read")
            return vendors.voices

        async def synth(text, voice, out, model=""):
            vendors.calls["voice"].append({"text": text, "voice_id": voice.voice_id, "language": voice.language, "spec": voice})
            if voice.voice_id in vendors.refuse:
                raise PluginError("ElevenLabs: HTTP 404: voice_not_found", retry_other_model=True)
            vid = voice.voice_id or "f_mid"
            hz = vendors.pitch.get(vid, PITCH.get(vid[:1], 180.0))
            media.ff("-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=44100", "-t", f"{max(1.0, len(text) * 0.06):.2f}", "-ac", "1", str(out))
            return out, Usage()

        async def clone(sample, name):
            vendors.calls["clone"].append(name)
            return "cloned_voice"
        orig_candidates = eleven.candidates

        async def candidates(spec, taken=()):
            vendors.calls["candidates"].append(spec)
            return await orig_candidates(spec, taken)
        eleven.list_voices = list_voices
        eleven.synthesize = synth
        eleven.clone = clone
        eleven.candidates = candidates

        async def picture(req):
            vendors.calls["picture"].append(req)
            long_side = 1536
            a, b = (float(x) for x in req.aspect.split(":")) if ":" in req.aspect else (16, 9)
            size = (long_side, 1024) if a / b >= 1.2 else (1024, long_side) if a / b <= 0.83 else (1024, 1024)
            Image.new("RGB", size, colour_for(req.prompt[:40] + req.model)).save(req.out)
            return req.out, Usage()
        for name in ("gpt_image", "fal_image"):
            reg.plugin(name).generate = picture

        async def video(req):
            vendors.calls["video"].append(req)
            w, h = Image.open(req.start_frame).size if req.start_frame else (1280, 720)
            w, h = w - w % 2, h - h % 2
            secs = f"{vendors.video_seconds:g}"
            if req.audio:      # a model with sound of its own (like Kling or Veo) returns a clip with its own sound
                media.ff("-loop", "1", "-i", str(req.start_frame), "-f", "lavfi", "-i", f"anoisesrc=color=pink:r=44100:d={secs},volume=0.3", "-t", secs,
                         "-vf", f"scale={min(w, 640)}:-2,fps=24,noise=alls=14:allf=t", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(req.out))
            else:
                media.ff("-loop", "1", "-i", str(req.start_frame), "-t", secs, "-vf", f"scale={min(w, 640)}:-2,fps=24,noise=alls=14:allf=t", "-c:v", "libx264",
                         "-pix_fmt", "yuv420p", "-an", str(req.out))
            return req.out, Usage()
        reg.plugin("fal").generate = video

        async def avatar(req):
            vendors.calls["avatar"].append(req)
            n = max(media.probe_duration(req.audio), 1.0)      # a talking-picture model makes a clip exactly as long as its audio
            media.ff("-loop", "1", "-i", str(req.photo), "-i", str(req.audio), "-t", f"{n:.2f}", "-vf", "scale=640:-2,fps=24,noise=alls=14:allf=t", "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(req.out))
            return req.out, Usage(seconds=n)
        reg.plugin("fal_avatar").generate = avatar

        async def sfx(prompt, seconds, out, model="", video=None, params=None):
            vendors.calls["sfx"].append({"prompt": prompt, "seconds": seconds, "video": video})
            media.ff("-f", "lavfi", "-i", f"anoisesrc=color=pink:r=44100:d={seconds:.2f}", "-af", "volume=0.4", "-ac", "2", str(out))
            return out, Usage(seconds=seconds)
        reg.plugin("fal_mmaudio").generate = sfx

        async def sync(video, audio, out, model=""):
            vendors.calls["lipsync"].append(video)
            import shutil
            shutil.copy(video, out)
            return out, Usage()
        reg.plugin("fal_lipsync").sync = sync


def pitch_of_id(vid: str) -> float:
    return PITCH.get((vid or "f")[:1], 180.0)


def lines_json(svc, pid: str, nid: str) -> dict:
    p = svc.project_path(pid) if hasattr(svc, "project_path") else None
    from video_generator.project import ProjectStore
    f = ProjectStore.path_for(pid) / "clips" / nid / "voice_lines.json"
    return json.loads(f.read_text()) if f.exists() else {}
