"""Re-plan inside the Optimizer: a leaner Goal and a new breakdown, with the CURRENT plan given to the planner as context.

When the gentle levels of the Optimizer cannot reach what you want, the Goal itself may need a small change (a few words, not a longer text) and the parts
and clips must follow it. The planner is shown the current breakdown (marked MADE, KEPT, EXACT) and the numbers, so it knows the current plan is not
enough. What comes back is only a PROPOSAL: the tool checks it (the Goal may not grow much or lose quoted text; a clip that holds a line marked exact, a
clip you keep or protect, can never silently disappear), shows it beside the current plan, and applies it only when you say so, as one change.

Your videos: a clip the planner keeps as it is (`reuse`) comes back with its takes and its video. A made clip that is not in the new plan is left out, its
video stays on disk (Undo brings it back); you can choose, clip by clip, to reuse it anyway or to make a new one.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from . import estimate as est
from . import musictrack
from . import optimizer as opt
from . import policy as policy_mod
from . import scaling
from .brain import to_continuity
from .models import Continuity, Node, NodeKind, NodeStatus, Project
from .tree import find, leaves, numbering, parent_of, remove, walk

MARKS = ("MADE", "KEPT", "EXACT")


# ------------------------------------------------------------------ the Goal: the smallest change, and never your quoted words
_QUOTES = (r'"([^"]{3,})"', r"“([^”]{3,})”", r"«([^»]{3,})»")


def quoted(text: str) -> list[str]:
    return [m for pat in _QUOTES for m in re.findall(pat, text or "")]


def check_goal(old: str, new: str) -> tuple[str, str]:
    """(the Goal to use, a plain note). The new Goal is used only when it keeps every quoted piece of the old one word for word and does not grow
    more than policy.goal_max_growth (with room for one short clause); otherwise the old Goal stays and the note says why."""
    old, new = (old or "").strip(), (new or "").strip()
    if not new or new == old:
        return old, ""
    lost = [q for q in quoted(old) if q not in new]
    if lost:
        return old, f"The AI's new Goal left out your quoted text (“{lost[0][:40]}”), so the Goal is unchanged."
    limit = max(len(old) * (1 + policy_mod.current().goal_max_growth), len(old) + 30)
    if len(new) > limit:
        return old, f"The AI's new Goal was much longer ({len(new)} characters against {len(old)}), so the Goal is unchanged."
    return new, ""


def structure_stamp(p: Project) -> str:
    """A fingerprint of the plan as it is now (goals, clips, whether they are made or kept). A proposal made against one stamp is refused against another."""
    rows = [p.goal] + [[n.id, n.goal, n.status.value, bool(n.locked), bool(n.output), n.target_seconds] for n, _ in walk(p.root)]
    return hashlib.sha1(json.dumps(rows, default=str).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ what the planner is shown
def scope_parts(project: Project, scope_id: str) -> list[Node]:
    """The parts that are re-planned: every child of the root (whole video), or just this part."""
    return list(project.root.children) if scope_id == project.root.id else [find(project, scope_id)]


def clips_of(node: Node) -> list[Node]:
    return [n for n, _ in walk(node) if n.is_leaf] if not node.is_leaf else [node]


def held(project: Project, node: Node, extra: frozenset, answers: dict) -> str:
    """Why a clip can never silently disappear in a re-plan ('' when it can)."""
    if node.kind != NodeKind.clip:
        return "it is your own slides or footage"
    if opt.has_fixed_text(node):
        return "it holds a line marked “say exactly this”"
    if node.locked:
        return "you keep it as it is"
    if answers.get(numbering(project).get(node.id, "")) == "keep":
        return "you said it must stay"
    if node.id in extra:
        return "you protected it"
    return ""


def marks(node: Node, extra: frozenset) -> str:
    out = []
    if node.status in scaling.MADE:
        out.append("MADE")
    if node.locked or node.id in extra:
        out.append("KEPT")
    if opt.has_fixed_text(node):
        out.append("EXACT")
    return f" [{', '.join(out)}]" if out else ""


def outline_text(project: Project, scope_id: str, extra: frozenset) -> str:
    nums = numbering(project)
    lines = []
    for part in scope_parts(project, scope_id):
        lines.append(f"{nums.get(part.id, '')} PART {part.title or part.goal[:40]}: {part.goal} ({part.duration.likely_s:.0f} s, about ${part.cost.likely_usd:.2f})")
        for c in clips_of(part):
            if c is part:
                continue
            s = c.script
            said = (" | says: " + " ".join(d.text for d in s.dialogue if d.text.strip())[:110]) if s and any(d.text.strip() for d in s.dialogue) else ""
            lines.append(f"  {nums.get(c.id, '')} {c.title or c.goal[:40]}{marks(c, extra)} ({c.duration.likely_s:.0f} s, about ${c.cost.likely_usd:.2f}, "
                         f"join: {c.continuity.join or 'not decided'}): {c.goal[:140]}{said}")
    return "\n".join(lines)


def answers_text(project: Project, answers: dict) -> str:
    """The person's answers to 'what may be cut?' in the planner's words."""
    nums = numbering(project)
    names = {"keep": "MUST STAY", "shorten": "MAY BE SHORTENED", "cut": "MAY BE CUT"}
    by = {k: [] for k in names}
    for number, how in answers.items():
        if how in by and number in nums.values():
            node = find(project, {v: k for k, v in nums.items()}[number])
            by[how].append(f"{'part ' if not node.is_leaf else 'clip '}{number}")
    return "\n".join(f"{names[k]}: {', '.join(v)}" for k, v in by.items() if v)


def situation_text(before: dict, ladder_floor: dict, goal: opt.Goal) -> str:
    bits = [f"now about {before['seconds']:.0f} s and ${before['cost']:.2f} still to spend"]
    bits.append(f"even with every gentle change (cut empty time, cheaper quality, fewer takes, no extras) it only reaches about {ladder_floor['seconds']:.0f} s "
                f"and ${ladder_floor['cost']:.2f}")
    return "; ".join(bits) + "."


def wish_text(goal: opt.Goal) -> str:
    bits = []
    if goal.length:
        bits.append(f"a length of about {goal.length:g} seconds")
    if goal.cost:
        bits.append(f"at most ${goal.cost:g} still to spend")
    if goal.lowest or not bits:
        bits.append("as short and cheap as possible without losing the meaning")
    return " and ".join(bits)


def structure(project: Project, scope_id: str, extra: frozenset, answers: dict, goal: opt.Goal) -> dict:
    """The current plan as data (the offline helper reads this; the real AI reads the outline text)."""
    nums = numbering(project)
    parts = []
    for part in scope_parts(project, scope_id):
        clips = []
        for c in clips_of(part):
            if c is part and part.kind != NodeKind.clip:
                continue
            clips.append({"number": nums.get(c.id, ""), "title": c.title, "goal": c.goal, "seconds": float(c.duration.likely_s),
                          "protected": bool(held(project, c, extra, answers)) or c.status in scaling.MADE,
                          "join": c.continuity.join, "join_reason": c.continuity.join_reason, "place": c.continuity.place, "present": list(c.continuity.present),
                          "start_state": c.continuity.start_state, "end_state": c.continuity.end_state, "carry_over": c.continuity.carry_over})
        parts.append({"number": nums.get(part.id, ""), "title": part.title, "goal": part.goal, "seconds": float(part.duration.likely_s), "clips": clips})
    is_root = scope_id == project.root.id
    return {"scope": "root" if is_root else "part", "scope_number": nums.get(scope_id, ""), "goal": project.goal,
            "part_goal": "" if is_root else find(project, scope_id).goal, "target_seconds": goal.length,
            "cut": [n for n, h in answers.items() if h == "cut"], "keep": [n for n, h in answers.items() if h == "keep"], "parts": parts}


def estimate(svc, project: Project, scope_id: str, extra: frozenset) -> dict:
    """What asking for a re-plan costs BEFORE it is asked, and what writing the new scripts will cost after you apply."""
    n = max(sum(1 for part in scope_parts(project, scope_id) for c in clips_of(part) if c.kind == NodeKind.clip and not opt.is_protected(c, extra)), 1)
    tokens = (est.PLAN_TOKENS[0] + 250 * n, est.PLAN_TOKENS[1])
    entry = svc.reg.llm_entry("replan")
    one = est._llm_cost(entry, tokens)
    script = est._llm_cost(svc.reg.llm_entry("write_clip_script"), est.SCRIPT_TOKENS)
    lo, hi = (list(policy_mod.current().optimize_ai_cost_range) + [0.6, 1.6])[:2]
    return {"call_low": round(one * lo, 3), "call_high": round(one * hi, 3), "scripts_low": round(script * n * lo, 3), "scripts_high": round(script * n * hi, 3),
            "clips": n, "model": entry.id if entry else "offline helper"}


# ------------------------------------------------------------------ the checklist "what may be cut?" (with what each saving would be)
def cut_list(svc, project: Project, scope_id: str, extra: frozenset) -> list[dict]:
    """Every part and clip in the scope with what dropping it would save (measured on a copy), so you can say what may be cut, with the numbers in front of you."""
    base = project.model_copy(deep=True)
    before = opt.measure(svc, base, scope_id)
    nums = numbering(base)
    rows = []
    for part in scope_parts(base, scope_id):
        for node in ([part] + [c for c in clips_of(part) if c is not part]) if not part.is_leaf else [part]:
            q = base.model_copy(deep=True)
            try:
                remove(q, node.id)
                svc._repair_joins(q)
                m = opt.measure(svc, q, scope_id)
            except (KeyError, ValueError):
                continue
            is_part = not node.is_leaf
            reason = "" if is_part else ("made: its video exists" if node.status in scaling.MADE else
                                         "you keep it as it is" if node.locked else "you protected it" if node.id in extra else "")
            rows.append({"number": nums.get(node.id, ""), "title": node.title or node.goal[:40], "kind": "part" if is_part else "clip",
                         "seconds": round(node.duration.likely_s, 1), "saves_seconds": round(before["seconds"] - m["seconds"], 1),
                         "saves_cost": round(before["cost"] - m["cost"], 2), "made": node.status in scaling.MADE if not is_part else False,
                         "exact": opt.has_fixed_text(node) if not is_part else any(opt.has_fixed_text(c) for c in clips_of(node)),
                         "note": reason, "protected": bool(reason) and not (reason.startswith("made"))})
    return rows


# ------------------------------------------------------------------ resolving what the AI sent into real ids, with the protections
def resolve(svc, base: Project, scope_id: str, raw: dict, extra: frozenset, answers: dict, goal: opt.Goal) -> dict:
    nums = numbering(base)
    by_number = {v: k for k, v in nums.items() if v}
    is_root = scope_id == base.root.id
    parts_old = scope_parts(base, scope_id)
    part_ids = {p.id for p in parts_old}
    clip_ids = {c.id for p in parts_old for c in clips_of(p)}
    warnings: list[str] = []
    new_goal, note = check_goal(base.goal, raw.get("goal", ""))
    if note:
        warnings.append(note)
    part_goal_old = "" if is_root else find(base, scope_id).goal
    part_goal_new = part_goal_old
    if not is_root and raw.get("part_goal"):
        part_goal_new, pnote = check_goal(part_goal_old, raw["part_goal"])
        if pnote:
            warnings.append(pnote)
    used_parts, used_clips = set(), set()
    parts: list[dict] = []
    for rp in raw.get("parts", []):
        pid = by_number.get(str(rp.get("keep", "")).strip())
        if pid not in part_ids or pid in used_parts:
            if rp.get("keep"):
                warnings.append(f"The AI named part {rp['keep']} for “{rp.get('title', '')}”, which is not a part of this plan; it is treated as a new part.")
            pid = None
        else:
            used_parts.add(pid)
        clips = []
        for rc in rp.get("clips", []):
            cid = by_number.get(str(rc.get("reuse", "")).strip())
            if cid not in clip_ids or cid in used_clips:
                if rc.get("reuse"):
                    warnings.append(f"The AI named clip {rc['reuse']} for “{rc.get('title', '')}”, which is not available; it is treated as a new clip.")
                cid = None
            else:
                used_clips.add(cid)
            c = to_continuity(type("C", (), {k: rc.get(k, "" if k != "present" else []) for k in
                                             ("join", "join_reason", "place", "present", "start_state", "end_state", "carry_over")})())
            clips.append({"reuse_id": cid, "reuse_number": nums.get(cid, "") if cid else "", "title": rc.get("title", ""), "goal": rc.get("goal", ""),
                          "seconds": min(max(float(rc.get("seconds") or 6), 2.0), 15.0), "continuity": c.model_dump(), "forced": ""})
        parts.append({"keep_id": pid, "keep_number": nums.get(pid, "") if pid else "", "title": rp.get("title", ""), "goal": rp.get("goal", ""),
                      "seconds": round(sum(c["seconds"] for c in clips), 1), "clips": clips})
    if not is_root and parts and part_goal_new:
        parts[0]["goal"] = part_goal_new                       # the part's own Goal is what was checked above, wherever the AI also wrote it
    # a part that stays (not named) in a one-part scope still has to exist: the AI returned nothing for it
    if not is_root and not parts:
        warnings.append("The AI returned no plan for this part.")
    # what can never silently disappear: your exact lines, kept and protected clips, your own slides and footage
    forced = []
    for part in parts_old:
        for idx, c in enumerate(clips_of(part)):
            if c is part and part.kind == NodeKind.goal:
                continue
            why = held(base, c, extra, answers)
            if not why or c.id in used_clips:
                continue
            target = next((p for p in parts if p["keep_id"] == part.id), None) or (parts[-1] if parts else None)
            if target is None:
                parts.append({"keep_id": part.id if part.id in part_ids else None, "keep_number": nums.get(part.id, ""), "title": part.title, "goal": part.goal, "seconds": 0.0, "clips": []})
                target = parts[-1]
            target["clips"].insert(min(idx, len(target["clips"])), {"reuse_id": c.id, "reuse_number": nums.get(c.id, ""), "title": c.title, "goal": c.goal,
                                                                      "seconds": float(c.target_seconds or c.duration.likely_s or 6), "continuity": c.continuity.model_dump(), "forced": why})
            used_clips.add(c.id)
            forced.append({"id": c.id, "number": nums.get(c.id, ""), "why": why})
            target["seconds"] = round(sum(x["seconds"] for x in target["clips"]), 1)
    # made videos the plan does not use: yours to reuse or replace
    unused = [{"id": c.id, "number": nums.get(c.id, ""), "title": c.title or c.goal[:40], "seconds": round(c.duration.likely_s, 1),
               "part_number": nums.get(part.id, ""), "part_id": part.id} for part in parts_old for c in clips_of(part)
              if c.kind == NodeKind.clip and c.status in scaling.MADE and c.id not in used_clips]
    total = round(sum(p["seconds"] for p in parts), 1)
    if goal.length and abs(total - goal.length) / goal.length > 0.1 and is_root:
        warnings.append(f"The new plan adds up to about {total:.0f} s, not the {goal.length:g} s you asked for.")
    return {"scope": scope_id, "stamp": structure_stamp(base),
            "goal": {"old": base.goal, "new": new_goal}, "part_goal": {"old": part_goal_old, "new": part_goal_new},
            "parts": parts, "forced": forced, "unused_made": unused, "warnings": warnings, "note": raw.get("note", ""),
            "questions": [q for q in raw.get("questions", [])], "total_seconds": total}


# ------------------------------------------------------------------ applying (always to a project you pass in, usually a copy)
def apply_plan(svc, p: Project, plan: dict, reuse: Optional[dict] = None, goal_text: Optional[str] = None, part_goal_text: Optional[str] = None) -> dict:
    """Make the plan the project's plan, in place. One change: the caller saves once, so one undo takes it all back. Returns what happened."""
    reuse = reuse or {}
    old_key = musictrack.key(p)
    scope = find(p, plan["scope"])
    is_root = scope.id == p.root.id
    inside = {n.id: n for n, _ in walk(scope)}
    new_goal = (goal_text if goal_text is not None else plan["goal"]["new"]).strip()
    goal_changed = False
    if new_goal and new_goal != p.goal:
        svc._set_main_goal(p, new_goal)
        goal_changed = True
    part_new = (part_goal_text if part_goal_text is not None else plan["part_goal"]["new"]).strip()
    if not is_root and part_new and part_new != scope.goal:
        scope.goal = part_new
        plan["parts"][0]["goal"] = part_new if plan["parts"] else part_new           # the part node is re-used below: its Goal is what you wrote
        goal_changed = True
    adopted: set[str] = set()
    added = 0

    def clip_node(c: dict) -> Node:
        nonlocal added
        rid = c["reuse_id"]
        if rid in inside and (c.get("forced") or reuse.get(rid, True)):
            node = inside[rid]
            adopted.add(rid)
            if node.status not in scaling.MADE and not node.locked:
                node.target_seconds = c["seconds"]                  # an unmade clip follows the new length; a made or kept clip keeps its own
            join = c["continuity"].get("join")
            if join:
                node.continuity.join, node.continuity.join_reason = join, c["continuity"].get("join_reason") or node.continuity.join_reason
            return node
        added += 1
        return Node(kind=NodeKind.clip, title=c["title"], goal=c["goal"], target_seconds=c["seconds"], continuity=Continuity(**c["continuity"]))

    new_parts: list[Node] = []
    for rp in plan["parts"]:
        keep = inside.get(rp["keep_id"]) if rp["keep_id"] else None
        if keep is not None and keep.is_leaf:                      # a clip directly under the root, kept as it is
            new_parts.append(keep)
            adopted.add(keep.id)
            continue
        node = keep or Node(kind=NodeKind.goal, title=rp["title"], goal=rp["goal"], target_seconds=rp["seconds"])
        if keep is not None:
            node.title, node.goal, node.target_seconds = rp["title"] or node.title, rp["goal"] or node.goal, rp["seconds"] or node.target_seconds
            adopted.add(keep.id)
        node.children = [clip_node(c) for c in rp["clips"]]
        new_parts.append(node)
    # a made video you chose to reuse although the plan left it out goes back where it was
    for u in plan.get("unused_made", []):
        if reuse.get(u["id"]) and u["id"] in inside and u["id"] not in adopted:
            target = next((n for n in new_parts if not n.is_leaf and n.id == u.get("part_id")), None) or next((n for n in reversed(new_parts) if not n.is_leaf), None)
            if target is not None:
                target.children.append(inside[u["id"]])
                adopted.add(u["id"])
    if is_root:
        p.root.children = new_parts
    else:
        scope.children = [c for part in new_parts for c in (part.children if not part.is_leaf else [part])]
    ids = {n.id for n, _ in walk(p.root)}
    p.dependencies = [d for d in p.dependencies if d.from_id in ids and d.to_id in ids]
    p.run.targets = [t for t in p.run.targets if t in ids]
    svc._apply_joins(p)
    svc._repair_joins(p)
    svc._sync_states(p)
    opt.resync_targets(svc, p)
    if goal_changed:
        musictrack.rebind(p, old_key)                              # reworded a little: the saved music still fits, so it is not bought again
    gone_made = [n for i, n in inside.items() if i not in adopted and n.kind == NodeKind.clip and n.status in scaling.MADE]
    return {"new_clips": added, "reused": len([i for i in adopted if inside[i].is_leaf]), "goal_changed": goal_changed, "left_out_made": [n.id for n in gone_made]}


