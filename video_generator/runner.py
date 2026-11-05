"""Generation engine: makes clips in dependency order, takes, review, picks,
assembly. One background run per project; state is saved after each step,
so `resume` continues after a restart."""
from __future__ import annotations

import asyncio
import json
import math
import shutil
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import deps as deps_mod
from . import estimate as est
from . import media
from .context import effective_context, item_by_id
from .models import (ContextItem, ContextRole, ContextType, DependencyType, EstimateBasis, Node, NodeKind,
                     NodeStatus, Project, ShotType, Take, now_iso)
from .plugins.base import (AvatarRequest, ImageRequest, PluginError, Usage, VideoRequest, VoiceSpec)
from .project import ProjectStore
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
            for nid in chosen:
                n = find(pr, nid)
                if n.status == NodeStatus.failed:
                    n.status = NodeStatus.ready
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
        for a in actors:
            if a.actor and not a.actor.reference_sheet:
                await self._reference_sheet(pid, a.id, plan.image)
            if a.actor and (a.actor.voice_provider != (plan.voice.plugin if plan.voice else None) or not a.actor.voice_id):
                if plan.voice:
                    await self._actor_voice(pid, a.id, plan.voice)

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
            plugin = self.svc.reg.plugin(image_entry.plugin)
            t0 = time.monotonic()
            _, usage = await plugin.generate(ImageRequest(prompt=prompt, out=out, model=image_entry.model,
                                                          references=photos[:4], aspect="1:1", label=f"{a.title} · reference"))
            await self.charge(pid, _row("image", f"reference sheet {a.title}", image_entry, image_entry.unit_price,
                                        usage, t0, image_entry.time.queue_s + image_entry.time.per_output_s))
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
        else:
            desc = (a.actor.voice_description if a.actor else "") or (a.actor.description if a.actor else "")
            vid = await plugin.match(desc)

        def f(pr: Project):
            item = item_by_id(pr, cid)
            if item.actor:
                item.actor.voice_id = vid
                item.actor.voice_provider = voice_entry.plugin
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
        if n.voice_audio and self.abs(pid, n.voice_audio).exists() and n.voice_seconds:
            return
        self.step(pid, nid, "Making the voice", n.time.likely_s)
        plan = est.plan_clip(p, n, self.svc.reg)
        entry = plan.voice
        plugin = self.svc.reg.plugin(entry.plugin)
        parts, timings, chars = [], [], 0
        t0 = time.monotonic()
        for i, (speaker, text, emotion) in enumerate(lines):
            spec = self._voice_spec(p, speaker, entry.plugin, emotion)
            out = d / f"line_{i:02d}.wav"
            try:
                await plugin.synthesize(text, spec, out, entry.model)
            except PluginError:
                if entry.is_free:
                    raise
                # fall back to a free local voice so the run can continue
                for alt in ("kokoro", "system_voice", "flite"):
                    if self.svc.reg.configured(alt):
                        await self.svc.reg.plugin(alt).synthesize(text, VoiceSpec(description=spec.description), out)
                        break
                else:
                    raise
            parts.append(out)
            timings.append({"speaker": speaker, "text": text, "seconds": round(media.probe_duration(out), 2)})
            chars += len(text)
        voice = d / "voice.wav"
        media.concat_audio(parts, voice, gap=est.LINE_PAUSE, lead=est.EDGE_PAD)
        secs = media.probe_duration(voice)
        (d / "voice_lines.json").write_text(json.dumps({"lead": est.EDGE_PAD, "gap": est.LINE_PAUSE, "lines": timings}))
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

    def _voice_spec(self, p: Project, speaker: str, plugin: str, emotion: str) -> VoiceSpec:
        actor: Optional[ContextItem] = None
        for c in p.context:
            if c.type == ContextType.actor and (c.id == speaker or c.title.lower() == speaker.lower()):
                actor = c
        if not actor and speaker == "narrator":
            for c in p.context:
                if c.type == ContextType.actor and c.actor and ("narrat" in c.title.lower() or c.role == ContextRole.voice):
                    actor = c
                    break
        if actor and actor.actor:
            vid = actor.actor.voice_id if actor.actor.voice_provider == plugin else None
            return VoiceSpec(voice_id=vid, description=actor.actor.voice_description or actor.actor.description,
                             language=p.settings.language, emotion=emotion)
        return VoiceSpec(description="warm clear narrator", language=p.settings.language, emotion=emotion)

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
                    photo = self._actor_photo(p, n)
                    a_entry = ventry
                    t0 = time.monotonic()
                    audio = voice or media.silence(d / "silence.wav", seconds)
                    _, usage = await self.svc.reg.plugin(a_entry.plugin).generate(
                        AvatarRequest(photo=photo, audio=audio, out=raw, model=a_entry.model,
                                      prompt=prompt[:500], aspect=p.settings.aspect, label=label))
                    cost = seconds * a_entry.unit_price
                    await self.charge(pid, _row("avatar", f"avatar {tag}", a_entry, cost, usage, t0,
                                                a_entry.time.queue_s + a_entry.time.per_output_s * seconds))
                    take.keyframe = self.rel(pid, photo) if photo else None
                    native = True
                else:
                    start = handoff
                    if not start:
                        kf = d / f"{tag}_keyframe.png"
                        img = plan.image
                        t0 = time.monotonic()
                        _, usage = await self.svc.reg.plugin(img.plugin).generate(
                            ImageRequest(prompt=prompt + f" (variation {i})" if i > 1 else prompt, out=kf, model=img.model,
                                         references=refs[: int(img.capabilities.get("reference_images", 0) or 0)],
                                         aspect=p.settings.aspect, negative=negative, label=label))
                        await self.charge(pid, _row("image", f"keyframe {tag}", img, img.unit_price, usage, t0,
                                                    img.time.queue_s + img.time.per_output_s))
                        start = kf
                    take.keyframe = self.rel(pid, start)
                    await self._video_parts(pid, ventry, VideoRequest(
                        prompt=prompt, out=raw, model=ventry.model, seconds=seconds, aspect=p.settings.aspect,
                        resolution=p.settings.resolution, start_frame=start, end_frame=end_frame,
                        references=refs[: int(ventry.capabilities.get("reference_images", 0) or 0)],
                        negative=negative, audio=bool(ventry.capabilities.get("native_audio")),
                        camera=n.script.camera, label=label), tag)
                    native = bool(ventry.capabilities.get("native_audio"))
                # post-process: fit frame, exact length, mix voice + sounds
                fitted = d / f"{tag}_fit.mp4"
                media.normalize_clip(raw, fitted, size, p.settings.fps, seconds=seconds, keep_audio=native)
                final = d / f"{tag}.mp4"
                sounds = [(path, 0.5) for path in self._sounds(p, nid)]
                if plan.route == "avatar":
                    media.replace_audio(fitted, None, final, keep_original=1.0, extra=sounds)
                else:
                    media.replace_audio(fitted, voice, final, keep_original=0.3 if native and voice else (1.0 if native else 0),
                                        extra=sounds)
                for tmp in (raw, fitted):
                    tmp.unlink(missing_ok=True)
                take.video = self.rel(pid, final)
                take.seconds = round(media.probe_duration(final), 2)
                take.cost_usd = round((ventry.unit_price * seconds if ventry else 0)
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

    async def _video_parts(self, pid: str, entry, req: VideoRequest, tag: str) -> None:
        """Make the clip; if it is longer than the model allows, chain parts from each last frame."""
        plugin = self.svc.reg.plugin(entry.plugin)
        max_s = float(entry.capabilities.get("max_seconds", 10) or 10)
        parts_n = max(1, math.ceil(req.seconds / max_s - 0.05))
        if parts_n == 1:
            t0 = time.monotonic()
            _, usage = await plugin.generate(req)
            await self.charge(pid, _row("video", f"video {tag}", entry, req.seconds * entry.unit_price, usage, t0,
                                        entry.time.queue_s + entry.time.per_output_s * req.seconds))
            return
        pieces = []
        start = req.start_frame
        each = req.seconds / parts_n
        for k in range(parts_n):
            piece = req.out.with_name(f"{req.out.stem}_p{k}.mp4")
            sub = VideoRequest(**{**req.__dict__, "out": piece, "seconds": each, "start_frame": start,
                                  "end_frame": req.end_frame if k == parts_n - 1 else None})
            t0 = time.monotonic()
            _, usage = await plugin.generate(sub)
            await self.charge(pid, _row("video", f"video {tag} part {k + 1}", entry, each * entry.unit_price, usage, t0,
                                        entry.time.queue_s + entry.time.per_output_s * each))
            pieces.append(piece)
            start = media.last_frame(piece, piece.with_suffix(".last.png"))
        media.join_clips(pieces, ["cut"] * len(pieces), req.out, (0, 0), 24)

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
                for f in (c.actor.reference_sheet or c.files)[:2]:
                    if f.lower().endswith(IMG_EXT):
                        out.append(self.abs(p.id, f))
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
            if r and r.scores:
                s += sum(r.scores.values()) / len(r.scores)
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
                media.normalize_clip(synced, fixed, size, p.settings.fps, seconds=take.seconds)
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
    async def assemble(self, pid: str) -> Optional[str]:
        """Join the finished clips into the final video (transitions, music, subtitles, export)."""
        self.step(pid, "final", "Joining the clips into one video", 30)
        try:
            return await self._assemble(pid)
        finally:
            self.end_step(pid, "final")
            self.emit(pid, {"type": "project"})

    async def _assemble(self, pid: str) -> Optional[str]:
        p = self.svc.load(pid)
        if not all(n.status == NodeStatus.done for n in leaves(p)):
            await self.message(pid, "Some clips are not made yet")
            return None
        await self.message(pid, "stitching the final video")
        size = media.frame_size(p.settings.aspect, p.settings.resolution)
        fps = p.settings.fps

        def build(node: Node) -> Path:
            if node.is_leaf:
                return self.abs(pid, node.output)
            kids = [build(c) for c in node.children]
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

        root_out = await asyncio.to_thread(build, p.root)

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
        if p.settings.music:
            self.step(pid, "final", "Making and mixing the background music", 30)
            try:
                m_entry = self.svc.reg.choose("music", mode=p.settings.quality_mode)
                music = out_dir / "music.mp3"
                ref = None
                for c in p.context:
                    if c.role in (ContextRole.music_reference, ContextRole.sound) and c.scope == "project":
                        files = [self.abs(pid, f) for f in c.files]
                        ref = files[0] if files else None
                mood = f"{p.style.mood} {p.style.look} music for: {p.goal}"
                t0 = time.monotonic()
                await self.svc.reg.plugin(m_entry.plugin).generate(mood, total, music.with_suffix(".wav") if m_entry.is_free else music,
                                                                   m_entry.model, ref)
                if m_entry.is_free:
                    music = music.with_suffix(".wav")
                cost = (total / 60 * m_entry.unit_price) if m_entry.price.unit == "minute" else m_entry.unit_price
                await self.charge(pid, _row("music", "music bed", m_entry, cost, Usage(), t0,
                                            m_entry.time.queue_s + m_entry.time.per_output_s * total))
                with_music = out_dir / "with_music.mp4"
                media.add_music(current, music, with_music)
                current = with_music
            except Exception as exc:
                traceback.print_exc()
                await self.message(pid, f"music skipped: {exc}")
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
            pr.run.message = f"Final video ready ({total:.0f} s)"
        await self.mutate(pid, done, snapshot=True)
        self.emit(pid, {"type": "final", "path": self.rel(pid, final)})
        p = self.svc.load(pid)
        if p.settings.review_enabled:
            self.step(pid, "final", "Review Agent is checking the whole video", 40)
            try:
                await self.reviewer.review_node(pid, p.root.id, final)
            except Exception:
                traceback.print_exc()
        return str(final)

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

    def _subtitle_entries(self, p: Project) -> list[tuple[float, float, str]]:
        entries = []
        offset = 0.0
        for leaf in leaves(p):
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
            "estimated_usd": round(cost, 4), "actual_usd": round(actual, 4),
            "wall_s": round(time.monotonic() - t0, 1), "expected_s": round(expected_s, 1)}


def build_visual_prompt(p: Project, n: Node) -> str:
    s = n.script
    style = effective_style(p, n.id)
    parts = [s.visual.strip()]
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
    if s.camera:
        parts.append(f"Camera: {s.camera}")
    if style:
        parts.append("Style: " + ", ".join(f"{k} {v}" for k, v in style.items() if k in ("look", "colour", "mood", "notes")))
    if est.is_people_shot(n):
        parts.append("Real people: photoreal, natural skin texture with pores, anatomically correct hands with five fingers, "
                     "natural believable motion, consistent faces")
    return ". ".join(x.rstrip(". ") for x in parts if x) + "."
