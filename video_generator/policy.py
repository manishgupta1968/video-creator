"""The quality policy: every threshold the tool uses, named, explained and in ONE place.

Nothing here is tied to a kind of video. They are the rules a good result must meet. Change a value in
`config.yaml` under `policy:` (or see them all with `vg policy`) and the tool behaves differently, with no code change.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


def _ranges() -> dict[str, dict[str, list[float]]]:
    """The pitch (Hz, median of the speech) a finished voice should have, by gender and pitch."""
    return {
        "male": {"low": [85, 125], "medium": [95, 150], "high": [120, 175]},
        "female": {"low": [160, 200], "medium": [175, 235], "high": [210, 290]},
    }


class Policy(BaseModel):
    # ---- timing of a clip
    action_seconds: float = Field(2.5, description="Seconds one action step needs (used to size clips that have no target length).")
    min_action_seconds: float = Field(1.5, description="The least time one action step may be given when a clip is made shorter. Below this the steps cannot be seen.")
    min_clip_s: float = Field(3.0, description="The shortest clip the tool will plan when it shortens a video, in seconds.")
    unspaced_chars_per_word: float = Field(2.0, description="In scripts written without spaces (Chinese, Japanese kana, Thai …) this many characters count as one word when the length of speech is worked out.")
    line_pause: float = Field(0.6, description="Pause between two spoken lines, in seconds.")
    edge_pad: float = Field(0.5, description="Quiet before the first and after the last spoken word, in seconds.")

    # ---- music (made once for the whole video, then reused)
    music_reuse_tolerance: float = Field(0.2, description="How much longer than the saved music track a video may get before new music is made (0.2 = 20%). A shorter video simply uses less of the track, and a slightly longer one repeats it.")
    music_part_fade_s: float = Field(1.0, description="Fade in and out at the two ends of the music in a downloaded part, in seconds.")

    # ---- price ballpark (shown before any plan exists)
    ballpark_clip_seconds: float = Field(6.0, description="Typical length of one clip, in seconds. Used only for the rough price shown on the Start screen, before a plan exists.")
    ballpark_speech_share: list[float] = Field(default_factory=lambda: [0.3, 0.8], description="Low and high guess of how much of a video is spoken (0.3 = 30%). Used only for the rough price shown on the Start screen.")

    # ---- picture integrity
    max_freeze_s: float = Field(0.5, description="The longest a picture may stay frozen at the end of a clip before it counts as a defect, in seconds.")
    max_freeze_ratio: float = Field(0.15, description="The largest share of a clip that may be frozen (0.15 = 15%).")
    length_tolerance_s: float = Field(0.1, description="How much shorter than planned a clip may come out before it is cut to its real length instead of being padded with a held frame, in seconds.")
    on_short: Literal["shorten", "pad"] = Field("shorten", description="A clip a model made shorter than planned: 'shorten' = keep its real length; 'pad' = hold the last frame to fill the planned length.")
    min_sharpness_ratio: float = Field(0.7, description="A clip softer than this share of its neighbour's sharpness is flagged and gets a mild finishing pass.")
    finish_sharpen: float = Field(0.8, description="Strength of the finishing sharpen (0 = off).")
    finish_grain: float = Field(4.0, description="Strength of the matching film grain in the finishing pass (0 = off).")
    precise_endings: Literal["auto", "on", "off"] = Field("auto", description="Make an end picture for a clip whose end is planned and which the next clip continues from: auto = when a usable model can use it; on = always ask for it; off = never.")

    join_max_difference: float = Field(0.15, description="How different the first picture of a clip may be from the last picture of the clip it continues from "
                                                          "(0 = identical, 1 = opposite). Above this the clip is flagged: it does not start where the one before ended.")

    # ---- the optimizer
    max_cut_ratio: float = Field(0.5, description="The most the AI may cut in one go when it tightens a script: of a clip's spoken words, and of the clips in a part (0.5 = half). "
                                                    "At least one clip always stays in every part.")
    optimize_slack_s: float = Field(0.5, description="The optimizer trims a clip only when it is longer than its content needs by at least this many seconds.")
    optimize_goal_tolerance: float = Field(0.02, description="A length or cost goal counts as met when it is within this share of the number you gave (0.02 = 2 %).")
    goal_max_growth: float = Field(0.25, description="When the optimizer rewrites a Goal to help the saving, the new text may be at most this much longer than the old one "
                                                      "(0.25 = a quarter longer, with room for a short clause). Quoted text in the old Goal must stay word for word.")
    optimize_ai_cost_range: list[float] = Field([0.6, 1.6], description="The low and high guess, as a share of the estimate, shown for what asking the AI to tighten a script would cost.")

    # ---- choosing models
    budget_min_strength: int = Field(3, description="Budget quality picks the cheapest model, but never one that scores below this (1 = poor, 5 = best) for the kind of shot.")

    # ---- sound
    bed_under_speech_lufs: float = Field(-34.0, description="Loudness of natural sound (wind, room tone …) under speech, in LUFS. Lower = quieter.")
    bed_alone_lufs: float = Field(-28.0, description="Loudness of natural sound when nobody speaks, in LUFS.")
    loudness_tolerance_lu: float = Field(1.5, description="How far a measured sound level may be from its target before it is corrected, in LU.")

    # ---- voices
    pitch_ranges: dict[str, dict[str, list[float]]] = Field(default_factory=_ranges, description="Pitch range in Hz a voice should have, by gender then pitch (low / medium / high).")
    max_pitch_shift_st: float = Field(4.0, description="The most the tool will change a finished voice's pitch, in semitones. More sounds unnatural; the user is told to pick another voice instead.")
    voice_accent_weight: float = Field(5.0, description="How strongly the accent the plan asks for counts when a voice is chosen (a voice whose accent label matches gets this many points; "
                                                         "being the right gender is 4, the right age 2). Higher = the accent matters more than the other traits.")
    voice_preview_candidates: int = Field(6, description="How many candidate voices to listen to (free sample clips) before choosing one. 0 = do not listen.")
    slow_tempo: float = Field(0.9, description="Speed of a voice the plan marks slow (1 = normal).")
    fast_tempo: float = Field(1.08, description="Speed of a voice the plan marks fast.")

    def pitch_range(self, gender: str, pitch: str) -> tuple[float, float]:
        row = (self.pitch_ranges.get(gender) or {})
        lo, hi = row.get(pitch or "medium") or row.get("medium") or [0, 0]
        return float(lo), float(hi)


_current = Policy()


def current() -> Policy:
    """The active policy (set from config.yaml when the configuration is loaded)."""
    return _current


def use(p: Policy) -> Policy:
    global _current
    _current = p
    return p


def describe() -> list[tuple[str, object, str]]:
    """(name, value, plain-words explanation) for every setting: used by `vg policy` and the Settings dialog."""
    p = current()
    return [(name, getattr(p, name), f.description or "") for name, f in Policy.model_fields.items()]
