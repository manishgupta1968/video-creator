"""Media helpers built on ffmpeg/ffprobe and Pillow (all local, free)."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

RES = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}


class MediaError(RuntimeError):
    pass


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run(args: list[str], timeout: int = 1800) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise MediaError(f"{Path(args[0]).name} failed: {proc.stderr[-1500:]}")
    return proc.stdout


def ff(*args: str, timeout: int = 1800) -> None:
    run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args], timeout=timeout)


def frame_size(aspect: str, resolution: str) -> tuple[int, int]:
    h = RES.get(resolution.lower(), 1080)
    try:
        a, b = (float(x) for x in aspect.split(":"))
    except ValueError:
        a, b = 16, 9
    if a >= b:
        w = int(round(h * a / b / 2) * 2)
        return w, h
    w = h
    return w, int(round(w * b / a / 2) * 2)


# ----------------------------------------------------------------- probing
def probe(path: Path) -> dict:
    out = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(out)


def video_size(path: Path) -> tuple[int, int]:
    """(width, height) of the first video stream, or (0, 0)."""
    try:
        v = next(x for x in probe(path)["streams"] if x.get("codec_type") == "video")
        return int(v["width"]), int(v["height"])
    except Exception:
        return 0, 0


def probe_duration(path: Path) -> float:
    try:
        return float(probe(path)["format"]["duration"])
    except Exception:
        return 0.0


def has_audio(path: Path) -> bool:
    try:
        return any(s.get("codec_type") == "audio" for s in probe(path)["streams"])
    except Exception:
        return False


def has_video(path: Path) -> bool:
    try:
        return any(s.get("codec_type") == "video" for s in probe(path)["streams"])
    except Exception:
        return False


def count_pages(path: Path) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(path) as doc:
            return doc.page_count
    if path.is_dir():
        return len([p for p in path.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
    return 1


# ----------------------------------------------------------------- slides & images
def office_to_pdf(path: Path, out_dir: Path) -> Path:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise MediaError("PowerPoint/Keynote import needs LibreOffice (https://www.libreoffice.org). Or export your slides as PDF.")
    out_dir.mkdir(parents=True, exist_ok=True)
    run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(path)], timeout=600)
    pdf = out_dir / (path.stem + ".pdf")
    if not pdf.exists():
        raise MediaError("slide conversion produced no PDF")
    return pdf


def pdf_to_images(pdf: Path, out_dir: Path, width: int = 1920) -> list[Path]:
    import fitz
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with fitz.open(pdf) as doc:
        for i, page in enumerate(doc, start=1):
            zoom = width / max(page.rect.width, 1)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            p = out_dir / f"slide_{i:03d}.png"
            pix.save(p)
            paths.append(p)
    return paths


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def placeholder_image(text: str, out: Path, size: tuple[int, int], subtitle: str = "",
                      seed: int = 0, base: Optional[Path] = None, label: str = "") -> Path:
    """A clean storyboard card used when no real image/video model is connected.
    Always stamped PREVIEW so nobody mistakes it for real footage."""
    w, h = size
    palette = [(30, 41, 59), (49, 46, 129), (22, 78, 99), (63, 63, 70), (88, 28, 135), (20, 83, 45)]
    top = palette[seed % len(palette)]
    img = Image.new("RGB", (w, h), top)
    if base and Path(base).exists():
        try:
            src = Image.open(base).convert("RGB")
            src.thumbnail((w, h))
            img.paste(src, ((w - src.width) // 2, (h - src.height) // 2))
            img = Image.blend(img, Image.new("RGB", (w, h), top), 0.35)
        except Exception:
            pass
    else:
        grad = Image.new("L", (1, h))
        for y in range(h):
            grad.putpixel((0, y), int(255 * y / h))
        dark = Image.new("RGB", (w, h), tuple(int(c * 0.35) for c in top))
        img = Image.composite(dark, img, grad.resize((w, h)))
    d = ImageDraw.Draw(img)
    pad = int(w * 0.07)
    # stamp (top-left) and clip label (top-right)
    stamp_font = _font(max(h // 36, 12))
    stamp = "PREVIEW — not real footage"
    tw = d.textlength(stamp, font=stamp_font)
    d.rounded_rectangle([pad, pad * 0.6, pad + tw + 24, pad * 0.6 + stamp_font.size + 14], radius=8, fill=(245, 158, 11))
    d.text((pad + 12, pad * 0.6 + 6), stamp, fill=(20, 20, 20), font=stamp_font)
    if label:
        lf = _font(max(h // 36, 12))
        lw = d.textlength(label, font=lf)
        d.text((w - pad - lw, pad * 0.6 + 6), label, fill=(226, 232, 240), font=lf)
    # main text: shrink the font until it fits, then cut with an ellipsis
    box_w, box_h = w - 2 * pad, int(h * 0.62)
    size1 = max(min(h // 17, w // 24), 16)
    text = " ".join(text.split())
    lines: list[str] = []
    while True:
        font = _font(size1)
        chars = max(int(box_w / (size1 * 0.55)), 10)
        lines = textwrap.wrap(text, width=chars) or [""]
        step = int(size1 * 1.35)
        if len(lines) * step <= box_h or size1 <= 15:
            break
        size1 -= 2
    max_lines = max(box_h // step, 1)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.;:") + " …"
    y = int(h * 0.2) + (box_h - len(lines) * step) // 2
    for line in lines:
        tw = d.textlength(line, font=font)
        d.text(((w - tw) / 2, y), line, fill=(248, 250, 252), font=font)
        y += step
    if subtitle:
        f2 = _font(max(h // 34, 12))
        tw = d.textlength(subtitle, font=f2)
        d.text(((w - tw) / 2, h - h // 8), subtitle, fill=(203, 213, 225), font=f2)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def photo_check(path: Path) -> dict:
    """Simple checks: resolution and blur (edge energy)."""
    try:
        img = Image.open(path).convert("L")
    except Exception as exc:
        return {"ok": False, "problems": [f"cannot open image: {exc}"]}
    problems = []
    if min(img.size) < 400:
        problems.append(f"low resolution ({img.size[0]}x{img.size[1]}); 1000 px or more is better")
    small = img.copy()
    small.thumbnail((512, 512))
    edges = small.filter(ImageFilter.FIND_EDGES)
    sharpness = ImageStat.Stat(edges).var[0]
    if sharpness < 60:
        problems.append("photo looks blurry")
    return {"ok": not problems, "problems": problems, "width": img.size[0], "height": img.size[1],
            "sharpness": round(sharpness, 1)}


def audio_check(path: Path) -> dict:
    secs = probe_duration(path)
    problems = []
    if secs < 5:
        problems.append(f"voice sample is short ({secs:.0f} s); 30 s – 2 min of clear speech clones best")
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-af", "astats=metadata=0", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=120).stderr
        floor = [float(l.split(":")[-1]) for l in out.splitlines() if "Noise floor dB" in l and "inf" not in l]
        if floor and max(floor) > -45:
            problems.append("background noise is high; a quieter recording clones better")
    except Exception:
        pass
    return {"ok": not problems, "problems": problems, "seconds": round(secs, 1)}


def clean_voice_sample(src: Path, out: Path) -> Path:
    ff("-i", str(src), "-af", "highpass=f=70,lowpass=f=12000,afftdn=nf=-25,loudnorm=I=-18:TP=-2",
       "-ar", "44100", "-ac", "1", str(out))
    return out


# ----------------------------------------------------------------- frames
def extract_frame(video: Path, out: Path, at: float = 0.0) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ff("-ss", f"{max(at, 0):.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out))
    return out


def last_frame(video: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        ff("-sseof", "-0.25", "-i", str(video), "-update", "1", "-q:v", "2", str(out))
    except MediaError:
        extract_frame(video, out, max(probe_duration(video) - 0.1, 0))
    return out


def sample_frames(video: Path, out_dir: Path, every: float = 1.0, max_frames: int = 12) -> list[tuple[float, Path]]:
    dur = probe_duration(video)
    if dur <= 0:
        return []
    n = min(max_frames, max(2, int(math.ceil(dur / every)) + 1))
    times = [min(dur - 0.05, i * dur / (n - 1)) for i in range(n)]
    out = []
    for i, t in enumerate(times):
        p = out_dir / f"frame_{i:02d}.jpg"
        try:
            extract_frame(video, p, t)
            out.append((round(t, 2), p))
        except MediaError:
            continue
    return out


# ----------------------------------------------------------------- audio
def silence(out: Path, seconds: float) -> Path:
    ff("-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{max(seconds, 0.1):.2f}", str(out))
    return out


def flite_available() -> bool:
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30).stdout
        return " flite " in out
    except Exception:
        return False


def concat_audio(parts: list[Path], out: Path, gap: float = 0.6, lead: float = 0.5) -> Path:
    """Join speech lines with small pauses, pad start/end."""
    if not parts:
        return silence(out, 1.0)
    inputs: list[str] = []
    filters = []
    for i, p in enumerate(parts):
        inputs += ["-i", str(p)]
        filters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]")
    chain = []
    n = len(parts)
    for i in range(n):
        delay = lead if i == 0 else gap
        filters.append(f"[a{i}]adelay={int(delay * 1000)}|{int(delay * 1000)}[d{i}]")
        chain.append(f"[d{i}]")
    filters.append("".join(chain) + f"concat=n={n}:v=0:a=1,apad=pad_dur={lead}[out]")
    ff(*inputs, "-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "44100", str(out))
    return out


def ambient_pad(out: Path, seconds: float, mood: str = "") -> Path:
    """A soft free music bed (two detuned sines + slow tremolo)."""
    base = 196 if "dark" in mood or "tense" in mood else 261.6
    expr = f"0.08*sin(2*PI*{base}*t)+0.06*sin(2*PI*{base * 1.5:.1f}*t)+0.04*sin(2*PI*{base * 2.01:.1f}*t)"
    ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={seconds:.2f}", "-af",
       f"tremolo=f=0.2:d=0.4,afade=t=in:d=2,afade=t=out:st={max(seconds - 2.5, 0):.2f}:d=2.5,aformat=channel_layouts=stereo",
       str(out))
    return out


# ----------------------------------------------------------------- video building
def normalize_clip(src: Path, out: Path, size: tuple[int, int], fps: int, seconds: Optional[float] = None,
                   keep_audio: bool = True, fill: str = "black") -> Path:
    """Fit to the frame, set fps, optional exact length (trim or freeze last frame).

    fill: what goes around a picture that is not the frame's shape. black (bars), blur (a blurred, enlarged
    copy of the picture behind it) or crop (fill the frame, losing the edges). Matching shapes are not touched."""
    w, h = size
    sw, sh = video_size(src)
    if sw and sh and abs(sw / sh - w / h) < 0.02:
        fill = "same"                                   # already the right shape: only scale, never blur or pad
    if fill == "same":
        fit = f"scale={w}:{h}"
    elif fill == "blur":
        fit = (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:4[bg];"
               f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    elif fill == "crop":
        fit = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    else:
        fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
    vf = f"{fit},setsar=1,fps={fps},format=yuv420p"
    args = ["-i", str(src)]
    if seconds:
        dur = probe_duration(src)
        if dur and dur < seconds:
            vf += f",tpad=stop_mode=clone:stop_duration={seconds - dur + 0.05:.2f}"
    a_ok = keep_audio and has_audio(src)
    if not a_ok:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    args += ["-vf", vf, "-map", "0:v:0", "-map", "0:a:0" if a_ok else "1:a:0",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-ar", "44100", "-ac", "2"]
    if seconds:
        args += ["-t", f"{seconds:.2f}"]
    else:
        args += ["-shortest"] if not a_ok else []
    ff(*args, str(out))
    return out


def fit_image(src: Path, out: Path, aspect: str, mode: str = "cover", long_side: int = 1536) -> Path:
    """Make a picture exactly the shape of the video (aspect like 16:9, 9:16, 1:1, 4:5).

    cover: fill the frame and crop the overflow (centre). blur: keep the whole picture on a blurred copy of itself.
    black: keep the whole picture on black. Pictures that already have the shape are only copied."""
    from PIL import Image, ImageFilter
    try:
        a, b = (float(x) for x in aspect.split(":"))
    except ValueError:
        a, b = 16.0, 9.0
    target = a / b
    img = Image.open(src).convert("RGB")
    iw, ih = img.size
    if abs(iw / ih - target) < 0.02:
        img.save(out)
        return out
    tw, th = (long_side, round(long_side / target)) if target >= 1 else (round(long_side * target), long_side)
    if mode == "cover":
        scale = max(tw / iw, th / ih)
        r = img.resize((max(round(iw * scale), tw), max(round(ih * scale), th)), Image.LANCZOS)
        left, top = (r.width - tw) // 2, (r.height - th) // 2
        canvas = r.crop((left, top, left + tw, top + th))
    else:
        scale = min(tw / iw, th / ih)
        fg = img.resize((max(round(iw * scale), 1), max(round(ih * scale), 1)), Image.LANCZOS)
        if mode == "blur":
            bs = max(tw / iw, th / ih)
            bg = img.resize((max(round(iw * bs), tw), max(round(ih * bs), th)), Image.BILINEAR)
            bl, bt = (bg.width - tw) // 2, (bg.height - th) // 2
            canvas = bg.crop((bl, bt, bl + tw, bt + th)).filter(ImageFilter.GaussianBlur(28))
        else:
            canvas = Image.new("RGB", (tw, th), (0, 0, 0))
        canvas.paste(fg, ((tw - fg.width) // 2, (th - fg.height) // 2))
    canvas.save(out)
    return out


def bars(video_or_image: Path, at: float = 0.5) -> dict:
    """Detect black bars: the share of each side that is (almost) pure black. Used to prove nothing is padded with black."""
    import subprocess
    import tempfile
    from PIL import Image
    tmp = Path(tempfile.mkdtemp()) / "f.png"
    if video_or_image.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        img = Image.open(video_or_image).convert("L")
    else:
        extract_frame(video_or_image, tmp, at=at)
        img = Image.open(tmp).convert("L")
    w, h = img.size
    px = img.load()

    def dark_cols() -> tuple[int, int]:
        def run(rng):
            n = 0
            for x in rng:
                if max(px[x, y] for y in range(0, h, max(h // 40, 1))) <= 12:
                    n += 1
                else:
                    break
            return n
        return run(range(w)), run(range(w - 1, -1, -1))

    def dark_rows() -> tuple[int, int]:
        def run(rng):
            n = 0
            for y in rng:
                if max(px[x, y] for x in range(0, w, max(w // 40, 1))) <= 12:
                    n += 1
                else:
                    break
            return n
        return run(range(h)), run(range(h - 1, -1, -1))
    l, r = dark_cols()
    t, b = dark_rows()
    return {"left": l / w, "right": r / w, "top": t / h, "bottom": b / h}


# ----------------------------------------------------------------- voice pitch
def voice_pitch(path: Path) -> Optional[float]:
    """Median pitch of the speech in Hz (about 85-180 for most men, 165-260 for most women), or None.
    Plain autocorrelation on 8 kHz audio: no extra libraries needed."""
    import array
    import statistics
    import tempfile
    import wave
    tmp = Path(tempfile.mkdtemp()) / "p.wav"
    try:
        ff("-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-sample_fmt", "s16", str(tmp))
        with wave.open(str(tmp)) as w:
            data = array.array("h", w.readframes(w.getnframes()))
    except Exception:
        return None
    sr, frame, hop = 8000, 320, 160
    if len(data) < frame * 3:
        return None
    peak = max(abs(x) for x in data) or 1
    x = [v / peak for v in data]
    lo, hi = sr // 400, sr // 70
    try:
        import numpy as np
        arr = np.asarray(x)
    except ImportError:
        arr = None
    f0s: list[float] = []
    for i in range(0, len(x) - frame, hop):
        seg = x[i:i + frame]
        if (sum(v * v for v in seg) / frame) ** 0.5 < 0.06:
            continue
        mean = sum(seg) / frame
        seg = [v - mean for v in seg]
        if arr is not None:
            s = np.asarray(seg)
            ac = np.correlate(s, s, "full")[frame - 1:]
            k = lo + int(np.argmax(ac[lo:hi]))
            ratio = ac[k] / (ac[0] + 1e-9)
        else:
            ac0 = sum(v * v for v in seg) or 1e-9
            best_k, best = lo, -1.0
            for k_ in range(lo, hi):
                c = sum(seg[j] * seg[j + k_] for j in range(frame - k_))
                if c > best:
                    best, best_k = c, k_
            k, ratio = best_k, best / ac0
        if ratio > 0.45:
            f0s.append(sr / k)
    return round(statistics.median(f0s), 1) if len(f0s) >= 5 else None


def shift_voice(src: Path, out: Path, semitones: float = 0.0, tempo: float = 1.0) -> Path:
    """Change a voice's pitch (semitones, negative = deeper) and speed (tempo < 1 = slower) with ffmpeg.
    The pitch change keeps the speed; asetrate+atempo does the work, no extra libraries."""
    rate = 44100
    ratio = 2 ** (semitones / 12.0)
    chain = [f"asetrate={rate * ratio:.0f}", f"aresample={rate}"]
    speed = tempo / ratio                      # undo the speed change that asetrate causes, then apply the wanted tempo
    while speed < 0.5 or speed > 2.0:
        step = 0.5 if speed < 0.5 else 2.0
        chain.append(f"atempo={step}")
        speed /= step
    chain.append(f"atempo={speed:.4f}")
    ff("-i", str(src), "-af", ",".join(chain), "-ar", str(rate), str(out))
    return out


# ----------------------------------------------------------------- free natural sound
AMBIENCE_RECIPES = {
    # keywords -> (noise colour, low-pass Hz, high-pass Hz, slow movement Hz, level)
    "wind": ("pink", 900, 80, 0.12, 0.22), "breeze": ("pink", 700, 60, 0.10, 0.18), "grass": ("pink", 1200, 120, 0.15, 0.18),
    "rain": ("white", 6000, 600, 0.0, 0.22), "storm": ("brown", 2500, 60, 0.08, 0.30), "sea": ("brown", 1500, 50, 0.09, 0.25),
    "wave": ("brown", 1500, 50, 0.09, 0.25), "river": ("white", 3500, 300, 0.1, 0.18),
    "crowd": ("pink", 2800, 200, 0.3, 0.2), "street": ("brown", 2500, 90, 0.2, 0.2), "traffic": ("brown", 1800, 60, 0.15, 0.22),
    "office": ("brown", 1200, 70, 0.0, 0.07), "room": ("brown", 900, 60, 0.0, 0.06), "studio": ("brown", 900, 60, 0.0, 0.05),
    "kitchen": ("brown", 1400, 70, 0.0, 0.08), "forest": ("pink", 3000, 150, 0.12, 0.16), "city": ("brown", 2200, 80, 0.18, 0.2),
}


def local_ambience(out: Path, seconds: float, notes: str = "") -> Path:
    """A free, plain natural-sound bed made with ffmpeg noise filters, picked from the words in the sound notes
    (wind, rain, sea, crowd, traffic, office, room tone ...). It is a safety net: a real sound model sounds better."""
    text = (notes or "").lower()
    recipe = next((r for k, r in AMBIENCE_RECIPES.items() if k in text), ("brown", 900, 60, 0.0, 0.06))   # default: quiet room tone
    colour, lp, hp, move, level = recipe
    sec = max(seconds, 0.5)
    chain = f"highpass=f={hp},lowpass=f={lp},volume={level * 2.5:.3f}"
    if move > 0:
        chain += f",tremolo=f={move}:d=0.5"
    chain += f",afade=t=in:d=0.4,afade=t=out:st={max(sec - 0.6, 0):.2f}:d=0.6,aformat=channel_layouts=stereo"
    ff("-f", "lavfi", "-i", f"anoisesrc=color={colour}:r=44100:d={sec:.2f}", "-af", chain, str(out))
    return out


def still_to_clip(image: Path, out: Path, seconds: float, size: tuple[int, int], fps: int, zoom: bool = True) -> Path:
    w, h = size
    frames = max(int(seconds * fps), 1)
    if zoom:
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"zoompan=z='min(1+0.0009*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps},"
              f"format=yuv420p")
    else:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"
    ff("-loop", "1", "-i", str(image), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
       "-vf", vf, "-t", f"{seconds:.2f}", "-map", "0:v", "-map", "1:a",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-shortest", str(out))
    return out


def replace_audio(video: Path, voice: Optional[Path], out: Path, keep_original: float = 0.35,
                  extra: Optional[list[tuple[Path, float]]] = None) -> Path:
    """Mix: clip's own sound (lowered) + voice + extra sound effects."""
    inputs = ["-i", str(video)]
    mixes = []
    idx = 1
    if has_audio(video) and keep_original > 0:
        mixes.append(f"[0:a]volume={keep_original}[o]")
        labels = ["[o]"]
    else:
        labels = []
    if voice:
        inputs += ["-i", str(voice)]
        mixes.append(f"[{idx}:a]aresample=44100,volume=1.0[v]")
        labels.append("[v]")
        idx += 1
    for path, vol in extra or []:
        inputs += ["-i", str(path)]
        mixes.append(f"[{idx}:a]aresample=44100,volume={vol}[x{idx}]")
        labels.append(f"[x{idx}]")
        idx += 1
    if not labels:
        shutil.copy(video, out)
        return out
    mixes.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0[mix]")
    ff(*inputs, "-filter_complex", ";".join(mixes), "-map", "0:v", "-map", "[mix]", "-c:v", "copy",
       "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out))
    return out


XFADE = {"crossfade": "fade", "fade_black": "fadeblack", "whip": "slideleft", "dissolve": "dissolve", "wipe": "wipeleft"}


def join_clips(clips: list[Path], transitions: list[str], out: Path, size: tuple[int, int], fps: int,
               tdur: float = 0.5) -> Path:
    """Join normalized clips; transitions[i] is the transition INTO clip i (i>=1)."""
    if not clips:
        raise MediaError("nothing to join")
    if len(clips) == 1:
        shutil.copy(clips[0], out)
        return out
    if all(t in ("cut", "", None) for t in transitions[1:]):
        lst = out.with_suffix(".txt")
        lst.write_text("".join(f"file '{Path(c).resolve().as_posix()}'\n" for c in clips))
        ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out))
        lst.unlink(missing_ok=True)
        return out
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    durs = [probe_duration(c) for c in clips]
    filters = []
    vprev, aprev = "[0:v]", "[0:a]"
    offset = 0.0
    for i in range(1, len(clips)):
        t = transitions[i] if i < len(transitions) else "cut"
        d = tdur if t not in ("cut", "", None) else 0.04
        kind = XFADE.get(t, "fade")
        offset += durs[i - 1] - d
        offset = max(offset, 0.01)
        filters.append(f"{vprev}[{i}:v]xfade=transition={kind}:duration={d}:offset={offset:.3f}[v{i}]")
        filters.append(f"{aprev}[{i}:a]acrossfade=d={d}[a{i}]")
        vprev, aprev = f"[v{i}]", f"[a{i}]"
    ff(*inputs, "-filter_complex", ";".join(filters), "-map", vprev, "-map", aprev,
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps), "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out))
    return out


