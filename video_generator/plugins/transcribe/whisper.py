"""Speech-to-text for the Review Agent: local faster-whisper or OpenAI."""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..base import PluginError, Segment, Transcriber
from ... import media


def _to_wav(src: Path) -> Path:
    wav = src.with_suffix(".stt.wav")
    media.ff("-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav))
    return wav


class FasterWhisper(Transcriber):
    name = "faster_whisper"
    env_keys: list[str] = []
    description = "Local Whisper (free; pip install 'video-generator[transcribe]')"
    _model = None

    def is_configured(self):
        try:
            import faster_whisper  # noqa: F401
            return True, "ok"
        except Exception:
            return False, "pip install 'video-generator[transcribe]'"

    async def transcribe(self, media_path: Path, language: str = "en", hint: str = ""):
        def _run():
            from faster_whisper import WhisperModel
            if FasterWhisper._model is None:
                FasterWhisper._model = WhisperModel("small", device="auto", compute_type="int8")
            wav = _to_wav(media_path)
            segs, _ = FasterWhisper._model.transcribe(str(wav), language=language or None)
            out = [Segment(s.start, s.end, s.text) for s in segs]
            wav.unlink(missing_ok=True)
            return out
        return await asyncio.to_thread(_run)


class OpenAITranscribe(Transcriber):
    name = "openai_transcribe"
    env_keys = ["OPENAI_API_KEY"]
    description = "OpenAI Whisper transcription"

    async def transcribe(self, media_path: Path, language: str = "en", hint: str = ""):
        import openai
        wav = await asyncio.to_thread(_to_wav, media_path)
        try:
            client = openai.AsyncOpenAI()
            with open(wav, "rb") as f:
                extra = {"language": language} if language else {}           # "" = let the service work out the language (a mixed-language clip)
                resp = await client.audio.transcriptions.create(model="whisper-1", file=f,
                                                                response_format="verbose_json", **extra)
        except openai.APIStatusError as exc:
            raise PluginError(f"OpenAI transcription error {exc.status_code}") from exc
        finally:
            wav.unlink(missing_ok=True)
        segs = getattr(resp, "segments", None) or []
        if segs:
            return [Segment(s.start if hasattr(s, "start") else s["start"], s.end if hasattr(s, "end") else s["end"],
                            s.text if hasattr(s, "text") else s["text"]) for s in segs]
        return [Segment(0, media.probe_duration(media_path), getattr(resp, "text", ""))]
