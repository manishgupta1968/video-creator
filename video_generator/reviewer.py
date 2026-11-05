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
from .tree import find, leaves, numbering, walk


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

    def _is_placeholder(self, take) -> bool:
        try:
            return self.svc.catalog.get(take.model).is_free
        except KeyError:
            return False

    async def review_take(self, pid: str, nid: str, take_id: str) -> Review:
        p = self.svc.load(pid)
        n = find(p, nid)
        take = next(t for t in n.takes if t.id == take_id)
        base = ProjectStore.path_for(pid)
        video = base / take.video
        work = base / "clips" / nid / "review" / take.id
        frames = media.sample_frames(video, work, every=1.0, max_frames=10)
        pairs = media.sample_pairs(video, work / "pairs")        # neighbouring frames expose warping and morphing
        expected = " ".join([l.text for l in n.script.dialogue] + [n.script.narration]) if n.script else ""
        try:
            segs = await self.transcriber().transcribe(video, p.settings.language, hint=expected)
            transcript = " ".join(s.text for s in segs).strip()
        except Exception as exc:
            transcript = f"(transcription failed: {exc})"
        # numbers measured locally, for free: movement, sharpness against the starting picture, loudness
        measurements = dict(take.quality)
        keyframe = base / take.keyframe if take.keyframe else None
        measurements.update(media.motion_stats(video))
        measurements.update(media.sharpness_ratio(video, keyframe, work / "sharp"))
        measurements.update(media.audio_stats(video))
        placeholder = self._is_placeholder(take)
        history = []
        for r in p.reviews:
            if r.target in {t.id for t in n.takes if t.id != take.id}:
                history += [s.text for s in r.suggestions if s.accepted]
        for v in n.versions:
            if v.feedback:
                history.append(v.feedback)
        brain = self.svc.brain
        draft = await brain.review_take(p, n, frames + pairs, transcript, measurements, take.seconds, video=video,
                                        history="; ".join(history[-8:]), pair_times=[t for t, _ in pairs])
        usage = brain.last_usage
        speech_expected = bool(expected.strip())
        draft = apply_quality_rules(draft, measurements, placeholder, speech_expected)
        review = Review(target=take.id, verdict=draft.verdict, scores=draft.scores.model_dump(),
                        issues=[ReviewIssue(check=i.check, text=i.text, at_s=i.at_s, severity=i.severity,
                                            frame=_nearest_frame(base, frames, i.at_s)) for i in draft.issues],
                        suggestions=[ReviewSuggestion(text=s) for s in draft.suggestions],
                        summary=draft.summary, measurements={k: float(v) for k, v in measurements.items() if isinstance(v, (int, float))},
                        reviewer_model=f"{usage.raw.get('plugin', '')}:{usage.raw.get('model', '')}",
                        cost_usd=round(usage.cost_usd, 4))
        ProjectStore.ledger_add(pid, {"kind": "review", "what": f"review {nid} {take.id}", "node": nid,
                                      "plugin": usage.raw.get("plugin", ""), "model": usage.raw.get("model", ""),
                                      "tokens_in": usage.input_tokens, "tokens_out": usage.output_tokens,
                                      "estimated_usd": round(usage.cost_usd, 4), "actual_usd": round(usage.cost_usd, 4)})
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
        for leaf in [x for x, _ in walk(n) if x.is_leaf]:          # only the clips inside this part
            s = leaf.script
            what = s.visual[:160] if s else leaf.goal
            said = " ".join(l.text for l in s.dialogue)[:120] + (" " + s.narration[:120] if s and s.narration else "") if s else ""
            summaries.append(f"{nums.get(leaf.id, '')} {leaf.title} ({leaf.duration.likely_s:.0f}s): {what} | says: {said}")
        frames = media.sample_frames(video, ProjectStore.path_for(pid) / "clips" / nid / "review_node", every=6, max_frames=12)
        boundaries, b_images = self._boundaries(p, n, nums, ProjectStore.path_for(pid) / "clips" / nid / "review_node")
        draft = await self.svc.brain.review_node(p, n, "\n".join(summaries), media.probe_duration(video), frames,
                                                 boundaries=boundaries, boundary_images=b_images)
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

    def _boundaries(self, p, n, nums: dict, work: Path) -> tuple[str, list[Path]]:
        """For clips that the plan says continue each other (same shot, or same scene): the last frame of one and the
        first frame of the next, so the Review Agent can see a jump in pose, place or look. A deliberate cut (no link)
        is not checked."""
        from . import deps as deps_mod
        from .models import DependencyType
        leaves_ = [x for x, _ in walk(n) if x.is_leaf]
        ids = {x.id: x for x in leaves_}
        lines: list[str] = []
        images: list[Path] = []
        work.mkdir(parents=True, exist_ok=True)
        for b in leaves_:
            for dep in deps_mod.upstream(p, b.id):
                a = ids.get(dep.from_id)
                if not a or dep.type not in (DependencyType.continues_from, DependencyType.same_location) or not a.output or not b.output:
                    continue
                src_a, src_b = ProjectStore.path_for(p.id) / a.output, ProjectStore.path_for(p.id) / b.output
                if not (src_a.exists() and src_b.exists()):
                    continue
                fa, fb = work / f"join_{a.id}_end.png", work / f"join_{b.id}_start.png"
                try:
                    media.last_frame(src_a, fa)
                    media.extract_frame(src_b, fb, at=0.0)
                except Exception:
                    continue
                i = len(images) + 1
                kind = "continues the same shot" if dep.type == DependencyType.continues_from else "is in the same scene"
                lines.append(f"clip {nums.get(b.id, '')} {kind} as clip {nums.get(a.id, '')}: boundary image {i} is the LAST frame of clip "
                             f"{nums.get(a.id, '')}, image {i + 1} is the FIRST frame of clip {nums.get(b.id, '')}")
                images += [fa, fb]
        return "\n".join(lines), images

    def _lock(self, pid: str):
        engine = getattr(self.svc, "engine", None)
        if engine:
            return engine.lock(pid)
        import asyncio
        return asyncio.Lock()


