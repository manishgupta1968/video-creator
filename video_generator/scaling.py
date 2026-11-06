"""Resize a part (or the whole video): its clips follow.

A part's own length does nothing when its clips already have lengths, so changing it must change the clips. They are resized in
proportion, never below the shortest each can honestly be (its speech, its action steps, policy.min_clip_s), and a clip that is
already made, or that you chose to keep as it is, is never touched silently: its length stays and the others take the change.
"""
from __future__ import annotations

from . import estimate as est
from .models import Node, NodeKind, NodeStatus, Project
from .tree import find, numbering, walk

MADE = (NodeStatus.done, NodeStatus.needs_pick, NodeStatus.generating, NodeStatus.queued)


def protected(node: Node) -> bool:
    """A clip whose length must not change by itself: made (or being made), kept by you, or not an AI clip (your slides, your footage)."""
    return node.locked or node.status in MADE or node.kind != NodeKind.clip


def _current(node: Node) -> float:
    return float(node.target_seconds or (node.script.target_seconds if node.script else None) or node.duration.likely_s or 6.0)


def scale_node(project: Project, node_id: str, seconds: float) -> dict:
    """Make everything under `node_id` as close to `seconds` as the clips allow. Changes the project in place and says what it did:
    {requested, achieved, changed: [{id, number, from, to}], kept: [number…], note}. `achieved` is larger than `requested` when the
    floors or the kept clips do not allow less (and the note says why)."""
    node = find(project, node_id)
    nums = numbering(project)
    leaves_ = [n for n, _ in walk(node) if n.is_leaf]
    if not leaves_:
        node.target_seconds = seconds
        return {"requested": seconds, "achieved": seconds, "changed": [], "kept": [], "note": ""}
    fixed = [c for c in leaves_ if protected(c)]
    free = [c for c in leaves_ if not protected(c)]
    fixed_total = sum(c.duration.likely_s for c in fixed)
    floors = {c.id: est.clip_floor(project, c) for c in free}
    cur = {c.id: _current(c) for c in free}
    new: dict[str, float] = {}
    budget = max(seconds - fixed_total, 0.0)
    left = list(free)
    k = 1.0
    while left:                                       # clips that would go below their floor stay at it; the rest share what is left
        k = budget / (sum(cur[c.id] for c in left) or 1.0)
        low = [c for c in left if cur[c.id] * k < floors[c.id][0]]
        if not low:
            break
        for c in low:
            new[c.id] = floors[c.id][0]
            budget = max(budget - floors[c.id][0], 0.0)
            left.remove(c)
    for c in left:
        new[c.id] = max(round(cur[c.id] * k * 2) / 2, floors[c.id][0])
    changed = []
    for c in free:
        if abs(new[c.id] - cur[c.id]) >= 0.05:
            c.target_seconds = new[c.id]
            if c.script:
                c.script.target_seconds = new[c.id]
            changed.append({"id": c.id, "number": nums.get(c.id, ""), "from": round(cur[c.id], 1), "to": round(new[c.id], 1)})
    achieved = round(fixed_total + sum(new.values()), 1)
    _roll(node)
    note = ""
    if achieved > seconds + 0.5:
        at_floor = [c for c in free if new[c.id] <= floors[c.id][0] + 0.01]
        why = floors[at_floor[0].id][1] if at_floor else ""
        parts = []
        if fixed:
            parts.append(f"{len(fixed)} clip{'s' if len(fixed) != 1 else ''} already made or kept as {'they are' if len(fixed) != 1 else 'it is'} "
                         f"take {fixed_total:.0f} s")
        if why:
            parts.append(f"in the rest, {why}")
        note = f"It cannot go below {achieved:.0f} s: " + "; ".join(parts) + "." if parts else f"It cannot go below {achieved:.0f} s."
    return {"requested": seconds, "achieved": achieved, "changed": changed, "kept": [nums.get(c.id, "") for c in fixed], "note": note}


def _roll(node: Node) -> float:
    """Every part under this node gets the length of what is inside it. Returns this node's length."""
    if node.is_leaf:
        return float(node.target_seconds or node.duration.likely_s or 0.0)
    total = round(sum(_roll(c) for c in node.children), 1)
    node.target_seconds = total
    return total
