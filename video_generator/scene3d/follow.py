"""Did the made clip follow the camera of its 3D reference? Measured, free, no AI.

How it works, in plain words:
1. Both videos are shrunk to small grey pictures, 6 per second.
2. Between every two neighbouring pictures, the tool measures how far the whole picture slid (left, right, up, down)
   with phase correlation, a standard way to line up two pictures.
3. Adding the slides up gives each video's camera path, for example "slides right, then up".
4. The two paths are compared on the same time line:
   - direction: do they move the same way at the same moments? (0 = opposite, 1 = the same)
   - amount: does the clip move about as much as the reference? (the smaller divided by the larger)
   camera_follow = 0.7 x direction + 0.3 x amount, from 0 (not followed) to 1 (followed closely).
   When the reference camera hardly moves, camera_follow says how still the clip's camera is.

It measures how the WHOLE picture moves. A camera that travels alongside its subject keeps the subject, the horizon and
the sky still, so such a shot reads as nearly still; a correct clip of it reads the same way, so they still compare
fairly. It sees slides (pans, tilts, sideways and up-down moves) best. A pure push-in or zoom slides very little, so for those
the Review Agent's look at the pictures matters more.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

from .. import media

FPS = 6
SIZE = (96, 54)
STILL = 0.06           # a camera path shorter than this (in picture widths) counts as a still camera


def _frames(video: Path, fps: int = FPS, size: tuple[int, int] = SIZE) -> np.ndarray:
    w, h = size
    out = subprocess.run([media.FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(video), "-vf",
                          f"fps={fps},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=300)
    if out.returncode != 0:
        raise media.MediaError(f"could not read {Path(video).name}: {out.stderr.decode(errors='replace')[-300:]}")
    data = np.frombuffer(out.stdout, dtype=np.uint8)
    n = len(data) // (w * h)
    return data[: n * w * h].reshape(n, h, w).astype(np.float64)


def _shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """How far picture b slid compared with picture a, in pixels (x to the right, y down)."""
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.fft2((a - a.mean()) * win), np.fft.fft2((b - b.mean()) * win)
    cross = fb * np.conj(fa)
    cross /= np.abs(cross) + 1e-9
    r = np.fft.ifft2(cross).real
    y, x = np.unravel_index(int(np.argmax(r)), r.shape)
    h, w = r.shape

    def refine(m, c, p):              # the peak between pixels: a parabola through the peak and its two neighbours
        d = m - 2 * c + p
        return 0.0 if abs(d) < 1e-12 else 0.5 * (m - p) / d
    fx = x + refine(r[y, (x - 1) % w], r[y, x], r[y, (x + 1) % w])
    fy = y + refine(r[(y - 1) % h, x], r[y, x], r[(y + 1) % h, x])
    return float(fx - w if fx > w / 2 else fx), float(fy - h if fy > h / 2 else fy)


def camera_path(video: Path) -> np.ndarray:
    """The picture's slide between neighbouring frames, as (x, y) in picture widths: shape (steps, 2)."""
    f = _frames(video)
    if len(f) < 2:
        return np.zeros((0, 2))
    steps = [_shift(f[i], f[i + 1]) for i in range(len(f) - 1)]
    return np.array(steps) / SIZE[0]


def _on_grid(steps: np.ndarray, n: int = 24) -> np.ndarray:
    """The added-up path at n even moments from start to end (so clips of slightly different length compare)."""
    cum = np.vstack([[0.0, 0.0], np.cumsum(steps, axis=0)])
    t = np.linspace(0, 1, len(cum))
    g = np.linspace(0, 1, n)
    return np.stack([np.interp(g, t, cum[:, 0]), np.interp(g, t, cum[:, 1])], axis=1)


def compare(reference: Path, take: Path) -> Optional[dict[str, float]]:
    """{camera_follow, camera_reference_move, camera_take_move}, or None when either video cannot be read."""
    try:
        ref, got = camera_path(reference), camera_path(take)
    except (media.MediaError, OSError, subprocess.SubprocessError):
        return None
    if len(ref) == 0 or len(got) == 0:
        return None
    a, b = _on_grid(ref), _on_grid(got)
    da, db = np.diff(a, axis=0), np.diff(b, axis=0)
    move_a = float(np.linalg.norm(da, axis=1).sum())
    move_b = float(np.linalg.norm(db, axis=1).sum())
    if move_a < STILL:
        follow = max(0.0, 1.0 - max(move_b - STILL, 0.0) / 0.3)          # a still reference: the clip should be still too
    else:
        weights = np.linalg.norm(da, axis=1)
        cos = (da * db).sum(axis=1) / (np.linalg.norm(da, axis=1) * np.linalg.norm(db, axis=1) + 1e-9)
        direction = float(((cos + 1) / 2 * weights).sum() / (weights.sum() + 1e-9))
        amount = min(move_a, move_b) / max(move_a, move_b, 1e-9)
        follow = 0.7 * direction + 0.3 * amount
    return {"camera_follow": round(follow, 2), "camera_reference_move": round(move_a, 3), "camera_take_move": round(move_b, 3)}
