"""Review Agent: watches each take (frames + transcript + measurements),
judges it against the goal, script and context, and SUGGESTS fixes.
It never re-makes anything by itself — the user decides."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from . import casting, languages, media
from . import policy as policy_mod
from .models import DependencyType, Review, ReviewIssue, ReviewJoin, ReviewSuggestion
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

    # ---------------------------------------------------------------- the stitch with the clip before
    @staticmethod
    def previous_clip(p, n):
        """The clip before this one in story order (also across parts), or None for the first clip."""
        ls = leaves(p)
        ids = [x.id for x in ls]
        return ls[ids.index(n.id) - 1] if n.id in ids and ids.index(n.id) > 0 else None

    @staticmethod
    def join_kind(p, a, b) -> str:
        """How clip b joins clip a, as the plan decided it: continues | same_scene | cut."""
        if b.continuity.join:
            return b.continuity.join
        for d in p.dependencies:
            if d.from_id == a.id and d.to_id == b.id:
                if d.type == DependencyType.continues_from:
                    return "continues"
                if d.type == DependencyType.same_location:
                    return "same_scene"
        return "cut"

    def _real_clip(self, prev) -> bool:
        """Was this clip made by a real model (not a free placeholder card)? Slides and your own footage count as real."""
        take = next((t for t in prev.takes if t.id == prev.chosen_take), None)
        if not take:
            return True
        return not self._is_placeholder(take)

    def _join_evidence(self, p, n, take, base: Path, work: Path, video: Path, frames, placeholder: bool):
        """What the Review Agent needs to judge the stitch with the clip before: (ReviewJoin, the words for the prompt, the two pictures)."""
        prev = self.previous_clip(p, n)
        nums = numbering(p)
        if prev is None:
            return ReviewJoin(why_not="this is the first clip: there is nothing before it"), "", []
        kind = self.join_kind(p, prev, n)
        info = ReviewJoin(previous=nums.get(prev.id, ""), kind=kind, reason=n.continuity.join_reason, transition=n.transition_in or "cut",
                          limit=policy_mod.current().join_max_difference)
        src = base / prev.output if prev.output else None
        if not src or not src.exists():
            info.why_not = f"clip {info.previous} is not made yet"
            return info, "", []
        if not self._real_clip(prev):
            info.why_not = f"clip {info.previous} is only a free placeholder card, so there is no real picture to compare with"
            return info, "", []
        if placeholder:
            info.why_not = "this take is only a free placeholder card"
            return info, "", []
        work.mkdir(parents=True, exist_ok=True)
        last, first = work / "join_prev_last.jpg", work / "join_this_first.jpg"
        try:
            media.last_frame(src, last)
            media.extract_frame(video, first, at=0.0)
        except Exception:
            info.why_not = "the pictures at the seam could not be read"
            return info, "", []
        try:
            info.difference = media.frame_difference(src, video, a_last=True)
        except Exception:
            info.difference = None
        info.previous_frame, info.this_frame = _rel(base, last), _rel(base, first)
        info.judged = True
        from .brain import join_block
        prev_end = (prev.script.end_state if prev.script and prev.script.end_state.strip() else prev.continuity.end_state).strip()
        this_start = (n.script.start_state if n.script and n.script.start_state.strip() else n.continuity.start_state).strip()
        text = join_block(info.previous, kind, info.reason, info.transition, info.difference, info.limit, prev_end, this_start)
        return info, text, [last, first]

    @staticmethod
    def _listen_language(p, n) -> str:
        """The language the speech-to-text listens in for this clip: the one language spoken in it; when several are spoken, "" = work it out
        by itself (policy.mixed_language_detection); when nothing is scripted, the video's main language."""
        spoken = casting.clip_languages(p, n.script)
        if len(spoken) > 1:
            return "" if policy_mod.current().mixed_language_detection else spoken[0]
        return spoken[0] if spoken else languages.effective(p.settings.language)

    async def review_take(self, pid: str, nid: str, take_id: str) -> Review:
        p = self.svc.load(pid)
        n = find(p, nid)
        take = next(t for t in n.takes if t.id == take_id)
        base = ProjectStore.path_for(pid)
        video = base / take.video
        work = base / "clips" / nid / "review" / take.id
        frames = media.sample_frames(video, work, every=1.0, max_frames=9)           # 9 + 6 pair pictures + 2 join pictures = 17 (a review model sees at most 18)
        pairs = media.sample_pairs(video, work / "pairs")        # neighbouring frames expose warping and morphing
        expected = " ".join([l.text for l in n.script.dialogue] + [n.script.narration]) if n.script else ""
        try:
            segs = await self.transcriber().transcribe(video, self._listen_language(p, n), hint=expected)
            transcript = " ".join(s.text for s in segs).strip()
        except Exception as exc:
            transcript = f"(transcription failed: {exc})"
        # numbers measured locally, for free: movement, sharpness against the starting picture, loudness
        measurements = dict(take.quality)
        keyframe = base / take.keyframe if take.keyframe else None
        measurements.update(media.motion_stats(video))
        measurements.update(media.freeze_stats(video))
        measurements.update(media.sharpness_ratio(video, keyframe, work / "sharp"))
        measurements.update(media.audio_stats(video))
        placeholder = self._is_placeholder(take)
        join, join_text, join_images = self._join_evidence(p, n, take, base, work, video, frames, placeholder)
        if join.judged and join.difference is not None:
            measurements["join_difference"] = join.difference
        history = []
        for r in p.reviews:
            if r.target in {t.id for t in n.takes if t.id != take.id}:
                history += [s.text for s in r.suggestions if s.accepted]
        for v in n.versions:
            if v.feedback:
                history.append(v.feedback)
        brain = self.svc.brain
        draft = await brain.review_take(p, n, frames + pairs, transcript, measurements, take.seconds, video=video,
                                        history="; ".join(history[-8:]), pair_times=[t for t, _ in pairs],
                                        join_text=join_text, join=join.model_dump(), join_images=join_images)
        usage = brain.last_usage
        speech_expected = bool(expected.strip())
        draft = apply_quality_rules(draft, measurements, placeholder, speech_expected, join=join)
        review = Review(target=take.id, verdict=draft.verdict, scores=draft.scores.model_dump(), join=join,
                        issues=[ReviewIssue(check=i.check, text=i.text, at_s=i.at_s, severity=i.severity,
                                            frame=(join.this_frame if i.check == "join" and join.this_frame else _nearest_frame(base, frames, i.at_s)))
                                for i in draft.issues],
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
        work = ProjectStore.path_for(pid) / "clips" / nid / "review_node"
        boundaries, b_images = self._boundaries(p, n, nums, work, stitched=video)
        frames = media.sample_frames(video, work, every=6, max_frames=max(18 - len(b_images), 4))        # a review model sees at most 18 pictures
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

    MAX_SEAMS = 6                      # two pictures per seam: up to 12 of the 18 pictures a review model sees

    def _boundaries(self, p, n, nums: dict, work: Path, stitched: Optional[Path] = None) -> tuple[str, list[Path]]:
        """Every seam between neighbouring clips inside this part (or the whole video), cuts included: the picture just BEFORE and just AFTER
        the seam, taken from the STITCHED video so a crossfade or a double exposure is seen too (from the single clip files when the stitched
        video is not available). When there are more seams than can be shown, the most demanding are kept: continuing shots, then same-scene
        joins, then cuts (shown in story order)."""
        leaves_ = [x for x, _ in walk(n) if x.is_leaf]
        base = ProjectStore.path_for(p.id)
        work.mkdir(parents=True, exist_ok=True)
        pairs = [(a, b) for a, b in zip(leaves_, leaves_[1:]) if a.output and b.output and (base / a.output).exists() and (base / b.output).exists()]
        if not pairs:
            return "", []
        kinds = {b.id: self.join_kind(p, a, b) for a, b in pairs}
        rank = {"continues": 0, "same_scene": 1, "cut": 2}
        shown = sorted(sorted(pairs, key=lambda ab: rank.get(kinds[ab[1].id], 2))[: self.MAX_SEAMS], key=lambda ab: leaves_.index(ab[1]))
        seam: dict[str, float] = {}
        if stitched and Path(stitched).exists():
            try:
                durs = [media.probe_duration(base / x.output) if x.output and (base / x.output).exists() else x.duration.likely_s for x in leaves_]
                times = media.seam_times(durs, [x.transition_in for x in leaves_], fps=p.settings.fps)
                seam = {leaves_[i + 1].id: t for i, (t, _d) in enumerate(times)}
            except Exception:
                seam = {}
        lines: list[str] = []
        images: list[Path] = []
        for a, b in shown:
            kind = kinds[b.id]
            words = {"continues": "continues the same shot", "same_scene": "stays in the same scene", "cut": "is a deliberate cut"}[kind]
            trans = b.transition_in if b.transition_in not in ("cut", "", None) else "hard cut"
            pic_a, pic_b = work / f"seam_{b.id}_before.jpg", work / f"seam_{b.id}_after.jpg"
            at = seam.get(b.id)
            try:
                if at is not None:
                    total = media.probe_duration(stitched)
                    media.extract_frame(stitched, pic_a, max(at - 0.35, 0.0))
                    media.extract_frame(stitched, pic_b, min(at + 0.35, max(total - 0.05, 0.0)))
                    where = f"at {at:.1f} s of the video: images {len(images) + 1} and {len(images) + 2} are just BEFORE and just AFTER the seam"
                else:
                    media.last_frame(base / a.output, pic_a)
                    media.extract_frame(base / b.output, pic_b, at=0.0)
                    where = f"images {len(images) + 1} and {len(images) + 2} are the LAST frame of clip {nums.get(a.id, '')} and the FIRST frame of clip {nums.get(b.id, '')}"
            except Exception:
                continue
            lines.append(f"clip {nums.get(b.id, '')} {words} (after clip {nums.get(a.id, '')}; transition: {trans}"
                         + (f"; plan: {b.continuity.join_reason}" if b.continuity.join_reason else "") + f"): {where}")
            images += [pic_a, pic_b]
        if len(pairs) > len(shown):
            lines.append(f"({len(pairs) - len(shown)} more seams are not shown; they are the less demanding ones)")
        return "\n".join(lines), images

    def _lock(self, pid: str):
        engine = getattr(self.svc, "engine", None)
        if engine:
            return engine.lock(pid)
        import asyncio
        return asyncio.Lock()


VERDICT_RANK = {"meets_goal": 0, "minor_issues": 1, "does_not_meet_goal": 2}
HARD_CHECKS = ("goal", "script", "realism", "motion", "join")


def apply_quality_rules(draft, meas: dict, placeholder: bool, speech_expected: bool, join=None):
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
        pol = policy_mod.current()
        longest, ratio = meas.get("longest_freeze_s", 0.0), meas.get("frozen_ratio", 0.0)
        if longest > pol.max_freeze_s or ratio > pol.max_freeze_ratio:
            tail = meas.get("tail_freeze_s", 0.0)
            issue("motion", f"The picture is frozen for {meas.get('frozen_s', longest):.1f} s ({ratio:.0%} of the clip"
                  + (f", {tail:.1f} s at the end" if tail else "") + "). Rules allow at most "
                  f"{pol.max_freeze_s:.1f} s or {pol.max_freeze_ratio:.0%}.", "major")
            cap("motion", 2)
            cap("realism", 3)
            suggestions.append("The model could not make this clip as long as planned. Split the clip so each part needs one kind of movement, "
                               "or shorten it to what the model made.")
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
    # the stitch with the clip before: no evidence means no score (the AI may not invent one); a continuing shot that does not start where the
    # clip before ended is capped by the measured picture difference, whatever the AI thinks
    if join is None or not getattr(join, "judged", False):
        scores["join"] = 0
    elif join.kind == "continues" and join.difference is not None and join.difference > join.limit:
        if not any(i.check == "join" and i.severity == "major" for i in issues):          # the AI may already have said it
            issue("join", f"This clip does not start where clip {join.previous} ended (the pictures differ by {join.difference:.2f}; the limit for a continuing shot is "
                          f"{join.limit:.2f}). It should begin on the very last picture of the clip before.", "major")
        cap("join", 2)
        suggestions.append(f"Re-make this clip from the hand-over picture (the last picture of clip {join.previous}), or change the join to a cut.")
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


def _rel(base: Path, path: Path) -> Optional[str]:
    try:
        return str(Path(path).resolve().relative_to(base.resolve()))
    except ValueError:
        return None


def _nearest_frame(base: Path, frames: list, at: Optional[float]) -> Optional[str]:
    if at is None or not frames:
        return None
    t, path = min(frames, key=lambda f: abs(f[0] - at))
    try:
        return str(Path(path).resolve().relative_to(base.resolve()))
    except ValueError:
        return None
