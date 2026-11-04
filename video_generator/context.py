"""Context scoping: project-wide, node subtree, single clip.

Effective context for a clip = project items, then each ancestor's items,
then the clip's own items; lower levels may switch off or override
inherited items.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ContextItem, ContextRole, ContextType, Project
from .tree import ancestors, find

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".heic"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
DOC_EXT = {".pdf", ".pptx", ".ppt", ".key", ".docx", ".txt", ".md"}


@dataclass
class EffectiveItem:
    item: ContextItem
    origin: str          # "shared" | "node:<num>" | "this"
    overridden_from: str | None = None


def item_by_id(project: Project, cid: str) -> ContextItem:
    for c in project.context:
        if c.id == cid:
            return c
    raise KeyError(cid)


def effective_context(project: Project, node_id: str) -> list[EffectiveItem]:
    from .tree import numbering

    nums = numbering(project)
    node = find(project, node_id)
    chain = ancestors(project, node_id) + [node]
    result: dict[str, EffectiveItem] = {}

    # project-wide items
    for c in project.context:
        if c.scope == "project":
            result[c.id] = EffectiveItem(c, "shared")

    for level in chain:
        origin = "this" if level.id == node_id else (f"node:{nums.get(level.id, '')}" if level.id != project.root.id else "shared")
        # items scoped to this level
        for c in project.context:
            if c.scope in (f"node:{level.id}", f"clip:{level.id}") and c.id not in result:
                result[c.id] = EffectiveItem(c, origin)
        for cid in level.context_add:
            try:
                c = item_by_id(project, cid)
            except KeyError:
                continue
            result.setdefault(c.id, EffectiveItem(c, origin))
        for old, new in level.context_override.items():
            if old in result:
                try:
                    repl = item_by_id(project, new)
                except KeyError:
                    continue
                del result[old]
                result[repl.id] = EffectiveItem(repl, origin, overridden_from=old)
        for cid in level.context_off:
            result.pop(cid, None)
    return list(result.values())


def actors_for(project: Project, node_id: str) -> list[ContextItem]:
    return [e.item for e in effective_context(project, node_id) if e.item.type == ContextType.actor]


def guess_type_and_role(filename: str, hint: str = "") -> tuple[ContextType, ContextRole]:
    """Best guess when a file is dropped without details (the user can change it)."""
    ext = Path(filename).suffix.lower()
    name = (Path(filename).stem + " " + hint).lower()
    if ext in AUDIO_EXT:
        if any(w in name for w in ("voice", "speech", "sample", "narrat", "me", "my")):
            return ContextType.audio, ContextRole.voice
        if any(w in name for w in ("music", "song", "track", "beat")):
            return ContextType.audio, ContextRole.music_reference
        return ContextType.audio, ContextRole.sound
    if ext in VIDEO_EXT:
        return ContextType.media, ContextRole.include
    if ext in DOC_EXT:
        if ext in (".pdf", ".pptx", ".ppt", ".key") and any(w in name for w in ("slide", "deck", "present")):
            return ContextType.media, ContextRole.include
        if any(w in name for w in ("brand", "guide")):
            return ContextType.entity, ContextRole.knowledge
        return ContextType.text, ContextRole.knowledge
    if ext in IMAGE_EXT:
        if any(w in name for w in ("logo", "brand", "mascot")):
            return ContextType.entity, ContextRole.must_appear
        if any(w in name for w in ("style", "look", "mood", "ref")):
            return ContextType.style, ContextRole.look_reference
        if any(w in name for w in ("location", "place", "set", "shop", "room", "street", "background")):
            return ContextType.location, ContextRole.look_reference
        if any(w in name for w in ("face", "portrait", "headshot", "person", "actor", "selfie")):
            return ContextType.actor, ContextRole.must_appear
        return ContextType.object, ContextRole.must_appear
    return ContextType.text, ContextRole.knowledge


def summarize_for_llm(items: list[EffectiveItem]) -> str:
    lines = []
    for e in items:
        c = e.item
        extra = ""
        if c.actor:
            a = c.actor
            bits = [a.description, f"clothing: {a.clothing}" if a.clothing else "",
                    f"behaviour: {a.behaviour}" if a.behaviour else "",
                    f"voice: {a.voice_description}" if a.voice_description else ""]
            extra = "; ".join(b for b in bits if b)
        files = f" ({len(c.files)} file(s))" if c.files else ""
        lines.append(f"- [{c.type.value}/{c.role.value}] id={c.id} {c.title}{files}: {c.text} {extra}".strip())
    return "\n".join(lines) or "(none)"
