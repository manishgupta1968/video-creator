"""Turn a scene plan into a reference video.

Two renderers, same result files:
1. Blender, run in the background (no window, no clicks). Used when Blender is installed.
2. The free sketch renderer: plain Python drawing of the same shapes with the same camera maths. Used when Blender is
   not installed, or when every Blender render engine fails. It is rougher, but the camera path and framing match.

Result files in the output folder:
    reference.mp4    the reference video (exact clip length, the video's shape, 24 fps by default)
    first.png        its first picture (made realistic later and used as the start picture)
    last.png         its last picture (the next clip that continues starts here)
    check_start.png, check_middle.png, check_end.png    three pictures for checking
    scene.blend      the Blender scene (Blender renderer only)
"""
from __future__ import annotations

import asyncio
import functools
import json
import os
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from .. import media
from .spec import ScenePlan, camera_at, corners, normalise, project

DEFAULT_ENGINES = ["BLENDER_WORKBENCH", "CYCLES"]     # Workbench is fast; Cycles on the CPU works even with no graphics card
REFERENCE_RESOLUTION = "480p"     # a reference needs clear movement, not detail; smaller renders much faster

# Making time per second of reference video at 480p, measured on a machine with no graphics card (Blender 4.0):
# Workbench about 35 s for 4 s at 360p, Cycles about 82 s. Scaled to 480p and rounded up so estimates are not low.
RENDER_S_PER_SECOND = {"BLENDER_WORKBENCH": 16.0, "CYCLES": 38.0, "sketch": 0.6}


def likely_engine(blender: str = "", engines: Optional[list[str]] = None, renderer: str = "auto") -> str:
    """The renderer that will most likely be used: 'sketch', or the first Blender engine that can run here."""
    if renderer == "sketch":
        return "sketch"
    return _likely_engine(blender, tuple(engines or DEFAULT_ENGINES))


@functools.lru_cache(maxsize=16)
def _likely_engine(blender: str, order: tuple) -> str:        # looks at the computer once (it does not change while running)
    if not find_blender(blender):
        return "sketch"
    import ctypes.util
    import sys
    for e in order:
        if e == "BLENDER_WORKBENCH" and sys.platform.startswith("linux") and not ctypes.util.find_library("EGL"):
            continue                     # no graphics libraries: Workbench cannot run here
        return e
    return order[-1]


def expected_seconds(clip_seconds: float, blender: str = "", engines: Optional[list[str]] = None, renderer: str = "auto") -> float:
    """About how long rendering a reference of this length takes, plus Blender's start-up."""
    engine = likely_engine(blender, engines, renderer)
    start = 0.0 if engine == "sketch" else 8.0
    return round(start + clip_seconds * RENDER_S_PER_SECOND.get(engine, 38.0), 0)


class RenderError(RuntimeError):
    pass


@dataclass
class RenderResult:
    renderer: str                    # blender | sketch
    video: Path
    first: Path
    last: Path
    checks: dict[str, Path] = field(default_factory=dict)
    blend: Optional[Path] = None
    engine: str = ""
    notes: list[str] = field(default_factory=list)


def find_blender(configured: str = "") -> Optional[str]:
    """The Blender program: the setting, then VG_BLENDER, then the PATH, then the usual install places."""
    for c in (configured, os.environ.get("VG_BLENDER", "")):
        if c and (Path(c).exists() or shutil.which(c)):
            return shutil.which(c) or c
    found = shutil.which("blender")
    if found:
        return found
    for c in ("/Applications/Blender.app/Contents/MacOS/Blender", r"C:\Program Files\Blender Foundation\Blender\blender.exe"):
        if Path(c).exists():
            return c
    return None


def build_script() -> Path:
    return Path(str(resources.files("video_generator.scene3d").joinpath("blender_build.py")))


def _encode(frames: list[Path], fps: int, out: Path) -> Path:
    """Pictures -> an mp4 every video model reads (H.264, yuv420p)."""
    folder = frames[0].parent
    tmp = folder / "_seq"
    tmp.mkdir(exist_ok=True)
    for i, f in enumerate(sorted(frames), 1):
        link = tmp / f"{i:05d}.png"
        link.unlink(missing_ok=True)
        try:
            link.symlink_to(f.resolve())
        except OSError:
            shutil.copy(f, link)
    media.ff("-framerate", str(fps), "-i", str(tmp / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-r", str(fps), str(out))
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def _finish(out_dir: Path, frames: list[Path], fps: int, renderer: str, **extra) -> RenderResult:
    if not frames:
        raise RenderError("the renderer made no pictures")
    frames = sorted(frames)
    video = _encode(frames, fps, out_dir / "reference.mp4")
    first, last = out_dir / "first.png", out_dir / "last.png"
    shutil.copy(frames[0], first)
    shutil.copy(frames[-1], last)
    checks = {}
    for name, f in (("start", frames[0]), ("middle", frames[len(frames) // 2]), ("end", frames[-1])):
        checks[name] = out_dir / f"check_{name}.png"
        shutil.copy(f, checks[name])
    return RenderResult(renderer=renderer, video=video, first=first, last=last, checks=checks, **extra)


# ----------------------------------------------------------------- Blender
async def render_blender(plan: ScenePlan, out_dir: Path, size: tuple[int, int], blender: str,
                         engines: Optional[list[str]] = None, timeout_s: int = 1800) -> RenderResult:
    p = normalise(plan)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_file = out_dir / "plan.json"
    plan_file.write_text(p.model_dump_json(indent=1))
    notes: list[str] = []
    for engine in engines or DEFAULT_ENGINES:
        shutil.rmtree(out_dir / "frames", ignore_errors=True)
        (out_dir / "result.json").unlink(missing_ok=True)
        cmd = [blender, "--background", "--factory-startup", "-noaudio", "--python", str(build_script()), "--",
               str(plan_file), str(out_dir), engine, str(size[0]), str(size[1])]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            log, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            notes.append(f"{engine}: Blender took longer than {timeout_s} s")
            continue
        (out_dir / f"blender_{engine.lower()}.log").write_bytes(log or b"")
        result = {}
        try:
            result = json.loads((out_dir / "result.json").read_text())
        except (OSError, ValueError):
            pass
        frames = sorted((out_dir / "frames").glob("*.png"))
        if proc.returncode == 0 and result.get("ok") and frames:
            return _finish(out_dir, frames, p.fps, "blender", blend=out_dir / "scene.blend", engine=engine,
                           notes=notes + [f"Rendered by Blender {result.get('blender', '')} ({engine})."])
        why = result.get("error") or (log or b"").decode(errors="replace").strip().splitlines()[-1:] or ["no pictures"]
        notes.append(f"{engine} did not work: {why if isinstance(why, str) else why[0]}")
    raise RenderError("Blender could not render the scene. " + " ".join(notes))


# ----------------------------------------------------------------- sketch
def _rgb(h: str) -> tuple[int, int, int]:
    h = (h or "#888888").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))   # type: ignore[return-value]


def _shade(c: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(v * f))) for v in c)   # type: ignore[return-value]


def _hull(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(pts))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p_ in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p_) <= 0:
            lower.pop()
        lower.append(p_)
    for p_ in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p_) <= 0:
            upper.pop()
        upper.append(p_)
    return lower[:-1] + upper[:-1]


