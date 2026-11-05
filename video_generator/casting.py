"""Voice casting: choose a voice for every speaker from a profile, for any kind of speaker.

A speaker is a person (any age), an animal, a robot, a mascot, a product with a voice, or the narrator.
The planner writes the profile (gender, age, pitch, pace, accent); the user can edit it. This module:
  - guesses what is missing from the words in the description (never from the species or the name);
  - asks the voice vendor for voices that fit, best first, using gender/age as hard filters;
  - gives every speaker a different voice, and keeps one voice per speaker for the whole video;
  - checks the finished voice by measuring its pitch and corrects it a little if it clearly does not fit.
A weak choice is never hidden: it comes back as a note that the clip and the actor card show.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import media
from .models import ContextItem, Project
from .plugins.base import VoiceChoice, VoiceSpec

_MALE = r"\b(male|man|men|boy|he|his|him|father|dad|king|gentleman|sir|husband|son|brother|uncle|grandfather|baritone|bass)\b"
_FEMALE = r"\b(female|woman|women|girl|she|her|mother|mom|mum|queen|lady|wife|daughter|sister|aunt|grandmother|lioness|soprano)\b"
_LOW = r"\b(deep|low|heavy|bass|baritone|growl\w*|gravelly|rumbl\w*|resonant|booming)\b"
_HIGH = r"\b(high|squeaky|shrill|bright|light|tiny|chirpy|piping)\b"
_SLOW = r"\b(slow|calm|measured|deliberate|unhurried|relaxed)\b"
_FAST = r"\b(fast|quick|rapid|energetic|excited|hurried|lively)\b"
_AGES = [("child", r"\b(child|kid|toddler|little (boy|girl))\b"), ("teen", r"\b(teen|teenager|adolescent)\b"),
         ("older", r"\b(old|older|elderly|aged|senior|grandfather|grandmother|grandpa|grandma|ancient|wise old)\b"),
         ("young", r"\b(young|youthful|student|twenties)\b")]

# Gender-correct pitch the finished voice should have (Hz, median of the speech)
PITCH_RANGE = {("male", "low"): (85, 125), ("male", "medium"): (95, 150), ("male", "high"): (120, 175),
               ("female", "low"): (160, 200), ("female", "medium"): (175, 235), ("female", "high"): (210, 290)}
MAX_SHIFT = 4.0            # semitones: more than this sounds unnatural


def guess_gender(*texts: str) -> str:
    """'male' or 'female' from the words in the texts, '' when unclear. Looks at words, not names or species."""
    for t in texts:
        t = (t or "").lower()
        f, m = re.search(_FEMALE, t), re.search(_MALE, t)
        if f and not m:
            return "female"
        if m and not f:
            return "male"
    return ""


def guess_age(*texts: str) -> str:
    for t in texts:
        t = (t or "").lower()
        for name, pat in _AGES:
            if re.search(pat, t):
                return name
    return ""


def _first(pat: str, *texts: str) -> bool:
    return any(re.search(pat, (t or "").lower()) for t in texts)


@dataclass
class Profile:
    gender: str = ""
    age: str = ""
    pitch: str = ""
    pace: str = ""
    accent: str = ""
    language: str = "en"
    description: str = ""


def profile_for(actor: Optional[ContextItem], project: Project) -> Profile:
    """The speaker's profile: what the planner/user set, completed from the words in the description."""
    lang = project.settings.language
    if not actor or not actor.actor:
        return Profile(language=lang, description="warm clear narrator")
    a = actor.actor
    texts = (a.voice_description, a.behaviour, a.description)
    g = (a.voice_gender or "").lower() or guess_gender(*texts)
    pitch = (a.voice_pitch or "").lower() or ("low" if _first(_LOW, a.voice_description) else "high" if _first(_HIGH, a.voice_description) else "")
    pace = (a.voice_pace or "").lower() or ("slow" if _first(_SLOW, a.voice_description) else "fast" if _first(_FAST, a.voice_description) else "")
    age = (a.voice_age or "").lower() or guess_age(a.voice_description, a.description)
    return Profile(gender=g, age=age, pitch=pitch, pace=pace, accent=a.voice_accent, language=lang,
                   description=a.voice_description or a.description)


def spec_from(profile: Profile, voice_id: Optional[str] = None, emotion: str = "") -> VoiceSpec:
    return VoiceSpec(voice_id=voice_id, description=profile.description, language=profile.language, emotion=emotion,
                     gender=profile.gender, age=profile.age, pitch=profile.pitch, pace=profile.pace, accent=profile.accent)


async def choose_voice(plugin, profile: Profile, taken: tuple = ()) -> tuple[list[VoiceChoice], str]:
    """Candidates for this speaker, best first, plus a note when the match is weak ('' when it is good).
    A vendor failure never stops casting: the note says what happened."""
    spec = spec_from(profile)
    try:
        cands = await plugin.candidates(spec, taken)
    except Exception as exc:                         # the vendor's list could not be read, or any other failure
        cands, why = [], str(exc)[:120]
    else:
        why = ""
    note = ""
    if not cands:
        note = f"no voice was found for this speaker{(' (' + why + ')') if why else ''}"
    elif profile.gender in ("male", "female") and not any(c.gender in ("", profile.gender) for c in cands[:1]):
        note = f"no {profile.gender} voice was found; check the voice"
    elif cands[0].note:
        note = cands[0].note
    return cands, note


def pitch_fix(measured: Optional[float], profile: Profile) -> tuple[float, str]:
    """(semitones to shift, plain-words note) so a finished voice fits the profile; (0, '') when it already does
    or when nothing is known. The shift is capped at MAX_SHIFT: a bigger change would sound unnatural, so the
    note then tells the user to pick another voice."""
    if not measured or profile.gender not in ("male", "female"):
        return 0.0, ""
    lo, hi = PITCH_RANGE[(profile.gender, profile.pitch or "medium")]
    if lo <= measured <= hi:
        return 0.0, ""
    target = hi if measured > hi else lo
    needed = 12 * math.log2(target / measured)
    shift = max(-MAX_SHIFT, min(MAX_SHIFT, needed))
    word = "deeper" if shift < 0 else "higher"
    note = f"the voice was made {abs(shift):.0f} semitones {word} to fit a {profile.pitch or ''} {profile.gender} voice".replace("  ", " ")
    if abs(needed) > MAX_SHIFT + 0.5:
        note += f"; it still sounds {'high' if needed < 0 else 'low'} for a {profile.gender} voice, so please choose another voice"
    return shift, note


def tempo_for(profile: Profile) -> float:
    return {"slow": 0.9, "fast": 1.08}.get(profile.pace, 1.0)


def fit_voice(wav: Path, profile: Profile, known_shift: Optional[float] = None,
              apply_pace: bool = True) -> tuple[Path, str, Optional[float]]:
    """Check a finished voice against the profile and correct it a little.
    Returns (file, note, semitones used). `known_shift` (from an earlier line of the same voice) skips the measuring;
    the third value is None when the pitch could not be measured (a very short line)."""
    if known_shift is None:
        measured = media.voice_pitch(wav)
        shift, note = pitch_fix(measured, profile)
        used: Optional[float] = shift if measured is not None else None
    else:
        shift, note, used = known_shift, "", known_shift
    tempo = tempo_for(profile) if apply_pace else 1.0
    if not shift and tempo == 1.0:
        return wav, note, used
    out = wav.with_name(wav.stem + "_fit.wav")
    media.shift_voice(wav, out, semitones=shift, tempo=tempo)
    return out, note, used
