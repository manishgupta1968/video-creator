"""The "Your next step" guide: reads the project as it is RIGHT NOW and says what to do next.

It follows plain rules (no AI, no cost, instant, works offline), so it can be recomputed after every click.
It returns an ordered checklist of the path to a finished video and the one step that is current, each with
a one-line reason and an action the screen can run or highlight.

Path:  connect services -> plan -> cast (photos, voices, consent) -> cost -> make clips -> join -> watch & download
Things that do not block the path (a review flag, a warning on a clip) are listed as `issues` next to it.
"""
from __future__ import annotations

from typing import Any, Optional

from .models import ContextType, NodeKind, NodeStatus, Project
from .tree import leaves, walk

STATES = ("done", "current", "attention", "todo")      # attention = not finished, but it no longer blocks the video


def _act(kind: str, label: str, **kw: Any) -> dict:
    """An action the screen can run. kind: settings | select | context | budget | run | scripts | assemble | final |
    resume | show | split | unpin.  `help` names a control the screen can highlight with 'Show me'."""
    return {"kind": kind, "label": label, **kw}


def _money(x: float) -> str:
    return f"${x:.2f}"


def _num(numbers: dict, nid: str) -> str:
    return numbers.get(nid, "")


def compute(svc, project: Project, summary: dict) -> dict:
    numbers = summary.get("numbers", {})
    ls = leaves(project)
    clips = [l for l in ls if l.kind in (NodeKind.clip, NodeKind.slides, NodeKind.user_clip)]
    ai_clips = [l for l in ls if l.kind == NodeKind.clip]
    run = project.run.status
    steps: list[dict] = []
    issues: list[dict] = []

    def step(id_: str, title: str, state: str, detail: str, action: Optional[dict] = None, extra: Optional[list] = None) -> None:
        steps.append({"id": id_, "title": title, "state": state, "detail": detail, "action": action, "also": extra or []})

    # ---- 1. services
    brain_offline = summary.get("brain", "fake_llm") == "fake_llm"
    prev = summary.get("preview", {})
    # only a REAL missing key asks you to connect something; `jobs` lists the kinds of work with no real model connected.
    # A clip you pinned to a free model, or free preview quality, is not a missing key (see Service.preview_info causes)
    previews = bool(prev.get("jobs")) and not prev.get("chosen_free_mode")
    missing = []
    if brain_offline:
        missing.append("an AI brain (OpenAI, Anthropic or Gemini) to plan and review")
    if previews:
        jobs = prev.get("jobs", {})
        if "video" in jobs or "avatar" in jobs:
            missing.append("fal.ai (or another video service) for real video")
        if "voice" in jobs:
            missing.append("ElevenLabs (or another voice service) for natural voices")
        if "image" in jobs and not any("fal.ai" in m for m in missing):
            missing.append("a picture service (fal.ai, OpenAI or Gemini)")
    if missing:
        step("services", "Connect your services", "current",
             "Without them you only get free preview cards, not real footage. Missing: " + "; ".join(missing) + ".",
             _act("settings", "Open Settings", help="settings"))
    else:
        step("services", "Connect your services", "done", "Your AI brain and media services are connected.")

    # ---- 2. plan
    no_script = [l for l in ai_clips if not l.script]
    if not clips:
        step("plan", "Plan the video", "current", "Describe the video, then let the AI break it into parts and clips.",
             _act("show", "Break it down with AI", node=project.root.id, help="breakdown"))
    elif no_script:
        step("plan", "Plan the video", "current", f"{len(no_script)} clip(s) have no script yet. The AI writes each clip's picture, speech and sound for you to check.",
             _act("scripts", "Write the scripts"))
    else:
        step("plan", "Plan the video", "done", f"{len(clips)} clip(s) planned, each with a script you can edit.")

    # ---- 3. cast (photos, voices, consent) and other things the clips need from you
    cast: list[dict] = []
    speakers = {d.speaker for l in ai_clips if l.script for d in l.script.dialogue if d.text.strip()}
    for c in project.context:
        if c.type != ContextType.actor and not (c.analysis.get("auto_photo_error") and not c.files):
            continue
        if c.needs_consent and not c.consent.confirmed:
            cast.append({"text": f"Confirm consent for {c.title}: say it is you or that you have permission.",
                         "action": _act("context", "Open " + c.title, id=c.id, help="consent-self")})
        elif c.analysis.get("auto_photo_error") and not c.files:
            cast.append({"text": f"No photo was found for {c.title}. Find one, or upload your own.",
                         "action": _act("context", "Open " + c.title, id=c.id, help="auto-photo")})
        elif c.actor and (c.id in speakers or "narrat" in c.title.lower()) and c.actor.voice_note and not c.analysis.get("voice_user_picked"):
            cast.append({"text": f"Check the voice of {c.title}: {c.actor.voice_note[:140]}",
                         "action": _act("context", "Open " + c.title, id=c.id, help="preview-voice")})
    if not clips:
        step("cast", "Check your characters", "todo", "Photos, voices and permissions for the people, animals and products in your video.")
    elif cast:
        step("cast", "Check your characters", "current", cast[0]["text"], cast[0]["action"], cast[1:])
    else:
        step("cast", "Check your characters", "done", "Photos, voices and permissions look fine.")

    # ---- 4. cost
    cost, budget, spent = summary.get("cost", 0.0), summary.get("budget", 0.0), summary.get("spent", 0.0)
    over = budget > 0 and spent + cost > budget + 1e-6
    if not clips:
        step("cost", "Check cost and time", "todo", "The estimate appears as soon as there are clips. It is shown before anything is paid for.")
    elif over:
        step("cost", "Check cost and time", "current",
             f"Still to spend about {_money(cost)} on top of {_money(spent)} already spent: that is over your budget of {_money(budget)}. "
             "Raise the budget, shorten the video, or choose a cheaper quality.",
             _act("budget", "See where the money goes", help="budget"))
    else:
        left = max(budget - spent - cost, 0)
        step("cost", "Check cost and time", "done",
             f"About {_money(cost)} still to spend, {_money(left)} of your {_money(budget)} budget left; about {int(round(summary.get('time_s', 0) / 60))} min to make.")

    # ---- 5. make the clips
    total = len(clips)
    done = sum(1 for l in clips if l.status == NodeStatus.done)
    failed = [l for l in clips if l.status == NodeStatus.failed]
    picks = [l for l in clips if l.status == NodeStatus.needs_pick]
    stale = [l for l in clips if l.status == NodeStatus.stale]
    if not clips:
        step("make", "Make the clips", "todo", "Make one clip first and look at it, then the rest.")
    elif done == total:
        step("make", "Make the clips", "done", f"All {total} clip(s) are made.")
    elif run == "running":
        step("make", "Make the clips", "current", f"Working now ({done} of {total} done). You can pause or stop from the bar above.", None)
    elif run == "paused":
        step("make", "Make the clips", "current", "The run is paused. Press Resume to carry on; finished clips are kept.",
             _act("resume", "Resume", help="resume"))
    elif failed:
        l = failed[0]
        reason = next((w for w in l.warnings if w.startswith("failed")), "")[:160]
        step("make", "Make the clips", "current", f"Clip {_num(numbers, l.id)} could not be made. {reason}".strip() + " Open it to read the reason, then try again or change the model.",
             _act("select", f"Open clip {_num(numbers, l.id)}", id=l.id))
    elif picks:
        l = picks[0]
        step("make", "Make the clips", "current", f"Clip {_num(numbers, l.id)} has more than one take. Look at them and pick the best.",
             _act("select", f"Open clip {_num(numbers, l.id)}", id=l.id, help="pick-take"))
    elif stale:
        step("make", "Make the clips", "current", f"{len(stale)} clip(s) are out of date because something they depend on changed. Make them again.",
             _act("run", "Make the rest", mode="continue", title="Make the clips that are out of date", help="continue-end"))
    elif any(l.needs_split for l in clips):
        l = next(x for x in clips if x.needs_split)
        step("make", "Make the clips", "current",
             f"Clip {_num(numbers, l.id)} needs more than any single route can do, so part of it could not be made well. "
             "Split it first (it costs a few cents); each part can then be made properly.",
             _act("split", f"Split clip {_num(numbers, l.id)}", id=l.id, help="split-clip"))
    elif done == 0:
        step("make", "Make the clips", "current", "Make the first clip only and look at it carefully before spending more. Check the cost in the window that opens.",
             _act("run", "Make the first clip", mode="next", title="Generate the next clip", help="generate-next"))
    else:
        step("make", "Make the clips", "current", f"{done} of {total} clips are made. If you like them, make the rest.",
             _act("run", "Make the rest", mode="continue", title="Continue to the end", help="continue-end"))

    # ---- 6. join
    ready, stale_final = summary.get("final_ready", False), summary.get("final_stale", False)
    all_done = summary.get("all_clips_done", False)
    if not clips or not all_done:
        step("join", "Join the clips into one video", "todo", "When every clip is made, join them with transitions, subtitles and sound.")
    elif not ready:
        step("join", "Join the clips into one video", "current", "Every clip is made. Join them into your final video.",
             _act("assemble", "Join clips into final video", help="join-final"))
    elif stale_final:
        step("join", "Join the clips into one video", "current", "Something changed since the final video was made. Join again so it matches your clips.",
             _act("assemble", "Update final video", help="join-final"))
    else:
        step("join", "Join the clips into one video", "done", "Your final video is made and up to date.")

    # ---- 7. watch and download
    if ready and not stale_final and all_done:
        step("finish", "Watch it, then download", "current", "Your video is ready. Watch it once from start to end, then download it.",
             _act("final", "Watch the final video", help="play-final"))
    else:
        step("finish", "Watch it, then download", "todo", "The last step: watch the whole video, then download the file.")

    # ---- things that do not block the path
    pinned = [x for x in prev.get("pinned", []) if x in numbers]
    if pinned:
        names = ", ".join(_num(numbers, x) for x in pinned[:4]) + ("…" if len(pinned) > 4 else "")
        issues.append({"text": f"{len(pinned)} clip(s) ({names}) are set to the free preview model, so they will only be placeholders. "
                               "This is a choice made on the clip, not a missing key.",
                       "action": _act("unpin", "Use the best model", ids=pinned, help="unpin")})
    for note in project.final_notes[:2]:
        issues.append({"text": note[:260], "action": _act("settings", "Open Settings", help="settings")})
    flagged = [r for r in project.reviews if r.verdict == "does_not_meet_goal" and r.target]
    for r in flagged[:2]:
        nid = r.target
        label = "the whole video" if nid == project.root.id else f"clip {_num(numbers, nid)}"
        issues.append({"text": f"The Review Agent says {label} does not meet your goal. You decide: read its notes and remake if you agree.",
                       "action": _act("select", "Open " + label, id=nid)})
    for l in ai_clips:
        if l.needs_split and len(issues) < 4:
            issues.append({"text": f"Clip {_num(numbers, l.id)} needs more than any single route can do. Split it so each part needs one kind of movement.",
                           "action": _act("split", f"Split clip {_num(numbers, l.id)}", id=l.id)})
    for l in ai_clips:
        warn = [w for w in l.warnings if not w.startswith(("failed", "compare failed"))]
        if l.needs_split:
            warn = [w for w in warn if w != next((x for x in l.warnings if x.startswith("This clip needs")), "")]
        if warn and len(issues) < 4:
            issues.append({"text": f"Clip {_num(numbers, l.id)}: {warn[0][:150]}", "action": _act("select", f"Open clip {_num(numbers, l.id)}", id=l.id)})

    # Only ONE step is current. Work that is running, paused, failed or waiting for a pick comes first;
    # otherwise the first blocking step on the path. When nothing is left to make, unfinished set-up steps no longer block.
    by_id = {x["id"]: x for x in steps}
    urgent = run in ("running", "paused") or bool(failed) or bool(picks)
    if urgent and by_id["make"]["state"] == "current":
        keep = "make"
    elif all_done and clips:
        for x in steps[:4]:
            if x["state"] == "current" and x["id"] != "cost":
                x["state"] = "attention"
        keep = next((x["id"] for x in steps if x["state"] == "current"), None)
    else:
        keep = next((x["id"] for x in steps if x["state"] == "current"), None)
    for x in steps:
        if x["state"] == "current" and x["id"] != keep:
            x["state"] = "todo"
    current = next((x for x in steps if x["state"] == "current"), None)
    n_done = sum(1 for s in steps if s["state"] == "done")
    if current:
        headline = {"services": "Connect your services", "plan": "Plan the video", "cast": "Check your characters", "cost": "Check the cost",
                    "make": "Make your clips", "join": "Join the clips", "finish": "Your video is ready"}.get(current["id"], current["title"])
    else:
        headline = "All done"
    return {"headline": headline, "current": current["id"] if current else None, "why": current["detail"] if current else "",
            "action": current["action"] if current else None, "steps": steps, "issues": issues,
            "progress": {"done": n_done, "total": len(steps)}}
