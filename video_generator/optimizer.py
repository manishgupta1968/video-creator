"""The Optimizer: a shorter and cheaper video, with every change proposed first and nothing taken silently.

Every change is a small pure edit (set a clip's length, a quality, the takes; switch natural sound, the Review Agent or music off; change a
script; drop or merge clips). A proposal is those edits applied to a COPY of the project and measured by the same `estimate.refresh` the screen
uses, so the "After" numbers are exactly what you see after Apply. It is stateless: the screen sends back the edits you ticked.

The ladder (it stops at the first level that meets the goal, and says so):
  1  No visible change   clips cut to what their content needs (no slack, no padding)
  2  Small change        one step cheaper quality; fewer takes for people clips; action steps at the fastest honest pace
  3  Noticeable change   natural sound off, Review Agent off (and music off for the whole video); each says what you lose
  4  Script change (AI)  shorter lines, dropped or merged clips, suggested by the AI and never applied without your tick

Never touched: clips already made, clips you keep as they are, clips you protect, and lines marked "say exactly this".
"""
from __future__ import annotations

import math
from typing import Any, Optional

from pydantic import BaseModel, Field

from . import continuity as continuity_mod
from . import estimate as est
from . import policy as policy_mod
from . import scaling
from .models import DependencyType, Node, NodeKind, NodeStatus, Project
from .tree import find, leaves, numbering, parent_of, remove, walk

LEVELS = {1: "No visible change", 2: "Small change", 3: "Noticeable change", 4: "Script change (AI)"}
LEVEL_HELP = {
    1: "Only empty time is taken out of clips: each keeps all its words and action at the normal pace.",
    2: "A little less polish: one step cheaper models, fewer takes to choose from, action a little faster.",
    3: "Something you would notice is switched off. Each change says what you lose.",
    4: "The AI suggests shorter lines or fewer clips. You see each one and tick what you want.",
}
STEP_DOWN = {"best": "balanced", "balanced": "budget"}
CARRYING = ("continues", "same_scene")
AI_TOKENS_BASE, AI_TOKENS_PER_CLIP = (1200, 500), (650, 220)       # in and out tokens: the instructions, and each clip shown to the AI


class Goal(BaseModel):
    """What the person wants. length and cost are numbers for the scope (seconds, dollars still to spend); lowest = as low as possible without losing quality."""
    length: Optional[float] = None
    cost: Optional[float] = None
    lowest: bool = False


class Edit(BaseModel):
    id: str
    level: int
    kind: str                      # seconds | mode | takes | sound_off | review_off | music_off | script | drop_clip | merge_clips
    nodes: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)
    value: Any = None
    label: str = ""                # plain words: what changes
    loses: str = ""                # what you lose ("" = nothing you would see)
    reason: str = ""               # why (the AI's reason)
    kept: str = ""                 # what meaning is kept (the AI says)
    effect: dict = Field(default_factory=dict)       # measured on its own: {seconds, cost} (negative = saved)


# ------------------------------------------------------------------ small helpers
def _secs(x: float) -> str:
    return f"{x:.0f} s" if abs(x - round(x)) < 0.05 else f"{x:.1f} s"


def _up(x: float) -> float:
    return math.ceil(x * 2 - 1e-9) / 2                 # to the next half second


def natural_seconds(project: Project, node: Node) -> float:
    """What a clip needs at the NORMAL pace: its speech with pauses, each action step at policy.action_seconds, never below policy.min_clip_s."""
    pol = policy_mod.current()
    steps = len(node.script.action_beats) * pol.action_seconds if node.script else 0.0
    return _up(max(est.speech_need(project, node), steps, pol.min_clip_s))


def is_protected(node: Node, extra: frozenset) -> bool:
    return scaling.protected(node) or node.id in extra


def has_fixed_text(node: Node) -> bool:
    s = node.script
    return bool(s and (s.narration_fixed or any(d.fixed for d in s.dialogue)))


