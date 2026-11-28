"""Pictures of the characters and objects, made for you: by Codex through your ChatGPT subscription when it is
installed (Claude Code cannot make pictures), else by the picture service you connected (fal.ai, Google, OpenAI).

A character's picture becomes its approved look (the reference sheet every clip uses, and the @Image reference given
to Seedance). An object's picture is added to its pictures. You can ask for changes in plain words; the earlier picture
is then given as the starting point, so only what you ask for changes."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import ContextType, MadePicture, now_iso
from .plugins.base import ImageRequest, PluginError
from .project import ProjectStore

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def picture_maker(svc):
    """The catalogue row that makes pictures now (Codex first when installed), or None with the reason."""
    try:
        e = svc.reg.choose("image", mode=None if svc.config.quality_mode != "free" else "balanced")
    except LookupError:
        return None, "No picture maker is connected."
    if e.is_free:
        return None, ("No picture maker is connected: install Codex and sign in with your ChatGPT account (no per-picture "
                      "cost), or add a fal.ai key in Settings → Vendors & keys.")
    return e, ""


def maker_name(e) -> str:
    return "Codex" if e.plugin == "codex_image" else {"fal_image": "fal.ai", "nano_banana": "Google", "gpt_image": "OpenAI"}.get(e.plugin, e.id)


def _prompt(project, item) -> tuple[str, str]:
    look = (project.style.look or "photoreal") if getattr(project, "style", None) else "photoreal"
    if item.type == ContextType.actor and item.actor:
        a = item.actor
        if a.kind == "animal":
            return (f"{look} picture of {item.title}: {a.description}. The whole animal, side-on, standing naturally, on a "
                    "plain light-grey background, soft even light, sharp focus, true-to-life colours.", "4:3")
        if a.kind == "product":
            return (f"{look} product picture of {item.title}: {a.description}. Front view on a plain light-grey background, "
                    "soft studio light, sharp focus, true-to-life colours.", "1:1")
        return (f"{look} full-body character reference picture of {item.title}: {a.description}. Wearing "
                f"{a.clothing or 'the clothes the story gives them'}. Standing, facing the camera, arms relaxed, the whole body "
                "from head to feet in the picture, plain light-grey background, soft even light, natural skin texture, "
                "sharp focus, true-to-life colours. No text.", "3:4")
    if item.type == ContextType.location:
        aspect = project.settings.aspect or "16:9"
        return (f"{look} wide establishing picture of the place {item.title}: {item.text or item.title}. Eye-level camera, "
                "the whole place in view with its buildings, plants and ground, natural daylight, no people, no animals, "
                "no text, true-to-life colours and materials.", aspect)
    return (f"{look} reference picture of {item.title}: {item.text or item.title}. The whole object, three-quarter view, "
            "on a plain light-grey background, soft even light, sharp focus, true-to-life colours, real size and "
            "materials. No text.", "1:1")


async def make_item_picture(svc, pid: str, cid: str, change: str = "") -> MadePicture:
    p = svc.load(pid)
    item = next((c for c in p.context if c.id == cid), None)
    if item is None:
        raise ValueError(f"There is no character or object with id {cid}.")
    if item.type not in (ContextType.actor, ContextType.object, ContextType.location):
        raise ValueError("Pictures are made for characters, places and objects only.")
    entry, why = picture_maker(svc)
    if entry is None:
        raise ValueError(why)
    base = ProjectStore.path_for(pid)
    prompt, aspect = _prompt(p, item)
    described_by = ""
    if not (change or "").strip() or not item.picture:
        # the AI brain you chose (Claude Code or Codex) writes the full description; the rules above are its first draft
        try:
            brief = await svc.brain.picture_brief(p, item, prompt)
            if brief.prompt.strip():
                prompt = brief.prompt.strip()
                described_by = svc.reg.llm_plugin_name("picture_brief")
            q = svc.load(pid)
            svc._ledger_llm(q, f"describe the picture of {item.title}")
            svc.save(q, snapshot=False)
        except PluginError:
            pass                                        # the AI brain could not answer: the first draft is drawn as it is
    elif item.picture:
        described_by = item.picture.described_by
    old = item.picture if item.picture and (base / item.picture.file).exists() else None
    photos = [base / f for f in item.files if f.lower().endswith(IMG_EXT) and (not old or f != old.file)]
    refs = list(photos[:4])
    change = (change or "").strip()
    if change and old:
        prompt = (f"Picture 1 is the current picture of {item.title}. Make the SAME picture with only this change: {change}. "
                  f"Keep everything else exactly as it is. For reference, it shows: {prompt}")
        refs = [base / old.file] + refs
    elif refs:
        prompt += " Keep the looks of the person or thing in the attached picture(s)."
    n = 1 + (len(old.changes) + 1 if old else 0)
    out = base / "cast" / item.id / f"picture_{n:02d}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    plugin = svc.reg.plugin(entry.plugin)
    try:
        made, usage = await plugin.generate(ImageRequest(prompt=prompt, out=out, model=entry.model, references=refs,
                                                         aspect=aspect, label=f"{item.title} · picture"))
    except PluginError as exc:
        raise ValueError(f"{maker_name(entry)} could not make the picture: {exc}") from exc
    rel = str(Path(made).relative_to(base))
    cost = float(getattr(usage, "cost_usd", 0) or 0) or (0.0 if entry.price.unit == "subscription" else entry.unit_price)
    if cost:
        ProjectStore.ledger_add(pid, {"kind": "image", "what": f"picture of {item.title}", "plugin": entry.plugin,
                                      "model": entry.id, "estimated_usd": round(entry.unit_price, 4), "actual_usd": round(cost, 4)})
    p = svc.load(pid)
    item = next(c for c in p.context if c.id == cid)
    pic = MadePicture(file=rel, by=entry.id, described_by=described_by, prompt=prompt, changes=(old.changes if old else []) + ([change] if change else []),
                      at=now_iso())
    if item.actor is not None:
        item.actor.reference_sheet = [rel]            # the approved look, used in every clip and given to Seedance
    else:
        keep = [f for f in item.files if not (old and f == old.file)]
        item.files = [rel] + keep                     # an object's or a place's pictures: the made one first
    item.picture = pic
    svc.save(p)
    return pic


BRAIN_WORDS = {"claude_code_brain": "Claude Code", "codex_brain": "Codex", "anthropic": "Claude (API)", "openai": "OpenAI (API)",
               "gemini": "Gemini (API)", "fake_llm": "the offline brain"}


def maker_info(svc) -> dict:
    e, why = picture_maker(svc)
    brain = svc.reg.llm_plugin_name("picture_brief")
    return {"id": e.id if e else "", "name": maker_name(e) if e else "", "subscription": bool(e and e.price.unit == "subscription"),
            "price": 0 if not e else (0 if e.price.unit == "subscription" else e.unit_price), "why": why,
            "brain": brain, "brain_name": BRAIN_WORDS.get(brain, brain),
            "note": ("Claude Code cannot draw pictures: it writes the description, and "
                     f"{maker_name(e) if e else 'a picture maker'} draws it.") if brain == "claude_code_brain" else ""}


def add_missing(svc, pid: str, items: list[dict]) -> list[str]:
    """Add the chosen missing characters, places and objects to the right panel. An item seen in one clip only is added
    to that clip; others are shared by all clips. Something already defined with the same name is skipped."""
    from .models import ContextItem, ContextRole
    from .tree import numbering
    p = svc.load(pid)
    ids = {v: k for k, v in numbering(p).items()}
    have = {(c.type.value, c.title.strip().lower()) for c in p.context}
    added = []
    for raw in items:
        t = str(raw.get("type") or "object")
        if t not in ("actor", "object", "location"):
            continue
        title = str(raw.get("title") or "").strip()
        if not title or (t, title.lower()) in have:
            continue
        clips = [ids[c] for c in raw.get("clips") or [] if c in ids]
        data = {"type": t, "title": title, "scope": f"node:{clips[0]}" if len(clips) == 1 else "project",
                "role": (ContextRole.look_reference if t == "location" else ContextRole.must_appear).value}
        desc = str(raw.get("description") or "")
        if t == "actor":
            kind = raw.get("kind") if raw.get("kind") in ("ai_person", "animal", "product") else "ai_person"
            data["actor"] = {"kind": kind, "description": desc}
        else:
            data["text"] = desc
        p.context.append(ContextItem.model_validate(data))
        have.add((t, title.lower()))
        added.append(title)
    if added:
        svc.save(p)
    return added
