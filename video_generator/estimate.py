"""Live estimates of length, cost and time for every node.

Stage 1 (goal):   length range from the goal / share of the parent's target
Stage 2 (script): words / speaking rate + action time + pauses
Stage 3 (actual): real voice length, then real clip length after making
Cost = unit price x units x takes, per line item; parents add up children.
Time = queue + processing per step; parallel steps counted once.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

from .catalog import CatalogEntry
from .context import effective_context
from .deps import topo_order, upstream
from .models import (ContextRole, ContextType, CostEstimate, CostLine, DependencyType,
                     DurationEstimate, EstimateBasis, Node, NodeKind, Project, ShotType, TimeEstimate)
from .registry import Registry
from .tree import find, leaves, walk

PEOPLE_SHOTS = {ShotType.talking_head, ShotType.dialogue_scene, ShotType.human_motion}
ACTION_SECONDS = 2.5
LINE_PAUSE = 0.6
EDGE_PAD = 0.5
SECONDS_PER_SLIDE = 5.0
SCRIPT_TOKENS = (6000, 2500)       # in, out per clip script
REVIEW_TOKENS = (14000, 1500)      # per take review (frames + context)
PLAN_TOKENS = (8000, 6000)


def _words(text: str) -> int:
    return len(re.findall(r"[\w'’-]+", text or ""))


def speaking_wpm(project: Project, node: Node, speaker: str) -> int:
    base = project.settings.default_wpm
    for e in effective_context(project, node.id):
        if e.item.id == speaker and e.item.actor:
            a = e.item.actor
            if a.speaking_wpm:
                return a.speaking_wpm
            b = (a.behaviour + " " + a.voice_description).lower()
            if any(w in b for w in ("fast", "excited", "energetic", "rapid", "quick")):
                return int(base * 1.15)
            if any(w in b for w in ("slow", "calm", "measured", "deliberate", "gentle")):
                return int(base * 0.88)
    return base


def is_people_shot(node: Node) -> bool:
    s = node.script
    if not s:
        return False
    return s.shot_type in PEOPLE_SHOTS or bool(s.actors_in_shot)


def takes_for(project: Project, node: Node) -> int:
    if node.takes_override:
        return node.takes_override
    return project.settings.takes_people if is_people_shot(node) else project.settings.takes_other


# --------------------------------------------------------------------- duration
def estimate_duration(project: Project, node: Node, siblings_share: Optional[float] = None) -> DurationEstimate:
    if node.kind == NodeKind.user_clip:
        secs = float(node.voice_seconds or node.duration.likely_s or 0)
        if node.media:
            from .media import probe_duration
            secs = probe_duration(project_path(project) / node.media) or secs
        return DurationEstimate(min_s=secs, likely_s=secs, max_s=secs, basis=EstimateBasis.actual,
                                explain="length of your clip")
    if node.kind == NodeKind.slides:
        pages = int(node.style_overrides.get("pages", "0") or 0)
        if node.media and not pages:
            from .media import count_pages
            pages = count_pages(project_path(project) / node.media)
        per = float(node.style_overrides.get("seconds_per_slide", SECONDS_PER_SLIDE))
        narration = node.script.narration if node.script else ""
        speech = _words(narration) / project.settings.default_wpm * 60 if narration else 0
        secs = max(pages * per, speech, per)
        return DurationEstimate(min_s=secs * 0.9, likely_s=secs, max_s=secs * 1.15, basis=EstimateBasis.script,
                                explain=f"{pages} slide(s) x {per:.0f} s" + (f"; narration {speech:.0f} s" if speech else ""))

    if node.output and node.status.value == "done" and node.duration.basis == EstimateBasis.actual:
        return node.duration

    if node.kind == NodeKind.clip and node.voice_seconds:
        s = node.script
        action = len(s.action_beats) * ACTION_SECONDS if s else 0
        secs = max(node.voice_seconds + 2 * EDGE_PAD * 0.5, action, 2.0)
        if node.script and node.script.target_seconds and not node.script.dialogue and not node.script.narration:
            secs = node.script.target_seconds
        return DurationEstimate(min_s=secs, likely_s=secs, max_s=secs, basis=EstimateBasis.actual,
                                explain=f"real voice length {node.voice_seconds:.1f} s + padding")

    if node.kind == NodeKind.clip and node.script and (node.script.dialogue or node.script.narration
                                                         or node.script.action_beats or node.script.visual):
        s = node.script
        parts, speech = [], 0.0
        lines = [(d.speaker, d.text) for d in s.dialogue if d.text.strip()]
        if s.narration.strip():
            lines.append(("narrator", s.narration))
        for speaker, text in lines:
            wpm = speaking_wpm(project, node, speaker)
            speech += _words(text) / wpm * 60
        pauses = LINE_PAUSE * max(len(lines) - 1, 0) + (2 * EDGE_PAD if lines else 0)
        action = len(s.action_beats) * ACTION_SECONDS
        likely = max(speech + pauses, action, s.target_seconds or 0, 3.0 if not lines else 0, 2.0)
        if lines:
            words = sum(_words(t) for _, t in lines)
            parts.append(f"{words} words ≈ {speech:.0f} s speech")
            if pauses:
                parts.append(f"{pauses:.1f} s pauses")
        if action:
            parts.append(f"{len(s.action_beats)} action beat(s) ≈ {action:.0f} s")
        if s.target_seconds and likely == s.target_seconds:
            parts.append("your target length")
        return DurationEstimate(min_s=round(likely * 0.88, 1), likely_s=round(likely, 1), max_s=round(likely * 1.2, 1),
                                basis=EstimateBasis.script, explain=" + ".join(parts) or "minimum clip length")

    # stage 1: from the goal
    target = node.target_seconds or (node.script.target_seconds if node.script else None) or siblings_share or 6.0
    return DurationEstimate(min_s=round(target * 0.7, 1), likely_s=round(target, 1), max_s=round(target * 1.35, 1),
                            basis=EstimateBasis.goal,
                            explain="from the goal" + (" (your target)" if node.target_seconds else " (share of the parent's length)"))


def project_path(project: Project):
    from .project import ProjectStore
    return ProjectStore.path_for(project.id)


# --------------------------------------------------------------------- routing per clip
@dataclass
class ClipPlan:
    route: str                         # video | avatar | slides | user_clip
    video: Optional[CatalogEntry]
    image: Optional[CatalogEntry]
    voice: Optional[CatalogEntry]
    lipsync: Optional[CatalogEntry]
    takes: int
    needs_start_frame: bool
    ref_images: int
    lipsync_needed: bool
    warnings: list[str]


def clip_actors(project: Project, node: Node):
    return [e.item for e in effective_context(project, node.id) if e.item.type == ContextType.actor]


def plan_clip(project: Project, node: Node, reg: Registry) -> ClipPlan:
    warnings: list[str] = []
    if node.kind in (NodeKind.slides, NodeKind.user_clip):
        voice = reg.choose("voice") if (node.script and node.script.narration) else None
        return ClipPlan(node.kind.value, None, None, voice, None, 1, False, 0, False, warnings)
    s = node.script
    shot = s.shot_type.value if s else "other"
    takes = takes_for(project, node)
    eff = effective_context(project, node.id)
    ref_images = sum(len([f for f in e.item.files if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
                     for e in eff if e.item.role in (ContextRole.must_appear, ContextRole.look_reference))
    needs_start = any(d.type == DependencyType.continues_from for d in upstream(project, node.id))
    mode = "free" if project.settings.quality_mode == "free" else project.settings.quality_mode
    voice = reg.choose("voice", mode=mode) if (s and (s.dialogue or s.narration)) else None
    image = reg.choose("image", mode=mode)

    avatar_actor = None
    if s and s.shot_type == ShotType.talking_head:
        for a in clip_actors(project, node):
            if a.actor and (a.files or a.actor.reference_sheet) and a.id in {x.actor_id for x in s.actors_in_shot} | {d.speaker for d in s.dialogue}:
                avatar_actor = a
                break
    if avatar_actor:
        av = reg.choose("avatar", mode=mode, override=node.provider_override)
        if av.is_free and not node.takes_override:
            takes = 1          # free previews are identical; one take is enough
        return ClipPlan("avatar", av, image, voice, None, takes, False, ref_images, False, warnings)

    need: dict = {}
    if needs_start:
        need["start_frame"] = True
    video = reg.choose("video", shot, need=need, override=node.provider_override, mode=mode)
    if video.is_free and not node.takes_override:
        takes = 1              # free previews are identical; one take is enough
    max_refs = int(video.capabilities.get("reference_images", 0) or 0)
    if ref_images > max(max_refs, 0) and ref_images > 0:
        warnings.append(f"{ref_images} reference image(s) but {video.id} accepts {max_refs}; the most relevant will be used")
    if needs_start and not video.capabilities.get("start_frame"):
        warnings.append(f"{video.id} cannot start from the previous clip's last frame")
    lip = bool(s and s.on_camera_speech)
    lipsync = reg.choose("lipsync", mode=mode) if lip else None
    return ClipPlan("video", video, image, voice, lipsync, takes, needs_start, ref_images, lip, warnings)


# --------------------------------------------------------------------- cost & time
def _llm_entry(reg: Registry, task: str) -> Optional[CatalogEntry]:
    name = reg.llm_plugin_name(task)
    for e in reg.catalog.for_job("llm"):
        if e.plugin == name:
            return e
    return None


def _llm_cost(e: Optional[CatalogEntry], tokens: tuple[int, int]) -> float:
    if not e:
        return 0.0
    return tokens[0] / 1e6 * e.price.usd_in + tokens[1] / 1e6 * e.price.usd_out


def _music_entry(reg: Registry, project: Project) -> Optional[CatalogEntry]:
    if not project.settings.music:
        return None
    try:
        return reg.choose("music", mode=project.settings.quality_mode)
    except LookupError:
        return None


def estimate_clip_cost(project: Project, node: Node, reg: Registry, plan: Optional[ClipPlan] = None,
                       total_seconds: float = 0) -> tuple[CostEstimate, TimeEstimate]:
    plan = plan or plan_clip(project, node, reg)
    d = node.duration
    lines: list[CostLine] = []
    secs = d.likely_s

    def add(item: str, calc: str, cost: float) -> None:
        lines.append(CostLine(item=item, calc=calc, cost=round(cost, 4)))

    step_times: list[float] = []
    if node.script is None and node.kind == NodeKind.clip:
        e = _llm_entry(reg, "write_clip_script")
        add("AI brain: write script", f"~{SCRIPT_TOKENS[0] // 1000}k in + {SCRIPT_TOKENS[1] // 1000}k out tokens", _llm_cost(e, SCRIPT_TOKENS))
        step_times.append(20)

    if plan.voice and node.script:
        chars = len(" ".join([l.text for l in node.script.dialogue] + [node.script.narration]))
        v = plan.voice
        add(f"Voice ({v.id})", f"{chars} chars x ${v.unit_price}/1k", chars / 1000 * v.unit_price)
        step_times.append((v.time.queue_s + v.time.per_output_s * secs) * reg.time_factor(v.id))

    if plan.route == "avatar" and plan.video:
        a = plan.video
        add(f"Avatar video ({a.id})", f"{plan.takes} take(s) x {secs:.0f} s x ${a.unit_price}/s",
            plan.takes * secs * a.unit_price)
        step_times.append((a.time.queue_s + a.time.per_output_s * secs) * reg.time_factor(a.id))
    elif plan.route == "video" and plan.video:
        img_count = 0 if plan.needs_start_frame else plan.takes
        if img_count and plan.image:
            add(f"Keyframe images ({plan.image.id})", f"{img_count} x ${plan.image.unit_price}",
                img_count * plan.image.unit_price)
            step_times.append((plan.image.time.queue_s + plan.image.time.per_output_s) * reg.time_factor(plan.image.id))
        v = plan.video
        max_s = float(v.capabilities.get("max_seconds", 10) or 10)
        billed = secs
        add(f"Video ({v.id})", f"{plan.takes} take(s) x {billed:.0f} s x ${v.unit_price}/s",
            plan.takes * billed * v.unit_price)
        parts = math.ceil(secs / max_s) if secs > max_s else 1
        step_times.append((v.time.queue_s + v.time.per_output_s * min(secs, max_s) * parts) * reg.time_factor(v.id))
        if plan.lipsync_needed and plan.lipsync:
            l = plan.lipsync
            add(f"Lip-sync ({l.id})", f"1 chosen take x {secs:.0f} s x ${l.unit_price}/s", secs * l.unit_price)
            step_times.append(l.time.queue_s + l.time.per_output_s * secs)

    if project.settings.review_enabled and node.review_enabled and plan.route in ("video", "avatar"):
        e = _llm_entry(reg, "review")
        add("Review agent", f"{plan.takes} review(s)", plan.takes * _llm_cost(e, REVIEW_TOKENS))
        step_times.append(25)

    m = _music_entry(reg, project)
    if m and total_seconds > 0 and secs > 0:
        if m.price.unit == "minute":
            share = secs / 60 * m.unit_price
        else:
            share = m.unit_price * secs / total_seconds
        add(f"Music share ({m.id})", f"{secs:.0f} s of {total_seconds:.0f} s", share)

    likely = sum(l.cost for l in lines)
    spread = {EstimateBasis.goal: (0.6, 1.6), EstimateBasis.script: (0.85, 1.2), EstimateBasis.actual: (0.97, 1.05)}[d.basis]
    cost = CostEstimate(min_usd=round(likely * spread[0], 2), likely_usd=round(likely, 2), max_usd=round(likely * spread[1], 2),
                        lines=lines, model=plan.video.id if plan.video else plan.route, basis=d.basis,
                        actual_usd=node.cost.actual_usd)
    t = sum(step_times)
    explain = " + ".join(f"{x:.0f}s" for x in step_times) if step_times else "instant"
    return cost, TimeEstimate(likely_s=round(t, 0), explain=explain)


# --------------------------------------------------------------------- whole project
@dataclass
class ProjectEstimate:
    seconds: float
    seconds_min: float
    seconds_max: float
    cost: float
    cost_min: float
    cost_max: float
    time_s: float
    spent: float
    warnings: list[str]


def refresh(project: Project, reg: Registry) -> ProjectEstimate:
    """Recompute every node's length, cost and time (cheap; call on every edit)."""
    warnings: list[str] = []

    def _dur(n: Node, share: Optional[float]) -> None:
        if n.is_leaf:
            n.duration = estimate_duration(project, n, share)
            return
        kids = n.children
        if not kids:
            n.duration = estimate_duration(project, n, share)
            return
        base = n.target_seconds or share or project.settings.target_seconds
        fixed = sum((c.target_seconds or 0) for c in kids)
        free = [c for c in kids if not c.target_seconds]
        each = max((base - fixed) / len(free), 2.0) if free else None
        for c in kids:
            _dur(c, c.target_seconds or each)
        n.duration = DurationEstimate(
            min_s=round(sum(c.duration.min_s for c in kids), 1),
            likely_s=round(sum(c.duration.likely_s for c in kids), 1),
            max_s=round(sum(c.duration.max_s for c in kids), 1),
            basis=min((c.duration.basis for c in kids), key=lambda b: ["goal", "script", "actual"].index(b.value)),
            explain=f"sum of {len(kids)} part(s)")

    _dur(project.root, project.settings.target_seconds)
    total = project.root.duration.likely_s

    clip_time: dict[str, float] = {}
    for leaf in leaves(project):
        plan = plan_clip(project, leaf, reg)
        kept = [w for w in leaf.warnings if leaf.status.value == "failed" and w.startswith(("failed:", "compare failed:"))]
        leaf.warnings = kept + list(plan.warnings)
        if leaf.script and plan.video and plan.route == "video":
            max_s = float(plan.video.capabilities.get("max_seconds", 10) or 10)
            if leaf.duration.likely_s > max_s + 0.5:
                leaf.warnings.append(f"~{leaf.duration.likely_s:.0f} s is longer than {plan.video.id} can make in one go "
                                     f"({max_s:.0f} s). Split it into {math.ceil(leaf.duration.likely_s / max_s)} parts?")
        for item in effective_context(project, leaf.id):
            if item.item.needs_consent and not item.item.consent.confirmed:
                leaf.warnings.append(f"consent needed for {item.item.title or 'an actor'} before this clip can be made")
        leaf.cost, leaf.time = estimate_clip_cost(project, leaf, reg, plan, total)
        if leaf.status.value == "done":
            leaf.time = TimeEstimate(likely_s=0, explain="already made")
        clip_time[leaf.id] = leaf.time.likely_s

    def _roll(n: Node) -> None:
        if n.is_leaf:
            return
        for c in n.children:
            _roll(c)
        n.cost = CostEstimate(
            min_usd=round(sum(c.cost.min_usd for c in n.children), 2),
            likely_usd=round(sum(c.cost.likely_usd for c in n.children), 2),
            max_usd=round(sum(c.cost.max_usd for c in n.children), 2),
            lines=[], basis=n.duration.basis,
            actual_usd=round(sum(c.cost.actual_usd or 0 for c in n.children), 2) or None)
        n.time = TimeEstimate(likely_s=sum(c.time.likely_s for c in n.children), explain="sum of parts (sequential)")

    _roll(project.root)

    # project time with parallelism and dependency waits
    try:
        order = topo_order(project)
    except ValueError:
        order = [l.id for l in leaves(project)]
        warnings.append("dependency loop detected — fix the links")
    finish: dict[str, float] = {}
    for nid in order:
        start = max([finish.get(d.from_id, 0) for d in upstream(project, nid)
                     if d.type != DependencyType.order_only] or [0])
        finish[nid] = start + clip_time.get(nid, 0)
    critical = max(finish.values() or [0])
    parallel = max(reg.config.max_parallel_jobs, 1)
    wall = max(critical, sum(clip_time.values()) / parallel) + (20 if order else 0)  # + final stitch
    project.root.time = TimeEstimate(likely_s=round(wall), explain=f"{len(order)} clip(s), up to {parallel} at the same time")

    target = project.settings.target_seconds
    if target and total:
        diff = (total - target) / target
        if abs(diff) > 0.10:
            biggest = max(project.root.children, key=lambda c: c.duration.likely_s, default=None)
            hint = f" Largest part: {biggest.title or biggest.goal[:30]} (~{biggest.duration.likely_s:.0f} s)." if biggest else ""
            warnings.append(f"Video is ~{_fmt(total)} vs target {_fmt(target)} ({diff:+.0%}).{hint}")
    spent = project.run.spent_usd
    if project.root.cost.likely_usd + spent > project.settings.budget_usd:
        warnings.append(f"Estimated cost ${project.root.cost.likely_usd:.2f} (+${spent:.2f} spent) is over the budget ${project.settings.budget_usd:.2f}")
    return ProjectEstimate(seconds=total, seconds_min=project.root.duration.min_s, seconds_max=project.root.duration.max_s,
                           cost=project.root.cost.likely_usd, cost_min=project.root.cost.min_usd,
                           cost_max=project.root.cost.max_usd, time_s=project.root.time.likely_s, spent=spent,
                           warnings=warnings)


def estimate_targets(project: Project, reg: Registry, targets: list[str]) -> dict:
    """Cost and time for making just these clips (used by the confirm dialog)."""
    from .deps import required_upstream
    todo: list[str] = []
    for t in targets:
        for u in required_upstream(project, t):
            if find(project, u).status.value != "done" and u not in todo:
                todo.append(u)
        if t not in todo:
            todo.append(t)
    cost = sum(find(project, t).cost.likely_usd for t in todo)
    times = [find(project, t).time.likely_s for t in todo]
    parallel = max(reg.config.max_parallel_jobs, 1)
    wall = max(max(times or [0]), sum(times) / parallel)
    extra = [t for t in todo if t not in targets]
    return {"clips": todo, "extra_upstream": extra, "cost_usd": round(cost, 2), "time_s": round(wall),
            "spent_usd": project.run.spent_usd, "budget_usd": project.settings.budget_usd,
            "over_budget": project.run.spent_usd + cost > project.settings.budget_usd}


def _fmt(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"
