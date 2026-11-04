"""Free local voices: Kokoro (good, optional install), ffmpeg flite, OS voice."""
from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from ... import media
from ..base import PluginError, Usage, VoiceSpec, VoiceSynth


class FliteVoice(VoiceSynth):
    name = "flite"
    env_keys: list[str] = []
    description = "ffmpeg's built-in robotic voice (free, for previews)"

    def is_configured(self):
        return (True, "ok") if media.flite_available() else (False, "your ffmpeg has no flite filter")

    async def synthesize(self, text: str, voice: VoiceSpec, out: Path, model: str = ""):
        v = "slt" if any(w in voice.description.lower() for w in ("female", "woman", "girl", "she")) else "kal"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(text.replace("\n", " "))
            tf = f.name
        try:
            esc = Path(tf).as_posix().replace(":", "\\:")
            await asyncio.to_thread(media.ff, "-f", "lavfi", "-i", f"flite=textfile='{esc}':voice={v}",
                                    "-ar", "44100", "-ac", "1", str(out))
        finally:
            Path(tf).unlink(missing_ok=True)
        return out, Usage()


class SystemVoice(VoiceSynth):
    name = "system_voice"
    env_keys: list[str] = []
    description = "Your computer's own voice (macOS say / Windows SAPI / espeak-ng)"

    def _engine(self) -> str:
        sysname = platform.system()
        if sysname == "Darwin" and shutil.which("say"):
            return "say"
        if sysname == "Windows":
            return "sapi"
        if shutil.which("espeak-ng") or shutil.which("espeak"):
            return "espeak"
        return ""

    def is_configured(self):
        return (True, "ok") if self._engine() else (False, "no system voice found (install espeak-ng)")

    async def synthesize(self, text: str, voice: VoiceSpec, out: Path, model: str = ""):
        engine = self._engine()
        raw = out.with_suffix(".raw.aiff" if engine == "say" else ".raw.wav")
        if engine == "say":
            cmd = ["say", "-o", str(raw), text]
        elif engine == "espeak":
            cmd = [shutil.which("espeak-ng") or "espeak", "-w", str(raw), text]
        elif engine == "sapi":
            ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  f"$s.SetOutputToWaveFile('{raw}'); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()")
            proc = await asyncio.to_thread(subprocess.run, ["powershell", "-NoProfile", "-Command", ps],
                                           input=text, capture_output=True, text=True)
            if proc.returncode != 0:
                raise PluginError(f"Windows voice failed: {proc.stderr[:200]}")
            cmd = None
        else:
            raise PluginError("no system voice available")
        if cmd:
            proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise PluginError(f"system voice failed: {proc.stderr[:200]}")
        await asyncio.to_thread(media.ff, "-i", str(raw), "-ar", "44100", "-ac", "1", str(out))
        raw.unlink(missing_ok=True)
        return out, Usage()


class KokoroVoice(VoiceSynth):
    name = "kokoro"
    env_keys: list[str] = []
    description = "Kokoro open voice model (free, local; pip install 'video-generator[local-voice]')"
    _pipe = None

    def is_configured(self):
        try:
            import kokoro  # noqa: F401
            import soundfile  # noqa: F401
            return True, "ok"
        except Exception:
            return False, "pip install 'video-generator[local-voice]'"

    async def match(self, description: str, language: str = "en"):
        d = description.lower()
        female = any(w in d for w in ("female", "woman", "girl", "she", "her"))
        british = "british" in d or "uk" in d
        if british:
            return "bf_emma" if female else "bm_george"
        return "af_heart" if female else "am_michael"

    async def synthesize(self, text: str, voice: VoiceSpec, out: Path, model: str = ""):
        def _run():
            import numpy as np
            import soundfile as sf
            from kokoro import KPipeline
            vid = voice.voice_id or "af_heart"
            if KokoroVoice._pipe is None:
                KokoroVoice._pipe = KPipeline(lang_code="b" if vid.startswith("b") else "a")
            chunks = [audio for _, _, audio in KokoroVoice._pipe(text, voice=vid, speed=voice.speed)]
            sf.write(str(out.with_suffix(".k.wav")), np.concatenate(chunks), 24000)
        await asyncio.to_thread(_run)
        await asyncio.to_thread(media.ff, "-i", str(out.with_suffix(".k.wav")), "-ar", "44100", "-ac", "1", str(out))
        out.with_suffix(".k.wav").unlink(missing_ok=True)
        return out, Usage()
