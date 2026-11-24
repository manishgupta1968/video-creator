"""Plan, check, build and approve one clip's 3D camera reference, and keep the result on the clip.

The steps, for one clip:
1. plan     the AI brain writes a scene plan from the clip's script (shapes, paths, camera path, light).
            A clip that continues the one before starts where that clip's camera and figures ended; a clip in the
            same place reuses the same set.
2. check    measured problems in plain words (a figure never in view, the camera inside a shape ...). No AI, no cost.
3. build    Blender in the background (or the free sketch) renders reference.mp4 and the check pictures.
4. approve  you approve the preview, or it is approved by itself when `auto_approve` is on and no major problem was found.

Nothing here spends money except the brain call in step 1, which is the same kind of call as writing a script.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from .. import deps as deps_mod
from .. import media
from ..models import DependencyType, Node, NodeKind, Project, Scene3DClip, now_iso  # noqa: F401
from ..project import ProjectStore
from ..tree import ancestors, find, leaves
from . import render as render_mod
from .spec import ScenePlan, camera_at, check, continue_from, normalise, thing_at


class Scene3DError(RuntimeError):
    pass


def enabled_for(project: Project, node: Node) -> bool:
    """Is the 3D camera reference on for this clip? Its own choice, else the nearest part above, else the video's."""
    if node.scene3d_enabled is not None:
        return node.scene3d_enabled
    for a in reversed(ancestors(project, node.id)):
        if a.scene3d_enabled is not None:
            return a.scene3d_enabled
    return project.settings.scene3d.enabled


def plan_hash(plan: ScenePlan) -> str:
    return hashlib.sha1(normalise(plan).model_dump_json().encode()).hexdigest()[:12]


def is_current(clip: Node) -> bool:
    """The rendered files belong to the plan the clip has now."""
    s = clip.scene3d
    return bool(s and s.plan and s.video and s.plan_hash == plan_hash(s.plan))


LENGTH_SLACK_S = 0.25      # a reference this much shorter or longer than the clip is still used (the clip is cut to length)


def stale_reason(clip: Node) -> str:
    """Why the clip's rendered reference cannot be used as it is ("" = it can): the plan changed, or the clip's length did."""
    s = clip.scene3d
    if not s or not s.plan or not s.video:
        return "no reference has been rendered yet"
    if s.plan_hash != plan_hash(s.plan):
        return "the 3D plan changed after it was rendered"
    secs = clip.duration.likely_s
    if secs and abs(secs - s.plan.seconds) > LENGTH_SLACK_S:
        return f"the clip is now {secs:g} s long but the reference is {s.plan.seconds:g} s; plan it again"
    return ""


def continues_from(project: Project, node: Node) -> Optional[Node]:
    for d in deps_mod.upstream(project, node.id):
        if d.type == DependencyType.continues_from:
            up = find(project, d.from_id)
            if up.scene3d and up.scene3d.plan:
                return up
    return None


def shared_set(project: Project, node: Node) -> Optional[ScenePlan]:
    """The plan of the nearest earlier clip that already has a set (same place in every shot is decided once)."""
    earlier = []
    for leaf in leaves(project):
        if leaf.id == node.id:
            break
        earlier.append(leaf)
    for leaf in reversed(earlier):
        if leaf.scene3d and leaf.scene3d.plan and leaf.scene3d.plan.set_id:
            return leaf.scene3d.plan
    return None


def _ending(plan: ScenePlan) -> str:
    p = normalise(plan)
    eye, target, lens = camera_at(p.camera, p.seconds)
    figs = "; ".join(f"{th.id} ({th.label}) at {[round(v, 2) for v in thing_at(th, p.seconds)]}" for th in p.things)
    return f"camera at {[round(v, 2) for v in eye]} looking at {[round(v, 2) for v in target]}, lens {lens:g} mm; {figs}"


def _clip_dir(pid: str, nid: str) -> Path:
    d = ProjectStore.path_for(pid) / "clips" / nid / "scene3d"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rel(pid: str, path: Optional[Path]) -> Optional[str]:
    if not path:
        return None
    return str(Path(path).resolve().relative_to(ProjectStore.path_for(pid).resolve()))


def _clip(project: Project, nid: str) -> Node:
    n = find(project, nid)
    if n.kind != NodeKind.clip:
        raise Scene3DError(f"'{n.title}' is not a clip: only clips have a 3D camera reference.")
    return n


