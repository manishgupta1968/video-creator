"""Service layer: every planning action the CLI and GUI can take."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from . import continuity as continuity_mod
from . import optimizer as optimizer_mod
from . import replan as replan_mod
from . import deps as deps_mod
from . import guide as guide_mod
from . import languages, models_list, musictrack, scaling
from . import policy as policy_mod
from . import estimate as est
from . import media
from . import stock
from .brain import (Brain, ClipScriptDraft, CommandPlan, Op, ProjectDraft, draft_to_script, normalize_join, preserve_fixed, to_continuity)
from .catalog import Catalog
from .config import Config
from .context import guess_type_and_role, item_by_id
from .models import (ActorDetails, ClipScript, ClipVersion, Consent, ContextItem, Continuity, ContextRole, ContextType,
                     Dependency, DependencyType, DialogueLine, Node, NodeKind, NodeStatus, Project, Settings, ShotType, Style, now_iso)
from .project import ProjectStore

SHOT_TYPES_ALL = [t.value for t in ShotType]
from .registry import Registry
from .tree import add_child, ancestors, find, leaves, move, numbering, remove, walk


class Service:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.load()
        ProjectStore.init(self.config)
        self.catalog = Catalog.load()
        self.reg = Registry(self.config, self.catalog)
        self.brain = Brain(self.reg)
        self.last_scale: dict[str, dict] = {}        # what the last length change did to the clips (shown to you once)

    def reload(self) -> None:
        self.config = Config.load()
        self.catalog = Catalog.load()
        self.reg = Registry(self.config, self.catalog)
        self.brain = Brain(self.reg)

    # ================================================================ projects
    def load(self, pid: str) -> Project:
        return ProjectStore.load(pid)

    def save(self, project: Project, snapshot: bool = True) -> Project:
        self.refresh(project)
        ProjectStore.save(project, snapshot=snapshot)
        return project

    def refresh(self, project: Project) -> est.ProjectEstimate:
        for leaf in leaves(project):
            if leaf.status in (NodeStatus.draft, NodeStatus.ready):
                leaf.status = NodeStatus.ready if (leaf.script or leaf.kind != NodeKind.clip) else NodeStatus.draft
        return est.refresh(project, self.reg)

    def summary(self, project: Project) -> dict:
        e = self.refresh(project)
        waiting = sum(1 for l in leaves(project) if l.status == NodeStatus.needs_pick)
        review_flags = sum(1 for r in project.reviews if r.verdict == "does_not_meet_goal")
        out = {"cost_total": e.cost_total, "seconds": e.seconds, "seconds_min": e.seconds_min, "seconds_max": e.seconds_max,
                "target_seconds": project.settings.target_seconds, "cost": e.cost, "cost_min": e.cost_min,
                "cost_max": e.cost_max, "time_s": e.time_s, "spent": e.spent, "budget": project.settings.budget_usd,
                "warnings": e.warnings, "waiting_picks": waiting, "review_flags": review_flags,
                "clips": len(leaves(project)), "done": sum(1 for l in leaves(project) if l.status == NodeStatus.done),
                "numbers": numbering(project), "brain": self.reg.llm_plugin_name("default"),
                "length_mode": project.settings.length_mode, "language": project.settings.language,
                "quality_mode": project.settings.quality_mode, "parts": self.parts_table(project),
                "preview": self.preview_info(project), **self.final_info(project)}
        try:
            out["continuity"] = continuity_mod.check(project, self.reg, ProjectStore.path_for(project.id))
        except FileNotFoundError:                       # a project that is not saved yet has no folder to look in
            out["continuity"] = continuity_mod.check(project, self.reg)
        out["guide"] = guide_mod.compute(self, project, out)
        return out

    def fix_continuity(self, pid: str, action: str, node_id: str = "", join: str = "") -> Project:
        """Run one mechanical fix offered by the continuity check: copy_start | set_join | joins_as_cuts."""
        if action == "set_join":
            return self.set_join(pid, node_id, join)
        p = self.load(pid)
        if action == "copy_start":
            self._sync_states(p)
        elif action == "joins_as_cuts":
            ls = leaves(p)
            for a, b in zip(ls, ls[1:]):
                linked = any(d.from_id == a.id and d.to_id == b.id and d.type in (DependencyType.continues_from, DependencyType.same_location)
                             for d in p.dependencies)
                if b.kind == NodeKind.clip and not b.continuity.join and not linked:
                    b.continuity.join, b.continuity.join_reason = "cut", "marked as a cut by you"
        else:
            raise ValueError("That fix is not one the tool can run for you.")
        return self.save(p)

    def parts_table(self, project: Project) -> list[dict]:
        """One row per part, sub-part and clip (story order, with depth): the numbers behind "Cost by part".
        Call after `refresh` (every node's length, cost and time are then current)."""
        nums = numbering(project)
        rows: list[dict] = []

        def add(node: Node, depth: int) -> None:
            for c in node.children:
                below = [x for x, _ in walk(c) if x.is_leaf]
                models: list[str] = []
                for x in below:
                    if x.cost.model and x.cost.model not in models:
                        models.append(x.cost.model)
                rows.append({"id": c.id, "number": nums.get(c.id, ""), "title": c.title or c.goal[:40], "kind": c.kind.value, "depth": depth,
                             "seconds": c.duration.likely_s, "cost": c.cost.likely_usd, "cost_min": c.cost.min_usd, "cost_max": c.cost.max_usd,
                             "time_s": c.time.likely_s, "quality": est.mode_for(project, c), "quality_own": c.quality_mode is not None, "models": models,
                             "clips": len(below), "done": sum(1 for x in below if x.status == NodeStatus.done)})
                if c.kind == NodeKind.goal:
                    add(c, depth + 1)
        add(project.root, 0)
        return rows

    def ballpark(self, seconds: Optional[float] = None, quality: Optional[str] = None) -> dict:
        """A rough price BEFORE any plan exists, from the catalogue prices (see estimate.ballpark)."""
        return est.ballpark(self.reg, self.config, quality or self.config.quality_mode, seconds)

    HINTS = {
        "video": "Add FAL_KEY (Kling, Seedance, Wan) or GEMINI_API_KEY (Veo) to get real video.",
        "avatar": "Add FAL_KEY to get a real talking animation (Kling Avatar); a presenter can also use HEYGEN_API_KEY.",
        "image": "Add FAL_KEY, GEMINI_API_KEY or OPENAI_API_KEY to get real pictures.",
        "voice": "Add ELEVENLABS_API_KEY or CARTESIA_API_KEY to get natural voices (and to copy a voice).",
    }

    def _real_usable(self, job: str) -> bool:
        """Is at least one paid (real) model of this kind connected and switched on?"""
        return any(not e.is_free and self.reg.entry_usable(e) for e in self.catalog.for_job(job))

    def _placeholder_cause(self, project: Project, leaf: Node, job: str, plan: "est.ClipPlan") -> str:
        """WHY a clip only gets a free placeholder, so the screen never blames a missing key when the cause is something else.
        free_mode: you chose free preview quality | pinned: you chose a free model for this very clip |
        no_key: no real model of this kind is connected | not_covered: real models exist but none fits what the clip needs."""
        if est.mode_for(project, leaf) == "free":
            return "free_mode"
        if job in ("video", "avatar") and leaf.provider_override and plan.video:
            try:
                pinned = self.catalog.get(leaf.provider_override)
            except KeyError:
                pinned = None
            if pinned and pinned.is_free and plan.video.id == pinned.id:
                return "pinned"
        if not self._real_usable(job):
            return "no_key"
        return "not_covered"

    def preview_info(self, project: Project) -> dict:
        """Which clips will only get free placeholder output, WHY (`causes`), and what to do about it.
        `jobs` carries the "add a key" hints and lists only kinds of work where no real model is connected."""
        clips: dict[str, list[str]] = {}
        causes: dict[str, dict[str, str]] = {}
        jobs: dict[str, str] = {}
        pinned: list[str] = []
        unused: list[str] = []
        for leaf in leaves(project):
            if leaf.kind != NodeKind.clip:
                continue
            plan = est.plan_clip(project, leaf, self.reg)
            reasons = []
            if plan.route in ("video", "avatar") and plan.video and plan.video.is_free:
                reasons.append(plan.route)
            if plan.image and plan.image.is_free and plan.route in ("video", "avatar"):
                reasons.append("image")
            if plan.voice and plan.voice.is_free:
                reasons.append("voice")
            if reasons:
                clips[leaf.id] = reasons
                causes[leaf.id] = {r: self._placeholder_cause(project, leaf, r, plan) for r in reasons}
                for r, why in causes[leaf.id].items():
                    if why == "no_key":
                        jobs[r] = self.HINTS[r]
                    elif why == "pinned" and leaf.id not in pinned:
                        pinned.append(leaf.id)
            unused += [w for w in plan.warnings if w.startswith("The voice sample")]
        needs_media = [l for l in leaves(project) if l.kind == NodeKind.clip]
        all_preview = bool(needs_media) and all(
            any(r in ("video", "avatar") and causes.get(l.id, {}).get(r) == "no_key" for r in clips.get(l.id, [])) for l in needs_media)
        return {"clips": clips, "causes": causes, "pinned": pinned, "jobs": jobs, "all_preview": all_preview,
                "chosen_free_mode": project.settings.quality_mode == "free", "voice_sample_unused": sorted(set(unused))}

    def unpin(self, pid: str, ids: Optional[list[str]] = None) -> Project:
        """Clear the model you chose for clips, so the tool picks the best model again. With no ids: every clip pinned to a
        free (placeholder) model. A clip that was already made as a placeholder is marked out of date so it can be made for real."""
        p = self.load(pid)
        if ids is None:
            ids = list(self.preview_info(p)["pinned"])
        for nid in ids:
            n = find(p, nid)
            if not n.provider_override:
                continue
            n.provider_override = None
            if n.status in (NodeStatus.done, NodeStatus.needs_pick):
                take = next((t for t in n.takes if t.id == n.chosen_take), None) or (n.takes[0] if n.takes else None)
                try:
                    placeholder = bool(take and self.catalog.get(take.model).is_free)
                except KeyError:
                    placeholder = False
                if placeholder:
                    n.status = NodeStatus.stale
                    deps_mod.mark_downstream_stale(p, nid)
        return self.save(p)

    def final_info(self, project: Project) -> dict:
        path = ProjectStore.path_for(project.id) / project.final_output if project.final_output else None
        ready = bool(path and path.exists())
        stale = ready and bool(project.final_hash) and project.final_hash != ProjectStore.final_signature(project)
        all_done = bool(leaves(project)) and all(l.status == NodeStatus.done for l in leaves(project))
        return {"final_ready": ready, "final_stale": stale, "all_clips_done": all_done}

    def new_project(self, goal: str, seconds: float = 60, aspect: str = "16:9", fmt: str = "mp4",
                    files: Optional[list[Path]] = None, name: str = "", budget: Optional[float] = None,
                    quality_mode: Optional[str] = None, length_mode: Optional[str] = None,
                    language: Optional[str] = None) -> Project:
        """length_mode "auto" = no length was asked for (the plan is as short as the story allows); language "auto" = the planner
        decides from the goal (it is replaced by a real code when the first draft is made)."""
        settings = Settings(target_seconds=seconds, aspect=aspect, format=fmt,
                            budget_usd=budget if budget is not None else self.config.budget_usd,
                            quality_mode=quality_mode or self.config.quality_mode,
                            length_mode="auto" if length_mode == "auto" else "fixed",
                            language=(language or "en"))
        p = Project(name=name or (goal[:60] or "New video"), goal=goal, settings=settings)
        p.root.goal = goal
        p.root.title = p.name
        p.root.target_seconds = seconds
        p = ProjectStore.create(p)
        for f in files or []:
            self.add_context_file(p, Path(f), scope="project", save=False)
        self.save(p)
        return p

    # ================================================================ drafting
    async def draft(self, pid: str, write_scripts: bool = True) -> Project:
        p = self.load(pid)
        d: ProjectDraft = await self.brain.draft_project(p)
        self._ledger_llm(p, "draft plan")
        p.name = d.title or p.name
        p.root.title = p.name
        if not languages.normalise(p.settings.language):               # "auto": the planner decided from the goal
            p.settings.language = languages.normalise(d.language) or "en"
        p.style = Style(look=d.style.look, colour=d.style.colour, mood=d.style.mood, notes=p.style.notes)
        existing = {c.title.lower(): c for c in p.context if c.type == ContextType.actor}
        for a in d.actors:
            if a.name.lower() in existing:
                c = existing[a.name.lower()]
                if c.actor:
                    for f in ("description", "clothing", "behaviour", "voice_description", "voice_gender", "voice_age",
                              "voice_pitch", "voice_pace", "voice_accent", "language", "speaking_wpm"):
                        if not getattr(c.actor, f):
                            setattr(c.actor, f, getattr(a, f))
                continue
            narrator = a.name.lower().startswith("narrator")
            p.context.append(ContextItem(type=ContextType.actor, title=a.name, role=ContextRole.voice if narrator else ContextRole.must_appear,
                                         actor=ActorDetails(kind=a.kind, description=a.description, clothing=a.clothing,
                                                            behaviour=a.behaviour, voice_description=a.voice_description,
                                                            voice_gender=a.voice_gender, voice_age=a.voice_age, voice_pitch=a.voice_pitch,
                                                            voice_pace=a.voice_pace, voice_accent=a.voice_accent,
                                                            language=languages.normalise(a.language) or "",
                                                            speaking_wpm=a.speaking_wpm or None)))
        p.music_advice = d.music_advice or p.music_advice
        p.root.children = []
        for part in d.parts:
            g = Node(kind=NodeKind.goal, title=part.title, goal=part.goal, target_seconds=part.seconds or None)
            for c in part.clips:
                g.children.append(Node(kind=NodeKind.clip, title=c.title, goal=c.goal, target_seconds=c.seconds or None,
                                       continuity=to_continuity(c)))
            if not g.children:
                g.kind = NodeKind.clip
            p.root.children.append(g)
        if p.settings.length_mode == "auto":
            self._roll_targets(p)                                      # no length asked for: the plan's own total IS the length
            clips_total = sum((n.target_seconds or 0) for n, _ in walk(p.root) if n.kind == NodeKind.clip)
            if clips_total > 0:
                p.settings.target_seconds = round(clips_total, 1)
                p.root.target_seconds = p.settings.target_seconds
        else:
            self._fit_to_target(p)
        self._attach_media_context(p)
        self._apply_joins(p)
        self._sync_states(p)                                           # a continuing clip starts exactly where the one before it ends
        self.save(p)
        try:
            await self.auto_photos(pid)          # free: real photos for animals/objects the user did not supply
        except Exception:
            pass
        if write_scripts:
            p = await self.write_all_scripts(pid)
        return p

    def _fit_to_target(self, p: Project) -> None:
        """The AI brain sometimes plans more seconds than asked. Scale clip lengths to the project target."""
        target = p.settings.target_seconds
        clips = [n for n, _ in walk(p.root) if n.kind == NodeKind.clip]
        total = sum((n.target_seconds or 6.0) for n in clips)
        if not clips or not target or total <= 0 or abs(total - target) / target <= 0.1:
            return
        f = target / total
        for n in clips:
            n.target_seconds = max(2.0, min(round((n.target_seconds or 6.0) * f * 2) / 2, 15.0))
        self._roll_targets(p)

    def _roll_targets(self, p: Project) -> None:
        """Every part's length = the sum of what is inside it (the root is set by the caller)."""
        def roll(node: Node) -> None:
            for c in node.children:
                if c.kind == NodeKind.goal:
                    roll(c)
            if node is not p.root and node.children:
                node.target_seconds = round(sum((c.target_seconds or 0) for c in node.children), 1) or node.target_seconds
        roll(p.root)

    # ================================================================ how a clip joins the one before it (see models.Continuity)
    JOIN_LINK = {"continues": DependencyType.continues_from, "same_scene": DependencyType.same_location}

    @staticmethod
    def _continues_from_previous(p: Project, n: Node) -> bool:
        return any(d.to_id == n.id and d.type == DependencyType.continues_from for d in p.dependencies)

    def _apply_joins(self, p: Project) -> None:
        """Make the links between clips say what the plan decided: continues = a "continues from" link, same_scene = a "same location" link,
        cut = no link. A link you made yourself wins over the plan. A continuing shot is always a hard cut (a dissolve would double-expose it)."""
        ls = leaves(p)
        for a, b in zip(ls, ls[1:]):
            between = [d for d in p.dependencies if d.from_id == a.id and d.to_id == b.id
                       and d.type in (DependencyType.continues_from, DependencyType.same_location)]
            mine = [d for d in between if d.source == "user"]
            if mine:
                b.continuity.join = "continues" if any(d.type == DependencyType.continues_from for d in mine) else "same_scene"
                b.continuity.join_reason = b.continuity.join_reason or "set by you"
            j = b.continuity.join
            if not j:
                continue
            for d in between:
                if d.source != "user" and (j == "cut" or d.type != self.JOIN_LINK[j]):
                    p.dependencies.remove(d)
            if j in self.JOIN_LINK and not any(d.type == self.JOIN_LINK[j] for d in p.dependencies if d.from_id == a.id and d.to_id == b.id):
                try:
                    deps_mod.add_dependency(p, Dependency(from_id=a.id, to_id=b.id, type=self.JOIN_LINK[j], source="ai",
                                                          note=b.continuity.join_reason or "planned join"))
                except ValueError:
                    pass
            if j == "continues":
                b.transition_in = "cut"

    def _sync_states(self, p: Project) -> list[str]:
        """A clip that continues the one before it starts exactly where that one ended: the tool COPIES the end state into the start state
        (it is never left to the AI). Clips already made that change are marked out of date. Returns the ids of clips whose start changed."""
        changed: list[str] = []
        ls = leaves(p)
        for a, b in zip(ls, ls[1:]):
            if b.continuity.join != "continues" and not (b.continuity.join == "" and self._continues_from_previous(p, b)):
                continue
            end = (a.script.end_state if a.script and a.script.end_state.strip() else a.continuity.end_state).strip()
            if not end:
                continue
            a.continuity.end_state = end
            if a.script and not a.script.end_state.strip():
                a.script.end_state = end
            b.continuity.start_state = end
            if b.script and b.script.start_state.strip() != end:
                b.script.start_state = end
                changed.append(b.id)
                if b.status in (NodeStatus.done, NodeStatus.needs_pick):
                    b.status = NodeStatus.stale
                    deps_mod.mark_downstream_stale(p, b.id)
        return changed

    def _repair_joins(self, p: Project) -> None:
        """After clips were added, moved or removed: a join that relied on the clip that used to be before this one no longer holds, so it
        becomes a cut. (Plan-made links to a clip that is no longer next are dropped; your own links stay.)"""
        ls = leaves(p)
        for i, b in enumerate(ls):
            prev = ls[i - 1] if i else None
            for d in list(p.dependencies):
                if d.to_id == b.id and d.type in (DependencyType.continues_from, DependencyType.same_location) and d.source != "user" \
                        and (prev is None or d.from_id != prev.id):
                    p.dependencies.remove(d)
            if i == 0:
                b.continuity.join, b.continuity.join_reason = "", ""
                continue
            want = self.JOIN_LINK.get(b.continuity.join)
            if want and not any(d.from_id == prev.id and d.to_id == b.id and d.type == want for d in p.dependencies):
                b.continuity.join, b.continuity.join_reason = "cut", "the clip before it changed"

    def set_join(self, pid: str, node_id: str, join: str, reason: str = "set by you") -> Project:
        """Change how a clip joins the one before it. continues copies the previous end into this start (and a clip already made is marked
        out of date, because it must be made again from the hand-over picture); the transition becomes a cut."""
        join = normalize_join(join)
        if not join:
            raise ValueError("A join is continues, same_scene or cut.")
        p = self.load(pid)
        n = find(p, node_id)
        ls = leaves(p)
        if not n.is_leaf or n.id == ls[0].id:
            raise ValueError("Only a clip that has a clip before it can have a join.")
        prev = ls[[x.id for x in ls].index(n.id) - 1]
        was_continuing = n.continuity.join == "continues" or (n.continuity.join == "" and self._continues_from_previous(p, n))
        n.continuity.join, n.continuity.join_reason = join, reason
        p.dependencies = [d for d in p.dependencies if not (d.from_id == prev.id and d.to_id == n.id
                                                            and d.type in (DependencyType.continues_from, DependencyType.same_location))]
        self._apply_joins(p)
        for d in p.dependencies:
            if d.from_id == prev.id and d.to_id == n.id and d.type in (DependencyType.continues_from, DependencyType.same_location):
                d.source = "user"
        self._sync_states(p)
        if join == "continues" and not was_continuing and n.status in (NodeStatus.done, NodeStatus.needs_pick):
            n.status = NodeStatus.stale
            deps_mod.mark_downstream_stale(p, n.id)
        return self.save(p)

    def _attach_media_context(self, p: Project) -> None:
        """Slides / footage the user dropped become leaves of their own."""
        for c in p.context:
            if c.role == ContextRole.include and c.files and c.scope == "project" and not c.analysis.get("placed"):
                f = c.files[0]
                kind = NodeKind.slides if f.lower().endswith((".pdf", ".pptx", ".ppt", ".key")) else NodeKind.user_clip
                media_path = c.analysis.get("pdf", f)
                node = Node(kind=kind, title=c.title or Path(f).stem, goal=c.text or f"Show {Path(f).name}",
                            media=media_path, status=NodeStatus.ready)
                target = p.root.children[len(p.root.children) // 2] if p.root.children else p.root
                if target.is_leaf:
                    target = p.root
                target.children.append(node)
                c.analysis["placed"] = node.id

    def rewrite_offer(self, pid: str, node_id: str) -> dict:
        """What 'update the clip scripts to match' would do under this part, and what the AI would cost: {clips, numbers, kept, cost_usd}.
        Clips that are made or kept are left alone (and counted in `kept`)."""
        p = self.load(pid)
        nums = numbering(p)
        clips = [n for n, _ in walk(find(p, node_id)) if n.kind == NodeKind.clip]
        todo = [n for n in clips if not scaling.protected(n)]
        brain = self.reg.llm_entry("default")
        one = est._llm_cost(brain, est.SCRIPT_TOKENS) if brain else 0.0
        return {"clips": len(todo), "numbers": [nums.get(n.id, "") for n in todo], "kept": [nums.get(n.id, "") for n in clips if scaling.protected(n)],
                "cost_usd": round(one * len(todo), 4)}

    async def write_all_scripts(self, pid: str, under: Optional[str] = None, overwrite: bool = False) -> Project:
        p = self.load(pid)
        base = find(p, under) if under else p.root
        targets = [n for n, _ in walk(base) if n.kind == NodeKind.clip and (not n.script or (overwrite and not scaling.protected(n)))]   # made or kept clips are never rewritten silently
        sem = asyncio.Semaphore(4)

        async def one(n: Node):
            async with sem:
                return n.id, await self.brain.write_clip_script(p, n)

        results = await asyncio.gather(*(one(n) for n in targets), return_exceptions=True)
        p = self.load(pid)
        errors = []
        for r in results:
            if isinstance(r, Exception):
                errors.append(str(r))
                continue
            nid, draft = r
            self._apply_script(p, find(p, nid), draft)
            self._ledger_llm(p, f"script {nid}")
        for dep in deps_mod.rule_based_dependencies(p):
            try:
                deps_mod.add_dependency(p, dep)
            except ValueError:
                pass
        self._apply_joins(p)                                  # the plan's decisions win over rule-based guesses
        self._sync_states(p)
        self.save(p)
        if errors:
            raise RuntimeError("; ".join(errors[:3]))
        return p

    def _apply_script(self, p: Project, node: Node, draft: ClipScriptDraft, feedback: str = "") -> None:
        if node.script:
            node.versions.append(ClipVersion(version=node.version, script=node.script, feedback=feedback))
            node.version += 1
        before = node.script if node.script is not None else (node.versions[-1].script if node.versions else None)
        node.script = draft_to_script(p, draft)
        preserve_fixed(before, node.script)                  # lines marked "say exactly this" survive any rewrite
        if node.target_seconds and not node.script.target_seconds:
            node.script.target_seconds = node.target_seconds
        limit = node.script.target_seconds or node.target_seconds
        if limit:                                  # the plan you see must match the length: no more steps than fit
            node.script.action_beats = node.script.action_beats[:max(1, round(limit / policy_mod.current().action_seconds))]
        node.voice_audio = None
        node.voice_seconds = None
        if node.status in (NodeStatus.done, NodeStatus.needs_pick, NodeStatus.failed):
            node.status = NodeStatus.stale
            deps_mod.mark_downstream_stale(p, node.id)
        elif node.status in (NodeStatus.draft,):
            node.status = NodeStatus.ready
        c = node.continuity
        if feedback.strip():                                  # you asked for a change: the new states are the truth now
            c.end_state = node.script.end_state.strip() or c.end_state
            if c.join != "continues":
                c.start_state = node.script.start_state.strip() or c.start_state
        else:                                                 # the plan's states are a contract: the script keeps them word for word
            if c.end_state:
                node.script.end_state = c.end_state
            if c.start_state and c.join != "continues":
                node.script.start_state = c.start_state
        prev = None
        for n, _ in walk(p.root):
            if n.id == node.id:
                break
            if n.is_leaf:
                prev = n
        if prev and not c.join:                               # only an undecided clip uses the script writer's guess about the join
            for flag, typ in ((draft.continues_from_previous, DependencyType.continues_from),
                              (draft.same_location_as_previous, DependencyType.same_location)):
                if flag:
                    try:
                        deps_mod.add_dependency(p, Dependency(from_id=prev.id, to_id=node.id, type=typ, source="ai",
                                                              note="suggested by the AI brain"))
                    except ValueError:
                        pass

    async def write_script(self, pid: str, node_id: str, feedback: str = "") -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        if n.kind != NodeKind.clip:
            raise ValueError("scripts are written for clip nodes")
        draft = await self.brain.write_clip_script(p, n, feedback)
        p = self.load(pid)
        self._apply_script(p, find(p, node_id), draft, feedback)
        self._apply_joins(p)
        self._sync_states(p)
        self._ledger_llm(p, f"script {node_id}")
        return self.save(p)

    async def decompose(self, pid: str, node_id: str) -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        dec = await self.brain.decompose(p, n)
        p = self.load(pid)
        n = find(p, node_id)
        if n.is_leaf:
            n.kind = NodeKind.goal
            n.script = None
        for c in dec.children:
            n.children.append(Node(kind=NodeKind.clip if c.kind == "clip" else NodeKind.goal, title=c.title,
                                   goal=c.goal, target_seconds=c.seconds or None,
                                   continuity=to_continuity(c) if c.kind == "clip" else Continuity()))
        self._apply_joins(p)
        self._sync_states(p)
        self._ledger_llm(p, f"break down {node_id}")
        self.save(p)
        return await self.write_all_scripts(pid, under=node_id)

    async def split_clip(self, pid: str, node_id: str) -> Project:
        """Replace one clip by consecutive clips that each need only what ONE route can do (see routes.describe).
        The AI writes the parts; the clips before and after keep their links, the parts are linked 'continues from'."""
        p = self.load(pid)
        n = find(p, node_id)
        if n.kind != NodeKind.clip or not n.script:
            raise ValueError("Only a clip with a script can be split.")
        split = await self.brain.split_clip(p, n)
        if len(split.parts) < 2:
            raise ValueError("The AI found nothing to split in this clip: it already needs only one kind of movement.")
        p = self.load(pid)
        n = find(p, node_id)
        parent = next((x for x, _ in walk(p.root) if any(c.id == node_id for c in x.children)), None)
        if parent is None:
            raise ValueError("This clip has no place in the story to split.")
        old = n.script
        total = n.target_seconds or old.target_seconds or n.duration.likely_s
        made: list[Node] = []
        for part in split.parts[:4]:
            shot = part.shot_type if part.shot_type in SHOT_TYPES_ALL else old.shot_type.value
            names = {c.title.lower(): c.id for c in p.context if c.type == ContextType.actor}
            script = ClipScript(
                shot_type=ShotType(shot), visual=part.visual or old.visual, action_beats=part.action_beats, camera=old.camera,
                actors_in_shot=list(old.actors_in_shot),
                dialogue=[DialogueLine(speaker=names.get(l.speaker_name.lower(), l.speaker_name), text=l.text, emotion=l.emotion, fixed=l.fixed)
                          for l in part.dialogue],
                narration=part.narration, narration_fixed=old.narration_fixed and part.narration.strip() == old.narration.strip(),
                on_camera_speech=bool(part.dialogue) and old.on_camera_speech,
                sound_notes=part.sound_notes or old.sound_notes, motion=part.motion if part.motion in ("face", "body", "scene") else "",
                start_state=part.start_state, end_state=part.end_state, negative=old.negative, target_seconds=part.seconds or None)
            first = not made
            cont = Continuity(join=n.continuity.join if first else "continues",
                              join_reason=n.continuity.join_reason if first else "made by splitting one clip: the next part starts where this one ends",
                              place=n.continuity.place, present=list(n.continuity.present), start_state=script.start_state,
                              end_state=script.end_state, carry_over=n.continuity.carry_over if first else "everything: it is the same shot")
            made.append(Node(kind=NodeKind.clip, title=part.title or n.title, goal=part.goal or n.goal, target_seconds=part.seconds or None,
                             script=script, status=NodeStatus.ready, continuity=cont, context_add=list(n.context_add), context_off=list(n.context_off),
                             context_override=dict(n.context_override), provider_override=n.provider_override, takes_override=n.takes_override,
                             review_enabled=n.review_enabled))
        made[0].transition_in = n.transition_in
        # the parts keep the total length when none of them follows its audio; the estimate shows the truth either way
        scale = (total / sum(m.target_seconds or 0 for m in made)) if total and sum(m.target_seconds or 0 for m in made) else 1.0
        if 0.5 < scale < 2.0 and abs(scale - 1) > 0.05 and not any(m.script.motion == "face" for m in made):
            for m in made:
                m.target_seconds = round((m.target_seconds or 0) * scale, 1)
                m.script.target_seconds = m.target_seconds
        i = next(k for k, c in enumerate(parent.children) if c.id == node_id)
        parent.children[i:i + 1] = made
        # links: what led into the clip now leads into the first part; what continued from it continues from the last
        for d in p.dependencies:
            if d.to_id == node_id:
                d.to_id = made[0].id
            if d.from_id == node_id:
                d.from_id = made[-1].id
        for a, b in zip(made, made[1:]):
            deps_mod.add_dependency(p, Dependency(from_id=a.id, to_id=b.id, type=DependencyType.continues_from, source="ai",
                                                  note="made by splitting one clip: the next part starts where this one ends"))
        self._ledger_llm(p, f"split clip {node_id}")
        return self.save(p)

    @staticmethod
    def _set_main_goal(p: Project, text: str) -> None:
        """The main Goal lives in two places (Project.goal, which the plan, the outline and the music mood read, and the root node's goal, which the
        screen edits). Every write goes through here so they never differ."""
        p.goal = text
        p.root.goal = text

    async def revise(self, pid: str, node_id: str, instruction: str) -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        if n.kind == NodeKind.clip:
            return await self.write_script(pid, node_id, feedback=instruction)
        rev = await self.brain.revise_goal(p, n, instruction)
        p = self.load(pid)
        n = find(p, node_id)
        n.title = rev.title or n.title
        if n.id == p.root.id:
            self._set_main_goal(p, rev.goal or n.goal)
            p.name = p.root.title = n.title
        else:
            n.goal = rev.goal or n.goal
        if rev.seconds:
            n.target_seconds = rev.seconds
        self._ledger_llm(p, f"revise {node_id}")
        return self.save(p)

    async def suggest_dependencies(self, pid: str) -> Project:
        p = self.load(pid)
        found = await self.brain.suggest_dependencies(p)
        p = self.load(pid)
        nums = {v: k for k, v in numbering(p).items()}
        for d in found.dependencies:
            a, b = nums.get(d.from_number), nums.get(d.to_number)
            if a and b:
                try:
                    deps_mod.add_dependency(p, Dependency(from_id=a, to_id=b, type=DependencyType(d.type),
                                                          source="ai", note=d.note))
                except ValueError:
                    pass
        for dep in deps_mod.rule_based_dependencies(p):
            try:
                deps_mod.add_dependency(p, dep)
            except ValueError:
                pass
        self._ledger_llm(p, "find links")
        return self.save(p)

    # ================================================================ commands (Ctrl+K / Ask AI)
    async def plan_command(self, pid: str, text: str, focus_id: Optional[str] = None) -> CommandPlan:
        p = self.load(pid)
        focus = find(p, focus_id) if focus_id else None
        plan = await self.brain.command(p, text, focus)
        self._ledger_llm(p, "command")
        ProjectStore.save(p, snapshot=False)
        return plan

    async def apply_command(self, pid: str, plan: CommandPlan) -> dict:
        p = self.load(pid)
        nums = {v: k for k, v in numbering(p).items()}
        actors = {c.title.lower(): c for c in p.context if c.type == ContextType.actor}
        actions: dict[str, Any] = {"generate": None, "regenerate": []}

        def node_for(target: str) -> Optional[Node]:
            if target in ("project", "", None):
                return p.root
            nid = nums.get(target.strip())
            return find(p, nid) if nid else None

        for op in plan.ops:
            n = node_for(op.target) if op.op not in ("set_actor", "set_style") else None
            if op.op == "set_title" and n:
                n.title = op.value
                if n.id == p.root.id:
                    p.name = op.value
            elif op.op == "set_goal" and n:
                if n.id == p.root.id:
                    self._set_main_goal(p, op.value)
                else:
                    n.goal = op.value
            elif op.op == "set_seconds" and n:
                cur = n.target_seconds or n.duration.likely_s or 6
                if op.value == "shorter":
                    n.target_seconds = round(cur * 0.75, 1)
                elif op.value == "longer":
                    n.target_seconds = round(cur * 1.3, 1)
                else:
                    try:
                        n.target_seconds = float(op.value)
                    except ValueError:
                        pass
                if n.is_leaf and n.script:
                    n.script.target_seconds = n.target_seconds
                if n.id == p.root.id:
                    p.settings.target_seconds = n.target_seconds or p.settings.target_seconds
            elif op.op == "set_script" and n and n.script and op.field in ("visual", "camera", "narration", "negative", "sound_notes"):
                setattr(n.script, op.field, op.value)
            elif op.op == "add_child" and n:
                add_child(p, n.id, Node(kind=NodeKind.clip, title=op.value[:40], goal=op.value))
            elif op.op == "remove" and n and n.id != p.root.id:
                remove(p, n.id)
            elif op.op == "set_actor":
                a = actors.get(op.target.lower())
                if a and a.actor and op.field in ("description", "clothing", "behaviour", "voice_description"):
                    setattr(a.actor, op.field, op.value)
                    actions["regenerate"].append("actors")
            elif op.op == "set_style" and op.field in ("look", "colour", "mood"):
                setattr(p.style, op.field, op.value)
            elif op.op == "regenerate_scripts" and n:
                actions["regenerate"].append(n.id)
            elif op.op == "generate":
                actions["generate"] = op.target or "next"
        self.save(p)
        for target in actions["regenerate"]:
            if target == "actors":
                continue
            await self.write_all_scripts(pid, under=target, overwrite=True)
        return actions

    # ================================================================ tree edits
    def update_node(self, pid: str, node_id: str, patch: dict) -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        script_changed = False
        resize = None
        if "target_seconds" in patch and n.children and patch["target_seconds"]:
            resize = float(patch["target_seconds"])                  # a part's length: its clips follow (see scaling.py)
        for key in ("title", "goal", "target_seconds", "provider_override", "takes_override", "transition_in",
                    "review_enabled", "style_overrides", "locked"):
            if key in patch and not (key == "target_seconds" and resize):
                setattr(n, key, patch[key])
        if n.id == p.root.id:                                            # the root's goal and title are the project's goal and name
            if "goal" in patch:
                self._set_main_goal(p, patch["goal"])
            if "title" in patch:
                p.name = patch["title"]
        if "quality_mode" in patch:
            if patch["quality_mode"] not in (None, "", "best", "balanced", "budget", "free"):
                raise ValueError("quality must be best, balanced, budget or free")
            n.quality_mode = patch["quality_mode"] or None               # "" or None = the part above decides
        if resize:
            self.last_scale[pid] = scaling.scale_node(p, node_id, resize)
            if n.id == p.root.id:
                n.target_seconds = resize
        if "kind" in patch and patch["kind"] in [k.value for k in NodeKind]:
            n.kind = NodeKind(patch["kind"])
            if n.kind != NodeKind.goal and n.children:
                n.kind = NodeKind.goal
        if "script" in patch and patch["script"] is not None:
            base = n.script.model_dump() if n.script else {}
            base.update(patch["script"])
            new = ClipScript.model_validate(base)
            if n.script and new != n.script:
                script_changed = True
            n.script = new
        if "target_seconds" in patch and n.script:
            n.script.target_seconds = patch["target_seconds"]
        if "script" in patch and patch["script"] is not None and n.script:
            if "end_state" in patch["script"]:
                n.continuity.end_state = n.script.end_state.strip()
            if "start_state" in patch["script"] and n.continuity.join != "continues":
                n.continuity.start_state = n.script.start_state.strip()
        if n.continuity.join == "continues" or self._continues_from_previous(p, n):
            n.transition_in = "cut"                              # a dissolve would double-expose a continuing shot
        if script_changed:
            n.voice_audio, n.voice_seconds = None, None
            if n.status in (NodeStatus.done, NodeStatus.needs_pick):
                n.status = NodeStatus.stale
                deps_mod.mark_downstream_stale(p, n.id)
        if n.id == p.root.id and "target_seconds" in patch and patch["target_seconds"]:
            p.settings.target_seconds = float(patch["target_seconds"])
            p.settings.length_mode = "fixed"                  # you asked for a length: it is no longer "as short as the story allows"
        if "script" in patch:
            self._sync_states(p)                              # a changed end state moves on to the clip that continues from it
        return self.save(p)

    def add_node(self, pid: str, parent_id: str, kind: str = "clip", title: str = "", goal: str = "",
                 index: Optional[int] = None, media_path: Optional[str] = None) -> tuple[Project, str]:
        p = self.load(pid)
        n = Node(kind=NodeKind(kind), title=title or "New clip", goal=goal, media=media_path)
        add_child(p, parent_id, n, index)
        self._repair_joins(p)
        self.save(p)
        return p, n.id

    def remove_node(self, pid: str, node_id: str) -> Project:
        p = self.load(pid)
        remove(p, node_id)
        self._repair_joins(p)
        return self.save(p)

    def move_node(self, pid: str, node_id: str, parent_id: str, index: int) -> Project:
        p = self.load(pid)
        move(p, node_id, parent_id, index)
        self._repair_joins(p)
        return self.save(p)

    def update_project(self, pid: str, patch: dict) -> Project:
        p = self.load(pid)
        if "name" in patch:
            p.name = patch["name"]
            p.root.title = p.name
        if "goal" in patch:
            self._set_main_goal(p, patch["goal"])
        if "settings" in patch:
            merged = {**p.settings.model_dump(), **patch["settings"]}
            if "target_seconds" in patch["settings"] and "length_mode" not in patch["settings"]:
                merged["length_mode"] = "fixed"
            p.settings = Settings.model_validate(merged)
            p.root.target_seconds = p.settings.target_seconds
            if "target_seconds" in patch["settings"] and p.root.children:
                self.last_scale[pid] = scaling.scale_node(p, p.root.id, p.settings.target_seconds)
                p.root.target_seconds = p.settings.target_seconds
        if "style" in patch:
            p.style = Style.model_validate({**p.style.model_dump(), **patch["style"]})
        return self.save(p)

    # ================================================================ context & actors
    def add_context_file(self, p: Project, src: Path, scope: str = "project", hint: str = "",
                         ctx_id: Optional[str] = None, save: bool = True) -> ContextItem:
        dest_dir = ProjectStore.path_for(p.id) / "inputs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        i = 2
        while dest.exists() and dest.resolve() != src.resolve():
            dest = dest_dir / f"{src.stem}_{i}{src.suffix}"
            i += 1
        if dest.resolve() != src.resolve():
            shutil.copy(src, dest)
        rel = f"inputs/{dest.name}"
        if ctx_id:
            item = item_by_id(p, ctx_id)
            ctype = item.type
            if ctype == ContextType.actor and dest.suffix.lower() in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"):
                item.actor = item.actor or ActorDetails()
                item.actor.voice_sample = rel
                item.analysis["voice_check"] = media.audio_check(dest)
                if item.actor.kind == "ai_person":
                    item.actor.kind = "real_person"
            else:
                item.files.append(rel)
                if item.actor and dest.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    item.actor.reference_sheet = []          # a new photo replaces the old reference picture
                if ctype == ContextType.actor and item.actor and item.actor.kind == "ai_person":
                    item.actor.kind = "real_person"
        else:
            ctype, role = guess_type_and_role(src.name, hint)
            item = ContextItem(type=ctype, role=role, title=src.stem.replace("_", " ").replace("-", " ").title(),
                               scope=scope, files=[rel])
            if ctype == ContextType.actor:
                item.actor = ActorDetails(kind="real_person")
            if role == ContextRole.voice:
                item.type = ContextType.actor
                item.files = []
                item.actor = ActorDetails(kind="real_person", voice_sample=rel)
                item.title = item.title.replace("Voice", "").strip() or "Narrator"
            p.context.append(item)
        self._analyse(p, item, dest)
        if save:
            self.save(p)
        return item

    # ---------------------------------------------------------------- automatic photo search
    GENERIC_TITLES = {"photo", "object", "location", "untitled", "new actor"}

    def wants_auto_photo(self, item: ContextItem) -> bool:
        """Search only when the user has NOT supplied a photo, and only for generic subjects:
        animals, objects and places. Never people, never the user's own product or brand."""
        a = item.analysis
        if item.files or a.get("auto_photo") or a.get("auto_photo_off") or a.get("auto_photo_tried"):
            return False
        if item.type == ContextType.actor:
            return bool(item.actor and item.actor.kind == "animal")
        if item.type in (ContextType.object, ContextType.location):
            return item.role in (ContextRole.must_appear, ContextRole.look_reference) and item.title.strip().lower() not in self.GENERIC_TITLES
        return False

    async def auto_photos(self, pid: str, only: Optional[list[str]] = None, force: bool = False) -> int:
        """Find a real photo for every item that needs one. Returns how many were found.
        Errors never stop the caller (offline, nothing found): the tool then generates a picture instead."""
        p = self.load(pid)
        if not p.settings.auto_photo and not force:
            return 0
        ids = [c.id for c in p.context if (not only or c.id in only) and (force or self.wants_auto_photo(c))]
        found = 0
        for cid in ids:
            try:
                if await self._auto_photo_one(pid, cid, force):
                    found += 1
            except Exception as exc:                                    # never block the plan
                q = self.load(pid)
                item = item_by_id(q, cid)
                item.analysis["auto_photo_tried"] = True
                item.analysis["auto_photo_error"] = str(exc)[:200]
                ProjectStore.save(q, snapshot=False)
        return found

    async def _auto_photo_one(self, pid: str, cid: str, force: bool) -> bool:
        p = self.load(pid)
        item = item_by_id(p, cid)
        if item.files and not force:
            return False                                                  # the user supplied one: never replace it
        subject = (item.actor.description if item.actor else "") or item.text or item.title
        try:
            query = (await self.brain.photo_query(item.title, subject)).query.strip() or item.title
        except Exception:
            query = item.title
        self._ledger_llm(p, f"photo search words for {item.title}")
        cands: list = []
        unreachable = False
        for source in stock.sources_available():
            try:
                cands += await stock.search(query, source, limit=12)
            except stock.StockError:
                continue
            except Exception:                                   # no internet, DNS, timeout …
                unreachable = True
        ranked = stock.rank(cands, query)[:6]
        q = self.load(pid)
        item = item_by_id(q, cid)
        item.analysis["auto_photo_tried"] = True
        if not ranked:
            item.analysis["auto_photo_error"] = ("the photo sites could not be reached; check your internet connection" if unreachable and not cands
                                                 else f"no suitable photo found for “{query}”")
            ProjectStore.save(q, snapshot=False)
            return False
        order = list(ranked)
        if len(ranked) > 1 and self.reg.llm_plugin_name("default") != "fake_llm":
            best = await self._pick_by_eye(q, subject, ranked)                 # a vision-capable brain looks at them
            if best is not None:
                order = [best] + [c for c in ranked if c is not best]
        last_problem = ""
        for choice in order[:4]:                                                # if one cannot be downloaded, try the next
            tmp = Path(tempfile.mkdtemp())
            try:
                path = await stock.download(choice.url, tmp, choice.title)
                q = self.load(pid)
                item = item_by_id(q, cid)
                if item.files and not force:
                    return False                                              # the user added one while we searched
                self.add_context_file(q, path, ctx_id=cid, save=False)
                item = item_by_id(q, cid)
                meta = {k: str(getattr(choice, k))[:300] for k in ("title", "author", "license", "source_url", "source")}
                item.analysis.setdefault("credits", []).append(meta)
                item.analysis["auto_photo"] = {"query": query, "photo": meta, "candidates": [stock.to_dict(c) for c in ranked]}
                item.analysis["auto_photo_tried"] = True
                item.analysis.pop("auto_photo_error", None)
                item.analysis.pop("auto_photo_off", None)
                self.save(q)
                return True
            except stock.StockError as exc:
                last_problem = str(exc)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        q = self.load(pid)
        item = item_by_id(q, cid)
        item.analysis["auto_photo_tried"] = True
        item.analysis["auto_photo_error"] = (f"found {len(ranked)} photo(s) for “{query}” but none could be downloaded "
                                             f"(last problem: {last_problem.rstrip('.')})")[:300]
        ProjectStore.save(q, snapshot=False)
        return False

    async def _pick_by_eye(self, project: Project, subject: str, ranked: list):
        tmp = Path(tempfile.mkdtemp())
        try:
            thumbs, kept = [], []
            for i, c in enumerate(ranked[:5]):
                try:
                    thumbs.append(await stock.download(c.thumb or c.url, tmp, f"cand{i}"))
                    kept.append(c)
                except stock.StockError:
                    continue
            if len(kept) < 2:
                return None
            res = await self.brain.pick_photo(project, subject, [c.title for c in kept], thumbs)
            self._ledger_llm(project, "choose the best photo")
            return kept[res.choice - 1] if 1 <= res.choice <= len(kept) else None
        except Exception:
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def add_stock_photo(self, pid: str, cid: str, url: str, meta: dict) -> Project:
        """Download a chosen stock photo into an animal/object/place/style item (never a person)."""
        p = self.load(pid)
        item = item_by_id(p, cid)
        if item.type == ContextType.actor and (item.actor is None or item.actor.kind in ("ai_person", "real_person", "digital_twin")):
            raise ValueError("Photos of people must be your own, or used with the person's permission. "
                             "Upload them instead of searching. Stock search is for animals, objects, places and styles.")
        tmp = Path(tempfile.mkdtemp())
        try:
            path = await stock.download(url, tmp, meta.get("title") or "photo")
            self.add_context_file(p, path, ctx_id=cid, save=False)
            item = item_by_id(p, cid)
            item.analysis.setdefault("credits", []).append({k: str(meta.get(k, ""))[:300] for k in
                                                           ("title", "author", "license", "source_url", "source")})
            item.analysis["auto_photo_tried"] = True
            self.save(p)
        except stock.StockError as exc:
            raise ValueError(str(exc))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return self.load(pid)

    def add_voice_recording(self, pid: str, cid: str, data: bytes, filename: str, consent_self: bool = False) -> Project:
        """Save a voice sample recorded in the browser (webm / mp4 / wav) as the actor's voice sample.
        The sample is only used to COPY the voice; it is never placed in the video."""
        if len(data) > 80_000_000:
            raise ValueError("The recording is too large.")
        p = self.load(pid)
        item = item_by_id(p, cid)
        if item.type != ContextType.actor:
            raise ValueError("A voice recording belongs to an actor.")
        inputs = ProjectStore.path_for(pid) / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        ext = Path(filename or "").suffix.lower()
        if ext not in (".webm", ".m4a", ".mp4", ".ogg", ".wav", ".mp3", ".aac", ".caf", ".oga"):
            ext = ".webm"
        raw = inputs / f"recording_raw{ext}"
        raw.write_bytes(data)
        n = 1
        while (inputs / f"voice_recording_{n}.wav").exists():
            n += 1
        out = inputs / f"voice_recording_{n}.wav"
        try:
            media.ff("-i", str(raw), "-vn", "-ar", "44100", "-ac", "1", str(out))
        except media.MediaError:
            raise ValueError("Could not read that recording. Try recording again.")
        finally:
            raw.unlink(missing_ok=True)
        secs = media.probe_duration(out)
        if secs < 1.5:
            out.unlink(missing_ok=True)
            raise ValueError("The recording is empty or too short.")
        item.actor = item.actor or ActorDetails()
        item.actor.voice_sample = f"inputs/{out.name}"
        item.actor.voice_id = None
        item.actor.voice_provider = None
        if item.actor.kind == "ai_person":
            item.actor.kind = "real_person"
        item.analysis["voice_check"] = media.audio_check(out)
        if consent_self:
            item.consent = Consent(confirmed=True, statement="self", confirmed_by=self.config.user_name or "user",
                                   confirmed_at=now_iso(), files=list(item.files) + [item.actor.voice_sample])
        self.save(p)
        return self.load(pid)

    def _analyse(self, p: Project, item: ContextItem, path: Path) -> None:
        ext = path.suffix.lower()
        try:
            if ext in (".png", ".jpg", ".jpeg", ".webp"):
                item.analysis.setdefault("photos", {})[path.name] = media.photo_check(path)
            elif ext in (".pptx", ".ppt", ".key"):
                pdf = media.office_to_pdf(path, path.parent)
                item.analysis["pdf"] = f"inputs/{pdf.name}"
                item.analysis["pages"] = media.count_pages(pdf)
            elif ext == ".pdf":
                item.analysis["pages"] = media.count_pages(path)
            elif ext in (".mp4", ".mov", ".mkv", ".webm", ".m4v"):
                item.analysis["seconds"] = round(media.probe_duration(path), 1)
            elif ext in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"):
                item.analysis["seconds"] = round(media.probe_duration(path), 1)
                if item.role == ContextRole.voice or item.type == ContextType.actor:
                    item.analysis["voice_check"] = media.audio_check(path)
            elif ext in (".txt", ".md"):
                item.text = (item.text + "\n" + path.read_text(errors="ignore")[:8000]).strip()
            if ext == ".pdf" and item.type in (ContextType.text, ContextType.entity):
                import fitz
                with fitz.open(path) as doc:
                    item.text = (item.text + "\n" + "\n".join(pg.get_text() for pg in doc)[:8000]).strip()
        except Exception as exc:
            item.analysis["error"] = str(exc)[:300]

    def add_context(self, pid: str, data: dict) -> tuple[Project, ContextItem]:
        p = self.load(pid)
        data = dict(data)
        if data.get("type") == "actor" and not data.get("actor"):
            data["actor"] = {}
        item = ContextItem.model_validate(data)
        p.context.append(item)
        self.save(p)
        return p, item

    def update_context(self, pid: str, cid: str, patch: dict) -> Project:
        p = self.load(pid)
        item = item_by_id(p, cid)
        data = item.model_dump()
        for k, v in patch.items():
            if k == "actor" and isinstance(v, dict):
                data["actor"] = {**(data.get("actor") or {}), **v}
            elif k == "analysis" and isinstance(v, dict):
                data["analysis"] = {**data.get("analysis", {}), **v}
            elif k in data:
                data[k] = v
        if "files" in patch and len(patch["files"]) < len(item.files):
            if data.get("actor"):
                data["actor"]["reference_sheet"] = []        # picture changed: make a new reference
            if item.analysis.get("auto_photo"):
                # the user removed the photo the tool found: do not search again for this item
                data["analysis"] = {k: v for k, v in data["analysis"].items() if k not in ("auto_photo", "credits")}
                data["analysis"]["auto_photo_off"] = True
        new = ContextItem.model_validate(data)
        profile = ("voice_description", "voice_gender", "voice_age", "voice_pitch", "voice_pace", "voice_accent")
        if (new.actor and item.actor and any(getattr(new.actor, f) != getattr(item.actor, f) for f in profile)
                and not new.analysis.get("voice_user_picked") and not new.actor.voice_sample):
            # the voice profile changed: choose the voice again next time (a voice the user picked by hand stays)
            new.actor.voice_id = None
            new.actor.voice_provider = None
            new.actor.voice_name = ""
            new.actor.voice_note = ""
            for k in ("voice_shift", "voice_alternatives"):
                new.analysis.pop(k, None)
        p.context = [new if c.id == cid else c for c in p.context]
        return self.save(p)

    def remove_context(self, pid: str, cid: str) -> Project:
        p = self.load(pid)
        p.context = [c for c in p.context if c.id != cid]
        for n, _ in walk(p.root):
            n.context_add = [x for x in n.context_add if x != cid]
            n.context_off = [x for x in n.context_off if x != cid]
            n.context_override = {k: v for k, v in n.context_override.items() if k != cid and v != cid}
        return self.save(p)

    def toggle_context(self, pid: str, node_id: str, cid: str, off: bool) -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        if off and cid not in n.context_off:
            n.context_off.append(cid)
        if not off:
            n.context_off = [x for x in n.context_off if x != cid]
        return self.save(p)

    def override_context(self, pid: str, node_id: str, original: str, replacement: Optional[str]) -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        if replacement:
            n.context_override[original] = replacement
        else:
            n.context_override.pop(original, None)
        return self.save(p)

    def give_consent(self, pid: str, cid: str, statement: str, by: str = "") -> Project:
        if statement not in ("self", "permission"):
            raise ValueError("statement must be 'self' or 'permission'")
        p = self.load(pid)
        item = item_by_id(p, cid)
        files = list(item.files) + ([item.actor.voice_sample] if item.actor and item.actor.voice_sample else [])
        item.consent = Consent(confirmed=True, statement=statement, confirmed_by=by or self.config.user_name or "user",
                               confirmed_at=now_iso(), files=files)
        if statement == "self" and item.actor:
            item.actor.kind = "digital_twin" if item.files else item.actor.kind
        return self.save(p)

    # ================================================================ dependencies
    def add_dependency(self, pid: str, from_id: str, to_id: str, typ: str, note: str = "") -> Project:
        p = self.load(pid)
        deps_mod.add_dependency(p, Dependency(from_id=from_id, to_id=to_id, type=DependencyType(typ), source="user", note=note))
        return self.save(p)

    def remove_dependency(self, pid: str, dep_id: str) -> Project:
        p = self.load(pid)
        p.dependencies = [d for d in p.dependencies if d.id != dep_id]
        return self.save(p)

    def update_dependency(self, pid: str, dep_id: str, typ: str) -> Project:
        p = self.load(pid)
        for d in p.dependencies:
            if d.id == dep_id:
                d.type = DependencyType(typ)
                d.source = "user"
        return self.save(p)

    # ================================================================ versions & feedback
    async def preview_remake(self, pid: str, node_id: str, accepted: list[str], user_feedback: str) -> dict:
        p = self.load(pid)
        n = find(p, node_id)
        suggestions = []
        for r in p.reviews:
            for s in r.suggestions:
                if s.id in accepted:
                    suggestions.append(s.text)
        parts = []
        if user_feedback.strip():
            parts.append(f"USER FEEDBACK (highest priority): {user_feedback.strip()}")
        if suggestions:
            parts.append("REVIEW AGENT SUGGESTIONS ACCEPTED BY THE USER: " + "; ".join(suggestions))
        feedback = "\n".join(parts) or "Improve realism and match the goal more closely."
        draft = await self.brain.write_clip_script(p, n, feedback)
        self._ledger_llm(p, f"merge feedback {node_id}")
        new_script = draft_to_script(p, draft)
        clone = p.model_copy(deep=True)
        cn = find(clone, node_id)
        cn.script = new_script
        cn.voice_seconds = None
        cn.voice_audio = None
        cn.status = NodeStatus.ready
        est.refresh(clone, self.reg)
        return {"old": n.script.model_dump() if n.script else None, "new": new_script.model_dump(),
                "change_summary": draft.change_summary, "feedback": feedback,
                "cost": cn.cost.model_dump(), "time": cn.time.model_dump(), "draft": draft.model_dump()}

    def apply_remake(self, pid: str, node_id: str, new_script: dict, feedback: str) -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        if n.script:
            n.versions.append(ClipVersion(version=n.version, script=n.script, feedback=feedback))
        n.version += 1
        n.script = ClipScript.model_validate(new_script)
        n.voice_audio, n.voice_seconds = None, None
        n.chosen_take = None
        n.output = None
        n.status = NodeStatus.ready
        deps_mod.mark_downstream_stale(p, node_id)
        return self.save(p)

    def revert_version(self, pid: str, node_id: str, version: int) -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        target = next((v for v in n.versions if v.version == version), None)
        if not target:
            raise ValueError(f"no version {version}")
        if n.script:
            n.versions.append(ClipVersion(version=n.version, script=n.script, feedback="(before going back)"))
        n.script = target.script
        n.version = max(v.version for v in n.versions) + 1
        old_takes = [t for t in n.takes if t.version == version]
        n.chosen_take = old_takes[0].id if old_takes else None
        n.output = None
        n.voice_audio, n.voice_seconds = None, None
        n.status = NodeStatus.needs_pick if old_takes else NodeStatus.ready
        deps_mod.mark_downstream_stale(p, node_id)
        return self.save(p)

    # ================================================================ explain everything
    KIND_LABEL = {
        "llm": "AI brain (planning, scripts, photo search words)", "review": "Review Agent (checking clips)",
        "image": "Pictures", "video": "Video", "avatar": "Talking animation", "lipsync": "Lip-sync",
        "voice": "Voices", "voice_clone": "Voice copies", "music": "Music",
    }

    def budget_report(self, pid: str) -> dict:
        """Where the money went: every paid call, grouped, with the arithmetic behind each number."""
        p = self.load(pid)
        self.refresh(p)
        rows = ProjectStore.ledger(pid)
        groups: dict[str, dict] = {}
        for r in rows:
            kind = r.get("kind", "other")
            g = groups.setdefault(kind, {"key": kind, "label": self.KIND_LABEL.get(kind, kind), "calls": 0, "estimated": 0.0, "actual": 0.0, "rows": []})
            g["calls"] += 1
            g["estimated"] += float(r.get("estimated_usd", 0) or 0)
            g["actual"] += float(r.get("actual_usd", 0) or 0)
            how = ""
            if r.get("tokens_in") is not None:
                how = f"{r.get('tokens_in', 0):,} tokens in + {r.get('tokens_out', 0):,} tokens out"
            elif r.get("units"):
                how = str(r["units"]) + (f" {r['rate']}" if r.get("rate") else "")
            elif r.get("rate"):
                how = str(r["rate"])
            g["rows"].append({"at": r.get("at", ""), "what": r.get("what", ""), "vendor": r.get("plugin", ""), "model": r.get("model", ""),
                              "how": how, "estimated": round(float(r.get("estimated_usd", 0) or 0), 4),
                              "actual": round(float(r.get("actual_usd", 0) or 0), 4)})
        for g in groups.values():
            g["estimated"], g["actual"] = round(g["estimated"], 4), round(g["actual"], 4)
        spent = round(p.run.spent_usd, 4)
        total = round(sum(g["actual"] for g in groups.values()), 4)
        todo = [l for l in leaves(p) if l.status != NodeStatus.done]
        remaining = round(sum(l.cost.likely_usd for l in todo), 2)
        budget = p.settings.budget_usd
        brain = self.reg.llm_plugin_name("default")
        brain_model = self.reg.llm_model("default", brain)
        brain_entry = self.reg.llm_entry("default")
        return {
            "budget": budget, "spent": spent, "ledger_total": total, "remaining_estimate": remaining,
            "left_in_budget": round(budget - spent - remaining, 2),
            "groups": sorted(groups.values(), key=lambda g: -g["actual"]),
            "brain": {"plugin": brain, "model": brain_model,
                      "price": (f"${brain_entry.price.usd_in}/${brain_entry.price.usd_out} per 1M tokens (in/out)" if brain_entry else "")},
            "explain": [
                f"Budget ${budget:.2f} is a safety limit you set. The default comes from Settings → Budget & quality; for this video you can change it in Cost & time → Whole video → Budget.",
                f"Spent ${spent:.2f} is the total of every paid call this tool made for this project (list below). Clips that are already made are counted here, not in “still to spend”.",
                f"Still to spend ≈ ${remaining:.2f} is the estimate for the clips not made yet (price × units × takes, from the model catalogue).",
                "AI brain and Review Agent calls are counted from the tokens the AI vendor reports, times the vendor's price per token.",
                "Other vendors (video, pictures, voices, music) rarely report the exact bill per call, so the tool counts catalogue price × amount (seconds, images, characters). Your vendor's own dashboard is the final truth.",
                "Budget guard: before each clip the tool checks spent + that clip's estimate. If it would pass the budget, the run pauses and asks you.",
            ],
        }

    def facts(self, pid: str, focus_id: Optional[str] = None) -> str:
        """Everything the help assistant may use to answer a question (plain facts, no opinions)."""
        p = self.load(pid)
        summ = self.summary(p)
        nums = numbering(p)
        rep = self.budget_report(pid)
        L = [
            f"Project: {p.name}. Goal: {p.goal}",
            f"Target length {p.settings.target_seconds:.0f}s; estimated length {summ['seconds']:.0f}s; shape {p.settings.aspect}; resolution {p.settings.resolution}; format {p.settings.format}.",
            f"Quality mode: {p.settings.quality_mode} (best = highest quality, balanced = quality per dollar, budget = cheapest, free = free previews only).",
            f"Takes per clip with people: {p.settings.takes_people}; other clips: {p.settings.takes_other}. Review Agent {'on' if p.settings.review_enabled else 'off'}; music {'on' if p.settings.music else 'off'}; auto-pick {'on' if p.settings.auto_pick else 'off'}.",
            f"AI brain in use: {rep['brain']['plugin']} ({rep['brain']['model']}) {rep['brain']['price']}.",
            f"MONEY: budget ${rep['budget']:.2f}; spent so far ${rep['spent']:.2f}; still to spend about ${rep['remaining_estimate']:.2f}; total estimate for all clips ${summ['cost_total']:.2f}.",
        ]
        L += [f"MONEY explanation: {x}" for x in rep["explain"]]
        for g in rep["groups"]:
            L.append(f"SPENT on {g['label']}: ${g['actual']:.4f} in {g['calls']} call(s). " + "; ".join(
                f"{r['what']} ({r['vendor']} {r['model']}) {r['how']} = ${r['actual']:.4f}" for r in g["rows"][:6]))
        L.append(f"TIME: about {summ['time_s'] / 60:.0f} minutes to make what is left (clips that do not depend on each other are made at the same time).")
        pv = summ["preview"]
        if pv["clips"]:
            L.append(f"PREVIEW MODE: {len(pv['clips'])} clip(s) will only be free placeholder cards. Missing: " + "; ".join(pv["jobs"].values()))
        for w in summ["warnings"]:
            L.append(f"WARNING: {w}")
        for leaf in leaves(p):
            if focus_id and leaf.id != focus_id and len(L) > 90:
                continue
            plan = est.plan_clip(p, leaf, self.reg)
            why = ""
            if plan.video:
                shot = leaf.script.shot_type.value if leaf.script else "other"
                why = (f"model {plan.video.id} via {plan.video.plugin}; its score for '{shot}' shots is {plan.video.strength(shot)}/5; "
                       f"price ${plan.video.unit_price}/{plan.video.price.unit}; route {plan.route}")
            lines = "; ".join(f"{c.item}: {c.calc} = ${c.cost:.3f}" for c in leaf.cost.lines)
            deps = "; ".join(f"{d.type.value} from {nums.get(d.from_id)}" for d in p.dependencies if d.to_id == leaf.id)
            L.append(f"CLIP {nums.get(leaf.id)} '{leaf.title}': status {leaf.status.value}; length ~{leaf.duration.likely_s:.0f}s ({leaf.duration.explain}); "
                     f"cost ≈ ${leaf.cost.likely_usd:.2f} [{lines}]; time {leaf.time.explain}; {why}; links: {deps or 'none'}; warnings: {'; '.join(leaf.warnings) or 'none'}")
        for r in p.reviews[-8:]:
            L.append(f"REVIEW of {r.target}: {r.verdict}; scores {r.scores}; issues: " + "; ".join(f"{i.check}: {i.text}" for i in r.issues[:4]))
        L.append(f"FINAL VIDEO: {'ready' if summ['final_ready'] else 'not made yet'}{' (out of date)' if summ['final_stale'] else ''}.")
        configured = [v["name"] for v in self.vendors_status() if v["configured"]]
        L.append("CONNECTED SERVICES: " + (", ".join(configured) or "none (free local tools only)"))
        return "\n".join(L)[:16000]

    def mode_costs(self, pid: str, node_id: str) -> dict:
        """What this part (or clip, or the whole video) would cost, and take, in each quality: worked out on a COPY, nothing is saved.
        `cost_todo` counts only clips not made yet, since made clips do not change."""
        p = self.load(pid)
        node = find(p, node_id)
        is_root = node.id == p.root.id

        def measure(mode: Optional[str]) -> dict:
            q = p.model_copy(deep=True)
            n = find(q, node_id)
            if is_root:
                q.settings.quality_mode = mode or q.settings.quality_mode
            else:
                n.quality_mode = mode
            self.refresh(q)
            n = find(q, node_id)
            below = [x for x, _ in walk(n) if x.is_leaf]
            todo = [x for x in below if x.status != NodeStatus.done]
            models: list[str] = []
            for x in below:
                if x.cost.model and x.cost.model not in models:
                    models.append(x.cost.model)
            return {"cost": n.cost.likely_usd, "cost_todo": round(sum(x.cost.likely_usd for x in todo), 2), "cost_min": n.cost.min_usd,
                    "cost_max": n.cost.max_usd, "seconds": n.duration.likely_s, "time_s": n.time.likely_s, "models": models,
                    "clips": len(below), "to_make": len(todo)}
        modes = {m: measure(m) for m in ("best", "balanced", "budget", "free")}
        parent_mode = p.settings.quality_mode
        if not is_root:
            chain = [a for a in ancestors(p, node_id) if a.quality_mode]
            parent_mode = chain[-1].quality_mode if chain else p.settings.quality_mode
        return {"current": "" if is_root else (node.quality_mode or ""), "effective": est.mode_for(p, node), "inherits": parent_mode,
                "is_whole_video": is_root, "modes": modes}

    # ================================================================ the optimizer (see optimizer.py)
    @staticmethod
    def _optimize_goal(body: dict) -> "optimizer_mod.Goal":
        def num(v):
            return float(v) if v not in (None, "") else None
        return optimizer_mod.Goal(length=num(body.get("length")), cost=num(body.get("cost")), lowest=bool(body.get("lowest")))

    def optimize_propose(self, pid: str, body: dict) -> dict:
        """A proposal for a length and/or cost goal on a scope (the whole video or one part). Nothing is saved or spent."""
        p = self.load(pid)
        self.refresh(p)
        return optimizer_mod.propose(self, p, body.get("scope") or p.root.id, self._optimize_goal(body), body.get("max_level"),
                                     body.get("ticked"), body.get("protect") or [], body.get("ai_edits") or [], self._answers(body))

    def optimize_apply(self, pid: str, body: dict) -> Project:
        """Apply the edits you ticked as ONE saved change, so a single undo takes it all back."""
        p = self.load(pid)
        self.refresh(p)
        optimizer_mod.apply(self, p, body.get("scope") or p.root.id, self._optimize_goal(body), body.get("ticked"), body.get("protect") or [],
                            body.get("ai_edits") or [], self._answers(body))
        return self.save(p)

    async def optimize_ai(self, pid: str, body: dict) -> dict:
        """Ask the AI to tighten the scripts in this scope. This SPENDS a little (the proposal showed the cost first). Returns the AI's suggestions,
        which you then tick; the tool checks every one against its rules before showing it."""
        p = self.load(pid)
        self.refresh(p)
        scope = body.get("scope") or p.root.id
        by_number = {v: k for k, v in numbering(p).items() if v}
        extra = frozenset(body.get("protect") or []) | frozenset(by_number[n] for n, how in self._answers(body).items() if how == "keep" and n in by_number)
        info = optimizer_mod.ai_estimate(self, p, scope, extra)
        if not info["available"]:
            raise ValueError(info["why"])
        goal = self._optimize_goal(body)
        nums = numbering(p)
        what = "the whole video" if scope == p.root.id else f"part {nums.get(scope, '')}"
        want = " and ".join(x for x in (f"a length of about {goal.length:g} seconds" if goal.length else "", f"a cost of about ${goal.cost:g}" if goal.cost else "",
                                         "as short and cheap as possible without losing meaning" if goal.lowest else "") if x)
        clips = optimizer_mod._free_clips(p, scope, extra)
        said = replan_mod.answers_text(p, self._answers(body))
        tight = await self.brain.tighten(p, what, (want or "shorter and cheaper") + (f". The person said: {said.replace(chr(10), '; ')}" if said else ""), clips)
        spent_before = p.run.spent_usd
        self._ledger_llm(p, "optimize")
        ProjectStore.save(p, snapshot=False)
        raw = [e.model_dump() for e in tight.edits]
        edits, skipped = optimizer_mod.validate_ai(self, p, scope, extra, raw)
        return {"edits": raw, "valid": [e.model_dump() for e in edits], "skipped": skipped, "note": tight.note, "cost_usd": round(p.run.spent_usd - spent_before, 4)}

    # ================================================================ re-plan from a leaner Goal (see replan.py)
    @staticmethod
    def _answers(body: dict) -> dict:
        """What you said may be cut: {clip or part number: keep | shorten | cut}."""
        return {str(k): v for k, v in (body.get("answers") or {}).items() if v in ("keep", "shorten", "cut")}

    def replan_estimate(self, pid: str, body: dict) -> dict:
        """What asking for a re-plan costs, and what the new scripts will cost after you apply (nothing is asked or spent)."""
        p = self.load(pid)
        self.refresh(p)
        scope = body.get("scope") or p.root.id
        return replan_mod.estimate(self, p, scope, frozenset(body.get("protect") or []))

    def cut_list(self, pid: str, body: dict) -> list[dict]:
        """Every part and clip in the scope with what dropping it would save: the list behind 'what may be cut?'."""
        p = self.load(pid)
        self.refresh(p)
        return replan_mod.cut_list(self, p, body.get("scope") or p.root.id, frozenset(body.get("protect") or []))

    async def replan_preview(self, pid: str, body: dict) -> dict:
        """Ask the planner for a leaner Goal and a new breakdown, giving it the CURRENT breakdown as context. This SPENDS (the estimate was shown first).
        Nothing is changed: the answer is a proposal, shown beside the current plan, with the Goal difference and what happens to your videos."""
        p = self.load(pid)
        self.refresh(p)
        scope = body.get("scope") or p.root.id
        goal = self._optimize_goal(body)
        answers = self._answers(body)
        by_number = {v: k for k, v in numbering(p).items() if v}
        extra = frozenset(body.get("protect") or []) | frozenset(by_number[n] for n, how in answers.items() if how == "keep" and n in by_number)
        base = optimizer_mod.propose(self, p, scope, goal, protect=list(extra))             # the gentle levels, for the numbers the planner is told
        nums = numbering(p)
        node = find(p, scope)
        qa = "\n".join(f"- {q['text']}: {a}" for q in (body.get("question_answers") or []) for a in [q.get("answer", "")] if a)
        said = replan_mod.answers_text(p, answers) + (("\nANSWERS TO YOUR QUESTIONS:\n" + qa) if qa else "")
        data = replan_mod.structure(p, scope, extra, answers, goal)
        before_spent = p.run.spent_usd
        raw = await self.brain.replan(p, "the whole video" if scope == p.root.id else f"part {nums.get(scope, '')}", p.goal, "" if scope == p.root.id else node.goal,
                                      replan_mod.wish_text(goal), replan_mod.situation_text(base["before"], base["levels"][2]["after"], goal),
                                      replan_mod.outline_text(p, scope, extra), said, data)
        self._ledger_llm(p, "re-plan")
        ProjectStore.save(p, snapshot=False)
        cost = round(p.run.spent_usd - before_spent, 4)
        r = raw.model_dump()
        if r.get("questions") and not r.get("parts"):
            return {"plan": None, "questions": r["questions"], "note": r.get("note", ""), "cost_usd": cost}
        plan = replan_mod.resolve(self, p, scope, r, extra, answers, goal)
        out = replan_mod.simulate(self, p, plan, None, scope)
        return {"plan": plan, "questions": [], **out, "cost_usd": cost, "estimate": replan_mod.estimate(self, p, scope, extra)}

    def replan_measure(self, pid: str, body: dict) -> dict:
        """The numbers for the plan with YOUR choices (which videos to reuse, an edited Goal): free, measured on a copy."""
        p = self.load(pid)
        self.refresh(p)
        plan = body["plan"]
        if replan_mod.structure_stamp(p) != plan.get("stamp"):
            raise ValueError("The project changed since this plan was made. Ask for the plan again.")
        return replan_mod.simulate(self, p, plan, {k: bool(v) for k, v in (body.get("reuse") or {}).items()}, plan["scope"])

    def replan_apply(self, pid: str, body: dict) -> Project:
        """Apply the plan as ONE change (one undo step): the Goal, the parts and clips, with the videos you chose to reuse. The new scripts are written
        afterwards with the usual 'Write the scripts' step, after you have seen what that costs."""
        p = self.load(pid)
        self.refresh(p)
        plan = body["plan"]
        if replan_mod.structure_stamp(p) != plan.get("stamp"):
            raise ValueError("The project changed since this plan was made. Ask for the plan again.")
        replan_mod.apply_plan(self, p, plan, {k: bool(v) for k, v in (body.get("reuse") or {}).items()}, body.get("goal"), body.get("part_goal"))
        return self.save(p)

    def music_status(self, pid: str) -> dict:
        """What the Join button needs to say about the music BEFORE it spends: is there a saved track that can be reused (cost 0),
        or would a new one be made, with which model, for how much."""
        p = self.load(pid)
        self.refresh(p)
        total = p.root.duration.likely_s
        entry = None
        if p.settings.music:
            try:
                entry = self.reg.choose("music", mode=p.settings.quality_mode)
            except LookupError:
                entry = None
        real_possible = any(not e.is_free and self.reg.entry_usable(e) for e in self.catalog.for_job("music"))
        st = musictrack.status(p, total, real_possible)
        new_cost = round(musictrack.cost(entry, total), 2)
        return {"enabled": bool(entry), "total_s": round(total, 1), "saved": st["exists"], "reusable": st["reusable"], "why": st["why"],
                "made_for_s": st["made_for_s"], "model": entry.id if entry else "", "free": bool(entry and entry.is_free),
                "cost_new_usd": new_cost, "cost_usd": 0.0 if (st["reusable"] or not entry) else new_cost}

    # ================================================================ every model, in plain words
    def model_rows(self) -> list[dict]:
        """EVERY catalogue model as a row for a list of choices: price in words, what it can do, whether it can be used and,
        if not, exactly why. Brain models also carry what one plan draft would cost with them."""
        rows = []
        for e in self.catalog.entries:
            why = self.reg.unusable_reason(e)
            rows.append(models_list.row(e, not why, why, est._llm_cost(e, est.PLAN_TOKENS) if e.job == "llm" else None))
        return rows

    async def discover_models(self) -> dict:
        """Ask each connected vendor which AI models your key can use (free, read-only). Models that are not in the catalogue yet
        come back with in_catalogue = False: the screen offers them with a box for their price. Never raises: problems are returned."""
        import os
        from .catalog import load_vendors
        specs = {v["id"]: v for v in load_vendors() if v.get("models_list")}
        plugin_of = {e.vendor: e.plugin for e in self.catalog.for_job("llm") if e.vendor in specs}
        known = {(e.plugin, e.model) for e in self.catalog.for_job("llm")}
        found: list[dict] = []
        errors: dict[str, str] = {}
        skipped: list[str] = []
        for vid, v in specs.items():
            key = next((os.environ.get(k) for k in v.get("env", []) if os.environ.get(k)), "")
            if not key:
                skipped.append(v["name"])
                continue
            try:
                got = await models_list.fetch(v["models_list"], key)
            except models_list.ListError as exc:
                errors[v["name"]] = str(exc)
                continue
            plugin = plugin_of.get(vid)
            for m in got:
                found.append({"id": m["id"], "name": m["name"], "vendor": vid, "plugin": plugin, "in_catalogue": (plugin, m["id"]) in known})
        return {"models": found, "errors": errors, "skipped": skipped}

    def add_model(self, plugin: str, model: str, usd_in: float, usd_out: float, note: str = "") -> dict:
        """Put an AI model found at the vendor into your catalogue with the price you read on the vendor's page. If it is already
        there, only its price is updated. The price matters: it is how every AI call and every estimate is counted."""
        import re
        from datetime import date
        from .catalog import CatalogEntry, Price, Timing
        if usd_in < 0 or usd_out < 0:
            raise ValueError("a price cannot be negative")
        rows = [e for e in self.catalog.for_job("llm") if e.plugin == plugin]
        if not rows:
            raise ValueError(f"unknown AI vendor: {plugin}")
        same = next((e for e in rows if e.model == model), None)
        base = same or rows[0]
        entry = (same or CatalogEntry(id=re.sub(r"[^a-z0-9]+", "_", f"{plugin}_{model}".lower()).strip("_"), job="llm", plugin=plugin,
                                      model=model, vendor=base.vendor, capabilities=dict(base.capabilities), quality=3,
                                      time=Timing(queue_s=0, per_output_s=15), pricing_url=base.pricing_url,
                                      note=note or "Found at the vendor; price entered by you")).model_copy(deep=True)
        entry.price = Price(unit="1m_tokens", usd_in=usd_in, usd_out=usd_out)
        entry.last_checked = date.today().isoformat()
        self.catalog.save_user_override(entry)
        self.reload()
        return next(r for r in self.model_rows() if r["id"] == entry.id)

    def vendors_status(self) -> list[dict]:
        import os
        from .catalog import load_vendors
        out = []
        for v in load_vendors():
            keys = v.get("env", [])
            out.append({**v, "configured": bool(keys) and all(os.environ.get(k) for k in keys)})
        return out

    async def explain(self, pid: str, question: str, focus_id: Optional[str] = None) -> str:
        facts = self.facts(pid, focus_id)
        res = await self.brain.explain(question, facts)
        p = self.load(pid)
        self._ledger_llm(p, "answer a question")
        ProjectStore.save(p, snapshot=False)
        return res.answer

    # ================================================================ misc
    def _ledger_llm(self, p: Project, what: str) -> None:
        u = self.brain.last_usage
        if u.cost_usd or u.input_tokens:
            ProjectStore.ledger_add(p.id, {"kind": "llm", "what": what, "plugin": u.raw.get("plugin", ""),
                                           "model": u.raw.get("model", ""), "estimated_usd": round(u.cost_usd, 4),
                                           "actual_usd": round(u.cost_usd, 4), "tokens_in": u.input_tokens,
                                           "tokens_out": u.output_tokens})
            p.run.spent_usd = round(p.run.spent_usd + u.cost_usd, 4)
            self.brain.last_usage = type(u)()

    def estimate_targets(self, pid: str, targets: list[str]) -> dict:
        p = self.load(pid)
        self.refresh(p)
        out = est.estimate_targets(p, self.reg, targets)
        out["reuses"] = continuity_mod.reuses(p, self.reg, out["clips"])       # what these clips take from the rest of the video
        return out
