"""ElevenLabs voices: speech, instant voice cloning, stock-voice matching."""
from __future__ import annotations

import os

import httpx

import re

from ..base import PluginError, Usage, VoiceChoice, VoiceSpec, VoiceSynth, raise_for
from ... import media

API = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"   # "Rachel" stock voice (only when nothing is known about the speaker)

# Stock ("premade") voices, used ONLY when the vendor's voice list cannot be read (a restricted API key).
# The ids are from memory: casting tries them one by one and a wrong id simply fails without a charge.
STOCK = {
    "male": [("pNInz6obpgDQGcFmaJgB", "Adam", "low"), ("TxGEqnHWrfWFTfGW9XjX", "Josh", "low"), ("nPczCjzI2devNBz1zQrb", "Brian", "low"),
             ("onwK4e9ZLuTAKqWW03F9", "Daniel", "low"), ("pqHfZKP75CvOlQylNhV4", "Bill", "low"), ("JBFqnCBsd6RMkjVDRZzb", "George", "medium"),
             ("VR6AewLTigWG4xSOukaG", "Arnold", "medium"), ("ErXwobaYiN019PkySvjV", "Antoni", "medium"), ("yoZ06aMxZJJ28mfd3POQ", "Sam", "high")],
    "female": [("21m00Tcm4TlvDq8ikWAM", "Rachel", "medium"), ("EXAVITQu4vr4xnSDxMaL", "Sarah", "medium"), ("XrExE9yKIg1WjnnlVkGX", "Matilda", "medium"),
               ("Xb7hH8MSUJpSbSDYk0k2", "Alice", "medium"), ("cgSgspJ2msm6clMCkdW9", "Jessica", "high"), ("AZnzlk1XvdvUeBnXmlld", "Domi", "high"),
               ("MF3mGyEYCl7XYWbV9V6O", "Elli", "high"), ("pFZP5JQG7iQjIQuC4Bku", "Lily", "high")],
}
AGE_LABEL = {"child": "young", "teen": "young", "young": "young", "adult": "middle_aged", "older": "old"}
DEEP_WORDS = ("deep", "authoritative", "gravel", "raspy", "resonant", "warm", "calm", "narrat", "baritone", "bass")
HIGH_WORDS = ("bright", "young", "energetic", "cheerful", "upbeat", "child")


