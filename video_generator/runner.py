"""Generation engine: makes clips in dependency order, takes, review, picks,
assembly. One background run per project; state is saved after each step,
so `resume` continues after a restart."""
from __future__ import annotations

import asyncio
import json
import math
import shutil
import dataclasses
import hashlib
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import casting
from . import policy as policy_mod
from . import deps as deps_mod
from . import estimate as est
from . import media
from . import musictrack
from .context import effective_context, item_by_id
from .models import (ActorDetails, ContextItem, ContextRole, ContextType, DependencyType, EstimateBasis, Node, NodeKind,
                     NodeStatus, Project, ShotType, Take, now_iso)
from .plugins.base import (AvatarRequest, ImageRequest, PluginError, Usage, VideoRequest, VoiceSpec)
from .project import ProjectStore, slug
from .reviewer import Reviewer
from .tree import effective_style, find, leaves, numbering, walk

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


class ConsentError(PluginError):
    pass


class BudgetPause(Exception):
    pass


@dataclass
class RunCtl:
    task: Optional[asyncio.Task] = None
    resume: asyncio.Event = field(default_factory=asyncio.Event)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    stop: bool = False
    running: dict[str, asyncio.Task] = field(default_factory=dict)


class Engine:
    def __init__(self, service, emit: Optional[Callable[[str, dict], Any]] = None, stop_when_waiting: bool = False):
        self.svc = service
        self.stop_when_waiting = stop_when_waiting
        self.emit_cb = emit
        self.runs: dict[str, RunCtl] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.reviewer = Reviewer(service)
        service.engine = self
        self.activity: dict[str, dict[str, dict]] = {}     # pid -> node id (or "final") -> live step

    # ================================================================ helpers
    def emit(self, pid: str, event: dict) -> None:
        if self.emit_cb:
            try:
                self.emit_cb(pid, event)
            except Exception:
                pass

    def lock(self, pid: str) -> asyncio.Lock:
        return self.locks.setdefault(pid, asyncio.Lock())

    async def mutate(self, pid: str, fn: Callable[[Project], Any], snapshot: bool = False) -> Any:
        async with self.lock(pid):
            p = self.svc.load(pid)
            result = fn(p)
            self.svc.save(p, snapshot=snapshot)
        self.emit(pid, {"type": "project"})
        return result

    def pdir(self, pid: str) -> Path:
        return ProjectStore.path_for(pid)

    def cdir(self, pid: str, nid: str) -> Path:
        d = self.pdir(pid) / "clips" / nid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def abs(self, pid: str, rel: Optional[str]) -> Optional[Path]:
        if not rel:
            return None
        p = Path(rel)
        return p if p.is_absolute() else self.pdir(pid) / rel

    def rel(self, pid: str, path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.pdir(pid).resolve()))
        except ValueError:
            return str(path)

    async def message(self, pid: str, text: str) -> None:
        def f(p: Project):
            p.run.message = text
        await self.mutate(pid, f)

    async def charge(self, pid: str, row: dict) -> None:
        ProjectStore.ledger_add(pid, row)
        if row.get("plugin") and row.get("wall_s") and row.get("expected_s"):
            self.svc.reg.record_time(row.get("catalog_id", row["plugin"]), row["wall_s"], row["expected_s"])

        def f(p: Project):
            p.run.spent_usd = round(p.run.spent_usd + float(row.get("actual_usd", 0)), 4)
        await self.mutate(pid, f)

    # ================================================================ public API
    def step(self, pid: str, nid: str, text: str, expected_s: float = 0) -> None:
        """Record what a clip (or the final join, nid="final") is doing right now."""
        cur = self.activity.setdefault(pid, {}).get(nid)
        since = cur["since"] if cur and cur.get("text") == text else time.time()
        self.activity[pid][nid] = {"text": text, "since": since, "expected_s": expected_s,
                                   "started": cur["started"] if cur else time.time()}
        self.emit(pid, {"type": "clip", "node": nid, "step": text})

    def end_step(self, pid: str, nid: str) -> None:
        self.activity.get(pid, {}).pop(nid, None)

    def status(self, pid: str) -> dict:
        ctl = self.runs.get(pid)
        now = time.time()
        acts = [{"node": nid, "step": a["text"], "elapsed_s": round(now - a["started"]), "step_elapsed_s": round(now - a["since"]),
                 "started": round(a["started"], 1), "since": round(a["since"], 1), "now": round(now, 1),
                 "expected_s": a["expected_s"]} for nid, a in self.activity.get(pid, {}).items()]
        return {"active": bool(ctl and ctl.task and not ctl.task.done()),
                "running_clips": list(ctl.running.keys()) if ctl else [], "activity": acts}

    async def start(self, pid: str, mode: str, targets: Optional[list[str]] = None,
                    auto_pick: Optional[bool] = None) -> dict:
        p = self.svc.load(pid)
        self.svc.refresh(p)
        order = deps_mod.topo_order(p)
        if mode in ("all", "continue"):
            chosen = [n for n in order]
        elif mode == "next":
            pending = [n for n in order if find(p, n).status not in (NodeStatus.done,)]
            ready = [n for n in pending if all(find(p, d.from_id).status == NodeStatus.done
                                               for d in deps_mod.upstream(p, n) if d.type != DependencyType.order_only)]
            chosen = (ready or pending)[:1]
        else:
            chosen = []
            for t in targets or []:
                for u in deps_mod.required_upstream(p, t):
                    if u not in chosen:
                        chosen.append(u)
                if t not in chosen:
                    chosen.append(t)
        ctl = self.runs.get(pid)
        if ctl and ctl.task and not ctl.task.done():
            def add(pr: Project):
                for c in chosen:
                    if c not in pr.run.targets:
                        pr.run.targets.append(c)
                if mode in ("all", "continue"):
                    pr.run.mode = mode
                pr.run.status = "running"
            await self.mutate(pid, add)
            ctl.resume.set()
            ctl.wake.set()
            return {"started": False, "added": chosen}

        def setup(pr: Project):
            pr.run.mode = mode
            pr.run.status = "running"
            pr.run.targets = chosen
            pr.run.started_at = now_iso()
            pr.run.message = "starting"
            if auto_pick is not None:
                pr.settings.auto_pick = auto_pick
            explicit = set(targets or []) if mode == "clip" else set()
            for nid in chosen:
                n = find(pr, nid)
                if n.status == NodeStatus.failed:
                    n.status = NodeStatus.ready
                elif nid in explicit and n.status in (NodeStatus.done, NodeStatus.needs_pick):
                    # "Re-make" on a finished clip: you asked for this clip again, so make it again.
                    n.status = NodeStatus.ready
                    deps_mod.mark_downstream_stale(pr, nid)             # clips that continue from it must follow
        await self.mutate(pid, setup)
        ctl = RunCtl()
        ctl.resume.set()
        self.runs[pid] = ctl
        ctl.task = asyncio.create_task(self._run(pid))
        return {"started": True, "clips": chosen}

    async def pause(self, pid: str) -> None:
        ctl = self.runs.get(pid)
        if ctl:
            ctl.resume.clear()

        def f(p: Project):
            if p.run.status == "running":
                p.run.status = "paused"
                p.run.message = "paused — running jobs will finish"
        await self.mutate(pid, f)

    async def resume(self, pid: str) -> dict:
        ctl = self.runs.get(pid)
        if ctl and ctl.task and not ctl.task.done():
            def f(p: Project):
                p.run.status = "running"
                p.run.message = "resumed"
            await self.mutate(pid, f)
            ctl.resume.set()
            ctl.wake.set()
            return {"resumed": True}
        p = self.svc.load(pid)
        if p.run.targets:
            return await self.start(pid, "continue" if p.run.mode in ("all", "continue") else "clip", p.run.targets)
        return await self.start(pid, "continue")

    async def stop(self, pid: str) -> None:
        ctl = self.runs.get(pid)
        if ctl:
            ctl.stop = True
            ctl.resume.set()
            ctl.wake.set()

        def f(p: Project):
            p.run.status = "stopping" if ctl and ctl.running else "idle"
            p.run.message = "stopping — finished clips are kept"
        await self.mutate(pid, f)

    async def pick(self, pid: str, nid: str, take_id: str) -> None:
        p = self.svc.load(pid)
        n = find(p, nid)
        if not any(t.id == take_id for t in n.takes):
            raise ValueError("unknown take")
        was_done = n.status == NodeStatus.done and n.chosen_take and n.chosen_take != take_id
        await self._finalize_clip(pid, nid, take_id)
        if was_done:
            await self.mutate(pid, lambda pr: deps_mod.mark_downstream_stale(pr, nid))
        ctl = self.runs.get(pid)
        if ctl:
            ctl.wake.set()

    def recover(self) -> None:
        """After a restart: anything half-made goes back to ready; runs pause."""
        for info in ProjectStore.list():
            try:
                p = self.svc.load(info["id"])
            except Exception:
                continue
            changed = False
            for n in leaves(p):
                if n.status in (NodeStatus.generating, NodeStatus.queued, NodeStatus.waiting):
                    n.status = NodeStatus.ready if not n.takes else NodeStatus.needs_pick
                    changed = True
            if p.run.status in ("running", "stopping"):
                p.run.status = "paused"
                p.run.message = "paused because the app restarted — press Resume"
                changed = True
            if changed:
                ProjectStore.save(p, snapshot=False)

    # ================================================================ scheduler
    async def _run(self, pid: str) -> None:
        ctl = self.runs[pid]
        parallel = max(self.svc.config.max_parallel_jobs, 1)
        try:
            while True:
                if ctl.stop:
                    break
                if not ctl.resume.is_set():
                    if not ctl.running:
                        try:
                            await asyncio.wait_for(ctl.resume.wait(), timeout=2)
                        except asyncio.TimeoutError:
                            p = self.svc.load(pid)
                            if p.run.status == "running":
                                ctl.resume.set()
                            elif p.run.status == "stopping":
                                ctl.stop = True
                        continue
                p = self.svc.load(pid)
                if p.run.status == "paused" and ctl.resume.is_set():
                    ctl.resume.clear()          # paused from another window / terminal
                    continue
                if p.run.status == "stopping":
                    ctl.stop = True
                    continue
                targets = [t for t in p.run.targets if _exists(p, t)]
                pending = [t for t in targets if find(p, t).status != NodeStatus.done]
                if not pending and not ctl.running:
                    break
                runnable = []
                for t in pending:
                    n = find(p, t)
                    if t in ctl.running or n.status in (NodeStatus.generating, NodeStatus.needs_pick, NodeStatus.failed):
                        continue
                    ups = [d for d in deps_mod.upstream(p, t) if d.type != DependencyType.order_only]
                    if all(find(p, d.from_id).status == NodeStatus.done for d in ups):
                        runnable.append(t)
                    elif n.status != NodeStatus.waiting:
                        await self.mutate(pid, lambda pr, t=t: setattr(find(pr, t), "status", NodeStatus.waiting))
                if ctl.resume.is_set():
                    for t in runnable:
                        if len(ctl.running) >= parallel:
                            break
                        n = find(p, t)
                        cost = n.cost.likely_usd
                        p2 = self.svc.load(pid)
                        if p2.run.spent_usd + cost > p2.settings.budget_usd + 1e-6:
                            ctl.resume.clear()

                            def f(pr: Project, cost=cost, t=t):
                                pr.run.status = "paused"
                                pr.run.message = (f"Paused by the budget guard: clip {numbering(pr).get(t, '')} needs ≈${cost:.2f}, "
                                                  f"spent ${pr.run.spent_usd:.2f} of ${pr.settings.budget_usd:.2f}. Raise the budget or press Resume.")
                            await self.mutate(pid, f)
                            break
                        ctl.running[t] = asyncio.create_task(self._make_clip(pid, t))
                if not ctl.running:
                    p = self.svc.load(pid)
                    picks = [t for t in pending if find(p, t).status == NodeStatus.needs_pick]
                    failed = [t for t in pending if find(p, t).status == NodeStatus.failed]
                    if picks:
                        await self.message(pid, f"{len(picks)} clip(s) waiting for you to pick a take")
                        if self.stop_when_waiting:
                            break
                        ctl.wake.clear()
                        await ctl.wake.wait()
                        continue
                    if failed and not runnable:
                        await self.message(pid, f"{len(failed)} clip(s) failed — see the clip for details")
                        break
                    if not runnable and ctl.resume.is_set():
                        await asyncio.sleep(0.5)
                        p = self.svc.load(pid)
                        if all(find(p, t).status in (NodeStatus.done, NodeStatus.failed, NodeStatus.needs_pick)
                               or t in ctl.running for t in pending):
                            continue
                        break
                    continue
                done, _ = await asyncio.wait(list(ctl.running.values()) + [asyncio.create_task(ctl.wake.wait())],
                                             return_when=asyncio.FIRST_COMPLETED, timeout=2)
                ctl.wake.clear()
                for t, task in list(ctl.running.items()):
                    if task.done():
                        del ctl.running[t]
            # end loop
            if ctl.running:
                await asyncio.gather(*ctl.running.values(), return_exceptions=True)
                ctl.running.clear()
            p = self.svc.load(pid)
            all_done = all(n.status == NodeStatus.done for n in leaves(p)) and leaves(p)
            if not ctl.stop and all_done and p.run.mode in ("all", "continue"):
                await self.assemble(pid)
            elif not ctl.stop and all_done:
                await self.message(pid, "All clips are made — press Generate entire video to stitch the final video")

            def fin(pr: Project):
                if ctl.stop:
                    pr.run.status, pr.run.message = "idle", "stopped — finished clips are kept"
                elif pr.run.status != "failed":
                    pr.run.status = "finished" if all_done else "idle"
                    if not pr.run.message or pr.run.message in ("starting", "resumed"):
                        pr.run.message = "done"
            await self.mutate(pid, fin)
        except Exception as exc:  # pragma: no cover - surfaced to UI
            traceback.print_exc()

            def f(pr: Project):
                pr.run.status = "failed"
                pr.run.message = f"run failed: {exc}"
            await self.mutate(pid, f)
        finally:
            self.activity.pop(pid, None)
            self.emit(pid, {"type": "run_finished"})

    # ================================================================ one clip
    async def _make_clip(self, pid: str, nid: str) -> None:
        t0 = time.monotonic()

        def start(p: Project):
            n = find(p, nid)
            n.status = NodeStatus.generating
            p.run.message = f"making clip {numbering(p).get(nid, '')}"
        await self.mutate(pid, start)
        self.emit(pid, {"type": "clip", "node": nid, "status": "generating", "step": "starting"})
        self.step(pid, nid, "Starting", find(self.svc.load(pid), nid).time.likely_s)
        try:
            p = self.svc.load(pid)
            n = find(p, nid)
            if n.kind == NodeKind.slides:
                await self._make_slides(pid, nid)
            elif n.kind == NodeKind.user_clip:
                await self._make_user_clip(pid, nid)
            else:
                if not n.script:
                    await self.svc.write_script(pid, nid)
                await self._check_consent(pid, nid)
                await self._prepare_actors(pid, nid)
                await self._make_voice(pid, nid)
                await self._make_takes(pid, nid)
        except Exception as exc:
            traceback.print_exc()
            msg = str(exc) if isinstance(exc, (PluginError, media.MediaError, ValueError)) else f"{type(exc).__name__}: {exc}"

            def fail(p: Project):
                n = find(p, nid)
                n.status = NodeStatus.failed
                n.warnings = [f"failed: {msg}"] + [w for w in n.warnings if not w.startswith("failed:")]
            await self.mutate(pid, fail)
            self.end_step(pid, nid)
            self.emit(pid, {"type": "clip", "node": nid, "status": "failed", "message": msg})
            return
        self.end_step(pid, nid)
        self.emit(pid, {"type": "clip", "node": nid, "status": "made", "seconds": round(time.monotonic() - t0)})

    async def _check_consent(self, pid: str, nid: str) -> None:
        p = self.svc.load(pid)
        n = find(p, nid)
        used = _actor_ids_in(n)
        for e in effective_context(p, nid):
            c = e.item
            if c.type == ContextType.actor and (c.id in used or not used) and c.needs_consent and not c.consent.confirmed:
                raise ConsentError(f"Consent needed for {c.title}: confirm it is you or that you have permission "
                                   f"(Actors → {c.title} → Consent).")

    # ---------------------------------------------------------------- actors
    async def _prepare_actors(self, pid: str, nid: str) -> None:
        p = self.svc.load(pid)
        n = find(p, nid)
        plan = est.plan_clip(p, n, self.svc.reg)
        used = _actor_ids_in(n)
        actors = [e.item for e in effective_context(p, nid) if e.item.type == ContextType.actor and e.item.id in used]
        if actors:
            self.step(pid, nid, "Preparing actors (picture and voice)", n.time.likely_s)
        # no photo supplied for an animal/object? search for a real one first (free), before generating anything
        wanting = [a.id for a in actors if self.svc.wants_auto_photo(a)] if p.settings.auto_photo else []
        if wanting:
            self.step(pid, nid, "Searching for a real photo", 20)
            await self.svc.auto_photos(pid, only=wanting)
            p = self.svc.load(pid)
            actors = [item_by_id(p, a.id) for a in actors]
        for a in actors:
            if a.actor and not a.actor.reference_sheet:
                await self._reference_sheet(pid, a.id, est.sheet_image(self.svc.reg, p) or plan.image)
            if a.actor and (a.actor.voice_provider != (plan.voice.plugin if plan.voice else None) or not a.actor.voice_id
                            or not a.actor.voice_name):       # a voice with no name was chosen by the old text match: choose it again
                if plan.voice:
                    await self._actor_voice(pid, a.id, plan.voice)

    async def _with_fallback(self, pid: str, first, alternatives, call, kind: str, what: str, cost_of, expected_of,
                             nid: Optional[str] = None, any_error: bool = False):
        """Make something with `first`; if that fails, try `alternatives` (other usable REAL models of the same kind).

        call(entry) does the work and returns its Usage. Only the model that really made it is charged, and the
        ledger and activity bar say so ("used X because Y failed").
        Pictures are cheap, so any error moves on (any_error=True). For video and talking animation only an error
        that means "refused before any work was done" (PluginError.retry_other_model) moves on, because a
        time-out or server error may already have been billed."""
        order = [first] + [e for e in alternatives if e is not None and e.id != first.id and not e.is_free][:2]
        if first.is_free:
            order = [first]
        problems: list[str] = []
        label = {"image": "picture", "avatar": "talking-animation"}.get(kind, kind)
        for i, e in enumerate(order):
            t0 = time.monotonic()
            try:
                usage = await call(e)
            except Exception as exc:
                problems.append(f"{e.id}: {exc}" if isinstance(exc, PluginError) else f"{e.id}: {type(exc).__name__}: {exc}")
                retry = any_error or (isinstance(exc, PluginError) and exc.retry_other_model)
                if retry and i < len(order) - 1:
                    if nid:
                        self.step(pid, nid, f"{e.id} did not work, trying {order[i + 1].id}")
                    continue
                if len(problems) == 1 and not any_error:
                    raise                                           # the vendor's own message, unchanged
                raise PluginError(f"No {label} model worked. " + " | ".join(problems))
            note = f" (used {e.id} because {order[0].id} failed)" if problems else ""
            row = _row(kind, what + note, e, cost_of(e), usage, t0, expected_of(e))
            if problems:
                row["failed_first"] = [x[:300] for x in problems]
            await self.charge(pid, row)
            return e, usage
        raise PluginError(f"No {label} model worked. " + " | ".join(problems))      # (only when `order` is empty)

    async def _make_image(self, pid: str, entry, make_req, what: str, nid: Optional[str] = None):
        """One picture. If the chosen picture model fails, the other usable picture models are tried."""
        reg = self.svc.reg
        p = self.svc.load(pid)
        mode = est.mode_for(p, find(p, nid)) if nid else p.settings.quality_mode        # a clip's picture follows its part's quality

        async def call(e):
            _, usage = await reg.plugin(e.plugin).generate(make_req(e))
            return usage
        return await self._with_fallback(pid, entry, reg.candidates("image", mode=mode), call, "image", what,
                                         cost_of=lambda e: e.unit_price,
                                         expected_of=lambda e: e.time.queue_s + e.time.per_output_s, nid=nid, any_error=True)

    async def _reference_sheet(self, pid: str, cid: str, image_entry) -> None:
        p = self.svc.load(pid)
        a = item_by_id(p, cid)
        out_dir = self.pdir(pid) / "cast" / a.id
        out_dir.mkdir(parents=True, exist_ok=True)
        photos = [self.abs(pid, f) for f in a.files if f.lower().endswith(IMG_EXT)]
        out = out_dir / "sheet.png"
        kind = a.actor.kind if a.actor else "ai_person"
        nonhuman = kind in ("animal", "product")
        if photos and (nonhuman or not image_entry or image_entry.is_free):
            # a photo of an animal/product (uploaded or found by search) is used exactly as it is
            shutil.copy(photos[0], out.with_suffix(photos[0].suffix))
            sheet = out.with_suffix(photos[0].suffix)
        else:
            desc = a.actor.description if a.actor else a.text
            if kind == "animal":
                prompt = (f"Photoreal wildlife portrait of {a.title}: {desc}. Facing the camera, head and upper body, mouth closed and relaxed, "
                          "natural fur/feather texture, soft natural daylight, shallow depth of field, sharp eyes, true-to-life colours.")
            elif kind == "product":
                prompt = (f"Photoreal product reference photo of {a.title}: {desc}. Front view on a clean neutral background, "
                          "soft studio light, sharp focus, true-to-life colours.")
            else:
                prompt = (f"Photoreal character reference portrait of {a.title}: {desc}. Wearing {a.actor.clothing if a.actor else ''}. "
                          "Front view, head and shoulders, even soft studio light, neutral background, natural skin texture with pores, "
                          "sharp focus, true-to-life colours.")
            await self._make_image(pid, image_entry, lambda e: ImageRequest(
                prompt=prompt, out=out, model=e.model, references=photos[:4], aspect="1:1", label=f"{a.title} · reference"),
                f"reference sheet {a.title}")
            sheet = out

        def f(pr: Project):
            item = item_by_id(pr, cid)
            if item.actor:
                item.actor.reference_sheet = [self.rel(pid, sheet)]
        await self.mutate(pid, f)

    async def _actor_voice(self, pid: str, cid: str, voice_entry) -> None:
        p = self.svc.load(pid)
        a = item_by_id(p, cid)
        plugin = self.svc.reg.plugin(voice_entry.plugin)
        vid = None
        sample = self.abs(pid, a.actor.voice_sample) if a.actor and a.actor.voice_sample else None
        if sample and getattr(plugin, "can_clone", False):
            if not a.consent.confirmed:
                raise ConsentError(f"Consent needed before cloning {a.title}'s voice.")
            clean = self.pdir(pid) / "cast" / a.id / "voice_clean.wav"
            clean.parent.mkdir(parents=True, exist_ok=True)
            try:
                media.clean_voice_sample(sample, clean)
            except media.MediaError:
                clean = sample
            vid = await plugin.clone(clean, f"{a.title} ({pid})")
            ProjectStore.ledger_add(pid, {"kind": "voice_clone", "what": a.title, "plugin": voice_entry.plugin,
                                          "estimated_usd": 0, "actual_usd": 0})
            await self._store_voice(pid, cid, voice_entry.plugin, vid, "your cloned voice", "")
            return
        await self._cast_actor(pid, cid, voice_entry)

    async def _store_voice(self, pid: str, cid: str, provider: str, vid: Optional[str], name: str, note: str,
                           alternatives: Optional[list] = None, profile=None) -> None:
        def f(pr: Project):
            item = item_by_id(pr, cid)
            if item.actor:
                item.actor.voice_id = vid
                item.actor.voice_provider = provider
                item.actor.voice_name = name
                item.actor.voice_note = note
                if alternatives is not None:
                    item.analysis["voice_alternatives"] = alternatives
                item.analysis.pop("voice_shift", None)               # a new voice must be measured again
                if profile:                                           # show what was decided, so the user can change it
                    a = item.actor
                    a.voice_gender = a.voice_gender or profile.gender
                    a.voice_age = a.voice_age or profile.age
                    a.voice_pitch = a.voice_pitch or profile.pitch
                    a.voice_pace = a.voice_pace or profile.pace
        await self.mutate(pid, f)

    async def _cast_actor(self, pid: str, cid: str, voice_entry) -> None:
        """Choose this speaker's voice from the planner's profile: gender and age are hard filters, every speaker gets
        a different voice, and the choice is kept for the whole video."""
        p = self.svc.load(pid)
        a = item_by_id(p, cid)
        plugin = self.svc.reg.plugin(voice_entry.plugin)
        profile = casting.profile_for(a, p)
        taken = tuple(c.actor.voice_id for c in p.context
                      if c.id != cid and c.actor and c.actor.voice_id and c.actor.voice_provider == voice_entry.plugin)
        cands, note = await casting.choose_voice(plugin, profile, taken)
        top = cands[0] if cands else None
        label = (top.name + (f" (sample about {top.pitch_hz:.0f} Hz)" if top.pitch_hz else "")) if top else ""
        await self._store_voice(pid, cid, voice_entry.plugin, top.voice_id if top else None, label, note,
                                [vars(c) for c in cands[:6]], profile)

    async def _ensure_narrator(self, pid: str) -> None:
        """A narrator is a speaker like any other: give them an actor card (voice only) so the user can see and edit the voice."""
        p = self.svc.load(pid)
        for c in p.context:
            if c.type == ContextType.actor and c.actor and ("narrat" in c.title.lower() or c.role == ContextRole.voice):
                return

        def f(pr: Project):
            pr.context.append(ContextItem(type=ContextType.actor, title="Narrator", role=ContextRole.voice, scope="project",
                                          actor=ActorDetails(kind="ai_person", description="the voice-over narrator (never seen)",
                                                             voice_description="warm, clear, natural narrator")))
        await self.mutate(pid, f)

    # ---------------------------------------------------------------- voice
    async def _make_voice(self, pid: str, nid: str) -> None:
        p = self.svc.load(pid)
        n = find(p, nid)
        s = n.script
        lines = [(d.speaker, d.text, d.emotion) for d in s.dialogue if d.text.strip()]
        if s.narration.strip():
            lines.append(("narrator", s.narration, ""))
        d = self.cdir(pid, nid)
        if not lines:
            def f(pr: Project):
                nn = find(pr, nid)
                nn.voice_audio, nn.voice_seconds = None, None
            await self.mutate(pid, f)
            return
        plan = est.plan_clip(p, n, self.svc.reg)
        entry = plan.voice
        plugin = self.svc.reg.plugin(entry.plugin)
        if any(sp == "narrator" for sp, _, _ in lines):
            await self._ensure_narrator(pid)
        for sp in {sp for sp, _, _ in lines}:                        # every speaker has a voice chosen from their profile
            item = self._speaker_item(self.svc.load(pid), sp)
            if item and item.actor and not entry.is_free and not (
                    item.actor.voice_id and item.actor.voice_provider == entry.plugin and item.actor.voice_name):
                await self._actor_voice(pid, item.id, entry)
        p = self.svc.load(pid)
        n = find(p, nid)
        voices_now = {sp: (self._speaker_item(p, sp).actor.voice_id if self._speaker_item(p, sp) and self._speaker_item(p, sp).actor else None)
                      for sp in {sp for sp, _, _ in lines}}
        lines_file = d / "voice_lines.json"
        if n.voice_audio and self.abs(pid, n.voice_audio).exists() and n.voice_seconds and lines_file.exists():
            try:
                if json.loads(lines_file.read_text()).get("voices") == voices_now:
                    return                                           # made with these same voices: nothing to do
            except ValueError:
                pass                                                 # (older files have no voice list: make it again)
        self.step(pid, nid, "Making the voice", n.time.likely_s)
        parts, timings, chars = [], [], 0
        t0 = time.monotonic()
        for i, (speaker, text, emotion) in enumerate(lines):
            spec = self._voice_spec(p, speaker, entry.plugin, emotion)
            out = d / f"line_{i:02d}.wav"
            try:
                await plugin.synthesize(text, spec, out, entry.model)
            except PluginError as exc:
                if entry.is_free:
                    raise
                # a voice the vendor refuses (wrong id, no permission): try the speaker's next best voices first
                item = self._speaker_item(p, speaker)
                tried = False
                for alt in ((item.analysis.get("voice_alternatives") or []) if item else []):
                    if alt.get("voice_id") in (None, "", spec.voice_id):
                        continue
                    try:
                        await plugin.synthesize(text, dataclasses.replace(spec, voice_id=alt["voice_id"]), out, entry.model)
                    except PluginError:
                        continue
                    await self._store_voice(pid, item.id, entry.plugin, alt["voice_id"], alt.get("name", ""),
                                            alt.get("note", ""), item.analysis.get("voice_alternatives"), None)
                    tried = True
                    break
                if not tried:
                    # last resort: a free local voice, so the run can continue (and say so)
                    for alt in ("kokoro", "system_voice", "flite"):
                        if self.svc.reg.configured(alt):
                            await self.svc.reg.plugin(alt).synthesize(text, dataclasses.replace(spec, voice_id=None), out)
                            if item:
                                await self._store_voice(pid, item.id, alt, None, f"free {alt} voice",
                                                        f"{entry.id} refused the voice ({str(exc)[:80]}); a free voice was used instead", None, None)
                            break
                    else:
                        raise
                p = self.svc.load(pid)
            out = await self._fit_voice(pid, p, speaker, out)
            parts.append(out)
            timings.append({"speaker": speaker, "text": text, "seconds": round(media.probe_duration(out), 2)})
            chars += len(text)
        voice = d / "voice.wav"
        media.concat_audio(parts, voice, gap=policy_mod.current().line_pause, lead=policy_mod.current().edge_pad)
        secs = media.probe_duration(voice)
        (d / "voice_lines.json").write_text(json.dumps({"lead": policy_mod.current().edge_pad, "gap": policy_mod.current().line_pause, "lines": timings,
                                                         "voices": self._voices_of(self.svc.load(pid), lines)}))
        cost = chars / 1000 * entry.unit_price
        await self.charge(pid, {"kind": "voice", "what": f"voice {numbering(p).get(nid, '')}", "plugin": entry.plugin,
                                "catalog_id": entry.id, "model": entry.model, "units": f"{chars} chars",
                                "estimated_usd": round(cost, 4), "actual_usd": round(cost, 4),
                                "wall_s": round(time.monotonic() - t0, 1),
                                "expected_s": entry.time.queue_s + entry.time.per_output_s * secs})

        def f(pr: Project):
            nn = find(pr, nid)
            nn.voice_audio = self.rel(pid, voice)
            nn.voice_seconds = round(secs, 2)
        await self.mutate(pid, f)
        self.emit(pid, {"type": "clip", "node": nid, "step": "voice ready", "seconds": secs})

    async def _fit_voice(self, pid: str, p: Project, speaker: str, wav: Path) -> Path:
        """Check the finished voice against the speaker's profile (pitch, pace) and correct it a little.
        The first measurable line decides the correction; later lines of the same voice reuse it, so one speaker
        never changes pitch from line to line."""
        item = self._speaker_item(p, speaker)
        prof = casting.profile_for(item, p)
        known = None
        if item:
            saved = item.analysis.get("voice_shift") or {}
            if saved.get("voice_id") == (item.actor.voice_id if item.actor else None) and "semitones" in saved:
                known = float(saved["semitones"])
        out, note, shift = await asyncio.to_thread(casting.fit_voice, wav, prof, known)
        if item and shift is not None and known is None:
            vid = item.actor.voice_id if item.actor else None

            def f(pr: Project):
                it = item_by_id(pr, item.id)
                it.analysis["voice_shift"] = {"voice_id": vid, "semitones": shift}
                if note and it.actor:
                    it.actor.voice_note = (it.actor.voice_note + "; " if it.actor.voice_note else "") + note
            await self.mutate(pid, f)
        return out

    def _voices_of(self, p: Project, lines) -> dict:
        out = {}
        for sp in {sp for sp, _, _ in lines}:
            it = self._speaker_item(p, sp)
            out[sp] = it.actor.voice_id if it and it.actor else None
        return out

    def _speaker_item(self, p: Project, speaker: str) -> Optional[ContextItem]:
        for c in p.context:
            if c.type == ContextType.actor and (c.id == speaker or c.title.lower() == speaker.lower()):
                return c
        if speaker == "narrator":
            for c in p.context:
                if c.type == ContextType.actor and c.actor and ("narrat" in c.title.lower() or c.role == ContextRole.voice):
                    return c
        return None

    def _voice_spec(self, p: Project, speaker: str, plugin: str, emotion: str) -> VoiceSpec:
        actor = self._speaker_item(p, speaker)
        prof = casting.profile_for(actor, p)
        vid = actor.actor.voice_id if actor and actor.actor and actor.actor.voice_provider == plugin else None
        return casting.spec_from(prof, vid, emotion)

    # ---------------------------------------------------------------- takes
    async def compare(self, pid: str, nid: str, model_ids: list[str]) -> None:
        """Make the same clip once with each model, side by side (user picks)."""
        entries = [self.svc.catalog.get(m) for m in model_ids]

        def f(p: Project):
            find(p, nid).status = NodeStatus.generating
        await self.mutate(pid, f)
        try:
            await self._check_consent(pid, nid)
            await self._prepare_actors(pid, nid)
            await self._make_voice(pid, nid)
            await self._make_takes(pid, nid, entries=entries)
        except Exception as exc:
            def fail(p: Project):
                n = find(p, nid)
                n.status = NodeStatus.failed
                n.warnings = [f"compare failed: {exc}"]
            await self.mutate(pid, fail)
            raise

    async def _make_takes(self, pid: str, nid: str, entries: Optional[list] = None) -> None:
        p = self.svc.load(pid)
        n = find(p, nid)
        self.svc.refresh(p)
        n = find(p, nid)
        plan = est.plan_clip(p, n, self.svc.reg)
        seconds = max(n.duration.likely_s, 2.0)
        version = n.version
        d = self.cdir(pid, nid)
        size = media.frame_size(p.settings.aspect, p.settings.resolution if not plan.video or not plan.video.is_free else "720p")
        handoff = await self._handoff_frame(pid, nid)
        end_frame = self._end_frame(p, nid)
        refs = self._references(p, n, plan)
        prompt = build_visual_prompt(p, n)
        label = f"Clip {numbering(p).get(nid, '')} · {n.title}"
        speaker = est.speaking_actor(p, n)
        if plan.route == "avatar" and speaker and speaker.actor and speaker.actor.kind in ("animal", "product"):
            prompt = (f"A talking {speaker.title}: natural mouth movement in sync with the speech, subtle head and eye movement, "
                      f"looking at the camera. {prompt}")
        done_takes = {"n": 0}
        short_notes: list[str] = []
        negative = (n.script.negative + ", " if n.script.negative else "") + "extra fingers, deformed hands, warped face, waxy skin, flicker, text, watermark"
        voice = self.abs(pid, n.voice_audio) if n.voice_audio else None
        sem = asyncio.Semaphore(max(self.svc.config.max_parallel_jobs, 1))

        async def one(i: int) -> Take:
            async with sem:
                ventry = entries[i - 1] if entries else plan.video
                tag = f"v{version}_t{i}" + (f"_{ventry.id}" if entries else "")
                take = Take(version=version, index=i, model=ventry.id if ventry else "")
                raw = d / f"{tag}_raw.mp4"
                if plan.route == "avatar":
                    # the picture that speaks: where the previous clip ended (continuity), else the look this character
                    # already has in the video, else their photo; always fitted to the video's shape
                    photo = handoff or (self._anchor(p, speaker) if speaker else None) or self._actor_photo(p, n)
                    if photo:
                        fitted_photo = d / f"{tag}_speaker.png"
                        media.fit_image(photo, fitted_photo, p.settings.aspect, mode=p.settings.fill if p.settings.fill != "crop" else "cover")
                        photo = fitted_photo
                    audio = voice or media.silence(d / "silence.wav", seconds)
                    nonhuman = bool(speaker and speaker.actor and speaker.actor.kind in ("animal", "product"))
                    alts = self.svc.reg.candidates("avatar", mode=est.mode_for(p, n), need={"non_human": True} if nonhuman else None)

                    async def call_avatar(e, audio=audio, photo=photo, raw=raw):
                        _, u = await self.svc.reg.plugin(e.plugin).generate(
                            AvatarRequest(photo=photo, audio=audio, out=raw, model=e.model,
                                          prompt=prompt[:500], aspect=p.settings.aspect, label=label))
                        return u
                    a_entry, _ = await self._with_fallback(
                        pid, ventry, alts, call_avatar, "avatar", f"avatar {tag}", cost_of=lambda e: seconds * e.unit_price,
                        expected_of=lambda e: e.time.queue_s + e.time.per_output_s * seconds, nid=nid)
                    ventry = a_entry
                    take.model = a_entry.id
                    take.keyframe = self.rel(pid, photo) if photo else None
                    native = True
                else:
                    start = handoff
                    if not start:
                        kf = d / f"{tag}_keyframe.png"
                        compose = f" Compose for a {p.settings.aspect} frame with the subject well inside it and room around."
                        await self._make_image(pid, plan.image, lambda e: ImageRequest(
                            prompt=(prompt + f" (variation {i})" if i > 1 else prompt) + compose, out=kf, model=e.model,
                            references=refs[: int(e.capabilities.get("reference_images", 0) or 0)],
                            aspect=p.settings.aspect, negative=negative, label=label), f"keyframe {tag}", nid)
                        media.fit_image(kf, kf, p.settings.aspect, mode="cover")     # picture models make 3:2; the video is not
                        start = kf
                    take.keyframe = self.rel(pid, start)
                    end_used = end_frame
                    if plan.end_picture and not end_used and plan.image:
                        # the clip should END as planned: make a picture of that ending from the start picture, hand it to
                        # the video model, and the next clip (which continues from here) starts from the same look
                        end_used = d / f"{tag}_end.png"
                        end_prompt = (f"The same scene, subject, place and light as the reference picture. {n.script.end_state.strip()} "
                                      f"Compose for a {p.settings.aspect} frame.")
                        await self._make_image(pid, plan.image, lambda e: ImageRequest(
                            prompt=end_prompt, out=end_used, model=e.model, references=[start],
                            aspect=p.settings.aspect, negative=negative, label=label), f"end picture {tag}", nid)
                        media.fit_image(end_used, end_used, p.settings.aspect, mode="cover")
                    need_v = {"start_frame": True} if start else {}
                    if end_used:
                        need_v["end_frame"] = True
                    v_alts = [e for e in self.svc.reg.candidates("video", n.script.shot_type.value, need_v, est.mode_for(p, n))
                              if float(e.capabilities.get("max_seconds", 10) or 10) >= min(seconds, 8)] if not entries else []
                    ventry = await self._video_parts(pid, ventry, VideoRequest(
                        prompt=prompt, out=raw, model=ventry.model, seconds=seconds, aspect=p.settings.aspect,
                        resolution=p.settings.resolution, start_frame=start, end_frame=end_used,
                        references=refs[: int(ventry.capabilities.get("reference_images", 0) or 0)],
                        negative=negative, audio=bool(ventry.capabilities.get("native_audio")),
                        camera=n.script.camera, label=label, params=dict(ventry.params)), tag, v_alts, nid)
                    take.model = ventry.id
                    native = bool(ventry.capabilities.get("native_audio"))
                # post-process: fit frame, exact length, mix voice + sounds
                fitted = d / f"{tag}_fit.mp4"
                made = media.probe_duration(raw)
                pol = policy_mod.current()
                length = seconds
                if made and made < seconds - pol.length_tolerance_s and pol.on_short == "shorten":
                    length = made                       # keep what the model really made: no frozen tail
                if made and made < seconds - pol.max_freeze_s and pol.on_short == "shorten":
                    short_notes.append(f"Made {made:.1f} s of the {seconds:.1f} s planned: the route that made it cannot make a longer clip. "
                                       "Split the clip so that each part needs one kind of movement, or lengthen what drives it (the speech).")
                media.normalize_clip(raw, fitted, size, p.settings.fps, seconds=length, keep_audio=native, fill=p.settings.fill)
                final = d / f"{tag}.mp4"
                sounds = [(path, 0.5) for path in self._sounds(p, nid)]
                if not entries and est.wants_ambience(p, n, plan):
                    amb = await self._ambience(pid, nid, p, n, fitted, length, d / f"{tag}_amb.wav", tag,
                                               speech=bool(voice) or plan.route == "avatar")
                    if amb:
                        sounds.append((amb, 1.0))                      # already at its policy level
                if plan.route == "avatar":
                    media.replace_audio(fitted, None, final, keep_original=1.0, extra=sounds)
                else:
                    media.replace_audio(fitted, voice, final, keep_original=0.3 if native and voice else (1.0 if native else 0),
                                        extra=sounds)
                for tmp in (raw, fitted):
                    tmp.unlink(missing_ok=True)
                take.video = self.rel(pid, final)
                take.seconds = round(media.probe_duration(final), 2)
                take.cost_usd = round((ventry.unit_price * ventry.billed_seconds(seconds) if ventry else 0)
                                      + (0 if handoff or plan.route == "avatar" or not plan.image else plan.image.unit_price), 4)
                take.quality = self._quality(p, n, final)
                done_takes["n"] += 1
                self.step(pid, nid, f"{done_takes['n']} of {count} take(s) finished" if done_takes["n"] < count else "Finishing takes", n.time.likely_s)
                return take

        count = len(entries) if entries else plan.takes
        what = "talking animation" if plan.route == "avatar" else "picture, then video"
        self.step(pid, nid, f"Making {count} take(s): {what} ({plan.video.id if plan.video else 'free preview'})", n.time.likely_s)
        results = await asyncio.gather(*(one(i) for i in range(1, count + 1)), return_exceptions=True)
        takes = [r for r in results if isinstance(r, Take)]
        errors = [r for r in results if isinstance(r, Exception)]
        if not takes:
            raise errors[0] if errors else PluginError("no takes were made")

        def save_takes(pr: Project):
            nn = find(pr, nid)
            nn.warnings = [w for w in nn.warnings if not w.startswith("Made ")] + list(dict.fromkeys(short_notes))[:1]
            nn.takes = ([t for t in nn.takes if t.version != version] if not entries else nn.takes) + takes
            nn.status = NodeStatus.needs_pick
            nn.duration.basis = EstimateBasis.actual
            if errors:
                nn.warnings.append(f"{len(errors)} take(s) failed: {errors[0]}")
        await self.mutate(pid, save_takes)

        # review each take (suggestions only)
        p = self.svc.load(pid)
        n = find(p, nid)
        if p.settings.review_enabled and n.review_enabled:
            for k, t in enumerate(takes, start=1):
                self.step(pid, nid, f"Review Agent is checking take {k} of {len(takes)}", 30)
                try:
                    await self.reviewer.review_take(pid, nid, t.id)
                except Exception as exc:  # review failure must not lose the takes
                    traceback.print_exc()
                    await self.message(pid, f"review skipped for one take: {exc}")
                    continue

        p = self.svc.load(pid)
        n = find(p, nid)
        if not entries and (len([t for t in n.takes if t.version == version]) == 1 or p.settings.auto_pick):
            best = self._best_take(p, n, version)
            await self._finalize_clip(pid, nid, best.id)

    async def _ambience(self, pid: str, nid: str, p: Project, n: Node, clip: Path, seconds: float, out: Path, tag: str,
                        speech: bool = False) -> Optional[Path]:
        """Natural sound for a clip that has none of its own, from the planner's sound notes. A sound model that fails
        never stops the clip: the next one is tried, and the free local sound is the last resort."""
        reg = self.svc.reg
        notes = (n.script.sound_notes or "").strip() or f"natural ambience that fits: {n.script.visual[:120]}"
        self.step(pid, nid, "Making natural sound", 15)
        real = [e for e in reg.candidates("sfx", mode=est.mode_for(p, n)) if not e.is_free]
        if real:
            async def call(e):
                _, u = await reg.plugin(e.plugin).generate(notes, seconds, out, e.model, clip, dict(e.params))
                return u
            try:
                await self._with_fallback(pid, real[0], real[1:], call, "sfx", f"natural sound {tag}",
                                          cost_of=lambda e: e.unit_price * seconds,
                                          expected_of=lambda e: e.time.queue_s + e.time.per_output_s * seconds, nid=nid, any_error=True)
                return self._level_bed(out, speech)
            except Exception as exc:
                traceback.print_exc()
                await self.message(pid, f"natural sound model failed ({str(exc)[:120]}); a free sound is used instead")
        try:
            local = reg.catalog.get("local_ambience")
            await reg.plugin(local.plugin).generate(notes, seconds, out, local.model)
            return self._level_bed(out, speech)
        except Exception:
            return None

    def _level_bed(self, wav: Path, speech: bool) -> Path:
        """Every made sound, from any model, is brought to the same policy level (under speech, or alone), so the
        sound does not jump in loudness from one clip to the next."""
        pol = policy_mod.current()
        try:
            media.set_loudness(wav, pol.bed_under_speech_lufs if speech else pol.bed_alone_lufs, pol.loudness_tolerance_lu)
        except media.MediaError:
            pass
        return wav

    async def _video_parts(self, pid: str, entry, req: VideoRequest, tag: str, alternatives=(), nid: Optional[str] = None):
        """Make the clip; if it is longer than the model allows, chain parts from each last frame.
        If the chosen model refuses the request, the next usable video model is tried (see _with_fallback).
        Returns the catalogue entry that really made the video."""
        reg = self.svc.reg
        max_s = float(entry.capabilities.get("max_seconds", 10) or 10)
        parts_n = max(1, math.ceil(req.seconds / max_s - 0.05))

        async def make(first, request: VideoRequest, what: str, secs: float):
            async def call(e):
                r = dataclasses.replace(request, model=e.model, params=dict(e.params), audio=bool(e.capabilities.get("native_audio")))
                _, u = await reg.plugin(e.plugin).generate(r)
                return u
            used, _ = await self._with_fallback(
                pid, first, alternatives, call, "video", what, cost_of=lambda e: e.billed_seconds(secs) * e.unit_price,
                expected_of=lambda e: e.time.queue_s + e.time.per_output_s * secs, nid=nid)
            return used

        if parts_n == 1:
            return await make(entry, req, f"video {tag}", req.seconds)
        pieces = []
        start = req.start_frame
        each = req.seconds / parts_n
        current = entry
        for k in range(parts_n):
            piece = req.out.with_name(f"{req.out.stem}_p{k}.mp4")
            sub = VideoRequest(**{**req.__dict__, "out": piece, "seconds": each, "start_frame": start,
                                  "end_frame": req.end_frame if k == parts_n - 1 else None})
            current = await make(current, sub, f"video {tag} part {k + 1}", each)
            pieces.append(piece)
            start = media.last_frame(piece, piece.with_suffix(".last.png"))
        media.join_clips(pieces, ["cut"] * len(pieces), req.out, (0, 0), 24)
        return current

    async def _handoff_frame(self, pid: str, nid: str) -> Optional[Path]:
        p = self.svc.load(pid)
        for dep in deps_mod.upstream(p, nid):
            if dep.type == DependencyType.continues_from:
                up = find(p, dep.from_id)
                chosen = next((t for t in up.takes if t.id == up.chosen_take), None)
                try:
                    if chosen and self.svc.catalog.get(chosen.model).is_free:
                        continue        # a placeholder card is not a real last frame
                except KeyError:
                    pass
                src = self.abs(pid, up.output) if up.output else None
                if src and src.exists():
                    frame = self.cdir(pid, nid) / f"handoff_from_{up.id}.png"
                    media.last_frame(src, frame)

                    def f(pr: Project, dep_id=dep.id, frame=frame):
                        for d in pr.dependencies:
                            if d.id == dep_id:
                                d.payload["handoff_frame"] = self.rel(pid, frame)
                    await self.mutate(pid, f)
                    return frame
        return None

    def _end_frame(self, p: Project, nid: str) -> Optional[Path]:
        for e in effective_context(p, nid):
            if e.item.role == ContextRole.end_frame and e.origin == "this":
                for f in e.item.files:
                    if f.lower().endswith(IMG_EXT):
                        return self.abs(p.id, f)
        return None

    def _references(self, p: Project, n: Node, plan) -> list[Path]:
        """Actors first, then must-appear items, then look references, then locations."""
        used = _actor_ids_in(n)
        eff = effective_context(p, n.id)
        out: list[Path] = []
        for e in eff:
            c = e.item
            if c.type == ContextType.actor and c.id in used and c.actor:
                anchor = self._anchor(p, c)
                if anchor:
                    out.append(anchor)               # the look this character already has in the video comes first
                for f in (c.actor.reference_sheet or c.files)[:2]:
                    if f.lower().endswith(IMG_EXT):
                        out.append(self.abs(p.id, f))
        out += self._scene_frames(p, n)
        for role in (ContextRole.must_appear, ContextRole.start_frame, ContextRole.look_reference):
            for e in eff:
                c = e.item
                if c.role == role and c.type != ContextType.actor:
                    out += [self.abs(p.id, f) for f in c.files if f.lower().endswith(IMG_EXT)]
        seen, uniq = set(), []
        for x in out:
            if x and x.exists() and str(x) not in seen:
                seen.add(str(x))
                uniq.append(x)
        return uniq

    def _clip_sharpness(self, video: Path) -> Optional[float]:
        tmp = Path(tempfile.mkdtemp()) / "mid.png"
        try:
            media.extract_frame(video, tmp, at=max(media.probe_duration(video) * 0.4, 0.0))
            return media.image_sharpness(tmp)
        except media.MediaError:
            return None
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)

    async def _match_neighbours(self, pid: str, nid: str) -> None:
        """A clip next to one of the SAME shot or scene (linked 'continues from' or 'same location') that is clearly softer
        gets a mild finishing pass, so the cut does not show a change of quality. The threshold is policy.min_sharpness_ratio."""
        pol = policy_mod.current()
        p = self.svc.load(pid)
        n = find(p, nid)
        if not n.output:
            return
        for dep in deps_mod.upstream(p, nid) + deps_mod.downstream(p, nid):
            if dep.type not in (DependencyType.continues_from, DependencyType.same_location):
                continue
            other = find(p, dep.from_id if dep.to_id == nid else dep.to_id)
            if not other.output or other.status != NodeStatus.done:
                continue
            a, b = self.abs(pid, n.output), self.abs(pid, other.output)
            sa, sb = await asyncio.to_thread(self._clip_sharpness, a), await asyncio.to_thread(self._clip_sharpness, b)
            if not sa or not sb:
                continue
            soft, soft_node, ratio = (n, a, sa / sb) if sa < sb else (other, b, sb / sa)
            if ratio >= pol.min_sharpness_ratio or any(w.startswith("Softer than") for w in soft.warnings):
                continue
            finished = soft_node.with_name(soft_node.stem + "_finish.mp4")
            await asyncio.to_thread(media.finish_clip, soft_node, finished, pol.finish_sharpen, pol.finish_grain)

            def f(pr: Project, sid=soft.id, ratio=ratio, finished=finished):
                x = find(pr, sid)
                x.output = self.rel(pid, finished)
                x.warnings = list(x.warnings) + [f"Softer than the clip next to it (sharpness {ratio:.2f}x): a mild finishing pass was applied so the cut is not visible."]
            await self.mutate(pid, f)
            break

    def _anchor(self, p: Project, c: ContextItem) -> Optional[Path]:
        """The frame where this character first appeared in a made clip. It keeps their look the same in every later
        scene, unless the user supplied their own photo (then the photo stays the truth)."""
        rel = c.analysis.get("anchor")
        user_photo = bool(c.files) and not c.analysis.get("auto_photo")
        if rel and not user_photo:
            path = self.abs(p.id, rel)
            if path and path.exists():
                return path
        return None

    def _scene_frames(self, p: Project, n: Node) -> list[Path]:
        """Frames of earlier clips of the SAME scene (planned as 'same location'), so a new angle keeps the place,
        light and props. Clips that continue a shot use the hand-off frame instead; new scenes carry only the actors."""
        out: list[Path] = []
        for dep in deps_mod.upstream(p, n.id):
            if dep.type == DependencyType.same_location:
                up = find(p, dep.from_id)
                src = self.abs(p.id, up.output) if up.output else None
                if src and src.exists():
                    frame = self.cdir(p.id, n.id) / f"scene_from_{up.id}.png"
                    try:
                        media.last_frame(src, frame)
                        out.append(frame)
                    except media.MediaError:
                        pass
        return out

    async def _remember_anchor(self, pid: str, nid: str, video: Path) -> None:
        """When a character appears alone in a finished clip for the first time, keep a frame of them as the anchor
        for their look in all later clips."""
        p = self.svc.load(pid)
        n = find(p, nid)
        if not n.script or len(_actor_ids_in(n)) != 1:
            return
        cid = next(iter(_actor_ids_in(n)))
        item = next((c for c in p.context if c.id == cid and c.type == ContextType.actor and c.actor), None)
        if not item or item.analysis.get("anchor") or (item.actor and item.actor.kind in ("real_person", "digital_twin")):
            return                                       # real people always keep their own photos
        dst = self.pdir(pid) / "cast" / cid / "anchor.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            media.extract_frame(video, dst, at=max(media.probe_duration(video) * 0.4, 0.0))
        except media.MediaError:
            return

        def f(pr: Project):
            it = item_by_id(pr, cid)
            it.analysis["anchor"] = self.rel(pid, dst)
        await self.mutate(pid, f)

    def _actor_photo(self, p: Project, n: Node) -> Optional[Path]:
        used = _actor_ids_in(n)
        for e in effective_context(p, n.id):
            c = e.item
            if c.type == ContextType.actor and c.id in used and c.actor:
                files = [f for f in c.files if f.lower().endswith(IMG_EXT)] or c.actor.reference_sheet
                if files:
                    return self.abs(p.id, files[0])
        return None

    def _sounds(self, p: Project, nid: str) -> list[Path]:
        out = []
        for e in effective_context(p, nid):
            if e.item.role == ContextRole.sound and e.origin == "this":
                out += [self.abs(p.id, f) for f in e.item.files if Path(f).suffix.lower() in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")]
        return [x for x in out if x and x.exists()]

    def _quality(self, p: Project, n: Node, video: Path) -> dict:
        q: dict = {}
        for name in ("flicker", "face_similarity"):
            if self.svc.reg.configured(name):
                try:
                    refs = []
                    if name == "face_similarity":
                        for e in effective_context(p, n.id):
                            c = e.item
                            if c.type == ContextType.actor and c.id in _actor_ids_in(n):
                                refs += [self.abs(p.id, f) for f in c.files if f.lower().endswith(IMG_EXT)]
                        if not refs:
                            continue
                    q.update(self.svc.reg.plugin(name).score(video, refs))
                except Exception:
                    continue
        return q

    def _best_take(self, p: Project, n: Node, version: int) -> Take:
        takes = [t for t in n.takes if t.version == version] or n.takes
        reviews = {r.id: r for r in p.reviews}

        def score(t: Take) -> float:
            s = 0.0
            r = reviews.get(t.review_id or "")
            checked = [v for v in (r.scores.values() if r else []) if v > 0]      # 0 = not checked
            if checked:
                s += sum(checked) / len(checked) + 0.5 * min(r.scores.get("motion", 0) or 3, r.scores.get("realism", 0) or 3)
            s -= t.quality.get("flicker", 0) * 10
            s += t.quality.get("face_similarity", 0) * 2
            return s
        return max(takes, key=score)

    async def _finalize_clip(self, pid: str, nid: str, take_id: str) -> None:
        p = self.svc.load(pid)
        n = find(p, nid)
        take = next(t for t in n.takes if t.id == take_id)
        src = self.abs(pid, take.video)
        out = src
        plan = est.plan_clip(p, n, self.svc.reg)
        if plan.lipsync_needed and plan.lipsync and n.voice_audio and plan.route == "video":
            synced = self.cdir(pid, nid) / f"{Path(take.video).stem}_lipsync.mp4"
            t0 = time.monotonic()
            self.step(pid, nid, "Matching the lips to the voice (lip-sync)", plan.lipsync.time.queue_s + plan.lipsync.time.per_output_s * take.seconds)
            try:
                _, usage = await self.svc.reg.plugin(plan.lipsync.plugin).sync(src, self.abs(pid, n.voice_audio), synced,
                                                                                plan.lipsync.model)
                fixed = synced.with_name(synced.stem + "_fit.mp4")
                size = media.frame_size(p.settings.aspect, p.settings.resolution)
                media.normalize_clip(synced, fixed, size, p.settings.fps, seconds=take.seconds, fill=p.settings.fill)
                out = fixed
                await self.charge(pid, _row("lipsync", f"lip-sync {nid}", plan.lipsync, take.seconds * plan.lipsync.unit_price,
                                            usage, t0, plan.lipsync.time.queue_s + plan.lipsync.time.per_output_s * take.seconds))
            except PluginError as exc:
                await self.message(pid, f"lip-sync skipped: {exc}")

        def f(pr: Project):
            nn = find(pr, nid)
            nn.chosen_take = take_id
            nn.output = self.rel(pid, out)
            nn.status = NodeStatus.done
            ledger = ProjectStore.ledger(pid)
            nn.cost.actual_usd = round(sum(r.get("actual_usd", 0) for r in ledger
                                           if nid in r.get("what", "") or r.get("node") == nid), 4) or take.cost_usd
        await self.mutate(pid, f, snapshot=True)
        try:
            real = bool(take.model) and not self.svc.catalog.get(take.model).is_free
            if real:
                await self._remember_anchor(pid, nid, out)
                await self._match_neighbours(pid, nid)
        except Exception:                               # the anchor and the matching are bonuses: never fail a finished clip
            traceback.print_exc()
        self.emit(pid, {"type": "clip", "node": nid, "status": "done"})

    # ---------------------------------------------------------------- slides & user clips
    async def _make_slides(self, pid: str, nid: str) -> None:
        p = self.svc.load(pid)
        n = find(p, nid)
        d = self.cdir(pid, nid)
        src = self.abs(pid, n.media)
        if not src or not src.exists():
            raise ValueError("the slides file is missing")
        if src.suffix.lower() in (".pptx", ".ppt", ".key"):
            src = media.office_to_pdf(src, d)
        images = media.pdf_to_images(src, d / "slides")
        size = media.frame_size(p.settings.aspect, p.settings.resolution)
        if n.script and n.script.narration:
            await self._make_voice(pid, nid)
            p = self.svc.load(pid)
            n = find(p, nid)
        per = float(n.style_overrides.get("seconds_per_slide", est.SECONDS_PER_SLIDE))
        total = max(per * len(images), n.voice_seconds or 0)
        each = total / max(len(images), 1)
        clips = []
        for i, img in enumerate(images):
            c = d / f"slide_{i:03d}.mp4"
            media.still_to_clip(img, c, each, size, p.settings.fps, zoom=False)
            clips.append(c)
        joined = d / "slides_joined.mp4"
        media.join_clips(clips, ["crossfade"] * len(clips), joined, size, p.settings.fps, tdur=0.4)
        out = d / "slides.mp4"
        voice = self.abs(pid, n.voice_audio) if n.voice_audio else None
        media.replace_audio(joined, voice, out, keep_original=0)
        take = Take(version=n.version, index=1, video=self.rel(pid, out), model="slides",
                    seconds=round(media.probe_duration(out), 2))

        def f(pr: Project):
            nn = find(pr, nid)
            nn.takes = [take]
            nn.duration.basis = EstimateBasis.actual
        await self.mutate(pid, f)
        await self._finalize_clip(pid, nid, take.id)

    async def _make_user_clip(self, pid: str, nid: str) -> None:
        p = self.svc.load(pid)
        n = find(p, nid)
        src = self.abs(pid, n.media)
        if not src or not src.exists():
            raise ValueError("your video file is missing")
        d = self.cdir(pid, nid)
        size = media.frame_size(p.settings.aspect, p.settings.resolution)
        out = d / "user_clip.mp4"
        media.normalize_clip(src, out, size, p.settings.fps)
        take = Take(version=n.version, index=1, video=self.rel(pid, out), model="your clip",
                    seconds=round(media.probe_duration(out), 2))

        def f(pr: Project):
            nn = find(pr, nid)
            nn.takes = [take]
        await self.mutate(pid, f)
        await self._finalize_clip(pid, nid, take.id)

    # ================================================================ assembly
    async def assemble(self, pid: str, music: str = "auto") -> Optional[str]:
        """Join the finished clips into the final video (transitions, music, subtitles, export).
        music: auto = reuse the saved track while it still fits, else make one | reuse = only the saved track |
        new = make a new track | none = no music this time."""
        self.step(pid, "final", "Joining the clips into one video", 30)
        try:
            return await self._assemble(pid, music)
        finally:
            self.end_step(pid, "final")
            self.emit(pid, {"type": "project"})

    def _join_node(self, pid: str, node: Node, size: tuple[int, int], fps: int) -> Path:
        """Join everything under a node into ONE video file, bottom up, each part with its own transitions (blocking: run in a thread)."""
        if node.is_leaf:
            return self.abs(pid, node.output)
        kids = [self._join_node(pid, c, size, fps) for c in node.children]
        out = self.cdir(pid, node.id) / "part.mp4"
        trans = [c.transition_in for c in node.children]
        fitted = []
        for i, k in enumerate(kids):
            f = self.cdir(pid, node.id) / f"in_{i:02d}.mp4"
            media.normalize_clip(k, f, size, fps)
            fitted.append(f)
        media.join_clips(fitted, trans, out, size, fps)
        for f in fitted:
            f.unlink(missing_ok=True)
        return out

    async def _assemble(self, pid: str, music: str = "auto") -> Optional[str]:
        p = self.svc.load(pid)
        if not all(n.status == NodeStatus.done for n in leaves(p)):
            await self.message(pid, "Some clips are not made yet")
            return None
        await self.message(pid, "stitching the final video")
        size = media.frame_size(p.settings.aspect, p.settings.resolution)
        fps = p.settings.fps

        root_out = await asyncio.to_thread(self._join_node, pid, p.root, size, fps)

        def mark_parts(pr: Project):
            for n, _ in walk(pr.root):
                if not n.is_leaf:
                    part = self.pdir(pid) / "clips" / n.id / "part.mp4"
                    if part.exists():
                        n.output = self.rel(pid, part)
                        n.status = NodeStatus.done
        await self.mutate(pid, mark_parts)

        out_dir = self.pdir(pid) / "output"
        out_dir.mkdir(exist_ok=True)
        total = media.probe_duration(root_out)
        current = root_out
        p = self.svc.load(pid)
        notes: list[str] = []
        if p.settings.music and music != "none":
            self.step(pid, "final", "Making and mixing the background music", 30)
            try:
                track = await self._ensure_music(pid, total, music)
                if track:
                    with_music = out_dir / "with_music.mp4"
                    media.add_music(current, track, with_music)
                    current = with_music
            except Exception as exc:
                traceback.print_exc()
                why = str(exc)
                await self.message(pid, f"music skipped: {why[:200]}")
                notes.append(f"Background music was not added. {why[:400]}")
        p.final_notes = notes
        self.step(pid, "final", "Adding subtitles and exporting the file", 20)
        # subtitles
        srt = out_dir / "final.srt"
        media.write_srt(self._subtitle_entries(p), srt)
        final = out_dir / f"final.{p.settings.format}"
        media.to_format(current, final, p.settings.format)
        try:
            media.proxy(final, out_dir / "preview.mp4")
        except media.MediaError:
            pass

        self._write_credits(p, out_dir)

        def done(pr: Project):
            pr.final_output = self.rel(pid, final)
            pr.final_hash = ProjectStore.final_signature(pr)
            pr.final_notes = notes
            pr.run.message = f"Final video ready ({total:.0f} s)"
        await self.mutate(pid, done, snapshot=True)
        self.emit(pid, {"type": "final", "path": self.rel(pid, final)})
        p = self.svc.load(pid)
        if p.settings.review_enabled:
            for n, _ in walk(p.root):
                if n.is_leaf or n.id == p.root.id or sum(1 for _c in walk(n) if _c[0].is_leaf) < 2 or not n.output:
                    continue                                       # one clip alone was already reviewed take by take
                self.step(pid, "final", f"Review Agent is checking part {numbering(p).get(n.id, '')}: {n.title}", 30)
                try:
                    await self.reviewer.review_node(pid, n.id, self.abs(pid, n.output))
                except Exception:
                    traceback.print_exc()
            self.step(pid, "final", "Review Agent is checking the whole video", 40)
            try:
                await self.reviewer.review_node(pid, p.root.id, final)
            except Exception:
                traceback.print_exc()
        return str(final)

    async def _ensure_music(self, pid: str, total: float, mode: str = "auto") -> Optional[Path]:
        """The background music for the WHOLE video. It is made once and saved (see musictrack), so joining again and every
        downloaded part reuse it. mode: auto = reuse the saved track while it still fits, else make one | reuse = the saved
        track whatever its age (None when there is none) | new = make a new track now."""
        p = self.svc.load(pid)
        reg = self.svc.reg
        qmode = p.settings.quality_mode
        saved = musictrack.status(p, total, any(not e.is_free and reg.entry_usable(e) for e in reg.catalog.for_job("music")))
        if mode == "reuse":
            return musictrack.path(pid) if saved["exists"] else None
        if mode == "auto" and saved["reusable"]:
            return musictrack.path(pid)
        out_dir = musictrack.folder(pid)
        out_dir.mkdir(parents=True, exist_ok=True)
        ref = musictrack.reference(p)
        mood = musictrack.mood_for(p)
        music = out_dir / "music.mp3"
        first = reg.choose("music", mode=qmode)
        rest = reg.candidates("music", mode=qmode)

        async def call_music(e):
            target = music.with_suffix(".wav") if e.is_free else music
            _, u = await reg.plugin(e.plugin).generate(mood, total, target, e.model, ref)
            return u
        used, _ = await self._with_fallback(
            pid, first, rest, call_music, "music", "music bed",
            cost_of=lambda e: musictrack.cost(e, total),
            expected_of=lambda e: e.time.queue_s + e.time.per_output_s * total, nid="final", any_error=True)
        made = music.with_suffix(".wav") if used.is_free else music
        (music if used.is_free else music.with_suffix(".wav")).unlink(missing_ok=True)       # only ONE saved track
        musictrack.save(self.svc.load(pid), made, total, used.id, used.is_free, musictrack.cost(used, total))
        return made

    def _timeline_starts(self, p: Project) -> dict[str, float]:
        """Where each clip starts in the joined whole video (seconds), allowing for the overlap of its transition."""
        starts: dict[str, float] = {}
        t = 0.0
        for i, leaf in enumerate(leaves(p)):
            if i and leaf.transition_in not in ("cut", "", None):
                t = max(t - 0.5, 0.0)
            starts[leaf.id] = t
            out = self.abs(p.id, leaf.output)
            t += media.probe_duration(out) if out and out.exists() else leaf.duration.likely_s
        return starts

    async def export_node(self, pid: str, nid: str, music: str = "auto") -> dict:
        """A finished video of ONE clip or part, ready to download. A clip is its finished file. A part is its clips joined with
        their transitions, with the SAME music as the final video (a free slice of the saved track) and a subtitle file.
        music: auto = use the saved track if there is one; if there is none and a new one would cost money, answer
        {needs_music_choice} and spend nothing | new = make the music for the whole video now (every part and the final video then
        reuse it) | none = no music."""
        p = self.svc.load(pid)
        self.svc.refresh(p)
        n = find(p, nid)
        nums = numbering(p)
        below = [x for x, _ in walk(n) if x.is_leaf]
        missing = [x for x in below if x.status != NodeStatus.done or not (x.output and self.abs(pid, x.output) and self.abs(pid, x.output).exists())]
        if missing:
            raise ValueError(f"{len(missing)} of {len(below)} clip(s) are still to make, so this {'clip' if n.is_leaf else 'part'} cannot be "
                             "downloaded yet.")
        fmt = p.settings.format
        label = "-".join(x for x in (slug(p.name), (nums.get(nid) or "video").replace(".", "-"), slug(n.title or n.goal)) if x)[:90]
        result = {"filename": f"{label}.{fmt}", "srt": None, "srt_filename": f"{label}.srt", "with_music": False, "notes": []}
        parts_dir = self.pdir(pid) / "output" / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)

        def stamp(x: Node) -> str:
            f = self.abs(pid, x.output)
            return f"{x.id}:{x.output}:{f.stat().st_mtime_ns}:{f.stat().st_size}:{x.transition_in}"

        if n.id == p.root.id and p.final_output and ProjectStore.final_signature(p) == p.final_hash and self.abs(pid, p.final_output).exists():
            return {**result, "path": p.final_output, "srt": self.rel(pid, self.pdir(pid) / "output" / "final.srt")
                    if (self.pdir(pid) / "output" / "final.srt").exists() else None, "with_music": bool(p.settings.music),
                    "seconds": round(media.probe_duration(self.abs(pid, p.final_output)), 1)}

        track: Optional[Path] = None
        if not n.is_leaf and p.settings.music and music != "none":
            track = musictrack.path(pid)
            if not track:
                total_est = p.root.duration.likely_s
                try:
                    entry = self.svc.reg.choose("music", mode=p.settings.quality_mode)
                except LookupError:
                    entry = None
                price = musictrack.cost(entry, total_est)
                if entry and price > 0 and music != "new":
                    return {"needs_music_choice": True, "cost_usd": round(price, 2), "model": entry.id, "seconds": round(total_est, 1)}
                if entry:
                    self.step(pid, nid, "Making the background music (kept for every part and the final video)", 30)
                    try:
                        track = await self._ensure_music(pid, total_est, "new")
                    finally:
                        self.end_step(pid, nid)
            else:
                saved = musictrack.status(p, p.root.duration.likely_s, False)
                if not saved["reusable"] and saved["why"]:
                    result["notes"].append(f"The music is from the saved track ({saved['why']}).")
        track_stamp = f"{track.name}:{track.stat().st_mtime_ns}" if track else "no-music"
        sig = hashlib.sha1(("|".join(stamp(x) for x in below) + f"|{fmt}|{track_stamp}|{n.is_leaf}").encode()).hexdigest()[:12]
        out = parts_dir / f"{nid}_{sig}.{fmt}"
        srt = parts_dir / f"{nid}_{sig}.srt"
        size = media.frame_size(p.settings.aspect, p.settings.resolution)
        starts = self._timeline_starts(p)
        entries = self._subtitle_entries(p, below)

        def build() -> float:
            if not out.exists():
                if n.is_leaf:
                    current = self.abs(pid, n.output)
                else:
                    current = self._join_node(pid, n, size, p.settings.fps)
                    if track:
                        length = media.probe_duration(current)
                        piece = parts_dir / f"{nid}_music.wav"
                        media.music_slice(track, piece, starts.get(below[0].id, 0.0), length, policy_mod.current().music_part_fade_s)
                        mixed = parts_dir / f"{nid}_with_music.mp4"
                        media.add_music(current, piece, mixed)
                        current = mixed
                media.to_format(current, out, fmt)
            if entries:
                media.write_srt(entries, srt)                  # times are counted from 0 at the first clip of this part
            return media.probe_duration(out)

        self.step(pid, nid, "Joining the clips of this part" if not n.is_leaf else "Preparing this clip for download", 20)
        try:
            seconds = await asyncio.to_thread(build)
        finally:
            self.end_step(pid, nid)
        return {**result, "path": self.rel(pid, out), "srt": self.rel(pid, srt) if entries else None, "with_music": bool(track),
                "seconds": round(seconds, 1)}

    def _write_credits(self, p: Project, out_dir: Path) -> None:
        """Credits for stock photos the user chose (many licences require attribution)."""
        lines = []
        for c in p.context:
            for cr in c.analysis.get("credits", []):
                lines.append(f"{c.title}: \"{cr.get('title', '')}\" by {cr.get('author', 'unknown')} — {cr.get('license', '')} — {cr.get('source_url', '')}")
        path = out_dir / "credits.txt"
        if lines:
            path.write_text("Photo credits\n\n" + "\n".join(lines) + "\n")
        elif path.exists():
            path.unlink()

    def _subtitle_entries(self, p: Project, only: Optional[list[Node]] = None) -> list[tuple[float, float, str]]:
        """Subtitle lines with their times. `only` = just these clips (a part), counted from 0 at the first of them."""
        entries = []
        offset = 0.0
        for leaf in (only if only is not None else leaves(p)):
            out = self.abs(p.id, leaf.output)
            dur = media.probe_duration(out) if out and out.exists() else leaf.duration.likely_s
            meta = self.cdir(p.id, leaf.id) / "voice_lines.json"
            if meta.exists():
                data = json.loads(meta.read_text())
                t = offset + data.get("lead", 0.5)
                for line in data["lines"]:
                    entries.append((t, t + line["seconds"], line["text"]))
                    t += line["seconds"] + data.get("gap", 0.6)
            offset += dur - (0.5 if leaf.transition_in not in ("cut", "", None) else 0)
        return entries