def _scope_clips(project: Project, scope_id: str) -> list[Node]:
    return [n for n, _ in walk(find(project, scope_id)) if n.kind == NodeKind.clip]


def _free_clips(project: Project, scope_id: str, extra: frozenset) -> list[Node]:
    return [c for c in _scope_clips(project, scope_id) if not is_protected(c, extra) and c.script]


def measure(svc, q: Project, scope_id: str) -> dict:
    """The numbers the screen shows for this scope: length, what is still to spend (made clips are already paid), the whole cost, making time."""
    svc.refresh(q)
    n = find(q, scope_id)
    below = [x for x, _ in walk(n) if x.is_leaf]
    todo = [x for x in below if x.status != NodeStatus.done]
    return {"seconds": round(n.duration.likely_s, 1), "cost": round(sum(x.cost.likely_usd for x in todo), 2), "cost_total": round(n.cost.likely_usd, 2),
            "time_s": round(q.root.time.likely_s if scope_id == q.root.id else n.time.likely_s), "clips": len(below), "to_make": len(todo)}


# ------------------------------------------------------------------ the candidates (levels 1 to 3)
def _weak_clips(svc, project: Project, scope_id: str, mode: str, clips: list[Node]) -> list[str]:
    """Clips that this quality would give a weak model for their kind of shot (below policy.budget_min_strength): a step that does that is not proposed."""
    q = project.model_copy(deep=True)
    if scope_id == q.root.id:
        q.settings.quality_mode = mode
    else:
        find(q, scope_id).quality_mode = mode
    nums = numbering(q)
    weak = []
    for c in clips:
        node = find(q, c.id)
        plan = est.plan_clip(q, node, svc.reg)
        if plan.video and not plan.video.is_free and plan.route == "video" and plan.video.strength(node.script.shot_type.value) < policy_mod.current().budget_min_strength:
            weak.append(nums.get(c.id, ""))
    return weak


