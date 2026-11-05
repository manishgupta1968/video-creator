"""Service layer: every planning action the CLI and GUI can take."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from . import deps as deps_mod
from . import estimate as est
from . import media
from . import stock
from .brain import (Brain, ClipScriptDraft, CommandPlan, Op, ProjectDraft, draft_to_script)
from .catalog import Catalog
from .config import Config
from .context import guess_type_and_role, item_by_id
from .models import (ActorDetails, ClipScript, ClipVersion, Consent, ContextItem, ContextRole, ContextType,
                     Dependency, DependencyType, Node, NodeKind, NodeStatus, Project, Settings, Style, now_iso)
from .project import ProjectStore
from .registry import Registry
from .tree import add_child, find, leaves, move, numbering, remove, walk


class Service:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.load()
        ProjectStore.init(self.config)
        self.catalog = Catalog.load()
        self.reg = Registry(self.config, self.catalog)
        self.brain = Brain(self.reg)

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
        return {"seconds": e.seconds, "seconds_min": e.seconds_min, "seconds_max": e.seconds_max,
                "target_seconds": project.settings.target_seconds, "cost": e.cost, "cost_min": e.cost_min,
                "cost_max": e.cost_max, "time_s": e.time_s, "spent": e.spent, "budget": project.settings.budget_usd,
                "warnings": e.warnings, "waiting_picks": waiting, "review_flags": review_flags,
                "clips": len(leaves(project)), "done": sum(1 for l in leaves(project) if l.status == NodeStatus.done),
                "numbers": numbering(project), "brain": self.reg.llm_plugin_name("default"),
                "preview": self.preview_info(project), **self.final_info(project)}

    HINTS = {
        "video": "Add FAL_KEY (Kling, Seedance, Wan) or GEMINI_API_KEY (Veo) to get real video.",
        "avatar": "Add FAL_KEY to get a real talking animation (Kling Avatar); a presenter can also use HEYGEN_API_KEY.",
        "image": "Add FAL_KEY, GEMINI_API_KEY or OPENAI_API_KEY to get real pictures.",
        "voice": "Add ELEVENLABS_API_KEY or CARTESIA_API_KEY to get natural voices (and to copy a voice).",
    }

    def preview_info(self, project: Project) -> dict:
        """Which clips will only get free placeholder output, and what to add to fix that."""
        clips: dict[str, list[str]] = {}
        jobs: dict[str, str] = {}
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
                for r in reasons:
                    jobs[r] = self.HINTS[r]
            unused += [w for w in plan.warnings if w.startswith("The voice sample")]
        needs_media = [l for l in leaves(project) if l.kind == NodeKind.clip]
        all_preview = bool(needs_media) and all(any(r in ("video", "avatar") for r in clips.get(l.id, [])) for l in needs_media)
        return {"clips": clips, "jobs": jobs, "all_preview": all_preview, "chosen_free_mode": project.settings.quality_mode == "free",
                "voice_sample_unused": sorted(set(unused))}

    def final_info(self, project: Project) -> dict:
        path = ProjectStore.path_for(project.id) / project.final_output if project.final_output else None
        ready = bool(path and path.exists())
        stale = ready and bool(project.final_hash) and project.final_hash != ProjectStore.final_signature(project)
        all_done = bool(leaves(project)) and all(l.status == NodeStatus.done for l in leaves(project))
        return {"final_ready": ready, "final_stale": stale, "all_clips_done": all_done}

    def new_project(self, goal: str, seconds: float = 60, aspect: str = "16:9", fmt: str = "mp4",
                    files: Optional[list[Path]] = None, name: str = "", budget: Optional[float] = None,
                    quality_mode: Optional[str] = None) -> Project:
        settings = Settings(target_seconds=seconds, aspect=aspect, format=fmt,
                            budget_usd=budget if budget is not None else self.config.budget_usd,
                            quality_mode=quality_mode or self.config.quality_mode)
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
        p.style = Style(look=d.style.look, colour=d.style.colour, mood=d.style.mood, notes=p.style.notes)
        existing = {c.title.lower(): c for c in p.context if c.type == ContextType.actor}
        for a in d.actors:
            if a.name.lower() in existing:
                c = existing[a.name.lower()]
                if c.actor:
                    for f in ("description", "clothing", "behaviour", "voice_description"):
                        if not getattr(c.actor, f):
                            setattr(c.actor, f, getattr(a, f))
                continue
            p.context.append(ContextItem(type=ContextType.actor, title=a.name, role=ContextRole.must_appear,
                                         actor=ActorDetails(kind=a.kind, description=a.description, clothing=a.clothing,
                                                            behaviour=a.behaviour, voice_description=a.voice_description)))
        p.root.children = []
        for part in d.parts:
            g = Node(kind=NodeKind.goal, title=part.title, goal=part.goal, target_seconds=part.seconds or None)
            for c in part.clips:
                g.children.append(Node(kind=NodeKind.clip, title=c.title, goal=c.goal, target_seconds=c.seconds or None))
            if not g.children:
                g.kind = NodeKind.clip
            p.root.children.append(g)
        self._fit_to_target(p)
        self._attach_media_context(p)
        self.save(p)
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

        def roll(node: Node) -> None:
            for c in node.children:
                if c.kind == NodeKind.goal:
                    roll(c)
            if node is not p.root and node.children:
                node.target_seconds = round(sum((c.target_seconds or 0) for c in node.children), 1) or node.target_seconds
        roll(p.root)

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

    async def write_all_scripts(self, pid: str, under: Optional[str] = None, overwrite: bool = False) -> Project:
        p = self.load(pid)
        base = find(p, under) if under else p.root
        targets = [n for n, _ in walk(base) if n.kind == NodeKind.clip and (overwrite or not n.script)]
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
        self.save(p)
        if errors:
            raise RuntimeError("; ".join(errors[:3]))
        return p

    def _apply_script(self, p: Project, node: Node, draft: ClipScriptDraft, feedback: str = "") -> None:
        if node.script:
            node.versions.append(ClipVersion(version=node.version, script=node.script, feedback=feedback))
            node.version += 1
        node.script = draft_to_script(p, draft)
        if node.target_seconds and not node.script.target_seconds:
            node.script.target_seconds = node.target_seconds
        node.voice_audio = None
        node.voice_seconds = None
        if node.status in (NodeStatus.done, NodeStatus.needs_pick, NodeStatus.failed):
            node.status = NodeStatus.stale
            deps_mod.mark_downstream_stale(p, node.id)
        elif node.status in (NodeStatus.draft,):
            node.status = NodeStatus.ready
        prev = None
        for n, _ in walk(p.root):
            if n.id == node.id:
                break
            if n.is_leaf:
                prev = n
        if prev:
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
                                   goal=c.goal, target_seconds=c.seconds or None))
        self._ledger_llm(p, f"break down {node_id}")
        self.save(p)
        return await self.write_all_scripts(pid, under=node_id)

    async def revise(self, pid: str, node_id: str, instruction: str) -> Project:
        p = self.load(pid)
        n = find(p, node_id)
        if n.kind == NodeKind.clip:
            return await self.write_script(pid, node_id, feedback=instruction)
        rev = await self.brain.revise_goal(p, n, instruction)
        p = self.load(pid)
        n = find(p, node_id)
        n.title, n.goal = rev.title or n.title, rev.goal or n.goal
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
            elif op.op == "set_goal" and n:
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
        for key in ("title", "goal", "target_seconds", "provider_override", "takes_override", "transition_in",
                    "review_enabled", "style_overrides"):
            if key in patch:
                setattr(n, key, patch[key])
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
        if script_changed:
            n.voice_audio, n.voice_seconds = None, None
            if n.status in (NodeStatus.done, NodeStatus.needs_pick):
                n.status = NodeStatus.stale
                deps_mod.mark_downstream_stale(p, n.id)
        if n.id == p.root.id and "target_seconds" in patch and patch["target_seconds"]:
            p.settings.target_seconds = float(patch["target_seconds"])
        return self.save(p)

    def add_node(self, pid: str, parent_id: str, kind: str = "clip", title: str = "", goal: str = "",
                 index: Optional[int] = None, media_path: Optional[str] = None) -> tuple[Project, str]:
        p = self.load(pid)
        n = Node(kind=NodeKind(kind), title=title or "New clip", goal=goal, media=media_path)
        add_child(p, parent_id, n, index)
        self.save(p)
        return p, n.id

    def remove_node(self, pid: str, node_id: str) -> Project:
        p = self.load(pid)
        remove(p, node_id)
        return self.save(p)

    def move_node(self, pid: str, node_id: str, parent_id: str, index: int) -> Project:
        p = self.load(pid)
        move(p, node_id, parent_id, index)
        return self.save(p)

    def update_project(self, pid: str, patch: dict) -> Project:
        p = self.load(pid)
        if "name" in patch:
            p.name = patch["name"]
            p.root.title = p.name
        if "goal" in patch:
            p.goal = patch["goal"]
            p.root.goal = p.goal
        if "settings" in patch:
            p.settings = Settings.model_validate({**p.settings.model_dump(), **patch["settings"]})
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
            elif k in data:
                data[k] = v
        new = ContextItem.model_validate(data)
        if new.actor and item.actor and new.actor.voice_description != item.actor.voice_description:
            new.actor.voice_id = None
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
        return est.estimate_targets(p, self.reg, targets)