def checker_step(plan: ScenePlan) -> float:
    """The size of one floor tile in metres: about 1 m in a room, larger in a big set (about 12 tiles along the long side)."""
    return max(1.0, round(max(plan.set.size[0], plan.set.size[1]) / 12))


def sketch_frame(plan: ScenePlan, t: float, size: tuple[int, int]) -> Image.Image:
    """One picture of the plan at time t: sky, a floor grid and every shape as a flat coloured block."""
    w, h = size
    img = Image.new("RGB", size, (140, 158, 184))
    draw = ImageDraw.Draw(img)
    eye, target, lens = camera_at(plan.camera, t)

    def to_px(pt):
        q = project(eye, target, lens, plan.aspect, pt)
        return (q[0] * w, q[1] * h, q[2]) if q else None

    lx, ly = plan.set.size[0], plan.set.size[1]
    # a checker floor of two greys: it makes the camera's movement visible (to the video model and to the camera check)
    step = checker_step(plan)
    light, dark = _rgb(plan.set.floor_colour), _shade(_rgb(plan.set.floor_colour), 0.8)
    nx, ny = max(1, round(lx / step)), max(1, round(ly / step))
    tiles = []
    for i in range(nx):
        for j in range(ny):
            x0, y0 = -lx / 2 + i * lx / nx, -ly / 2 + j * ly / ny
            x1, y1 = x0 + lx / nx, y0 + ly / ny
            pts = [to_px(c) for c in ([x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0])]
            if all(pts):
                tiles.append((sum(p_[2] for p_ in pts) / 4, (i + j) % 2, [(x, y) for x, y, _ in pts]))
    for _, odd, poly in sorted(tiles, key=lambda t: -t[0]):
        draw.polygon(poly, fill=dark if odd else light)
    blocks = []
    for th in plan.things:
        pts = [to_px(c) for c in corners(th, t)]
        if not all(pts):
            continue                          # partly behind the camera: left out of the sketch
        depth = sum(p_[2] for p_ in pts) / len(pts)
        blocks.append((depth, th, pts))
    for depth, th, pts in sorted(blocks, key=lambda b: -b[0]):     # far first, near last
        colour = _rgb(th.colour)
        base = [(p_[0], p_[1]) for i, p_ in enumerate(pts) if i % 2 == 0]
        top = [(p_[0], p_[1]) for i, p_ in enumerate(pts) if i % 2 == 1]
        draw.polygon(_hull(base + top), fill=_shade(colour, 0.75), outline=_shade(colour, 0.45))
        if len(_hull(top)) >= 3:
            draw.polygon(_hull(top), fill=colour)
    return img


async def render_sketch(plan: ScenePlan, out_dir: Path, size: tuple[int, int], why: str = "") -> RenderResult:
    p = normalise(plan)
    frames_dir = out_dir / "frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(p.model_dump_json(indent=1))
    n = max(1, int(round(p.seconds * p.fps)))

    def draw_all() -> list[Path]:
        out = []
        for i in range(n):
            f = frames_dir / f"{i + 1:04d}.png"
            sketch_frame(p, min(i / p.fps, p.seconds), size).save(f)
            out.append(f)
        return out
    frames = await asyncio.to_thread(draw_all)
    return _finish(out_dir, frames, p.fps, "sketch", notes=["Drawn by the free sketch renderer" + (f" ({why})." if why else ".")])


async def render(plan: ScenePlan, out_dir: Path, size: tuple[int, int], blender: str = "", engines: Optional[list[str]] = None,
                 use_blender: bool = True) -> RenderResult:
    """Blender when it is installed (and wanted); the sketch renderer otherwise, or when Blender fails."""
    exe = find_blender(blender) if use_blender else None
    if exe:
        try:
            return await render_blender(plan, out_dir, size, exe, engines)
        except RenderError as exc:
            res = await render_sketch(plan, out_dir, size, "Blender could not render it")
            res.notes.insert(0, str(exc))
            return res
    return await render_sketch(plan, out_dir, size, "Blender is not installed" if use_blender else "the sketch was asked for")
