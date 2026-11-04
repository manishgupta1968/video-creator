"""Review Agent: watches each take (frames + transcript + measurements),
judges it against the goal, script and context, and SUGGESTS fixes.
It never re-makes anything by itself — the user decides."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from . import media
from .models import Review, ReviewIssue, ReviewSuggestion
from .project import ProjectStore
from .tree import find, leaves, numbering


class Reviewer:
    def __init__(self, service):
        self.svc = service

    def transcriber(self):
        for name in ("faster_whisper", "openai_transcribe"):
            if self.svc.reg.configured(name):
                return self.svc.reg.plugin(name)
        return self.svc.reg.plugin("fake_transcribe")

    def _brain_can_see(self) -> bool:
        name = self.svc.reg.llm_plugin_name("review")
        return name in ("anthropic", "openai", "gemini")

    async def review_take(self, pid: str, nid: str, take_id: str) -> Review:
        p = self.svc.load(pid)
        n = find(p, nid)
        take = next(t for t in n.takes if t.id == take_id)
        base = ProjectStore.path_for(pid)
        video = base / take.video
        frames_dir = base / "clips" / nid / "review" / take.id
        frames = media.sample_frames(video, frames_dir, every=1.0, max_frames=10)
        expected = " ".join([l.text for l in n.script.dialogue] + [n.script.narration]) if n.script else ""
        try:
            segs = await self.transcriber().transcribe(video, p.settings.language, hint=expected)
            transcript = " ".join(s.text for s in segs).strip()
        except Exception as exc:
            transcript = f"(transcription failed: {exc})"
        measurements = dict(take.quality)
        history = []
        for r in p.reviews:
            if r.target in {t.id for t in n.takes if t.id != take.id}:
                history += [s.text for s in r.suggestions if s.accepted]
        for v in n.versions:
            if v.feedback:
                history.append(v.feedback)
        brain = self.svc.brain
        draft = await brain.review_take(p, n, frames, transcript, measurements, take.seconds, video=video,
                                        history="; ".join(history[-8:]))
        usage = brain.last_usage
        review = Review(target=take.id, verdict=draft.verdict, scores=draft.scores.model_dump(),
                        issues=[ReviewIssue(check=i.check, text=i.text, at_s=i.at_s, severity=i.severity,
                                            frame=_nearest_frame(base, frames, i.at_s)) for i in draft.issues],
                        suggestions=[ReviewSuggestion(text=s) for s in draft.suggestions],
                        summary=draft.summary + ("" if self._brain_can_see() else ""),
                        reviewer_model=f"{usage.raw.get('plugin', '')}:{usage.raw.get('model', '')}",
                        cost_usd=round(usage.cost_usd, 4))
        ProjectStore.ledger_add(pid, {"kind": "review", "what": f"review {nid} {take.id}", "node": nid,
                                      "plugin": usage.raw.get("plugin", ""), "estimated_usd": round(usage.cost_usd, 4),
                                      "actual_usd": round(usage.cost_usd, 4)})
        brain.last_usage = type(usage)()

        async with self._lock(pid):
            p = self.svc.load(pid)
            p.reviews = [r for r in p.reviews if r.target != take.id] + [review]
            nn = find(p, nid)
            for t in nn.takes:
                if t.id == take.id:
                    t.review_id = review.id
            p.run.spent_usd = round(p.run.spent_usd + review.cost_usd, 4)
            self.svc.save(p, snapshot=False)
        return review

    async def review_node(self, pid: str, nid: str, video: Path) -> Review:
        p = self.svc.load(pid)
        n = find(p, nid)
        nums = numbering(p)
        summaries = []
        for leaf in leaves(p):
            s = leaf.script
            what = s.visual[:160] if s else leaf.goal
            said = " ".join(l.text for l in s.dialogue)[:120] + (" " + s.narration[:120] if s and s.narration else "") if s else ""
            summaries.append(f"{nums.get(leaf.id, '')} {leaf.title} ({leaf.duration.likely_s:.0f}s): {what} | says: {said}")
        frames = media.sample_frames(video, ProjectStore.path_for(pid) / "clips" / nid / "review_node", every=6, max_frames=12)
        draft = await self.svc.brain.review_node(p, n, "\n".join(summaries), media.probe_duration(video), frames)
        usage = self.svc.brain.last_usage
        review = Review(target=nid, verdict=draft.verdict, scores=draft.scores.model_dump(),
                        issues=[ReviewIssue(check=i.check, text=i.text, at_s=i.at_s, severity=i.severity) for i in draft.issues],
                        suggestions=[ReviewSuggestion(text=s, accepted=False) for s in draft.suggestions],
                        summary=draft.summary, reviewer_model=f"{usage.raw.get('plugin', '')}",
                        cost_usd=round(usage.cost_usd, 4))
        async with self._lock(pid):
            p = self.svc.load(pid)
            p.reviews = [r for r in p.reviews if r.target != nid] + [review]
            if nid == p.root.id:
                p.final_review_id = review.id
            p.run.spent_usd = round(p.run.spent_usd + review.cost_usd, 4)
            self.svc.save(p, snapshot=False)
        return review

    def _lock(self, pid: str):
        engine = getattr(self.svc, "engine", None)
        if engine:
            return engine.lock(pid)
        import asyncio
        return asyncio.Lock()


def _nearest_frame(base: Path, frames: list, at: Optional[float]) -> Optional[str]:
    if at is None or not frames:
        return None
    t, path = min(frames, key=lambda f: abs(f[0] - at))
    try:
        return str(Path(path).resolve().relative_to(base.resolve()))
    except ValueError:
        return None
