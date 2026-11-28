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
        h.update(json.dumps(_lines(p, leaf)).encode() + f"|{leaf.voice_audio or ''}|".encode())   # the spoken words are in the film
        h.update(f"{leaf.id}|{leaf.kind.value}|{leaf.duration.likely_s:.2f}|{s3.enabled_for(p, leaf)}|"
                 f"{s.plan_hash if s and s.video else ''}|{s3.stale_reason(leaf) if s and s.video else ''}|{leaf.media}\n".encode())
    h.update(p.settings.aspect.encode() + p.settings.scene3d.film_voice.encode())
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


def _lines(project, node) -> list[tuple[str, str, str]]:
    """(speaker, words, language) of every spoken line of a clip: its dialogue, then its narration."""
    from .. import casting
    sc = node.script
    if not sc:
        return []
    out = [(d.speaker, d.text.strip(), casting.line_language(project, d.speaker, d.language)) for d in sc.dialogue if d.text.strip()]
    who = sc.narration_by or "narrator"
    if sc.narration_audio:                       # your own recording (the path is part of the line, so a new one is noticed)
        out.append(("(your recording)", sc.narration_audio, ""))
    elif sc.narration.strip():
        out.append((who, sc.narration.strip(), casting.line_language(project, who, sc.narration_language)))
    return out


def _free_voice(svc, language: str):
    """The best free voice on this computer for a language (your computer's own voice speaks most languages)."""
    order = ["system_voice", "kokoro", "flite"] if language and language != "en" else ["kokoro", "system_voice", "flite"]
    for name in order:
        try:
            if svc.reg.configured(name):
                return svc.reg.plugin(name)
        except Exception:
            continue
    return None


async def clip_voice(svc, pid: str, node, mode: str) -> tuple[Optional[Path], str]:
    """The spoken words of one clip as one sound file, and where they came from. The voice made for the real video is
    used when it exists (its words have not changed since); else your voice service ("service": made once, and the
    video reuses it), else your computer's own voice (free, rough, but it shows the timing)."""
    from ..plugins.base import PluginError, VoiceSpec
    p = svc.load(pid)
    lines = _lines(p, node)
    if not lines or mode == "off":
        return None, ""
    base = ProjectStore.path_for(pid)
    if node.voice_audio and (base / node.voice_audio).exists():
        return base / node.voice_audio, "the voice made for the video"
    if mode == "service":
        try:
            engine = getattr(svc, "engine", None)
            if engine is None:
                from ..runner import Engine
                engine = Engine(svc)
            await engine._make_voice(pid, node.id)
            n = next(l for l in leaves(svc.load(pid)) if l.id == node.id)
            if n.voice_audio and (base / n.voice_audio).exists():
                return base / n.voice_audio, "your voice service (the video will reuse it)"
        except Exception as exc:                  # fall back to the free voice, and say why
            note = f"your voice service could not speak it ({str(exc)[:120]}), so your computer's voice is used"
        else:
            note = "your voice service gave no sound, so your computer's voice is used"
    else:
        note = "your computer's own voice (free preview)"
    stamp = [int((base / w).stat().st_mtime) if sp == "(your recording)" and (base / w).exists() else 0 for sp, w, _ in lines]
    key = hashlib.sha1(json.dumps([lines, stamp]).encode()).hexdigest()[:12]
    out = base / "film3d" / "voice" / f"{node.id}_{key}.wav"
    if len(lines) == 1 and lines[0][0] == "(your recording)":
        note = "your own recording"
    if out.exists():
        return out, note
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, (speaker, words, lang) in enumerate(lines):
        if speaker == "(your recording)":
            rec = base / words
            if rec.exists():
                part = out.parent / f"{node.id}_{key}_{i:02d}.wav"
                await asyncio.to_thread(media.ff, "-i", str(rec), "-ar", "44100", "-ac", "1", str(part))
                parts.append(part)
                note = "your own recording" if len(lines) == 1 else note + " and your own recording"
            continue
        plugin = _free_voice(svc, lang)
        if plugin is None:
            return None, "no voice on this computer (install espeak-ng, or choose your voice service)"
        part = out.parent / f"{node.id}_{key}_{i:02d}.wav"
        try:
            await plugin.synthesize(words, VoiceSpec(language=lang), part)
        except PluginError as exc:
            return None, f"your computer's voice could not speak it: {exc}"
        parts.append(part)
    from ..policy import current as _policy
    await asyncio.to_thread(media.concat_audio, parts, out, _policy().line_pause, _policy().edge_pad)
    for part in parts:
        part.unlink(missing_ok=True)
    return out, note