def candidates(svc, project: Project, scope_id: str, extra: frozenset = frozenset()) -> tuple[list[Edit], list[str]]:
    """Every edit of levels 1 to 3 that could apply to this scope, and plain notes about what was not proposed and why."""
    pol = policy_mod.current()
    nums = numbering(project)
    scope = find(project, scope_id)
    is_root = scope_id == project.root.id
    free = _free_clips(project, scope_id, extra)
    plans = {c.id: est.plan_clip(project, c, svc.reg) for c in free}
    edits: list[Edit] = []
    notes: list[str] = []

    # level 1: cut each clip to what its content needs
    for c in free:
        cur, nat = c.duration.likely_s, natural_seconds(project, c)
        if cur - nat >= pol.optimize_slack_s:
            edits.append(Edit(id=f"L1:seconds:{c.id}", level=1, kind="seconds", nodes=[c.id], numbers=[nums[c.id]], value=nat,
                              label=f"Clip {nums[c.id]}: {_secs(cur)} to {_secs(nat)}"))

    # level 2: a little less polish. One quality step down; when the next step changes nothing (the same model is picked), the step after it.
    cur_mode = est.mode_for(project, scope)
    cheaper = [m for m in ("balanced", "budget") if ("best", "balanced", "budget").index(m) > ("best", "balanced", "budget").index(cur_mode)] if cur_mode in ("best", "balanced", "budget") else []
    base_cost = measure(svc, project.model_copy(deep=True), scope_id)["cost"] if cheaper and any(p.video and not p.video.is_free for p in plans.values()) else None
    for nxt in cheaper if base_cost is not None else []:
        weak = _weak_clips(svc, project, scope_id, nxt, free)
        if weak:
            notes.append(f"{nxt.title()} quality was not proposed: it would give clip{'s' if len(weak) > 1 else ''} {', '.join(weak[:4])} a model that is weak for that kind of shot.")
            break
        q = project.model_copy(deep=True)
        if is_root:
            q.settings.quality_mode = nxt
        else:
            find(q, scope_id).quality_mode = nxt
        if abs(measure(svc, q, scope_id)["cost"] - base_cost) < 0.005:
            continue                                               # the same models would be used: try the next step
        edits.append(Edit(id=f"L2:mode:{scope_id}", level=2, kind="mode", nodes=[scope_id], value=nxt,
                          label=f"{'The whole video' if is_root else 'Part ' + nums[scope_id]}: {cur_mode} quality to {nxt}",
                          loses="Cheaper video, picture and sound models: they may look a little less polished. Voices and music do not change."))
        break
    takes: dict[str, int] = {}
    for c in free:
        plan = plans[c.id]
        if est.is_people_shot(c) and plan.video and not plan.video.is_free and plan.route in ("video", "avatar") and plan.takes > 1:
            takes[c.id] = plan.takes - 1
    if takes:
        edits.append(Edit(id=f"L2:takes:{scope_id}", level=2, kind="takes", nodes=list(takes), numbers=[nums[i] for i in takes], value=takes,
                          label=f"People clips {', '.join(nums[i] for i in list(takes)[:5])}{'…' if len(takes) > 5 else ''}: one take fewer each",
                          loses="Fewer takes to choose from, so a flaw is more likely to be in the one you get."))
    for c in free:
        nat, fast = natural_seconds(project, c), _up(est.clip_floor(project, c)[0])
        if nat - fast >= pol.optimize_slack_s and c.script and c.script.action_beats:
            edits.append(Edit(id=f"L2:pace:{c.id}", level=2, kind="seconds", nodes=[c.id], numbers=[nums[c.id]], value=fast,
                              label=f"Clip {nums[c.id]}: action at the fastest honest pace, {_secs(nat)} to {_secs(fast)}",
                              loses=f"Each action step moves a little faster ({pol.min_action_seconds:g} s instead of {pol.action_seconds:g} s)."))

    # level 3: something you would notice
    amb = [c for c in free if est.wants_ambience(project, c, plans[c.id])]
    if amb:
        edits.append(Edit(id=f"L3:sound:{scope_id}", level=3, kind="sound_off", nodes=[scope_id],
                          label=f"{'The whole video' if is_root else 'Part ' + nums[scope_id]}: no made natural sound",
                          loses="No wind, room tone or footsteps made under the clips (a video model's own sound stays)."))
    reviewing = [c for c in free if project.settings.review_enabled and c.review_enabled and plans[c.id].route in ("video", "avatar")]
    if reviewing:
        edits.append(Edit(id=f"L3:review:{scope_id}", level=3, kind="review_off", nodes=[c.id for c in reviewing], numbers=[nums[c.id] for c in reviewing],
                          label=f"No Review Agent on {len(reviewing)} clip{'s' if len(reviewing) != 1 else ''}",
                          loses="No second opinion on the takes: you judge them yourself."))
    if project.settings.music and est._music_entry(svc.reg, project):
        if is_root:
            edits.append(Edit(id="L3:music:" + scope_id, level=3, kind="music_off", nodes=[scope_id], label="No background music",
                              loses="The video has no music at all."))
        else:
            notes.append("Music is one track for the whole video, so a single part cannot switch it off. Every second taken out of a part also lowers the music cost, "
                         "and a track that was already made is reused at no cost.")
    return edits, notes


# ------------------------------------------------------------------ applying edits (always to a project you pass in, usually a copy)
def _trim_to_natural(project: Project, node: Node) -> None:
    nat = natural_seconds(project, node)
    cur = node.target_seconds or node.duration.likely_s
    if cur and nat < cur:
        node.target_seconds = nat
        if node.script:
            node.script.target_seconds = nat


