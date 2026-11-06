"""What each way of making a clip can do, written from the model catalogue (data), not from code.

The planner is shown this text so it plans clips that one route can really make. When you change a model's row in
catalog.yaml (what it can animate, how long its clips are, whether it speaks), the text changes with it.
"""
from __future__ import annotations

from .registry import MOTION_LEVELS, Registry

MOTION_WORDS = {"face": "only the face and head move", "body": "the subject's body can move too",
                "scene": "the whole scene can move (body, camera, surroundings)"}
LENGTH_WORDS = {"follows_audio": "the clip is exactly as long as the speech", "flexible": "any length",
                "fixed": "one of a fixed list of lengths"}
SUBJECT_WORDS = {"human": "people", "animal": "animals", "object": "objects and products"}


def _models(rows) -> str:
    return ", ".join(r.id for r in rows) or "none connected yet"


def describe(reg: Registry) -> str:
    """The text the planner reads. Built only from catalogue rows (usable ones when any are, else all real ones)."""
    def rows(job: str):
        every = [e for e in reg.catalog.for_job(job) if e.enabled and not e.is_free]
        usable = [e for e in every if reg.entry_usable(e)]
        return usable or every

    lines = ["WHAT EACH ROUTE CAN DO (generated from the tool's model catalogue; the tool sends every clip to a route whose abilities cover what the clip needs):"]
    for job, label in (("avatar", "Talking-picture route"), ("video", "Video route")):
        group = rows(job)
        if not group:
            continue
        levels = sorted({(e.capabilities.get("animates") or ("face" if job == "avatar" else "scene")) for e in group}, key=MOTION_LEVELS.index)
        top = levels[-1]
        lens = sorted({e.capabilities.get("length") or ("follows_audio" if job == "avatar" else "fixed") for e in group})
        parts = [f"{MOTION_WORDS[top]}", "; ".join(LENGTH_WORDS[x] for x in lens)]
        if job == "video":
            secs = [float(e.capabilities.get("max_seconds", 0) or 0) for e in group]
            parts.append(f"clips up to {max(secs):.0f} s each" if any(secs) else "")
            speakers = [e for e in group if e.capabilities.get("speech")]
            parts.append("models that speak the line themselves: " + _models(speakers) if speakers else "no model speaks the line itself")
        lines.append(f"- {label} (models: {_models(group)}): " + "; ".join(x for x in parts if x) + ".")
    lip = rows("lipsync")
    if lip:
        kinds = sorted({k for e in lip for k in ([e.capabilities.get("faces")] if isinstance(e.capabilities.get("faces"), str) else (e.capabilities.get("faces") or []))})
        works = ", ".join(SUBJECT_WORDS.get(k, k) for k in kinds) or "faces"
        lines.append(f"- Lip-sync step (models: {_models(lip)}): puts spoken words onto a face in a video clip; works for {works} only.")
    voices = rows("voice")
    if voices:
        singers = [e for e in voices if e.capabilities.get("sing")]
        lines.append("- Voices (models: " + _models(voices) + "): " + (
            "models that can sing: " + _models(singers) + "; the others only speak." if singers else
            "they only SPEAK; none can sing. Write lines to be recited, spoken or chanted, never 'sung', and do not plan a sung performance."))
    lines.append("HOW TO PLAN: write for every clip what it needs and set `motion`: `face` (only the face and head move: someone speaking to the camera), "
                 "`body` (the subject's body moves) or `scene` (the camera or the scene moves). A clip must need only what ONE route can do. "
                 "Speech on camera together with body or scene movement is one clip only if the video route has a model that speaks the line or a lip-sync step "
                 "that fits that speaker; otherwise split it into consecutive clips so that each needs one thing, and make each clip's end state the next clip's start state.")
    return "\n".join(lines)
