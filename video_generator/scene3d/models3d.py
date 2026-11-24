"""3D models of the characters and objects in a video (the 3D camera reference add-on).

Nothing about a model is hard-wired:
1. Brief. The planner reads every moment a character or object appears in the scripts and writes its brief: what it
   looks like (filling in what the story does not say), its real size, its colours, its parts, and every pose the
   script needs (walk, kneel, touch_ground, bless …).
2. Build. Claude Code (or Codex) writes model.py, a Blender script that builds the model low-poly but recognisable,
   with bones and the poses from the brief, in a locked work folder. It may run the free model check
   (`python -m video_generator.scene3d.model_check model.py`), which builds the model in Blender, renders it from four
   sides and in every pose, and lists problems, as often as it likes.
3. Check. The tool runs the same check itself; problems go back to the agent for another round (up to
   max_fix_rounds). A model that passes is kept: model.py, model.blend and the pictures.
4. Use. Every clip's 3D scene builds its characters from their model.py and moves them through the poses its plan
   asks for. The model is built once and reused, so the guru looks the same in every clip.
With no Blender or no agent installed, or a model that keeps failing, the clips use plain shapes (as before).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

from ..models import ContextItem, ContextType, Model3D, NodeKind, Project, now_iso
from ..plugins.base import AgentTask, PluginError
from ..project import ProjectStore
from ..tree import leaves
from . import service as s3
from .model_check import check_model
from .spec import ModelRef

CHECK = "video_generator.scene3d.model_check"

MODEL_TASK = """You build ONE low-poly 3D model in Blender with Python, for a video's rough 3D scenes. Work only in this folder.

Files:
- brief.json: what the model must look like and every pose it must be able to take (from the story).
- reference_*.png / .jpg (when present): pictures of how it really looks. Match them as far as low-poly allows.
- model.py: the script you write (or improve, when it is there already). This is the ONLY file you may change.

Low-poly means blocky but recognisable, like a stylised game character: a blocky head with simple eyes, eyebrows, nose
and mouth, hair or a head-dress, a beard if it has one, clothes as simple shapes in their real colours, arms with
simple hands, legs with feet. Build it from simple meshes (bpy.data.meshes + from_pydata, or bmesh); no add-ons, no
files from outside.

model.py MUST define (this is the only contract; the model itself is yours to design):
    POSES = {{"stand": {{}}, "<pose>": {{"<bone name>": [x, y, z], ...}}, ...}}
        Every pose in brief.json, by its name. Values are rotations in degrees of your own bones, relative to the rest
        pose. An optional "__lift__": <metres> moves the whole body up or down (for kneeling or sitting, so the knees
        or seat touch the floor). An object with no moving parts has POSES = {{"stand": {{}}}}.
    def build(name): returns the root object: an armature for a character (each part parented to its bone), else
        the object (or an empty holding its parts). Build it at the world origin, standing on the floor (Z = 0),
        FACING +X, at the real size in brief.json, in metres.