VERDICT_RANK = {"meets_goal": 0, "minor_issues": 1, "does_not_meet_goal": 2}
HARD_CHECKS = ("goal", "script", "realism", "motion")


def apply_quality_rules(draft, meas: dict, placeholder: bool, speech_expected: bool):
    """Rules that no AI opinion can override: a placeholder card, a still image or a blurry or silent clip
    can never pass as realistic video. Measured facts are quoted, so every judgement can be explained."""
    from .brain import IssueDraft
    d = draft.model_copy(deep=True)
    scores = d.scores.model_dump()
    issues = list(d.issues)
    suggestions = list(d.suggestions)

    def cap(key: str, value: int) -> None:
        cur = scores.get(key, 0)
        scores[key] = value if cur == 0 else min(cur, value)

    def issue(check: str, text: str, severity: str) -> None:
        issues.append(IssueDraft(check=check, text=text, severity=severity))

    if placeholder:
        issues.insert(0, IssueDraft(check="realism", severity="major", text=(
            "This is a free preview card with a slow zoom, not real animation. It cannot look like real footage.")))
        suggestions.insert(0, "Connect a video model (for example FAL_KEY or GEMINI_API_KEY in Settings), then re-make this clip.")
        for k in ("realism", "motion", "fidelity"):
            scores[k] = 1
    else:
        m, st = meas.get("motion"), meas.get("static_ratio", 0)
        if m is not None:
            if m < 0.3 or st > 0.6:
                issue("motion", f"Almost nothing moves (measured movement {m:.2f}; real footage is about 1 to 3). It looks like a still image.", "major")
                cap("motion", 1 if m < 0.1 else 2)
                suggestions.append('Ask for real movement in the prompt (for example "slow blink, breathing, subtle head turn") or use a model with stronger motion.')
            elif m < 0.8:
                issue("motion", f"Little movement (measured {m:.2f}). Check that the subject really moves, not only the camera.", "minor")
                cap("motion", 3)
        sv = meas.get("sharpness_vs_start")
        if sv is not None:
            if sv < 0.5:
                issue("fidelity", f"Much softer than the picture it started from (sharpness {sv:.2f}× the start). Detail was lost.", "major")
                cap("fidelity", 2)
            elif sv < 0.75:
                issue("fidelity", f"Softer than the picture it started from (sharpness {sv:.2f}× the start).", "minor")
                cap("fidelity", 3)
        if meas.get("flicker", 0) > 0.05:
            issue("consistency", f"Brightness jumps between frames (flicker {meas['flicker']:.2f}).", "minor")
            cap("consistency", 2)
        fs = meas.get("face_similarity")
        if fs is not None and fs < 0.5:
            issue("actors", f"The face does not match the actor's photos (similarity {fs:.2f}).", "major")
            cap("actors", 2)
    if speech_expected:
        if meas.get("has_audio") == 0:
            issue("audio", "The clip has no sound but speech was expected.", "major")
            cap("audio", 1)
        else:
            lufs, peak, sil = meas.get("lufs"), meas.get("peak_db"), meas.get("silence_ratio", 0)
            if lufs is not None and lufs < -35:
                issue("audio", f"Very quiet (loudness {lufs:.0f} LUFS; speech should be about -16 to -23).", "major")
                cap("audio", 2)
            if peak is not None and peak > -1:
                issue("audio", f"The loudest point is at {peak:.1f} dB, which risks distortion.", "minor")
                cap("audio", 3)
            if sil > 0.6:
                issue("audio", f"{sil:.0%} of the clip is silent although speech was expected.", "major")
                cap("audio", 2)
    # the final verdict is the worse of the AI's verdict and what the scores and measurements say
    checked = {k: v for k, v in scores.items() if v > 0}
    if any(checked.get(k, 5) <= 2 for k in HARD_CHECKS):
        by_scores = "does_not_meet_goal"
    elif any(v < 4 for v in checked.values()) or any(i.severity != "info" for i in issues):
        by_scores = "minor_issues"
    else:
        by_scores = "meets_goal"
    d.verdict = max(d.verdict, by_scores, key=lambda v: VERDICT_RANK[v])
    d.scores = type(d.scores)(**scores)
    d.issues, d.suggestions = issues, suggestions
    return d


def _nearest_frame(base: Path, frames: list, at: Optional[float]) -> Optional[str]:
    if at is None or not frames:
        return None
    t, path = min(frames, key=lambda f: abs(f[0] - at))
    try:
        return str(Path(path).resolve().relative_to(base.resolve()))
    except ValueError:
        return None
