"""The free continuity check: plain rules, no AI, no cost, instant, works offline.

It looks at the plan as it is RIGHT NOW and lists what would make the clips (and parts) feel like they belong to one video. Every finding says what
is wrong in plain words and, where the repair is mechanical, carries a fix the screen can run with one click.

A finding is a dict:  code (stable name of the rule) · node (clip id, "" = the whole video) · number (clip number shown to the person) ·
severity ("problem" = the video will look wrong; "note" = worth a look) · text · fixes (list of {action, label, ...}).
Fix actions the tool runs itself: copy_start, set_join (join), joins_as_cuts.   Fix actions the screen runs: remake, open_actor (id).
"""
from __future__ import annotations

import json
import re
from typing import Optional

from . import casting, languages
from . import estimate as est
from .deps import upstream
from .models import ContextItem, ContextType, DependencyType, NodeKind, NodeStatus, Project
from .registry import Registry
from .tree import ancestors, find, leaves, numbering

JOIN_LINKS = (DependencyType.continues_from, DependencyType.same_location)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W\d_]{3,}", (text or "").lower())}


def _same(a: str, b: str) -> bool:
    x, y = _words(a), _words(b)
    return bool(x) and x == y


def _similar(a: str, b: str, at_least: float = 0.5) -> bool:
    """Do two short descriptions say about the same thing (the share of words they have in common)?"""
    x, y = _words(a), _words(b)
    if not x or not y:
        return True
    return len(x & y) / len(x | y) >= at_least


def _speaker_card(p: Project, speaker: str) -> Optional[ContextItem]:
    for c in p.context:
        if c.type == ContextType.actor and c.actor and (c.id == speaker or c.title.lower() == (speaker or "").lower()):
            return c
    if speaker == "narrator":
        for c in p.context:
            if c.type == ContextType.actor and c.actor and "narrat" in c.title.lower():
                return c
    return None


def _item(code: str, node: str, number: str, text: str, fixes: Optional[list] = None, severity: str = "note") -> dict:
    return {"code": code, "node": node, "number": number, "severity": severity, "text": text, "fixes": fixes or []}