def _merge_scripts(a: Node, b: Node) -> None:
    sa, sb = a.script, b.script
    sa.visual = f"{sa.visual.rstrip('. ')}. Then: {sb.visual}".strip()
    sa.action_beats = list(sa.action_beats) + list(sb.action_beats)
    sa.dialogue = list(sa.dialogue) + list(sb.dialogue)
    sa.narration = (sa.narration.rstrip() + " " + sb.narration.lstrip()).strip()
    sa.narration_fixed = sa.narration_fixed or sb.narration_fixed
    seen = {x.actor_id for x in sa.actors_in_shot}
    sa.actors_in_shot = list(sa.actors_in_shot) + [x for x in sb.actors_in_shot if x.actor_id not in seen]
    sa.end_state = sb.end_state or sa.end_state
    a.continuity.end_state = b.continuity.end_state or sb.end_state or a.continuity.end_state
    a.target_seconds = (a.target_seconds or a.duration.likely_s) + (b.target_seconds or b.duration.likely_s)
    sa.target_seconds = a.target_seconds


def apply_edits(svc, project: Project, edits: list[Edit]) -> dict[str, str]:
    """Apply these edits to `project` (in place), the lower levels first. Returns {merged clip id: the clip it was merged into}."""
    merged_into: dict[str, str] = {}
    for e in sorted(edits, key=lambda x: x.level):
        try:
            if e.kind == "seconds":
                n = find(project, e.nodes[0])
                n.target_seconds = float(e.value)
                if n.script:
                    n.script.target_seconds = float(e.value)
            elif e.kind == "mode":
                if e.nodes[0] == project.root.id:
                    project.settings.quality_mode = e.value
                else:
                    find(project, e.nodes[0]).quality_mode = e.value
            elif e.kind == "takes":
                for nid, k in e.value.items():
                    find(project, nid).takes_override = int(k)
            elif e.kind == "sound_off":
                if e.nodes[0] == project.root.id:
                    project.settings.ambience = False
                else:
                    find(project, e.nodes[0]).ambience = False
            elif e.kind == "review_off":
                for nid in e.nodes:
                    find(project, nid).review_enabled = False
            elif e.kind == "music_off":
                project.settings.music = False
            elif e.kind == "script":
                n = find(project, e.nodes[0])
                s = n.script
                if e.value.get("narration") is not None:
                    s.narration = e.value["narration"]
                lines = []
                for line, text in zip(s.dialogue, e.value.get("dialogue", [])):
                    if text.strip() or line.fixed:
                        line.text = text if text.strip() else line.text
                        lines.append(line)
                s.dialogue = lines if e.value.get("dialogue") else s.dialogue
                n.voice_audio, n.voice_seconds = None, None            # the words changed, so any earlier voice no longer fits
                _trim_to_natural(project, n)
            elif e.kind == "drop_clip":
                remove(project, e.nodes[0])
            elif e.kind == "merge_clips":
                a, b = find(project, e.nodes[0]), find(project, e.nodes[1])
                _merge_scripts(a, b)
                for d in project.dependencies:                          # what continued from the second clip now continues from the merged one
                    if d.from_id == b.id and d.to_id != a.id:
                        d.from_id = a.id
                merged_into[b.id] = a.id
                remove(project, b.id)
                _trim_to_natural(project, a)
        except KeyError:
            continue                                                    # the clip is gone already (for example it was dropped by another edit)
    if any(e.kind in ("drop_clip", "merge_clips") for e in edits):
        svc._repair_joins(project)
        svc._sync_states(project)
    return merged_into


def resync_targets(svc, project: Project) -> None:
    """After a change the part and video lengths follow what is inside them (a length you asked for earlier is replaced by what you chose now)."""
    svc.refresh(project)
    total = scaling._roll(project.root)
    project.settings.target_seconds = total
    project.root.target_seconds = total


