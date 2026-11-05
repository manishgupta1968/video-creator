"""Free local stand-ins for every paid job, so a full draft video can be made
offline at no cost (storyboard cards with gentle motion, real timing)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from ... import media
from ..base import (AvatarGenerator, AvatarRequest, ImageGenerator, ImageRequest, LipSync, MusicGenerator,
                    Segment, Transcriber, Usage, VideoGenerator, VideoRequest)


class FakeImage(ImageGenerator):
    name = "fake_image"
    env_keys: list[str] = []
    description = "Free storyboard card (placeholder keyframe)"

    async def generate(self, req: ImageRequest):
        size = media.frame_size(req.aspect, "720p")
        base = req.references[0] if req.references else None
        seed = abs(hash(req.prompt)) % 97
        media.placeholder_image(req.prompt, req.out, size, subtitle="", seed=seed, base=base, label=req.label)
        return req.out, Usage()


class FakeVideo(VideoGenerator):
    name = "fake_video"
    env_keys: list[str] = []
    description = "Free preview motion (slow zoom on the keyframe)"

    async def generate(self, req: VideoRequest):
        size = media.frame_size(req.aspect, "720p")
        still = req.start_frame
        if not still or not Path(still).exists():
            still = req.out.with_suffix(".png")
            media.placeholder_image(req.prompt, still, size, label=req.label)
        media.still_to_clip(Path(still), req.out, max(req.seconds, 1.0), size, 24, zoom=True)
        return req.out, Usage(seconds=req.seconds)


class FakeAvatar(AvatarGenerator):
    name = "fake_avatar"
    env_keys: list[str] = []
    description = "Free preview presenter (photo with voice)"

    async def generate(self, req: AvatarRequest):
        size = media.frame_size(req.aspect, "720p")
        secs = media.probe_duration(req.audio) or 3
        still = req.photo
        if not still or not Path(still).exists():
            still = req.out.with_suffix(".png")
            media.placeholder_image(req.prompt or "Presenter", still, size, subtitle="preview presenter", label=req.label)
        tmp = req.out.with_name(req.out.stem + "_silent.mp4")
        media.still_to_clip(Path(still), tmp, secs, size, 24, zoom=True)
        media.replace_audio(tmp, req.audio, req.out, keep_original=0)
        tmp.unlink(missing_ok=True)
        return req.out, Usage(seconds=secs)


class FakeLipSync(LipSync):
    name = "fake_lipsync"
    env_keys: list[str] = []
    description = "No lip change (passthrough)"

    async def sync(self, video: Path, audio: Path, out: Path, model: str = ""):
        shutil.copy(video, out)
        return out, Usage()


class FakeMusic(MusicGenerator):
    name = "fake_music"
    env_keys: list[str] = []
    description = "Free ambient pad"

    async def generate(self, prompt: str, seconds: float, out: Path, model: str = "", reference: Optional[Path] = None):
        media.ambient_pad(out, seconds, prompt.lower())
        return out, Usage(seconds=seconds)


class FakeTranscriber(Transcriber):
    name = "fake_transcribe"
    env_keys: list[str] = []
    description = "Assumes the audio matches the script"

    async def transcribe(self, media_path: Path, language: str = "en", hint: str = ""):
        dur = media.probe_duration(media_path)
        return [Segment(0, dur, hint)] if hint else []
