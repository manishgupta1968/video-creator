"""Offline brain: simple rules so the whole tool works with no API keys.

It is deliberately plain. Connect Anthropic, OpenAI or Gemini for real
creative writing and real visual review.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Type

from pydantic import BaseModel

from ..base import LLM, Usage

ANIMALS = ["lion", "deer", "tiger", "elephant", "dog", "cat", "horse", "bird", "eagle", "wolf", "bear", "fox", "monkey", "shark", "whale"]
PEOPLE = ["presenter", "man", "woman", "person", "people", "customer", "host", "girl", "boy", "chef", "doctor", "teacher", "founder", "me", "i "]
PRODUCT = ["product", "bag", "bottle", "phone", "app", "shoe", "watch", "car", "brand", "advert", "advertise", "launch"]
BIG_ANIMALS = ["lion", "tiger", "elephant", "bear", "wolf", "horse", "whale", "shark"]
SMALL_ANIMALS = ["bird", "cat", "monkey", "fox", "eagle"]
OUTDOOR = ["savannah", "field", "street", "beach", "forest", "garden", "outdoor", "park", "mountain", "desert", "river", "jungle", "sunset"]


def _profile_for(text: str, animal: str = "") -> dict:
    """An offline voice profile from the words (the real AI brain decides this from the whole story)."""
    from ... import casting
    if not animal:        # words like "male lion" or "deep voice" in the goal describe the animal, not a presenter
        has_animal = any(a in text for a in ANIMALS)
        text = re.sub(r"\b(male|female)\s+(?:%s)\b" % "|".join(ANIMALS), "", text)
        if has_animal:
            text = re.sub(r"\b(deep|heavy|bass|slow|growly)\b", "", text)
    g = casting.guess_gender(text)
    pitch = "low" if animal in BIG_ANIMALS else "high" if animal in SMALL_ANIMALS else ("low" if re.search(r"\b(deep|heavy|bass)\b", text) else "")
    return {"voice_gender": g or "neutral", "voice_age": casting.guess_age(text) or "adult", "voice_pitch": pitch or "medium",
            "voice_pace": "slow" if animal in BIG_ANIMALS else "normal"}


def _sound_for(goal: str, shot: str, has_animal: bool) -> str:
    g = goal.lower()
    outdoors = any(w in g for w in OUTDOOR) or shot in ("wildlife", "landscape")
    if outdoors:
        return "light wind through grass, distant birds" + (", soft footsteps" if has_animal or "walk" in g else "")
    if shot == "product":
        return "quiet room tone, subtle handling sounds"
    return "quiet room tone"


def _sentences(goal: str, words: int) -> str:
    base = re.sub(r"\s+", " ", goal).strip().rstrip(".")
    if not base:
        return ""
    out = base
    fillers = ["Every detail matters.", "Watch closely.", "This is the moment.", "Here is what happens next.",
               "It changes everything.", "Take a closer look."]
    i = 0
    while len(out.split()) < words and i < len(fillers):
        out += ". " + fillers[i]
        i += 1
    return " ".join(out.split()[:max(words, 4)]).rstrip(",") + "."


def topic_of(goal: str) -> str:
    """'A 30-second advert where a presenter introduces our bag' -> 'a presenter introduces our bag'"""
    t = re.sub(r"\s+", " ", goal).strip().rstrip(".")
    t = re.sub(r"^(please\s+)?(create|make|produce|generate)\s+", "", t, flags=re.I)
    t = re.sub(r"^(an?\s+)?(\d+[- ]?(second|sec|minute|min)s?[- ]?(long)?\s+)?(video|advert|ad|clip|film|short|reel)\s+"
               r"(that|which|where|of|about|showing|to|for)?\s*", "", t, flags=re.I)
    return t or goal


def _shot_type(text: str, has_actor: bool) -> str:
    t = text.lower()
    if any(w in t for w in ("present", "explain", "introduce", "to camera", "speaks to", "says to camera", "talks to camera")) and has_actor:
        return "talking_head"
    if any(w in t for w in ("talk", "conversation", "dialogue", "argue", "chat", "interview")):
        return "dialogue_scene"
    if any(a in t for a in ANIMALS) or "wildlife" in t or "jungle" in t:
        return "wildlife"
    if any(w in t for w in ("walk", "run", "hold", "hand", "pick", "carry", "dance", "struggle", "snap", "lift")):
        return "human_motion"
    if any(w in t for w in PRODUCT):
        return "product"
    if any(w in t for w in ("sky", "city", "landscape", "mountain", "ocean", "street", "sunrise", "sunset", "platform")):
        return "landscape"
    return "other"


class FakeLLM(LLM):
    name = "fake_llm"
    env_keys: list[str] = []
    description = "Free offline brain (simple rules)"
    licence = "free"

    async def generate_json(self, *, system: str, user: str, schema: Type[BaseModel], model: str,
                            images: Optional[list[Path]] = None, video: Optional[Path] = None,
                            max_tokens: int = 16000, meta: Optional[dict] = None):
        meta = meta or {}
        task = meta.get("task", "")
        fn = getattr(self, f"_{task}", None)
        data = fn(meta) if fn else {}
        return schema.model_validate(data), Usage(input_tokens=len(user) // 4, output_tokens=200)

    # ---------------------------------------------------------------- tasks
    def _draft(self, m: dict) -> dict:
        goal = m.get("goal", "").strip()
        secs = float(m.get("seconds") or 60)
        if m.get("auto_length"):
            secs = 24.0                       # no length asked for: the offline planner keeps it short, one clip per part
        g = goal.lower()
        actors = []
        existing = [c for c in m.get("context", []) if c.get("type") == "actor"]
        if not existing:
            found = [a for a in ANIMALS if a in g]
            for a in found[:3]:
                actors.append({"name": a.title(), "kind": "animal", "description": f"a powerful, realistic {a}",
                               "behaviour": "natural animal behaviour",
                               "voice_description": ("a deep, heavy, slow voice" if a in BIG_ANIMALS else "a light, quick voice"),
                               **_profile_for(g, a)})
            if any(p in g for p in PEOPLE) or (any(w in g for w in PRODUCT) and not found):
                actors.append({"name": "Presenter", "kind": "ai_person",
                               "description": "friendly adult presenter, natural skin texture, warm smile",
                               "clothing": "smart casual navy shirt", "behaviour": "confident, open hand gestures",
                               "voice_description": "warm, clear, medium pace", **_profile_for(g)})
            if re.search(r"narrat|voice.?over|explain", g) and not any(a["name"] == "Narrator" for a in actors):
                actors.append({"name": "Narrator", "kind": "ai_person", "description": "the voice-over narrator (never seen)",
                               "voice_description": "warm, clear, natural narrator", **_profile_for(g)})
        from ... import languages
        spoken = languages.normalise(m.get("language") or "")
        if spoken:                       # offline, the planner cannot know where a character is from: the accent is the language they speak
            for a in actors:
                a.setdefault("voice_accent", languages.name_of(spoken))
                a.setdefault("language", spoken)
        topic = topic_of(goal)
        n_parts = 3 if secs >= 30 else 2
        names = [("Opening", "Hook: set the scene — "), ("Main", "Main moment — "),
                 ("Ending", "Close with a memorable final image — ")]
        if n_parts == 2:
            names = [names[0], names[2]]
        shares = [0.25, 0.5, 0.25] if n_parts == 3 else [0.5, 0.5]
        parts = []
        for (title, prefix), share in zip(names, shares):
            psecs = round(secs * share, 1)
            n_clips = max(1, min(4, round(psecs / 7)))
            beats = ["establishing view", "closer detail", "reaction", "key action"]
            clips = []
            for i in range(n_clips):
                cgoal = f"{prefix}{topic} ({beats[i % 4]})"
                first_of_video = not parts and i == 0
                continuing = i > 0 and any(w in cgoal.lower() for w in ("continues", "then", "same moment"))
                join = "" if first_of_video else "continues" if continuing else "same_scene" if i > 0 else "cut"
                reason = ("" if first_of_video else "the same shot goes on" if continuing
                          else "same place and people, a new angle" if i > 0 else "a new part of the story")
                clips.append({"title": f"{title}: {beats[i % 4]}", "goal": cgoal, "seconds": round(psecs / n_clips, 1),
                              "join": join, "join_reason": reason, "place": topic[:60], "present": [a["name"] for a in actors],
                              "start_state": f"Opening of '{beats[i % 4]}': {topic[:50]}", "end_state": f"End of '{beats[i % 4]}': {topic[:50]}, the subject in frame"})
            parts.append({"title": title, "goal": prefix + topic, "seconds": psecs, "clips": clips})
        mood = "tense" if any(w in g for w in ("chase", "danger", "fight", "escape")) else "uplifting"
        title = topic if len(topic) <= 50 else topic[:50].rsplit(" ", 1)[0] + "…"
        return {"title": (title or "New video").strip()[:1].upper() + (title or "New video").strip()[1:],
                "style": {"look": "cinematic, photoreal, natural light", "colour": "rich natural colour", "mood": mood},
                "actors": actors, "parts": parts,
                "music_advice": ("subtle: upbeat modern, in at the start, out under the final line" if any(w in g for w in PRODUCT)
                                 else "none: natural sound carries the scene" if any(a in g for a in ANIMALS)
                                 else f"subtle: {mood}, quiet under speech")}

    def _explain(self, m: dict) -> dict:
        q = (m.get("question") or "").lower()
        words = {w for w in re.findall(r"[a-z]{4,}", q) if w not in ("what", "does", "this", "that", "mean", "with", "from", "have", "tool", "about", "explain", "please")}
        lines = [l for l in (m.get("facts") or "").splitlines() if l.strip()]
        hits = [l for l in lines if any(w in l.lower() for w in words)][:12] or lines[:10]
        return {"answer": "I am the offline helper, so I can only show the matching facts about your project (connect an AI brain in Settings for a written explanation):\n" + "\n".join(hits)}

    def _photo_query(self, m: dict) -> dict:
        text = f"{m.get('title', '')} {m.get('description', '')}".lower()
        for a in ANIMALS:
            if a in text:
                extra = "male " if any(w in text for w in ("male", "mane", "stag")) and a in ("lion", "deer") else ""
                return {"query": f"{extra}{a}".strip()}
        words = [w for w in re.findall(r"[a-z]{4,}", text) if w not in ("realistic", "powerful", "adult", "with", "that", "this")]
        return {"query": " ".join(words[:2]) or (m.get("title") or "photo")}

    def _pick_photo(self, m: dict) -> dict:
        return {"choice": 1, "reason": "offline brain: first ranked result"}

    def _decompose(self, m: dict) -> dict:
        goal, secs = m.get("goal", ""), float(m.get("seconds") or 18)
        n = max(2, min(4, round(secs / 7)))
        labels = ["Set up", "Develop", "Turn", "Pay off"][:n]
        goal = topic_of(goal)
        has_before = bool(m.get("has_previous") or m.get("prev_end"))
        return {"children": [{"title": f"{l}", "goal": f"{l} — {goal}", "seconds": round(secs / n, 1), "kind": "clip",
                              "join": "same_scene" if i else ("cut" if has_before else ""),
                              "join_reason": "same place and people, a later moment" if i else ("a new part of the story" if has_before else ""),
                              "place": goal[:60], "start_state": f"{l}: {goal[:50]}", "end_state": f"End of '{l}': {goal[:50]}"}
                             for i, l in enumerate(labels)], "note": "offline brain: simple split"}

    def _split_clip(self, m: dict) -> dict:
        """Offline fallback: split at the script's own structure. The spoken part (all dialogue) becomes a face-only clip about as long
        as the speech; the action steps become the other clip(s)."""
        sc = m.get("script") or {}
        secs = float(m.get("seconds") or 6)
        lines = sc.get("dialogue") or []
        beats = sc.get("action_beats") or []
        words = sum(len((l.get("text") or "").split()) for l in lines)
        speech_s = round(min(max(words / 2.5 + 1.0, 2.0), max(secs - 1.0, 2.0)), 1)
        start, end = sc.get("start_state") or "", sc.get("end_state") or ""
        mid = f"Right after the speech: {(sc.get('visual') or m.get('title') or '')[:80]}"
        if lines:
            parts = [{"title": f"{m.get('title', 'Clip')}: speaking", "goal": "speak to the camera", "seconds": speech_s, "shot_type": "talking_head",
                      "motion": "face", "visual": sc.get("visual", ""), "dialogue": [{"speaker_name": l.get("speaker", ""), "text": l.get("text", ""), "fixed": bool(l.get("fixed"))} for l in lines],
                      "sound_notes": sc.get("sound_notes", ""), "start_state": start, "end_state": mid},
                     {"title": f"{m.get('title', 'Clip')}: movement", "goal": m.get("goal", ""), "seconds": round(max(secs - speech_s, 2.0), 1),
                      "shot_type": sc.get("shot_type", "other") if sc.get("shot_type") != "talking_head" else "other", "motion": "body",
                      "visual": sc.get("visual", ""), "action_beats": beats, "sound_notes": sc.get("sound_notes", ""), "start_state": mid, "end_state": end}]
        else:
            half = max(len(beats) // 2, 1)
            parts = [{"title": f"{m.get('title', 'Clip')}: first", "goal": m.get("goal", ""), "seconds": round(secs / 2, 1), "shot_type": sc.get("shot_type", "other"),
                      "motion": sc.get("motion") or "scene", "visual": sc.get("visual", ""), "action_beats": beats[:half], "sound_notes": sc.get("sound_notes", ""),
                      "start_state": start, "end_state": mid},
                     {"title": f"{m.get('title', 'Clip')}: second", "goal": m.get("goal", ""), "seconds": round(secs / 2, 1), "shot_type": sc.get("shot_type", "other"),
                      "motion": sc.get("motion") or "scene", "visual": sc.get("visual", ""), "action_beats": beats[half:], "sound_notes": sc.get("sound_notes", ""),
                      "start_state": mid, "end_state": end}]
        return {"parts": parts, "note": "offline brain: split at the script's own structure"}

    def _write_clip_script(self, m: dict) -> dict:
        goal = m.get("goal", "")
        secs = float(m.get("seconds") or 6)
        actors = m.get("actors") or []
        feedback = m.get("feedback") or ""
        g = goal.lower()
        named = [a for a in actors if a.get("title", "").lower() in g] or (actors[:1] if any(p in g for p in PEOPLE + PRODUCT) else [])
        st = _shot_type(goal, bool(named))
        people = [a for a in named if (a.get("actor") or {}).get("kind") not in ("animal", "product")]
        words = int(secs * 2.2)
        visual = f"{topic_of(goal)}. Photoreal, cinematic lighting, natural textures"
        if named:
            desc = "; ".join(f"{a['title']}: {(a.get('actor') or {}).get('description', '')}, wearing {(a.get('actor') or {}).get('clothing', '')}"
                             for a in named)
            visual += f". {desc}"
        if feedback and feedback != "(none)":
            visual += f". Changes requested: {feedback}"
        dialogue, narration, on_camera = [], "", False
        if st == "talking_head" and people:
            dialogue = [{"speaker_name": people[0]["title"], "text": _sentences(topic_of(goal), words), "emotion": "warm"}]
            on_camera = True
        elif st == "dialogue_scene" and people:
            half = max(words // 2, 4)
            dialogue = [{"speaker_name": people[0]["title"], "text": _sentences(goal, half), "emotion": ""}]
            if len(people) > 1:
                dialogue.append({"speaker_name": people[1]["title"], "text": "I see what you mean.", "emotion": ""})
            on_camera = True
        else:
            narration = _sentences(topic_of(goal), words) if secs >= 4 else ""
        return {"shot_type": st, "visual": visual, "action_beats": [goal[:80]],
                "camera": "slow push-in, eye level" if st != "wildlife" else "tracking shot, long lens",
                "actors_in_shot": [{"actor_name": a["title"]} for a in named], "dialogue": dialogue,
                "narration": narration, "on_camera_speech": on_camera,
                "sound_notes": _sound_for(goal, st, any((a.get("actor") or {}).get("kind") == "animal" for a in named) or any(a in g for a in ANIMALS)),
                "start_state": (m.get("previous_end_state") or "") if (m.get("has_previous") and m.get("previous_end_state")) else f"Opening: {goal[:80]}",
                "end_state": f"After '{goal[:60]}': the subject still in frame, same place and light, facing the camera",
                "negative": "extra fingers, warped faces, text artifacts, flicker",
                "continues_from_previous": any(w in g for w in ("continues", "then", "same moment")) and m.get("has_previous", False),
                "same_location_as_previous": False,
                "change_summary": "applied feedback to the visual description" if feedback and feedback != "(none)" else ""}

    def _revise(self, m: dict) -> dict:
        instr = m.get("instruction", "")
        secs = float(m.get("seconds") or 0)
        if "short" in instr.lower():
            secs = round(secs * 0.75, 1)
        elif "long" in instr.lower():
            secs = round(secs * 1.3, 1)
        return {"title": m.get("title", ""), "goal": f"{m.get('goal', '')} ({instr})", "seconds": secs,
                "change_summary": f"added: {instr}"}

    def _suggest_dependencies(self, m: dict) -> dict:
        deps = []
        clips = m.get("clips", [])
        for a, b in zip(clips, clips[1:]):
            text = (b.get("visual") or "").lower()
            if any(w in text for w in ("continues", "same moment", "then she", "then he", "picks up where")):
                deps.append({"from_number": a["number"], "to_number": b["number"], "type": "continues_from",
                             "note": "the next clip continues the action"})
        return {"dependencies": deps}

    def _command(self, m: dict) -> dict:
        text = m.get("instruction", "").strip()
        t = text.lower()
        focus = m.get("focus") or "project"
        ops = []
        if re.search(r"\bgenerate\b.*\bnext\b", t):
            ops.append({"op": "generate", "target": "next"})
        elif re.search(r"\bgenerate\b.*\ball\b|\bmake the (whole|entire) video\b", t):
            ops.append({"op": "generate", "target": "all"})
        elif "shorter" in t or "longer" in t:
            ops.append({"op": "set_seconds", "target": focus, "value": "shorter" if "shorter" in t else "longer"})
        elif m_ := re.search(r"give (\w+) (?:a |an )?(.+?) in all clips", t):
            ops.append({"op": "set_actor", "target": m_.group(1), "field": "clothing", "value": m_.group(2)})
        else:
            ops.append({"op": "set_goal", "target": focus, "value": text})
        return {"summary": f"Offline brain understood: {ops[0]['op'].replace('_', ' ')}", "ops": ops}

    def _review(self, m: dict) -> dict:
        issues, suggestions = [], []
        scores = {"goal": 4, "script": 4, "actors": 4, "behaviour": 4, "realism": 0, "motion": 0, "consistency": 0,
                  "fidelity": 0, "audio": 0, "continuity": 4, "timing": 4, "lipsync": 5}   # 0 = the offline brain cannot see or hear
        if m.get("node_review"):
            target, actual = float(m.get("target") or 0), float(m.get("actual") or 0)
            if target and abs(actual - target) / target > 0.15:
                scores["timing"] = 2
                issues.append({"check": "timing", "text": f"part is {actual:.0f} s against a {target:.0f} s goal", "severity": "minor"})
                suggestions.append("shorten the longest clip" if actual > target else "add a short establishing clip")
            verdict = "minor_issues" if issues else "meets_goal"
            return {"verdict": verdict, "scores": scores, "issues": issues, "suggestions": suggestions,
                    "summary": "Offline check of length only. Connect an AI brain for a full story review."}
        script = m.get("script") or {}
        transcript = (m.get("transcript") or "").lower()
        expected = [l.get("text", "") for l in script.get("dialogue", [])] + ([script.get("narration")] if script.get("narration") else [])
        for line in expected:
            words = [w for w in re.findall(r"[a-z']+", line.lower()) if len(w) > 3]
            if words and transcript and sum(1 for w in words if w in transcript) / len(words) < 0.5:
                scores["script"] = 2
                issues.append({"check": "script", "text": f'line not clearly heard: "{line[:60]}"', "severity": "major"})
                suggestions.append(f'make sure the line "{line[:40]}…" is spoken clearly')
        meas = m.get("measurements") or {}
        if meas.get("flicker", 0) > 0.05:
            scores["consistency"] = 2
            issues.append({"check": "consistency", "text": "visible flicker between frames", "severity": "minor"})
            suggestions.append("add 'stable lighting, no flicker' and try another take")
        fs = meas.get("face_similarity")
        if fs is not None and fs < 0.5:
            scores["actors"] = 2
            issues.append({"check": "actors", "text": f"face does not match the actor's photos ({fs:.2f})", "severity": "major"})
            suggestions.append("use the actor's reference sheet as the start frame")
        target, actual = float(m.get("target") or 0), float(m.get("actual") or 0)
        if target and actual and abs(actual - target) > max(1.5, target * 0.2):
            scores["timing"] = 2
            issues.append({"check": "timing", "text": f"clip is {actual:.1f} s, planned {target:.1f} s", "severity": "minor"})
            suggestions.append("trim the clip" if actual > target else "add an action beat or a pause")
        bad = any(v <= 2 for k, v in scores.items() if k in ("goal", "script"))
        verdict = "does_not_meet_goal" if bad else ("minor_issues" if issues else "meets_goal")
        return {"verdict": verdict, "scores": scores, "issues": issues, "suggestions": suggestions,
                "summary": "Offline check: speech, timing and the measured numbers only. Connect an AI brain (Anthropic, OpenAI or Gemini) so the Review Agent can also look at realism, motion and quality."}