# ------------------------------------------------------------------ joins
def joins_of(project: Project) -> dict[tuple[str, str], str]:
    """Every join that carries something over (continues, same scene) between neighbouring clips."""
    links = {(d.from_id, d.to_id): d.type for d in project.dependencies if d.type in (DependencyType.continues_from, DependencyType.same_location)}
    out = {}
    ls = leaves(project)
    for a, b in zip(ls, ls[1:]):
        if a.kind != NodeKind.clip or b.kind != NodeKind.clip:
            continue
        j = b.continuity.join or ("continues" if links.get((a.id, b.id)) == DependencyType.continues_from
                                  else "same_scene" if links.get((a.id, b.id)) == DependencyType.same_location else "")
        if j in CARRYING:
            out[(a.id, b.id)] = j
    return out


def joins_report(before: Project, after: Project, merged_into: dict[str, str]) -> dict:
    """"Joins kept: 5 of 5": how many of the joins that carry something over are still there, and which are lost."""
    nums = numbering(before)
    jb, ja = joins_of(before), joins_of(after)
    kept, broken = 0, []
    for (a, b), j in jb.items():
        a2, b2 = merged_into.get(a, a), merged_into.get(b, b)
        if a2 == b2 or ja.get((a2, b2)) == j:
            kept += 1
        else:
            what = "continuing shot" if j == "continues" else "same-scene join"
            broken.append(f"The {what} between clips {nums.get(a, '')} and {nums.get(b, '')} is lost: the clip after it now starts with a cut.")
    return {"kept": kept, "of": len(jb), "broken": broken}