class ElevenLabsVoice(VoiceSynth):
    name = "elevenlabs"
    env_keys = ["ELEVENLABS_API_KEY"]
    description = "ElevenLabs voices and cloning"
    can_clone = True
    _voices: list[dict] | None = None

    def _h(self) -> dict:
        return {"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", "")}

    async def synthesize(self, text: str, voice: VoiceSpec, out, model: str = ""):
        vid = voice.voice_id or await self.match(voice.description) or DEFAULT_VOICE
        body = {"text": text, "model_id": model or "eleven_v3"}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{API}/text-to-speech/{vid}", params={"output_format": "mp3_44100_128"},
                                  headers=self._h(), json=body)
            if r.status_code == 400 and "model" in r.text.lower():
                body["model_id"] = "eleven_multilingual_v2"
                r = await client.post(f"{API}/text-to-speech/{vid}", params={"output_format": "mp3_44100_128"},
                                      headers=self._h(), json=body)
            raise_for(r, "ElevenLabs")
        mp3 = out.with_suffix(".mp3")
        mp3.write_bytes(r.content)
        media.ff("-i", str(mp3), "-ar", "44100", "-ac", "1", str(out))
        mp3.unlink(missing_ok=True)
        return out, Usage(raw={"chars": len(text)})

    async def clone(self, sample, name: str) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            with open(sample, "rb") as f:
                r = await client.post(f"{API}/voices/add", headers=self._h(), data={"name": name[:60]},
                                      files={"files": (sample.name, f, "audio/mpeg")})
            raise_for(r, "ElevenLabs clone")
            vid = r.json().get("voice_id")
        if not vid:
            raise PluginError("ElevenLabs returned no voice id")
        return vid

    async def list_voices(self) -> list[dict]:
        if self._voices is None:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(f"{API}/voices", headers=self._h())
                raise_for(r, "ElevenLabs voices")
                self._voices = r.json().get("voices", [])
        return self._voices

    def _stock(self, spec: VoiceSpec, taken: tuple, why: str) -> list[VoiceChoice]:
        genders = [spec.gender] if spec.gender in STOCK else ["female", "male"]
        order = {"low": 0, "medium": 1, "high": 2}
        out: list[VoiceChoice] = []
        for g in genders:
            want = order.get(spec.pitch or "medium", 1)
            for vid, name, pitch in sorted(STOCK[g], key=lambda x: abs(order[x[2]] - want)):
                out.append(VoiceChoice(vid, name, self.name, 1.0, g, note=why))
        return sorted(out, key=lambda c: c.voice_id in taken)

    async def candidates(self, spec: VoiceSpec, taken: tuple = ()) -> list[VoiceChoice]:
        """Voices that fit the profile, best first. Gender is a hard filter; voices already used by another
        speaker come last. If the voice list cannot be read, a short stock list for the gender is used (with a note)."""
        try:
            voices = await self.list_voices()
        except PluginError:
            return self._stock(spec, taken, "stock voice: the voice list could not be read (the ElevenLabs key may need "
                                            "the 'Voices: Read' permission), so the voice may not be the best match")
        words = {w for w in re.findall(r"[a-z]{3,}", (spec.description or "").lower())}
        accent = {w for w in re.findall(r"[a-z]{3,}", (spec.accent or "").lower())}
        scored: list[VoiceChoice] = []
        for v in voices:
            lab = {k: str(x).lower() for k, x in (v.get("labels") or {}).items()}
            g = lab.get("gender", "")
            if spec.gender in ("male", "female") and g and g != spec.gender:
                continue                                            # hard filter: never a male voice for a female speaker
            text = " ".join(lab.values()) + " " + (v.get("description") or "").lower() + " " + (v.get("name") or "").lower()
            score = 4.0 if (spec.gender in ("male", "female") and g == spec.gender) else 0.0
            if spec.age and lab.get("age") == AGE_LABEL.get(spec.age):
                score += 2
            score += min(sum(1 for w in words if w in text), 3)
            score += 2 * sum(1 for w in accent if w in lab.get("accent", ""))
            if spec.pitch == "low" and any(w in text for w in DEEP_WORDS):
                score += 1.5
            if spec.pitch == "high" and any(w in text for w in HIGH_WORDS):
                score += 1.5
            if spec.pace == "slow" and any(w in text for w in ("calm", "soothing", "relaxed", "gentle")):
                score += 0.5
            if v.get("voice_id") in taken:
                score -= 100
            scored.append(VoiceChoice(v.get("voice_id", ""), v.get("name", ""), self.name, score, g, preview_url=v.get("preview_url") or ""))
        scored = [c for c in scored if c.voice_id]
        scored.sort(key=lambda c: -c.score)
        if not scored and spec.gender in STOCK:
            return self._stock(spec, taken, f"no {spec.gender} voice in your ElevenLabs voice list; stock voices are tried instead")
        return scored[:8]

    async def preview(self, choice: VoiceChoice):
        """The free sample clip of a voice (no key, no charge), as a wav file; None when there is none."""
        if not choice.preview_url:
            return None
        import tempfile
        from pathlib import Path
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(choice.preview_url)
            if r.status_code >= 400 or not r.content:
                return None
            tmp = Path(tempfile.mkdtemp())
            raw = tmp / "preview.mp3"
            raw.write_bytes(r.content)
            wav = tmp / "preview.wav"
            media.ff("-i", str(raw), "-ac", "1", "-ar", "16000", str(wav))
            return wav
        except Exception:
            return None

    async def match(self, description: str, language: str = "en"):
        cands = await self.candidates(VoiceSpec(description=description, language=language))
        return cands[0].voice_id if cands else None