def issues_text(plan: ScenePlan) -> tuple[list[str], bool]:
    found = check(plan)
    return [f"{i.severity}: {i.text}" for i in found], any(i.severity == "major" for i in found)


async def plan_clip(svc, pid: str, nid: str, wishes: str = "") -> Scene3DClip:
    """Step 1 and 2: write the scene plan with the AI brain and check it. `wishes` = what you want in the scene, in
    your own words ("a big empty kitchen, the chef at the far end"); the script is used either way."""
    p = svc.load(pid)
    n = _clip(p, nid)
    if not n.script:
        raise Scene3DError(f"Clip '{n.title}' has no script yet. Write the script first; the 3D plan is made from it.")
    prev = continues_from(p, n)
    base = shared_set(p, n)
    shared = (f"set_id {base.set_id}: {base.set.model_dump_json()}" if base else "")
    from .models3d import describe, refs as model_refs
    models = model_refs(p)
    poses_text = describe(p, models)
    plan = await svc.brain.scene_plan(p, n, shared_set=shared, previous=_ending(prev.scene3d.plan) if prev else "",
                                      wishes=wishes, poses=poses_text,
                                      pose_map={cid: r.poses for cid, r in models.items()})
    svc._ledger_llm(p, f"3D plan {nid}")
    svc.save(p, snapshot=False)
    plan.seconds = n.duration.likely_s or plan.seconds
    plan.aspect = p.settings.aspect
    plan.fps = p.settings.fps
    if prev:
        plan = continue_from(prev.scene3d.plan, plan)
    elif base and plan.set_id == base.set_id:
        plan.set = base.set.model_copy(deep=True)            # the same place keeps exactly the same size and colours
    plan = normalise(attach_models(plan, models))
    texts, _ = issues_text(plan)
    p = svc.load(pid)
    n = _clip(p, nid)
    n.scene3d = Scene3DClip(plan=plan, status="planned", issues=texts, wishes=wishes.strip())
    svc.save(p)
    return n.scene3d


def attach_models(plan: ScenePlan, models: dict) -> ScenePlan:
    """Every shape that stands for a character or object with a built 3D model uses that model (its real size, and
    only poses it knows); the others stay plain shapes."""
    p = plan.model_copy(deep=True)
    used = {}
    for th in p.things:
        ref = models.get(th.actor_id) or models.get(th.model)
        if not ref:
            th.model = ""
            th.scale = 1.0
            for k in th.keys:
                k.pose = None
            continue
        cid = th.actor_id if th.actor_id in models else th.model
        th.model = cid
        used[cid] = ref
        k = min(max(th.scale or 1.0, 0.05), 20.0)
        th.scale = k
        th.size = [round(v * k, 3) for v in ([max(ref.depth, 0.2), max(ref.width, 0.2), max(ref.height, 0.2)] if th.kind == "figure" else
                                             [max(ref.width, 0.1), max(ref.depth, 0.1), max(ref.height, 0.1)])]
        for k in th.keys:
            if k.pose and k.pose not in ref.poses:
                k.pose = None
    p.models = used
    return p


def keep_resizes(before: ScenePlan, after: ScenePlan) -> ScenePlan:
    """A change that made a modelled character or object bigger or smaller becomes its scale (the model itself keeps
    its real size, so the size alone would be put back)."""
    old = {t.id: t for t in before.things}
    p = after.model_copy(deep=True)
    for th in p.things:
        o = old.get(th.id)
        if not o or not o.model or th.model != o.model or th.scale != o.scale:
            continue
        ratios = [n / b for n, b in zip(th.size, o.size) if b > 0 and abs(n - b) > 1e-6]
        if ratios:
            th.scale = round(o.scale * max(ratios, key=lambda r: abs(r - 1)), 3)
    return p


def refresh_models(project: Project, plan: ScenePlan) -> ScenePlan:
    """The plan with the models as they are now (a rebuilt model has a new version, so the preview goes out of date)."""
    from .models3d import refs as model_refs
    return attach_models(plan, model_refs(project))


def set_plan(svc, pid: str, nid: str, plan: ScenePlan) -> Scene3DClip:
    """Replace a clip's plan (an edit by you or by an agent). The rendered files become out of date."""
    p = svc.load(pid)
    n = _clip(p, nid)
    plan = normalise(refresh_models(p, plan))
    texts, _ = issues_text(plan)
    old = n.scene3d or Scene3DClip()
    n.scene3d = old.model_copy(update={"plan": plan, "status": "planned", "issues": texts, "approved_by": "",
                                       "updated_at": now_iso()})
    svc.save(p)
    return n.scene3d


