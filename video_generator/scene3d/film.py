"""The whole 3D film: every clip's 3D preview joined in story order, to watch BEFORE anything is paid for.

- A clip with an up-to-date 3D preview shows that preview.
- Your own video clips show your footage.
- Any other clip shows a card of the same length saying why it has no 3D preview (for example "3D camera reference
  off for this clip"), so the timing of the whole video is right.

It is saved as film.mp4 (to watch in the app) and, when Blender is installed, as film.blend: the same clips one after
another in Blender's video editor, each with its number and title on top.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Optional

from .. import media
from ..models import FilmPart, NodeKind, Project, Scene3DFilm, now_iso
from ..project import ProjectStore
from ..tree import leaves, numbering
from . import service as s3
from .render import REFERENCE_RESOLUTION, find_blender


class FilmError(RuntimeError):
    pass


def signature(p: Project) -> str:
    """What the film is made from: every clip, its length and its preview."""
    h = hashlib.sha1()
    for leaf in leaves(p):
        s = leaf.scene3d
        h.update(f"{s3.models_changed(p, leaf)}|".encode())
        h.update(f"{leaf.id}|{leaf.kind.value}|{leaf.duration.likely_s:.2f}|{s3.enabled_for(p, leaf)}|"
                 f"{s.plan_hash if s and s.video else ''}|{s3.stale_reason(leaf) if s and s.video else ''}|{leaf.media}\n".encode())
    h.update(p.settings.aspect.encode())
    return h.hexdigest()[:16]


def stale_reason(p: Project) -> str:
    f = p.scene3d_film
    if not f or not f.video:
        return "the whole 3D film has not been made yet"
    if f.signature != signature(p):
        return "a clip or its 3D preview changed after the film was made"
    return ""


def _why_none(p: Project, leaf) -> str:
    if leaf.kind == NodeKind.slides:
        return "slides (shown as they are)"
    if leaf.kind == NodeKind.user_clip:
        return "your own video"
    if not s3.enabled_for(p, leaf):
        return "3D camera reference off for this clip"
    if not leaf.script:
        return "no script yet"
    s = leaf.scene3d
    if not s or not s.plan:
        return "no 3D preview yet"
    if not s.video:
        return "the 3D preview is not rendered" + (f" ({s.notes[0]})" if s.notes else "")
    return s3.stale_reason(leaf)


async def make_film(svc, pid: str, prepare: bool = True, renderer: Optional[str] = None) -> Scene3DFilm:
    """Make (and, with prepare, first plan, fix and render) every clip's 3D preview, then join them into the film."""
    if prepare:
        from .agent import prepare_all
        await prepare_all(svc, pid, fix=True, renderer=renderer)
    p = svc.load(pid)
    base = ProjectStore.path_for(pid)
    out = base / "film3d"
    out.mkdir(parents=True, exist_ok=True)
    size = media.frame_size(p.settings.aspect, REFERENCE_RESOLUTION)
    fps = p.settings.fps
    nums = numbering(p)
    pieces: list[Path] = []
    parts: list[FilmPart] = []

    def build() -> None:
        for i, leaf in enumerate(leaves(p), 1):
            secs = max(leaf.duration.likely_s or 3.0, 1.0)
            piece = out / f"part_{i:02d}.mp4"
            s = leaf.scene3d
            why = _why_none(p, leaf)
            label = f"{nums.get(leaf.id, '')} · {leaf.title}"
            if leaf.kind == NodeKind.clip and s and s.video and not s3.stale_reason(leaf):
                media.normalize_clip(base / s.video, piece, size, fps, seconds=secs, keep_audio=False, fill="black")
                source = "3d"
            elif leaf.kind == NodeKind.user_clip and leaf.media and (base / leaf.media).exists() and \
                    (base / leaf.media).suffix.lower() in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
                media.normalize_clip(base / leaf.media, piece, size, fps, seconds=secs, keep_audio=False, fill="black")
                source = "footage"
            else:
                card = out / f"part_{i:02d}.png"
                media.placeholder_image(leaf.title or "Clip", card, size, subtitle=why[:1].upper() + why[1:], label=label)
                media.still_to_clip(card, piece, secs, size, fps, zoom=False)
                source = "card"
            pieces.append(piece)
            parts.append(FilmPart(nid=leaf.id, number=nums.get(leaf.id, ""), title=leaf.title, seconds=round(secs, 2),
                                  source=source, why="" if source == "3d" else why))
        if not pieces:
            raise FilmError("The video has no clips yet.")
        media.join_clips(pieces, ["cut"] * len(pieces), out / "film.mp4", size, fps)

    try:
        await asyncio.to_thread(build)
    except media.MediaError as exc:
        raise FilmError(f"The film could not be joined: {exc}") from exc
    notes: list[str] = []
    blend: Optional[Path] = None
    exe = find_blender(svc.config.blender_path)
    if exe:
        spec = out / "film.json"
        spec.write_text(json.dumps({"fps": fps, "width": size[0], "height": size[1],
                                    "clips": [{"path": str(pc.resolve()), "label": f"{pt.number} · {pt.title}",
                                               "frames": int(round(pt.seconds * fps))}
                                              for pc, pt in zip(pieces, parts)]}))
        script = Path(__file__).with_name("blender_film.py")
        proc = await asyncio.create_subprocess_exec(exe, "--background", "--factory-startup", "-noaudio", "--python", str(script),
                                                    "--", str(spec), str(out / "film.blend"),
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        log, _ = await proc.communicate()
        if proc.returncode == 0 and (out / "film.blend").exists():
            blend = out / "film.blend"
        else:
            notes.append("Blender could not put the film together: " + (log or b"").decode(errors="replace").strip()[-200:])
    else:
        notes.append("Blender is not installed, so the film can be watched here but not opened in Blender.")
    p = svc.load(pid)
    film = Scene3DFilm(video=str((out / "film.mp4").relative_to(base)), blend=str(blend.relative_to(base)) if blend else None,
                       parts=parts, seconds=round(sum(pt.seconds for pt in parts), 2), signature=signature(p),
                       notes=notes, updated_at=now_iso())
    p.scene3d_film = film
    svc.save(p, snapshot=False)
    return film
