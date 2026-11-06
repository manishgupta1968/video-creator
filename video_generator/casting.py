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

from . import languages, media
from . import policy as policy_mod
from .models import ContextItem, ContextType, Project
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


def speaker_card(project: Project, speaker: str) -> Optional[ContextItem]:
    """The character card of a speaker (by id or name); the narrator falls back to the card named like a narrator."""
    for c in project.context:
        if c.type == ContextType.actor and c.actor and (c.id == speaker or c.title.lower() == (speaker or "").lower()):
            return c
    if speaker == "narrator":
        for c in project.context:
            if c.type == ContextType.actor and c.actor and "narrat" in c.title.lower():
                return c
    return None


def line_language(project: Project, speaker: str, line_language: str = "") -> str:
    """The language one spoken line is in: the line's own, else the speaker's, else the video's main language (never 'auto')."""
    card = speaker_card(project, speaker)
    return languages.pick(line_language, card.actor.language if card and card.actor else "", project.settings.language) or "en"


def clip_languages(project: Project, script) -> list[str]:
    """Every language spoken in a clip's script (lines and narration), in the order first heard. [] when nothing is spoken."""
    seen: list[str] = []
    if script is None:
        return seen
    for d in script.dialogue:
        if d.text.strip():
            c = line_language(project, d.speaker, d.language)
            if c not in seen:
                seen.append(c)
    if script.narration.strip():
        c = line_language(project, "narrator", script.narration_language)
        if c not in seen:
            seen.append(c)
    return seen


def profile_for(actor: Optional[ContextItem], project: Project) -> Profile:
    """The speaker's profile: what the planner/user set, completed from the words in the description."""
    lang = languages.effective(project.settings.language)
    if not actor or not actor.actor:
        return Profile(language=lang, description="warm clear narrator")
    a = actor.actor
    lang = languages.effective(a.language) if languages.normalise(a.language) else lang        # this character's own language, else the video's
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
    pol = policy_mod.current()
    if cands and pol.voice_preview_candidates > 0 and profile.gender in ("male", "female") and not cands[0].note:
        cands, _heard = await _listen(plugin, cands, profile, pol)
    if not cands:
        note = f"no voice was found for this speaker{(' (' + why + ')') if why else ''}"
    elif profile.gender in ("male", "female") and not any(c.gender in ("", profile.gender) for c in cands[:1]):
        note = f"no {profile.gender} voice was found; check the voice"
    elif cands[0].note:
        note = cands[0].note
    elif accent_mismatch(cands[0].accent, profile.accent):
        note = accent_mismatch(cands[0].accent, profile.accent)
    return cands, note


def accent_mismatch(label: str, wanted: str) -> str:
    """A plain sentence when the accent a vendor labels a voice with does not match the accent the plan asks for ('' when it matches, or when either is
    unknown). The vendor sets the accent through the voice itself, so the result depends on the voice library: this only says so honestly."""
    words = set(re.findall(r"[a-z]{3,}", (wanted or "").lower()))
    have = (label or "").strip().lower()
    if not words or not have or any(w in have for w in words):
        return ""
    return (f"this voice is labelled '{label}', but the plan asks for '{wanted}'. Your voice library may have no closer match; "
            "choose another voice if it sounds wrong.")


async def _listen(plugin, cands: list[VoiceChoice], profile: Profile, pol) -> tuple[list[VoiceChoice], int]:
    """Listen to the vendor's free sample of the best candidates, measure their pitch, and put the voices that fit
    the profile's pitch range first. Candidates that cannot be heard keep their label-based order after those that fit."""
    import asyncio
    n = pol.voice_preview_candidates
    head, tail = cands[:n], cands[n:]
    lo, hi = pol.pitch_range(profile.gender, profile.pitch)

    async def measure(c: VoiceChoice) -> None:
        try:
            wav = await plugin.preview(c)
            c.pitch_hz = await asyncio.to_thread(media.voice_pitch, wav) if wav else None
        except Exception:
            c.pitch_hz = None
    await asyncio.gather(*(measure(c) for c in head))
    heard = sum(1 for c in head if c.pitch_hz)
    if not heard or not (lo and hi):
        return cands, heard

    def misfit(c: VoiceChoice) -> float:
        if c.pitch_hz is None:
            return 3.0                                   # not heard: after the ones that clearly fit, before the ones that clearly do not
        if lo <= c.pitch_hz <= hi:
            return 0.0
        edge = lo if c.pitch_hz < lo else hi
        return abs(12 * math.log2(c.pitch_hz / edge))      # semitones away from the range
    ranked = sorted(enumerate(head), key=lambda x: (misfit(x[1]), x[0]))
    return [c for _, c in ranked] + tail, heard


def pitch_fix(measured: Optional[float], profile: Profile) -> tuple[float, str]:
    """(semitones to shift, plain-words note) so a finished voice fits the profile; (0, '') when it already does
    or when nothing is known. The shift is capped at policy.max_pitch_shift_st: a bigger change would sound unnatural, so the
    note then tells the user to pick another voice."""
    if not measured or profile.gender not in ("male", "female"):
        return 0.0, ""
    pol = policy_mod.current()
    lo, hi = pol.pitch_range(profile.gender, profile.pitch)
    if lo <= measured <= hi:
        return 0.0, ""
    target = hi if measured > hi else lo
    needed = 12 * math.log2(target / measured)
    shift = max(-pol.max_pitch_shift_st, min(pol.max_pitch_shift_st, needed))
    word = "deeper" if shift < 0 else "higher"
    note = f"the voice was made {abs(shift):.0f} semitones {word} to fit a {profile.pitch or ''} {profile.gender} voice".replace("  ", " ")
    if abs(needed) > pol.max_pitch_shift_st + 0.5:
        note += f"; it still sounds {'high' if needed < 0 else 'low'} for a {profile.gender} voice, so please choose another voice"
    return shift, note


def tempo_for(profile: Profile) -> float:
    pol = policy_mod.current()
    return {"slow": pol.slow_tempo, "fast": pol.fast_tempo}.get(profile.pace, 1.0)


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