async def build_clip(svc, pid: str, nid: str, renderer: Optional[str] = None) -> Scene3DClip:
    """Step 3 and 4: render the reference, then approve it by itself when that is switched on and the checks pass."""
    p = svc.load(pid)
    n = _clip(p, nid)
    if not n.scene3d or not n.scene3d.plan:
        raise Scene3DError(f"Clip '{n.title}' has no 3D plan yet. Make the plan first.")
    plan = normalise(refresh_models(p, n.scene3d.plan))        # the 3D models as they are now
    settings = p.settings.scene3d
    how = renderer or settings.renderer
    size = media.frame_size(p.settings.aspect, render_mod.REFERENCE_RESOLUTION)
    out = _clip_dir(pid, nid)
    try:
        result = await render_mod.render(plan, out, size, blender=svc.config.blender_path,
                                         engines=svc.config.blender_engines, use_blender=how != "sketch")
    except (render_mod.RenderError, media.MediaError) as exc:
        p = svc.load(pid)
        n = _clip(p, nid)
        n.scene3d.status = "failed"
        n.scene3d.notes = [str(exc)]
        svc.save(p)
        raise Scene3DError(str(exc)) from exc
    if how == "blender" and result.renderer != "blender":
        result.notes.append("Blender was asked for but could not be used (see the notes above).")
    texts, major = issues_text(plan)
    p = svc.load(pid)
    n = _clip(p, nid)
    s = n.scene3d
    s.plan = plan
    s.status = "rendered"
    s.renderer, s.engine = result.renderer, result.engine
    s.video, s.first, s.last = _rel(pid, result.video), _rel(pid, result.first), _rel(pid, result.last)
    s.checks = {k: _rel(pid, v) for k, v in result.checks.items()}
    s.blend = _rel(pid, result.blend)
    s.issues, s.notes = texts, result.notes
    s.plan_hash = plan_hash(plan)
    s.approved_by = ""
    if nid in p.run.scene3d_asked:              # a new preview: the next run asks about it again
        p.run.scene3d_asked.remove(nid)
    if settings.auto_approve and not major and not stale_reason(n):
        s.status, s.approved_by = "approved", "auto"
        _outdate_made_clip(n)
    s.updated_at = now_iso()
    svc.save(p)
    return s


def approve(svc, pid: str, nid: str) -> Scene3DClip:
    """You approve the rendered preview: its reference is then used when the clip's video is made."""
    p = svc.load(pid)
    n = _clip(p, nid)
    why = stale_reason(n)
    if why:
        raise Scene3DError(f"Clip '{n.title}' has no up-to-date 3D preview to approve ({why}). Build it first.")
    n.scene3d.status, n.scene3d.approved_by = "approved", "you"
    n.scene3d.updated_at = now_iso()
    _outdate_made_clip(n)
    svc.save(p)
    return n.scene3d


def _outdate_made_clip(n: Node) -> None:
    """A clip already made without this reference is marked out of date, so you can make it again with it."""
    from ..models import NodeStatus
    if n.status == NodeStatus.done and n.scene3d and n.scene3d.status == "approved":
        n.status = NodeStatus.stale
        note = "Made before its 3D camera reference was approved: make it again to follow the reference."
        if note not in n.warnings:
            n.warnings.append(note)



def models_changed(project: Project, node: Node) -> str:
    """'' when the 3D models the preview was rendered with are still the same; else which one was rebuilt."""
    from .models3d import refs as model_refs
    s = node.scene3d
    if not s or not s.plan or not s.plan.models:
        return ""
    now = model_refs(project)
    for cid, ref in s.plan.models.items():
        if cid not in now or now[cid].version != ref.version:
            title = next((c.title for c in project.context if c.id == cid), cid)
            return f"the 3D model of {title} changed after the preview was rendered"
    return ""


def ready_reference(project: Project, node: Node) -> Optional[Scene3DClip]:
    """The approved, up-to-date reference of a clip, or None (the clip is then made the usual way)."""
    s = node.scene3d
    if enabled_for(project, node) and s and s.status == "approved" and not stale_reason(node) and not models_changed(project, node):
        return s
    return None