def simulate(svc, base: Project, plan: dict, reuse: Optional[dict], scope_id: str) -> dict:
    """The new plan beside the current one: Before and After (measured on a copy by the same estimate the screen uses) and the new outline."""
    before = opt.measure(svc, base.model_copy(deep=True), scope_id)
    q = base.model_copy(deep=True)
    report = apply_plan(svc, q, plan, reuse)
    after = opt.measure(svc, q, scope_id)
    nums = numbering(q)
    old_ids = {n.id for n, _ in walk(base.root)}
    rows = []
    for part in scope_parts(q, scope_id) if scope_id == q.root.id else [find(q, scope_id)]:
        crows = []
        for c in clips_of(part):
            if c is part:
                continue
            crows.append({"number": nums.get(c.id, ""), "title": c.title or c.goal[:40], "seconds": round(c.duration.likely_s, 1), "cost": round(c.cost.likely_usd, 2),
                          "cost_min": round(c.cost.min_usd, 2), "cost_max": round(c.cost.max_usd, 2), "reused": c.id in old_ids, "made": c.status in scaling.MADE,
                          "estimate_only": c.script is None})
        rows.append({"number": nums.get(part.id, ""), "title": part.title or part.goal[:40], "seconds": round(part.duration.likely_s, 1), "cost": round(part.cost.likely_usd, 2),
                     "clips": crows})
    return {"before": before, "after": after, "outline": rows, "report": report}