def check(project: Project, reg: Registry, project_dir=None) -> list[dict]:
    """Every continuity finding for the plan as it is now. `project_dir` (the project's folder) lets it also see which voice a made clip used."""
    nums = numbering(project)
    ls = [l for l in leaves(project)]
    found: list[dict] = []
    pairs = [(a, b) for a, b in zip(ls, ls[1:]) if a.kind == NodeKind.clip and b.kind == NodeKind.clip]
    linked = {(d.from_id, d.to_id): d.type for d in project.dependencies if d.type in JOIN_LINKS}

    # 1. every clip after the first has a decided join (a join left blank is read as a cut, so say so)
    undecided = [b for a, b in pairs if not b.continuity.join and (a.id, b.id) not in linked]
    if undecided:
        names = ", ".join(nums.get(b.id, "") for b in undecided[:6]) + ("…" if len(undecided) > 6 else "")
        found.append(_item("join_undecided", "", "", f"{len(undecided)} clip(s) ({names}) have no decided join with the clip before them, so each is treated as a "
                           "cut (a new place or time). Decide it, so the look and the starting picture are kept where they should be.",
                           [{"action": "joins_as_cuts", "label": "Mark them as cuts"}]))

    for a, b in pairs:
        join = b.continuity.join or ("continues" if linked.get((a.id, b.id)) == DependencyType.continues_from
                                     else "same_scene" if linked.get((a.id, b.id)) == DependencyType.same_location else "")
        an, bn = nums.get(a.id, ""), nums.get(b.id, "")
        # 2. a continuing clip starts exactly where the clip before it ends
        if join == "continues":
            end = (a.script.end_state if a.script and a.script.end_state.strip() else a.continuity.end_state).strip()
            start = (b.script.start_state if b.script and b.script.start_state.strip() else b.continuity.start_state).strip()
            if end and start and end != start:
                found.append(_item("start_not_end", b.id, bn, f"Clip {bn} continues clip {an}, but it is planned to start differently from how clip {an} ends. "
                                   "A continuing clip must start exactly where the one before ended.",
                                   [{"action": "copy_start", "label": "Copy the end into the start", "node": b.id}], "problem"))
            # 3. measured: the first picture of this clip against the last picture of the clip before
            miss = est.join_miss(project, b)
            if miss:
                found.append(_item("join_measured", b.id, bn, miss, [
                    {"action": "remake", "label": "Re-make from the hand-over picture", "node": b.id},
                    {"action": "set_join", "label": "Change this join to a cut", "node": b.id, "join": "cut"}], "problem"))
        # 5. the same place and the same people, yet joined as a cut: the look would not be kept
        if join == "cut" and (a.id, b.id) not in linked:
            pa, pb = a.continuity, b.continuity
            if _same(pa.place, pb.place) and pa.present and sorted(x.lower() for x in pa.present) == sorted(x.lower() for x in pb.present):
                found.append(_item("same_place_cut", b.id, bn, f"Clips {an} and {bn} happen in the same place with the same people, but they are joined as a cut. "
                                   "A same-scene join keeps the look, the light and the props.",
                                   [{"action": "set_join", "label": "Make it a same-scene join", "node": b.id, "join": "same_scene"}]))
        # 6. clothing changes inside one scene
        if join in ("continues", "same_scene") and a.script and b.script:
            before = {x.actor_id: x.clothing for x in a.script.actors_in_shot if x.clothing.strip()}
            for x in b.script.actors_in_shot:
                if x.actor_id in before and x.clothing.strip() and not _similar(before[x.actor_id], x.clothing):
                    card = next((c for c in project.context if c.id == x.actor_id), None)
                    who = card.title if card else "A character"
                    found.append(_item("clothing_changes", b.id, bn, f"{who} wears '{before[x.actor_id][:60]}' in clip {an} and '{x.clothing[:60]}' in clip {bn}, "
                                       "though the join says it is the same scene. Change one of them unless the story needs it."))
        # 8. neighbouring parts made with different video models
        if [x.id for x in ancestors(project, a.id)][-1:] != [x.id for x in ancestors(project, b.id)][-1:]:         # a part boundary
            try:
                ma, mb = est.plan_clip(project, a, reg).video, est.plan_clip(project, b, reg).video
            except LookupError:
                ma = mb = None
            if ma and mb and ma.id != mb.id and not ma.is_free and not mb.is_free:
                found.append(_item("parts_differ", b.id, bn, f"Clip {an} (end of one part) is made with {ma.id} and clip {bn} (start of the next) with {mb.id}: "
                                   "the look may differ slightly where the parts meet."))

    # 4 and 9. every speaker: an accent, a gender; and lines written in the speaker's own script
    spoken: dict[str, str] = {}
    for l in ls:
        if l.kind != NodeKind.clip or not l.script:
            continue
        lines = [(d.speaker, d.text) for d in l.script.dialogue if d.text.strip()] + ([("narrator", l.script.narration)] if l.script.narration.strip() else [])
        for sp, text in lines:
            card = _speaker_card(project, sp)
            if card and card.id not in spoken:
                spoken[card.id] = l.id
            lang = languages.normalise(card.actor.language) if card and card.actor else ""
            lang = lang or languages.normalise(project.settings.language)
            want = languages.scripts().get(lang)
            top, share, n = languages.script_of(text)
            if want and top and n >= 3 and share >= 0.7 and top not in want:
                who = card.title if card else sp
                found.append(_item("script_differs", l.id, nums.get(l.id, ""),
                                   f"In clip {nums.get(l.id, '')}, a line spoken by {who} is written in {top.title()} letters, but {who} speaks {languages.name_of(lang)} "
                                   f"(normally written in {', '.join(w.title() for w in want)}). A voice reads a language best in its own script."))
    for cid, first in spoken.items():
        card = next(c for c in project.context if c.id == cid)
        prof = casting.profile_for(card, project)
        gaps = [w for w, missing in (("an accent", not (card.actor.voice_accent or "").strip()), ("a gender", not prof.gender)) if missing]
        if gaps:
            found.append(_item("speaker_incomplete", first, nums.get(first, ""), f"{card.title} speaks in the video but has no {' and no '.join(gaps)} decided. "
                               "Every speaker needs them, so the same person sounds the same in every part.",
                               [{"action": "open_actor", "label": f"Open {card.title}", "id": card.id}]))
        elif card.actor and casting.accent_mismatch(card.actor.voice_accent_label, card.actor.voice_accent):
            found.append(_item("accent_label", first, nums.get(first, ""), f"{card.title}: {casting.accent_mismatch(card.actor.voice_accent_label, card.actor.voice_accent)}",
                               [{"action": "open_actor", "label": f"Open {card.title}", "id": card.id}]))

    # 7. a clip made with a voice that has since changed
    if project_dir is not None:
        for l in ls:
            if l.kind != NodeKind.clip or l.status != NodeStatus.done:
                continue
            meta = project_dir / "clips" / l.id / "voice_lines.json"
            if not meta.exists():
                continue
            try:
                made_with = json.loads(meta.read_text()).get("voices") or {}
            except ValueError:
                continue
            changed = []
            for sp, vid in made_with.items():
                card = _speaker_card(project, sp)
                now = card.actor.voice_id if card and card.actor else None
                if vid and now and vid != now:
                    changed.append(card.title)
            if changed:
                found.append(_item("voice_changed", l.id, nums.get(l.id, ""), f"Clip {nums.get(l.id, '')} was made with another voice for {', '.join(changed)}. "
                                   "Make it again so the voice is the same in every clip.",
                                   [{"action": "remake", "label": "Make it again", "node": l.id}], "problem"))
    return found


def reuses(project: Project, reg: Registry, targets: list[str], project_dir=None) -> list[str]:
    """What making these clips will REUSE instead of inventing again (shown in the confirm dialog, so you see what keeps them in sync with the rest)."""
    nums = numbering(project)
    out: list[str] = []
    ids = set(targets)
    cards: dict[str, ContextItem] = {}
    for tid in targets:
        n = find(project, tid)
        if n.kind != NodeKind.clip or not n.script:
            continue
        for sp in {d.speaker for d in n.script.dialogue if d.text.strip()} | ({"narrator"} if n.script.narration.strip() else set()):
            card = _speaker_card(project, sp)
            if card:
                cards[card.id] = card
        for x in n.script.actors_in_shot:
            card = next((c for c in project.context if c.id == x.actor_id), None)
            if card:
                cards.setdefault(card.id, card)
        for d in upstream(project, tid):
            if d.type == DependencyType.continues_from and d.from_id not in ids and find(project, d.from_id).status == NodeStatus.done:
                out.append(f"the last picture of clip {nums.get(d.from_id, '')} (clip {nums.get(tid, '')} starts from it)")
    for card in cards.values():
        a = card.actor
        if not a:
            continue
        if a.voice_id and a.voice_name:
            out.append(f"{card.title}'s voice ({a.voice_name})")
        if a.reference_sheet:
            out.append(f"{card.title}'s look (reference pictures already made)")
    return list(dict.fromkeys(out))