def _what_was_done(reports, nums: dict, replan: bool) -> list[str]:
    """What making the film really did, in plain words (so a quick run is not mistaken for nothing happening)."""
    planned = [nums.get(r.nid, "") for r in reports if r.planned]
    rendered = [nums.get(r.nid, "") for r in reports if r.rendered]
    kept = [nums.get(r.nid, "") for r in reports if not r.rendered and not r.error]
    lines = []
    if planned:
        lines.append(f"Planned {'afresh' if replan else 'now'}: clip {', '.join(planned)}.")
    if rendered:
        lines.append(f"Rendered now: clip {', '.join(rendered)}.")
    if kept and not rendered and not planned:
        lines.append("Nothing had changed since the last time, so every clip's 3D preview was kept and the film was only joined again "
                     "(that takes a second). To change it, use \"Change the whole 3D film\", or \"Plan every scene again\" for new scenes.")
    elif kept:
        lines.append(f"Kept (already up to date): clip {', '.join(kept)}.")
    lines += [f"Clip {nums.get(r.nid, '')} could not be made: {r.error}" for r in reports if r.error]
    return lines


async def make_film(svc, pid: str, prepare: bool = True, renderer: Optional[str] = None, replan: bool = False,
                    done: Optional[list[str]] = None) -> Scene3DFilm:
    """Make (and, with prepare, first plan, fix and render) every clip's 3D preview, then join them into the film.
    replan: plan every scene afresh first. The film's notes say what was really done."""
    done = list(done or [])
    if prepare:
        from .agent import prepare_all
        mark = ProjectStore.history_mark(svc.load(pid)) if replan else None    # new plans for every scene: ONE undo step
        try:
            reports = await prepare_all(svc, pid, fix=True, renderer=renderer, replan=replan)
        finally:
            if mark is not None:
                ProjectStore.collapse_history(pid, mark)
        done += _what_was_done(reports, numbering(svc.load(pid)), replan)
    p = svc.load(pid)
    base = ProjectStore.path_for(pid)
    out = base / "film3d"
    out.mkdir(parents=True, exist_ok=True)
    mode = p.settings.scene3d.film_voice
    voices: dict[str, tuple[Optional[Path], str]] = {}
    for leaf in leaves(p):                       # the spoken words of each clip, made before the film is joined
        if leaf.kind == NodeKind.clip:
            voices[leaf.id] = await clip_voice(svc, pid, leaf, mode)
    p = svc.load(pid)
    size = media.frame_size(p.settings.aspect, REFERENCE_RESOLUTION)
    fps = p.settings.fps
    nums = numbering(p)
    pieces: list[Path] = []
    parts: list[FilmPart] = []
    audio_for: dict[int, str] = {}               # piece number -> the sound file of its spoken words (for Blender)
    heard: list[str] = []
    timing: list[str] = []

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
            voice, spoken_by = voices.get(leaf.id, (None, ""))
            if voice is not None and voice.exists():
                said = media.probe_duration(voice)
                spoken = out / f"part_{i:02d}_voice.mp4"
                media.replace_audio(piece, voice, spoken, keep_original=0)
                piece.unlink(missing_ok=True)
                spoken.rename(piece)
                audio_for[i] = str(voice.resolve())
                heard.append(f"{label}: {spoken_by}")
                if said > secs + 0.2:
                    timing.append(f"Clip {nums.get(leaf.id, '')}: the spoken words take {said:.1f} s but the clip is {secs:.1f} s, "
                                  "so the end is cut in this film. Shorten the words, or make the clip longer.")
            elif spoken_by and _lines(p, leaf):
                heard.append(f"{label}: no sound ({spoken_by})")
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
    notes: list[str] = done
    if heard:
        notes.append("Spoken words: " + "; ".join(heard) + ".")
    notes += timing
    blend: Optional[Path] = None
    exe = find_blender(svc.config.blender_path)
    if exe:
        spec = out / "film.json"
        spec.write_text(json.dumps({"fps": fps, "width": size[0], "height": size[1],
                                    "clips": [{"path": str(pc.resolve()), "label": f"{pt.number} · {pt.title}",
                                               "frames": int(round(pt.seconds * fps)), "audio": audio_for.get(k + 1, "")}
                                              for k, (pc, pt) in enumerate(zip(pieces, parts))]}))
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
