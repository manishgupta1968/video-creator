"""Media helpers built on ffmpeg/ffprobe and Pillow (all local, free)."""
from __future__ import annotations

import json
import math
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
                      seed: int = 0, base: Optional[Path] = None) -> Path:
    """A clean storyboard card (free preview keyframe)."""
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
    f1, f2 = _font(max(h // 18, 18)), _font(max(h // 34, 12))
    lines = textwrap.wrap(text, width=48)[:6]
    y = h // 2 - len(lines) * (h // 30)
    for line in lines:
        tw = d.textlength(line, font=f1)
        d.text(((w - tw) / 2, y), line, fill=(248, 250, 252), font=f1)
        y += int(h / 15)
    if subtitle:
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
                   keep_audio: bool = True) -> Path:
    """Scale/pad to frame, set fps, optional exact length (trim or freeze last frame)."""
    w, h = size
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p"
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