def add_music(video: Path, music: Path, out: Path, music_volume: float = 0.18) -> Path:
    """Duck music under speech (sidechain) and normalize loudness."""
    ff("-i", str(video), "-stream_loop", "-1", "-i", str(music), "-filter_complex",
       f"[1:a]volume={music_volume},aformat=channel_layouts=stereo[m];"
       f"[0:a]asplit=2[voice][sc];[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
       f"[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
       "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(out))
    return out


def loudnorm(video: Path, out: Path) -> Path:
    ff("-i", str(video), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy", "-c:a", "aac", str(out))
    return out


def burn_subtitles(video: Path, srt: Path, out: Path) -> Path:
    path = srt.resolve().as_posix().replace(":", "\\:").replace("'", "\\'")
    ff("-i", str(video), "-vf", f"subtitles='{path}':force_style='FontSize=18,Outline=1,MarginV=28'",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", str(out))
    return out


def to_format(video: Path, out: Path, fmt: str) -> Path:
    if fmt == "mov":
        ff("-i", str(video), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac",
           "-movflags", "+faststart", "-f", "mov", str(out))
    else:
        ff("-i", str(video), "-c", "copy", "-movflags", "+faststart", str(out))
    return out


def silent_proxy(video: Path, out: Path, height: int = 360) -> Path:
    """A small copy of a clip without sound (for models that only need to see the pictures)."""
    ff("-i", str(video), "-an", "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", str(out))
    return out


def proxy(video: Path, out: Path, height: int = 360) -> Path:
    ff("-i", str(video), "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
       "-c:a", "aac", "-b:a", "96k", str(out))
    return out


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(entries: list[tuple[float, float, str]], out: Path) -> Path:
    lines = []
    for i, (a, b, text) in enumerate(entries, start=1):
        lines.append(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text.strip()}\n")
    out.write_text("\n".join(lines))
    return out


def motion_stats(video: Path) -> dict:
    """How much actually moves. motion = mean frame-to-frame luma change (a real scene is ~1-3; a still
    image is 0; a slow zoom on a photo is below ~1). static_ratio = share of frames that are identical."""
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-f", "lavfi", "-i",
                              f"movie={Path(video).as_posix()},signalstats", "-show_entries",
                              "frame_tags=lavfi.signalstats.YDIF", "-of", "csv=p=0"],
                             capture_output=True, text=True, timeout=300).stdout
        vals = [float(x) for x in out.split() if x.replace(".", "", 1).isdigit()]
        if not vals:
            return {}
        mean = sum(vals) / len(vals)
        return {"motion": round(mean, 3), "static_ratio": round(sum(1 for v in vals if v < 0.05) / len(vals), 3),
                "flicker": round(sum(1 for v in vals if v > mean * 3 + 2) / len(vals), 4)}
    except Exception:
        return {}


def image_sharpness(path: Path) -> float:
    """Edge energy of a picture (higher = sharper). Only meaningful when compared with another picture of the same scene."""
    try:
        im = Image.open(path).convert("L")
        im.thumbnail((640, 640))
        return round(ImageStat.Stat(im.filter(ImageFilter.FIND_EDGES)).var[0], 2)
    except Exception:
        return 0.0


def sharpness_ratio(video: Path, reference: Optional[Path], tmp_dir: Path) -> dict:
    """Sharpness of the video's frames, and relative to the picture the clip started from."""
    frames = sample_frames(video, tmp_dir, every=1.5, max_frames=5)
    vals = [image_sharpness(p) for _, p in frames]
    vals = [v for v in vals if v > 0]
    if not vals:
        return {}
    out = {"sharpness": round(sum(vals) / len(vals), 1)}
    if reference and Path(reference).exists():
        ref = image_sharpness(reference)
        if ref > 0:
            out["sharpness_vs_start"] = round(out["sharpness"] / ref, 2)
    return out


def audio_stats(video: Path) -> dict:
    """Loudness (LUFS), peak, and how much of the clip is silent."""
    if not has_audio(video):
        return {"has_audio": 0}
    out: dict = {"has_audio": 1}
    try:
        err = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af",
                              "ebur128=peak=true,silencedetect=n=-45dB:d=0.4", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=300).stderr
        lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
        peak = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)
        if lufs:
            out["lufs"] = float(lufs[-1])
        if peak:
            out["peak_db"] = float(peak[-1])
        dur = probe_duration(video) or 1
        sil = sum(float(x) for x in re.findall(r"silence_duration:\s+([\d.]+)", err))
        out["silence_ratio"] = round(min(sil / dur, 1.0), 3)
    except Exception:
        pass
    return out