Check your work with:  {check} model.py --name {name} --needs {needs}
It builds the model in Blender, renders front / three_quarter / side / back pictures and one picture per pose into
this folder, and lists problems. LOOK AT THE PICTURES: the model must look like the brief (and the reference
pictures), and every pose must look like its description. Stop when it reports no problems and the pictures are right.
Do not use the internet. Do not change any file except model.py.
When you finish, reply with one or two plain sentences about the model.
{extra}"""


def _dir(pid: str, cid: str) -> Path:
    d = ProjectStore.path_for(pid) / "models3d" / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rel(pid: str, path: Path) -> str:
    return str(Path(path).resolve().relative_to(ProjectStore.path_for(pid).resolve()))


def _item(project: Project, cid: str) -> ContextItem:
    for c in project.context:
        if c.id == cid:
            return c
    raise s3.Scene3DError(f"There is no character or object with id {cid}.")


def appears_in(project: Project, item: ContextItem) -> list:
    """The clips (with the 3D camera reference on) that show this character or object."""
    out = []
    for leaf in leaves(project):
        sc = leaf.script
        if leaf.kind != NodeKind.clip or not sc or not s3.enabled_for(project, leaf):
            continue
        if item.type == ContextType.actor and any(a.actor_id == item.id for a in sc.actors_in_shot):
            out.append(leaf)
        elif item.type == ContextType.object and item.title and item.title.lower() in (sc.visual + " " + " ".join(sc.action_beats)).lower():
            out.append(leaf)
    return out


def actions_of(project: Project, item: ContextItem) -> list[str]:
    """Every moment it appears in the scripts, as plain lines for the brief."""
    lines = []
    for leaf in appears_in(project, item):
        sc = leaf.script
        parts = [sc.visual] + sc.action_beats + ([f"starts: {sc.start_state}"] if sc.start_state else []) + \
                ([f"ends: {sc.end_state}"] if sc.end_state else [])
        lines.append(f"{leaf.title}: " + " · ".join(x for x in parts if x))
    return lines


def needed_items(project: Project, clip_ids: Optional[list[str]] = None) -> list[ContextItem]:
    """Characters and objects that appear in these clips (all clips when none are given) and need a 3D model."""
    wanted = set(clip_ids or [])
    out = []
    for c in project.context:
        if c.type not in (ContextType.actor, ContextType.object):
            continue
        if c.type == ContextType.actor and c.actor and "never seen" in (c.actor.description or "").lower():
            continue                                   # a narrator has no body
        clips = appears_in(project, c)
        if clips and (not wanted or any(cl.id in wanted for cl in clips)):
            out.append(c)
    return out


def describe(project: Project, models: dict) -> str:
    """The models, as the planner reads them: "Guru (actor_id ctx_1): 1.72 m standing; poses: sit 1.05 m, bless 1.72 m"."""
    lines = []
    for c in project.context:
        r = models.get(c.id)
        if r:
            poses = ", ".join(f"{name} {r.pose_heights.get(name, r.height):.2f} m" for name in r.poses) or "stand"
            lines.append(f"{c.title} (actor_id {c.id}): {r.height:.2f} m standing, {r.width:.2f} m wide; poses: {poses}")
    return "\n".join(lines)


def version_of(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def refs(project: Project) -> dict[str, ModelRef]:
    """Every built model, as the scenes use them: context id -> its script, size, poses and version."""
    out = {}
    for c in project.context:
        m = c.model3d
        if m and m.status == "built" and m.script:
            path = ProjectStore.path_for(project.id) / m.script
            if path.exists():
                out[c.id] = ModelRef(script=str(path), height=m.height or 1.7, width=m.width or 0.5, depth=m.depth or 0.4,
                                     poses=list(m.poses), pose_heights=dict(m.pose_heights), version=m.version)
    return out


async def write_brief(svc, pid: str, cid: str) -> Model3D:
    p = svc.load(pid)
    item = _item(p, cid)
    brief = await svc.brain.model_brief(p, item, actions_of(p, item))
    p = svc.load(pid)
    svc._ledger_llm(p, f"3D model brief {item.title}")
    item = _item(p, cid)
    old = item.model3d or Model3D()
    item.model3d = old.model_copy(update={"brief": brief.model_dump(), "updated_at": now_iso()})
    svc.save(p, snapshot=False)
    return item.model3d


async def build_model(svc, pid: str, cid: str, change: str = "", agent: Optional[str] = None) -> Model3D:
    """Write the brief (when there is none), let the agent build model.py, check it ourselves, and keep it when it passes.
    `change`: what you want different ("give him a longer white beard"); the agent improves the existing model."""
    from .agent import _call, pick_agents
    from .render import find_blender
    p = svc.load(pid)
    item = _item(p, cid)
    if not find_blender(svc.config.blender_path):
        raise s3.Scene3DError("Blender is not installed, so 3D models cannot be built. Install it free from blender.org.")
    builder, _, notes = pick_agents(svc, agent or p.settings.scene3d.agent)
    if not builder:
        raise s3.Scene3DError("Neither Claude Code nor Codex is installed, so 3D models cannot be built.")
    if not item.model3d or not item.model3d.brief:
        await write_brief(svc, pid, cid)
        p = svc.load(pid)
        item = _item(p, cid)
    m = item.model3d
    brief = dict(m.brief)
    needs = [x["name"] if isinstance(x, dict) else str(x) for x in brief.get("poses") or []] or ["stand"]
    name = "".join(ch for ch in item.title.lower().replace(" ", "_") if ch.isalnum() or ch == "_") or "model"
    st = p.settings.scene3d
    budget = max(st.agent_max_usd - (m.agent_cost_usd or 0), 0.0)
    home = _dir(pid, cid)
    m.status = "building"
    m.updated_at = now_iso()
    svc.save(p, snapshot=False)
    log: list[str] = list(notes)
    cost = 0.0
    last: dict = {}
    problems: list[str] = []
    for round_no in range(1, max(st.max_fix_rounds, 1) + 1):
        folder = home / f"round_{round_no}"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        (folder / "brief.json").write_text(json.dumps({"name": item.title, **brief}, indent=1))
        pictures = (item.actor.reference_sheet if item.actor else []) or [f for f in item.files if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        for i, f in enumerate(pictures[:3], 1):
            src = ProjectStore.path_for(pid) / f
            if src.exists():
                shutil.copy(src, folder / f"reference_{i}{src.suffix.lower()}")
        earlier = folder.parent / f"round_{round_no - 1}" / "model.py" if round_no > 1 else home / "model.py"
        if earlier.exists() and (change or round_no > 1):
            shutil.copy(earlier, folder / "model.py")
        extra = ""
        if change:
            extra += f"\nTHE USER WANTS THIS CHANGED (keep everything else): {change}\n"
        if problems:
            extra += "\nTHE LAST CHECK FOUND THESE PROBLEMS (fix them):\n" + "\n".join(f"- {x}" for x in problems) + "\n"
        task = AgentTask(folder=folder, role="model", request=change,
                         instructions=MODEL_TASK.format(check=f"{sys.executable} -m {CHECK}", name=name, needs=",".join(needs), extra=extra),
                         allowed_command=f"{sys.executable} -m {CHECK}", max_usd=budget, timeout_s=1800)
        try:
            res = await _call(svc, pid, builder, task, f"3D model {item.title} round {round_no}")
        except PluginError as exc:
            log.append(f"Round {round_no}: {builder} failed: {exc}")
            break
        cost += res.cost_usd
        budget -= res.cost_usd
        if not (folder / "model.py").exists():
            log.append(f"Round {round_no}: {builder} wrote no model.py ({res.summary or 'no reply'}).")
            problems = ["there is no model.py"]
            continue
        try:
            last = check_model(folder / "model.py", name, needs, svc.config.blender_path, svc.config.blender_engines)
        except RuntimeError as exc:
            raise s3.Scene3DError(str(exc)) from exc
        problems = list(last.get("problems") or [])
        log.append(f"Round {round_no}: {builder} — {res.summary or 'no reply'}" + (f" (${res.cost_usd:.2f})" if res.cost_usd else "")
                   + (f" Still wrong: {'; '.join(problems)}" if problems else " The check passes."))
        if last.get("ok") or (last.get("height") and all(x.startswith("poses the script needs") for x in problems)):
            for f in [folder / "model.py", folder / "model.blend", *[Path(v) for v in last.get("previews", {}).values()]]:
                if f.exists():
                    shutil.copy(f, home / f.name)
            break
        if budget <= 0:
            log.append(f"The money cap for this model (${st.agent_max_usd:.2f}) is reached.")
            break
    p = svc.load(pid)
    item = _item(p, cid)
    m = item.model3d
    built = bool(last.get("height")) and (home / "model.py").exists() and (last.get("ok") or all(
        x.startswith("poses the script needs") for x in problems))
    if built:
        text = (home / "model.py").read_text()
        m.status, m.script = "built", _rel(pid, home / "model.py")
        m.blend = _rel(pid, home / "model.blend") if (home / "model.blend").exists() else None
        m.previews = {Path(v).stem: _rel(pid, home / Path(v).name) for v in last.get("previews", {}).values() if (home / Path(v).name).exists()}
        m.height, m.width, m.depth = float(last.get("height") or 0), float(last.get("width") or 0), float(last.get("depth") or 0)
        m.poses, m.missing, m.version = list(last.get("poses") or []), list(last.get("missing") or []), version_of(text)
        m.pose_heights = {k: float(v) for k, v in (last.get("pose_heights") or {}).items()}
        m.issues = problems
    else:
        m.status = "failed"
        m.issues = problems or ["the model could not be built"]
    if change:
        m.changes = (m.changes + [change])[-30:]
    m.agent_cost_usd = round(m.agent_cost_usd + cost, 4)
    m.agent_log = (m.agent_log + [f"{now_iso()[:16]} {x}" for x in log])[-40:]
    m.updated_at = now_iso()
    svc.save(p)
    return m


async def ensure_models(svc, pid: str, clip_ids: Optional[list[str]] = None) -> list[str]:
    """Build the models these clips need and do not have yet (when models are on, and Blender and an agent exist).
    A model that failed before is not tried again here (press Build on its card to try again). Returns notes."""
    from .agent import pick_agents
    from .render import find_blender
    p = svc.load(pid)
    if not p.settings.scene3d.models:
        return []
    todo = [c for c in needed_items(p, clip_ids) if not c.model3d or c.model3d.status in ("needed", "building")]
    if not todo:
        return []
    if not find_blender(svc.config.blender_path):
        return ["Blender is not installed, so the characters stay plain shapes."]
    if not pick_agents(svc, p.settings.scene3d.agent)[0]:
        return ["Neither Claude Code nor Codex is installed, so the characters stay plain shapes."]
    notes = []
    for c in todo:
        try:
            m = await build_model(svc, pid, c.id)
            if m.status != "built":
                notes.append(f"The 3D model of {c.title} could not be built; it stays a plain shape ({'; '.join(m.issues)[:200]}).")
        except (s3.Scene3DError, PluginError) as exc:
            notes.append(f"The 3D model of {c.title} could not be built: {exc}")
    return notes
