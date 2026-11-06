"""The background music is made ONCE for the whole video and kept, so that:
  - joining again after one clip changed does not buy the music again,
  - every downloaded part can use the same music as a free slice of the saved track.

The track lives in the project's output folder as music.mp3 (or music.wav for a free track), with music.json beside it saying
what it was made from. It is reused while the mood text and the music reference are unchanged and the video is not much longer
than the track (policy.music_reuse_tolerance).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from . import policy as policy_mod
from .models import ContextRole, Project
from .project import ProjectStore

META = "music.json"


def folder(project_id: str) -> Path:
    return ProjectStore.path_for(project_id) / "output"


def mood_for(project: Project) -> str:
    """What the music is asked to be: the planner's music advice, the style, and the goal."""
    return f"{project.music_advice or ''} {project.style.mood} {project.style.look} music for: {project.goal}".strip()


def reference(project: Project) -> Optional[Path]:
    """The music (or sound) example the user gave for the whole video, if any (the last one given wins)."""
    ref = None
    base = ProjectStore.path_for(project.id)
    for c in project.context:
        if c.role in (ContextRole.music_reference, ContextRole.sound) and c.scope == "project":
            ref = (base / c.files[0]) if c.files else None
    return ref


def key(project: Project) -> str:
    """A fingerprint of what the music is made from: change the mood text or the reference and it changes."""
    ref = reference(project)
    stamp = f"{ref.name}:{ref.stat().st_size}" if ref and ref.exists() else ""
    return hashlib.sha1(f"{mood_for(project)}|{stamp}".encode()).hexdigest()[:16]


def cost(entry, seconds: float) -> float:
    """What a NEW track for a video of this length costs: per minute, or one flat price per track."""
    if entry is None or entry.is_free:
        return 0.0
    return seconds / 60 * entry.unit_price if entry.price.unit == "minute" else entry.unit_price


def read(project_id: str) -> dict:
    try:
        return json.loads((folder(project_id) / META).read_text())
    except (OSError, ValueError, FileNotFoundError):
        return {}


def path(project_id: str) -> Optional[Path]:
    """The saved track, when its file is really there."""
    try:
        meta = read(project_id)
        f = folder(project_id) / meta.get("file", "")
        return f if meta.get("file") and f.exists() else None
    except FileNotFoundError:
        return None


def save(project: Project, track: Path, made_for_s: float, model: str, free: bool, spent_usd: float) -> None:
    meta = {"file": track.name, "made_for_s": round(made_for_s, 1), "key": key(project), "model": model, "free": bool(free),
            "spent_usd": round(spent_usd, 4)}
    (folder(project.id) / META).write_text(json.dumps(meta))


def status(project: Project, total_s: float, real_music_possible: bool = False) -> dict:
    """What is saved and whether it can be used for a video of `total_s` seconds.
    reusable = a track exists, was made from the same mood and reference, is not a free placeholder when a real track is now
    possible, and the video is not longer than the track by more than the tolerance."""
    out = {"exists": False, "made_for_s": 0.0, "free": False, "reusable": False, "why": "", "model": ""}
    try:
        f = path(project.id)
        meta = read(project.id)
    except FileNotFoundError:
        return out
    if not f:
        return out
    out.update({"exists": True, "made_for_s": float(meta.get("made_for_s", 0) or 0), "free": bool(meta.get("free")), "model": meta.get("model", ""),
                "spent_usd": float(meta.get("spent_usd", 0) or 0)})
    tol = policy_mod.current().music_reuse_tolerance
    if meta.get("key") != key(project):
        out["why"] = "the music mood or example changed since the saved track was made"
    elif out["free"] and real_music_possible:
        out["why"] = "the saved track is a free placeholder and real music can now be made"
    elif total_s > out["made_for_s"] * (1 + tol) + 0.5:
        out["why"] = f"the video is now {total_s:.0f} s; the saved music was made for {out['made_for_s']:.0f} s"
    else:
        out["reusable"] = True
    return out