# ------------------------------------------------------------------ the AI's suggestions (level 4), checked before you ever see them
def validate_ai(svc, base: Project, scope_id: str, extra: frozenset, raw: list[dict]) -> tuple[list[Edit], list[str]]:
    """Turn what the AI suggested into edits, and refuse (with a plain reason) anything that breaks a rule: a protected clip, a line marked exact,
    cutting more than policy.max_cut_ratio, the last clip of a part, or a merge across a cut."""
    pol = policy_mod.current()
    nums = numbering(base)
    by_number = {v: k for k, v in nums.items() if v}
    inside = {c.id for c in _scope_clips(base, scope_id)}
    edits: list[Edit] = []
    skipped: list[str] = []
    used: set[str] = set()
    gone: dict[str, int] = {}                                       # per part: how many clips this set of suggestions already removes

    def skip(why: str) -> None:
        skipped.append(why)

    for r in raw:
        number = str(r.get("clip", "")).strip()
        nid = by_number.get(number)
        action = r.get("action", "shorten")
        if not nid or nid not in inside:
            skip(f"Clip {number}: not part of this scope.")
            continue
        node = find(base, nid)
        if is_protected(node, extra) or not node.script:
            skip(f"Clip {number}: it is made, kept or protected, so it is left as it is.")
            continue
        if nid in used:
            skip(f"Clip {number}: two suggestions for one clip; the first is used.")
            continue
        reason, kept = str(r.get("reason", ""))[:240], str(r.get("kept", ""))[:240]
        parent = parent_of(base, nid)
        siblings = [c for c in parent.children if c.is_leaf]
        if action == "shorten":
            s = node.script
            old_lines = [d.text for d in s.dialogue]
            new_lines = list(r.get("dialogue") or old_lines)
            if len(new_lines) != len(old_lines):
                skip(f"Clip {number}: the AI changed the number of lines; ignored.")
                continue
            new_lines = [d.text if d.fixed else t for d, t in zip(s.dialogue, new_lines)]       # a line marked exact is never changed
            new_narr = s.narration if s.narration_fixed or r.get("narration") is None else str(r["narration"])
            old_words = sum(est._words(t) for t in old_lines) + est._words(s.narration)
            new_words = sum(est._words(t) for t in new_lines) + est._words(new_narr)
            if new_lines == old_lines and new_narr == s.narration:
                skip(f"Clip {number}: nothing to shorten (the lines are marked exact, or already short).")
                continue
            if old_words and new_words < old_words * (1 - pol.max_cut_ratio) - 0.5:
                skip(f"Clip {number}: the AI would cut more than {pol.max_cut_ratio:.0%} of the words ({old_words} to {new_words}); ignored.")
                continue
            edits.append(Edit(id=f"L4:script:{nid}", level=4, kind="script", nodes=[nid], numbers=[number],
                              value={"narration": new_narr if new_narr != s.narration else None, "dialogue": new_lines if new_lines != old_lines else []},
                              label=f"Clip {number}: shorter lines ({old_words} to {new_words} words)",
                              loses="Fewer words. The AI says what meaning is kept.", reason=reason, kept=kept))
            used.add(nid)
        elif action == "drop":
            if has_fixed_text(node):
                skip(f"Clip {number}: it holds a line marked “say exactly this”, so it stays.")
                continue
            limit = max(int(len(siblings) * pol.max_cut_ratio), 0)
            if len(siblings) - gone.get(parent.id, 0) <= 1 or gone.get(parent.id, 0) + 1 > limit:
                skip(f"Clip {number}: a part keeps at least one clip and loses at most {pol.max_cut_ratio:.0%} of them; this drop is ignored.")
                continue
            gone[parent.id] = gone.get(parent.id, 0) + 1
            edits.append(Edit(id=f"L4:drop:{nid}", level=4, kind="drop_clip", nodes=[nid], numbers=[number],
                              label=f"Drop clip {number}: {node.title or node.goal[:40]}",
                              loses="The clip is gone. Any join that depended on it becomes a cut.", reason=reason, kept=kept))
            used.add(nid)
        elif action == "merge_with_next":
            i = [c.id for c in siblings].index(nid)
            nxt = siblings[i + 1] if i + 1 < len(siblings) else None
            if not nxt or nxt.id in used or is_protected(nxt, extra) or not nxt.script:
                skip(f"Clip {number}: it cannot be merged with the next clip (none, protected, or already used).")
                continue
            if nxt.continuity.join not in CARRYING:
                skip(f"Clips {number} and {nums.get(nxt.id, '')}: a merge across a cut would change the place or time; ignored.")
                continue
            if node.script.shot_type != nxt.script.shot_type or node.script.on_camera_speech != nxt.script.on_camera_speech:
                skip(f"Clips {number} and {nums.get(nxt.id, '')}: they need different kinds of shot, so one clip could not make both; ignored.")
                continue
            limit = max(int(len(siblings) * pol.max_cut_ratio), 0)
            if len(siblings) - gone.get(parent.id, 0) <= 1 or gone.get(parent.id, 0) + 1 > limit:
                skip(f"Clips {number} and {nums.get(nxt.id, '')}: a part keeps at least one clip and loses at most {pol.max_cut_ratio:.0%} of them; ignored.")
                continue
            gone[parent.id] = gone.get(parent.id, 0) + 1
            edits.append(Edit(id=f"L4:merge:{nid}", level=4, kind="merge_clips", nodes=[nid, nxt.id], numbers=[number, nums.get(nxt.id, "")],
                              label=f"Merge clips {number} and {nums.get(nxt.id, '')} into one",
                              loses="Two clips become one; the join between them is inside it now.", reason=reason, kept=kept))
            used.update({nid, nxt.id})
        else:
            skip(f"Clip {number}: unknown suggestion “{action}”; ignored.")
    return edits, skipped