def sample_pairs(video: Path, out_dir: Path, n: int = 3, gap: float = 0.25) -> list[tuple[float, Path]]:
    """Adjacent frame pairs (t, t+gap) at spread-out moments: exposes warping, morphing and identity changes."""
    dur = probe_duration(video)
    if dur < 1.0:
        return []
    out = []
    for k in range(n):
        t = min(max(dur * (k + 1) / (n + 1), 0.0), dur - gap - 0.05)
        for j, tt in enumerate((t, t + gap)):
            p = out_dir / f"pair_{k}_{j}.jpg"
            try:
                extract_frame(video, p, tt)
                out.append((round(tt, 2), p))
            except MediaError:
                continue
    return out


def frame_diff_score(video: Path) -> float:
    """Average frame-to-frame luma change (YDIF). High spikes suggest flicker."""
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-f", "lavfi", "-i",
                              f"movie={Path(video).as_posix()},signalstats", "-show_entries",
                              "frame_tags=lavfi.signalstats.YDIF", "-of", "csv=p=0"],
                             capture_output=True, text=True, timeout=300).stdout
        vals = [float(x) for x in out.split() if x.replace(".", "", 1).isdigit()]
        if not vals:
            return 0.0
        mean = sum(vals) / len(vals)
        spikes = sum(1 for v in vals if v > mean * 3 + 2)
        return round(spikes / max(len(vals), 1), 4)
    except Exception:
        return 0.0
