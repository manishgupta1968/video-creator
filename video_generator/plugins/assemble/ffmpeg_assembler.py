"""The assembler plugin: thin wrapper so a different assembler can be plugged in."""
from __future__ import annotations

from ..base import Plugin
from ... import media


class FFmpegAssembler(Plugin):
    name = "ffmpeg"
    job = "assemble"
    env_keys: list[str] = []
    description = "ffmpeg: fit, mix, join, subtitles, export"

    def is_configured(self):
        return (True, "ok") if media.have_ffmpeg() else (False, "install ffmpeg (https://ffmpeg.org)")

    normalize = staticmethod(media.normalize_clip)
    still = staticmethod(media.still_to_clip)
    mix = staticmethod(media.replace_audio)
    join = staticmethod(media.join_clips)
    music = staticmethod(media.add_music)
    subtitles = staticmethod(media.burn_subtitles)
    export = staticmethod(media.to_format)