def ai_estimate(svc, project: Project, scope_id: str, extra: frozenset) -> dict:
    """What asking the AI to tighten this scope would cost BEFORE it is asked: {available, clips, cost_low, cost_high, why}."""
    clips = [c for c in _free_clips(project, scope_id, extra)]
    if not clips:
        return {"available": False, "clips": 0, "cost_low": 0.0, "cost_high": 0.0, "why": "Every clip here is made, kept or protected, so there is nothing for the AI to change."}
    tokens = (AI_TOKENS_BASE[0] + AI_TOKENS_PER_CLIP[0] * len(clips), AI_TOKENS_BASE[1] + AI_TOKENS_PER_CLIP[1] * len(clips))
    entry = svc.reg.llm_entry("optimize")
    one = est._llm_cost(entry, tokens)
    lo, hi = (list(policy_mod.current().optimize_ai_cost_range) + [0.6, 1.6])[:2]
    return {"available": True, "clips": len(clips), "cost_low": round(one * lo, 3), "cost_high": round(one * hi, 3), "model": entry.id if entry else "offline helper", "why": ""}


# ------------------------------------------------------------------ the proposal
def _meets(m: dict, goal: Goal) -> bool:
    tol = policy_mod.current().optimize_goal_tolerance
    ok_len = goal.length is None or m["seconds"] <= goal.length * (1 + tol) + 0.25
    ok_cost = goal.cost is None or m["cost"] <= goal.cost * (1 + tol) + 0.005
    return ok_len and ok_cost


def _delta(a: dict, b: dict) -> dict:
    return {"seconds": round(b["seconds"] - a["seconds"], 1), "cost": round(b["cost"] - a["cost"], 2), "time_s": round(b["time_s"] - a["time_s"])}


def propose(svc, project: Project, scope_id: str, goal: Goal, max_level: Optional[int] = None, ticked: Optional[list[str]] = None,
            protect: list[str] = (), ai_edits: list[dict] = ()) -> dict:
    """The whole proposal for a goal. Nothing is saved. `ticked` = the edits you chose (None = let the ladder choose)."""
    if goal.length is None and goal.cost is None and not goal.lowest:
        raise ValueError("Choose a goal: a length, a cost, or as low as possible without losing quality.")
    base = project.model_copy(deep=True)
    base_m = measure(svc, base, scope_id)
    nums = numbering(base)
    extra = frozenset(protect)
    scope = find(base, scope_id)
    if max_level is None:
        max_level = 1 if goal.lowest else 3
    cands, notes = candidates(svc, base, scope_id, extra)
    ai, skipped = validate_ai(svc, base, scope_id, extra, list(ai_edits)) if ai_edits else ([], [])
    notes += skipped

    # what each edit does on its own; an edit that changes nothing is not proposed
    kept_edits: list[Edit] = []
    for e in cands + ai:
        q = base.model_copy(deep=True)
        apply_edits(svc, q, [e])
        m = measure(svc, q, scope_id)
        e.effect = _delta(base_m, m)
        if abs(e.effect["seconds"]) >= 0.05 or abs(e.effect["cost"]) >= 0.005:
            kept_edits.append(e)
    all_edits = sorted(kept_edits, key=lambda e: e.level)

    # the ladder: what you would have after taking everything up to each level
    levels, met_at = [], None
    for L in (1, 2, 3, 4):
        upto = [e for e in all_edits if e.level <= L]
        q = base.model_copy(deep=True)
        apply_edits(svc, q, upto)
        m = measure(svc, q, scope_id)
        meets = _meets(m, goal) if not goal.lowest else False
        if meets and met_at is None:
            met_at = L
        here = [e for e in all_edits if e.level == L]
        levels.append({"level": L, "name": LEVELS[L], "help": LEVEL_HELP[L], "edits": [e.id for e in here], "after": m, "saves": _delta(base_m, m),
                       "meets_goal": meets, "available": bool(here) or L == 4})

    floor_m = levels[3]["after"] if ai else levels[2]["after"]      # the most that can be done (without the AI's script changes unless they were asked for)
    if ticked is not None:
        chosen = [e for e in all_edits if e.id in set(ticked)]
    elif goal.lowest:
        chosen = [e for e in all_edits if e.level <= max_level and e.level < 4]
    elif met_at:
        chosen = [e for e in all_edits if e.level <= met_at]
    else:
        chosen = [e for e in all_edits if e.level <= max(max_level, 4 if ai else 0)]

    q = base.model_copy(deep=True)
    merged = apply_edits(svc, q, chosen)
    after = measure(svc, q, scope_id)
    met = _meets(after, goal) if not goal.lowest else True
    reason = "" if met else _reason(goal, base_m, floor_m, base, scope_id, extra, bool(ai))
    before_findings = {(f["code"], f["node"], f["text"]) for f in continuity_mod.check(base, svc.reg)}
    new_findings = [f for f in continuity_mod.check(q, svc.reg) if (f["code"], f["node"], f["text"]) not in before_findings]
    protected = [nums[c.id] for c in _scope_clips(base, scope_id) if is_protected(c, extra)]
    chosen_ids = {e.id for e in chosen}
    return {
        "scope": {"id": scope_id, "number": nums.get(scope_id, ""), "title": scope.title or scope.goal[:40], "is_whole_video": scope_id == base.root.id},
        "goal": goal.model_dump(), "max_level": max_level, "met": met, "stopped_at": met_at or 0, "reason": reason, "notes": notes,
        "before": base_m, "after": after, "saves": _delta(base_m, after), "levels": levels,
        "edits": [{**e.model_dump(), "checked": e.id in chosen_ids} for e in all_edits],
        "joins": joins_report(base, q, merged), "findings": new_findings,
        "protected": {"numbers": protected, "count": len(protected)},
        "ai": ai_estimate(svc, base, scope_id, extra),
    }