# ===================================================================== helpers
def _exists(p: Project, nid: str) -> bool:
    try:
        find(p, nid)
        return True
    except KeyError:
        return False


def _actor_ids_in(n: Node) -> set[str]:
    if not n.script:
        return set()
    return {a.actor_id for a in n.script.actors_in_shot} | {d.speaker for d in n.script.dialogue if d.speaker != "narrator"}


def _row(kind: str, what: str, entry, cost: float, usage: Usage, t0: float, expected_s: float) -> dict:
    actual = usage.cost_usd if usage.cost_usd else cost
    return {"kind": kind, "what": what, "plugin": entry.plugin, "catalog_id": entry.id, "model": entry.model,
            "rate": f"at ${entry.unit_price}/{entry.price.unit.replace('_', ' ')}",
            "estimated_usd": round(cost, 4), "actual_usd": round(actual, 4),
            "wall_s": round(time.monotonic() - t0, 1), "expected_s": round(expected_s, 1)}


def build_visual_prompt(p: Project, n: Node) -> str:
    s = n.script
    style = effective_style(p, n.id)
    parts = [s.visual.strip()]
    if s.start_state.strip():
        parts.append(f"The clip begins as: {s.start_state.strip()}")
    used = _actor_ids_in(n)
    shot_actor = {a.actor_id: a for a in s.actors_in_shot}
    for e in effective_context(p, n.id):
        c = e.item
        if c.type == ContextType.actor and c.id in used and c.actor:
            a = c.actor
            clothing = (shot_actor.get(c.id).clothing if shot_actor.get(c.id) and shot_actor[c.id].clothing else a.clothing)
            behaviour = (shot_actor.get(c.id).behaviour if shot_actor.get(c.id) and shot_actor[c.id].behaviour else a.behaviour)
            parts.append(f"{c.title}: {a.description}" + (f", wearing {clothing}" if clothing else "")
                         + (f", {behaviour}" if behaviour else ""))
        elif c.role == ContextRole.must_appear and c.type != ContextType.actor and (c.text or c.title):
            parts.append(f"Must show: {c.title}{(' — ' + c.text) if c.text else ''}")
        elif c.type == ContextType.location and (c.text or c.title):
            parts.append(f"Location: {c.title}{(' — ' + c.text) if c.text else ''}")
        elif c.role == ContextRole.look_reference and c.text:
            parts.append(f"Look: {c.text}")
    if s.action_beats:
        parts.append("Action: " + "; then ".join(s.action_beats))
    if s.end_state.strip():
        parts.append(f"The clip ends as: {s.end_state.strip()}")
    if s.camera:
        parts.append(f"Camera: {s.camera}")
    if style:
        parts.append("Style: " + ", ".join(f"{k} {v}" for k, v in style.items() if k in ("look", "colour", "mood", "notes")))
    if est.is_people_shot(n):
        parts.append("Real people: photoreal, natural skin texture with pores, anatomically correct hands with five fingers, "
                     "natural believable motion, consistent faces")
    return ". ".join(x.rstrip(". ") for x in parts if x) + "."