def _reason(goal: Goal, before: dict, floor: dict, base: Project, scope_id: str, extra: frozenset, tried_ai: bool) -> str:
    """Why the goal cannot be met, in plain words, and what would be needed."""
    held = [c for c in _scope_clips(base, scope_id) if is_protected(c, extra)]
    parts = []
    if goal.length is not None and floor["seconds"] > goal.length * (1 + policy_mod.current().optimize_goal_tolerance) + 0.25:
        if tried_ai:
            parts.append(f"Even with the AI's suggestions it cannot go below about {floor['seconds']:.0f} s: lines marked “say exactly this” always stay, "
                         f"and no more than {policy_mod.current().max_cut_ratio:.0%} of the words or clips may be cut.")
        else:
            parts.append(f"Below about {floor['seconds']:.0f} s needs cutting spoken lines or dropping clips. Lines marked “say exactly this” always stay.")
    if goal.cost is not None and floor["cost"] > goal.cost * (1 + policy_mod.current().optimize_goal_tolerance) + 0.005:
        parts.append(f"The lowest cost reachable here {'with the AI' + chr(39) + 's suggestions' if tried_ai else 'without changing the script'} is about ${floor['cost']:.2f}.")
    if held:
        parts.append(f"{len(held)} clip{'s are' if len(held) != 1 else ' is'} made, kept or protected, so {'they stay' if len(held) != 1 else 'it stays'} as {'they are' if len(held) != 1 else 'it is'}.")
    if not tried_ai:
        parts.append("Asking the AI to tighten the script can go further; you see its cost first and tick each change.")
    return " ".join(parts)


def apply(svc, project: Project, scope_id: str, goal: Goal, ticked: Optional[list[str]] = None, protect: list[str] = (), ai_edits: list[dict] = ()) -> Project:
    """Apply exactly the edits you ticked (None = the ones the ladder chose), as one change (one undo step). Returns the project, not yet saved."""
    p = propose(svc, project, scope_id, goal, ticked=ticked, protect=list(protect), ai_edits=list(ai_edits))
    chosen_ids = {e["id"] for e in p["edits"] if e["checked"]}
    edits = [Edit(**{k: v for k, v in e.items() if k != "checked"}) for e in p["edits"] if e["id"] in chosen_ids]
    apply_edits(svc, project, edits)
    resync_targets(svc, project)
    return project
