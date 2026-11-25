"""Offline scene agent: a plain, predictable fix so the whole check-and-fix loop works (and is tested) with no agent
installed. As builder it points the camera at the middle of the figures from far enough back to see them all; as
checker it approves, unless `checker_problems` holds problems to report (tests use this)."""
from __future__ import annotations

import json

from ..base import AgentResult, AgentTask, SceneAgent


def simple_change(plan: dict, request: str) -> tuple[dict, str]:
    """The offline way to apply a change asked in plain words: a few common requests, done plainly.
    "bigger" / "twice as big" / "smaller" (the shape named in the request, else every figure), "closer" / "further"
    (the camera), "slower" / "faster" (how far things move). Returns the plan and what was done ("" = nothing understood)."""
    import re
    p = json.loads(json.dumps(plan))
    words = request.lower()
    named = [t for t in p.get("things", []) if t.get("label") and any(w in words for w in re.findall(r"[a-z]{3,}", t["label"].lower()))]
    targets = named or [t for t in p.get("things", []) if t.get("kind") == "figure"]
    done = []
    factor = 2.0 if re.search(r"twice|double|2x|much bigger|huge", words) else 1.5 if "bigger" in words or "larger" in words else \
        0.5 if re.search(r"half|much smaller", words) else 0.7 if "smaller" in words else None
    if factor:
        for t in targets:
            t["size"] = [round(v * factor, 3) for v in t["size"]]
        done.append(f"made {', '.join(t.get('label') or t['id'] for t in targets)} {factor:g} times the size")
    cam = p.get("camera", {}).get("keys", [])
    if cam and re.search(r"closer|nearer|zoom in|push in", words):
        for k in cam[-1:] if "end" in words else cam:
            k["at"] = [a + (b - a) * 0.5 for a, b in zip(k["at"], k.get("look_at", k["at"]))]
        done.append("moved the camera halfway closer" + (" at the end" if "end" in words else ""))
    elif cam and re.search(r"further|farther|zoom out|pull back|wider", words):
        for k in cam:
            k["at"] = [b + (a - b) * 1.6 for a, b in zip(k["at"], k.get("look_at", k["at"]))]
        done.append("moved the camera further back")
    speed = 0.5 if "slower" in words else 1.5 if "faster" in words else None
    if speed:
        for t in p.get("things", []):
            ks = t.get("keys", [])
            if len(ks) > 1:
                x0 = ks[0]["at"]
                for k in ks[1:]:
                    k["at"] = [a + (b - a) * speed for a, b in zip(x0, k["at"])]
        done.append("made the movement " + ("slower" if speed < 1 else "faster"))
    return p, "; ".join(done)


class FakeAgent(SceneAgent):
    name = "fake_agent"
    env_keys: list[str] = []
    description = "Free offline fixer (simple camera fix, for trying the flow)"

    def __init__(self, config=None):
        super().__init__(config)
        self.checker_problems: list[list[str]] = []     # one list per checker run, used in order
        self.runs: list[AgentTask] = []

    async def run(self, task: AgentTask) -> AgentResult:
        from ...scene3d.spec import ScenePlan, normalise, thing_at
        self.runs.append(task)
        if task.role == "checker":
            problems = self.checker_problems.pop(0) if self.checker_problems else []
            (task.folder / "verdict.json").write_text(json.dumps({"ok": not problems, "problems": problems}))
            return AgentResult(ok=True, summary="looked at the pictures: " + ("; ".join(problems) or "the camera matches"))
        if task.role == "reviewer":              # the AI checker: criteria once, then a verdict on the rendered frames
            crit_file = task.folder / "criteria.json"
            if not crit_file.exists():
                clip = json.loads((task.folder / "clip.json").read_text())
                crit = [f"The camera does what the script says: {clip.get('camera') or 'a clear view of the action'}",
                        "Every character is in the frame at the start, middle and end"]
                history = (task.folder / "history.md").read_text() if (task.folder / "history.md").exists() else ""
                asked = [ln.split(": ", 1)[1].split("  →")[0] for ln in history.splitlines() if ln.startswith("- ") and ": " in ln]
                crit += [f"As the user asked: {a}" for a in asked[-2:]]
                crit_file.write_text(json.dumps({"criteria": crit}))
            crit = json.loads(crit_file.read_text())["criteria"]
            problems = self.checker_problems.pop(0) if self.checker_problems else []
            results = [{"criterion": c, "met": not (problems and i == 0), "why": problems[0] if problems and i == 0 else "seen in the frames"}
                       for i, c in enumerate(crit)]
            (task.folder / "verdict.json").write_text(json.dumps({"ok": not problems, "results": results, "feedback": problems}))
            return AgentResult(ok=True, summary="checked the rendered frames: " + ("; ".join(problems) or "every criterion is met"))
        if task.role == "model":                  # the offline stand-in figure, sized and coloured from the brief
            brief = json.loads((task.folder / "brief.json").read_text())
            if task.request:
                for word, hexc in (("saffron", "#f4a62a"), ("white", "#f2f2f2"), ("blue", "#2f5fb3"), ("red", "#c0392b")):
                    if word in task.request.lower():
                        brief.setdefault("colours", {})["clothes"] = hexc
            if brief.get("kind") == "object":
                (task.folder / "model.py").write_text(object_script(brief))
            else:
                (task.folder / "model.py").write_text(mannequin_script(brief))
            return AgentResult(ok=True, summary="Built a simple jointed figure from the brief." if brief.get("kind") != "object"
                               else "Built a simple block object from the brief.")
        if task.role == "change":
            data, done = simple_change(json.loads((task.folder / "plan.json").read_text()), task.request)
            (task.folder / "plan.json").write_text(json.dumps(data, indent=1))
            return AgentResult(ok=True, summary=(done[:1].upper() + done[1:] + ".") if done else "I did not understand that change.")
        problems_file = task.folder / "problems.txt"
        if problems_file.exists():                # feedback in plain words ("bring the camera closer") is acted on first
            data, done_all = json.loads((task.folder / "plan.json").read_text()), []
            for line in problems_file.read_text().splitlines():
                data, done = simple_change(data, line)
                if done:
                    done_all.append(done)
            if done_all:
                (task.folder / "plan.json").write_text(json.dumps(data, indent=1))
                return AgentResult(ok=True, summary="; ".join(done_all))
        plan = normalise(ScenePlan.model_validate(json.loads((task.folder / "plan.json").read_text())))
        figures = [t for t in plan.things if t.kind == "figure"] or plan.things
        keys = []
        for t in (0.0, plan.seconds):
            pts = [thing_at(f, t) for f in figures]
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            spread = max([abs(p[0] - cx) + f.size[0] for p, f in zip(pts, figures)] + [max(f.size[2] for f in figures)])
            keys.append({"t": t, "at": [cx, cy - (spread * 2.2 + 6), 2.5], "look_at": [cx, cy, 1.0]})
        data = plan.model_dump()
        data["camera"]["keys"] = keys
        (task.folder / "plan.json").write_text(json.dumps(data, indent=1))
        return AgentResult(ok=True, summary="moved the camera back so every figure is in view")


MANNEQUIN = '''# A simple jointed figure (the offline stand-in for a model Claude Code or Codex would build from the brief).
# Contract: POSES = {name: {bone: [x, y, z] degrees}} (optional "__lift__": metres up/down for the whole body),
# build(name) -> root object, at the origin, on the floor, facing +X, real size.
import bpy
from mathutils import Matrix, Vector

H = __HEIGHT__
COLOURS = __COLOURS__
s = H / 1.75
POSES = __POSES__


def _material(name, hex_colour):
    h = hex_colour.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*lin, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*lin, 1)
    return m


def _box(name, size, centre, material, arm, bone):
    sx, sy, sz = size
    v = [(x * sx / 2, y * sy / 2, z * sz / 2) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.parent, ob.parent_type, ob.parent_bone = arm, "BONE", bone
    bpy.context.view_layer.update()
    ob.matrix_world = Matrix.Translation(Vector(centre))
    return ob


def build(name):
    arm = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    def bone(n, head, tail, parent=None):
        b = eb.new(n)
        b.head, b.tail = [v * s for v in head], [v * s for v in tail]
        if parent:
            b.parent = eb[parent]
        return b
    bone("hips", (0, 0, 0.95), (0, 0, 1.05))
    bone("spine", (0, 0, 1.05), (0, 0, 1.45), "hips")
    bone("head", (0, 0, 1.47), (0, 0, 1.75), "spine")
    for side, y in (("L", 0.21), ("R", -0.21)):
        bone(f"upper_arm.{side}", (0, y, 1.42), (0, y, 1.12), "spine")
        bone(f"forearm.{side}", (0, y, 1.12), (0, y, 0.86), f"upper_arm.{side}")
        bone(f"thigh.{side}", (0, y / 2, 0.95), (0, y / 2, 0.5), "hips")
        bone(f"shin.{side}", (0, y / 2, 0.5), (0, y / 2, 0.06), f"thigh.{side}")
    bpy.ops.object.mode_set(mode="OBJECT")
    skin, cloth, hair = (_material(name + "_" + k, COLOURS.get(k, d)) for k, d in
                         (("skin", "#c68e5c"), ("clothes", "#e8e8e8"), ("hair", "#2b2b2b")))
    _box(name + "_torso", (0.24 * s, 0.38 * s, 0.5 * s), (0, 0, 1.2 * s), cloth, arm, "spine")
    _box(name + "_pelvis", (0.22 * s, 0.34 * s, 0.16 * s), (0, 0, 0.97 * s), cloth, arm, "hips")
    _box(name + "_head", (0.2 * s, 0.18 * s, 0.24 * s), (0, 0, 1.6 * s), skin, arm, "head")
    _box(name + "_hair", (0.21 * s, 0.19 * s, 0.06 * s), (-0.01 * s, 0, 1.73 * s), hair, arm, "head")
    _box(name + "_nose", (0.04 * s, 0.03 * s, 0.05 * s), (0.11 * s, 0, 1.6 * s), skin, arm, "head")
    for side, y in (("L", 0.21), ("R", -0.21)):
        _box(f"{name}_upper_arm.{side}", (0.09 * s, 0.09 * s, 0.3 * s), (0, y * s, 1.27 * s), cloth, arm, f"upper_arm.{side}")
        _box(f"{name}_forearm.{side}", (0.08 * s, 0.08 * s, 0.24 * s), (0, y * s, 0.99 * s), skin, arm, f"forearm.{side}")
        _box(f"{name}_hand.{side}", (0.09 * s, 0.05 * s, 0.1 * s), (0, y * s, 0.82 * s), skin, arm, f"forearm.{side}")
        _box(f"{name}_thigh.{side}", (0.13 * s, 0.13 * s, 0.45 * s), (0, y / 2 * s, 0.72 * s), cloth, arm, f"thigh.{side}")
        _box(f"{name}_shin.{side}", (0.11 * s, 0.11 * s, 0.42 * s), (0, y / 2 * s, 0.28 * s), cloth, arm, f"shin.{side}")
        _box(f"{name}_foot.{side}", (0.24 * s, 0.1 * s, 0.06 * s), (0.06 * s, y / 2 * s, 0.03 * s), skin, arm, f"shin.{side}")
    return arm
'''

# the poses this simple figure knows (a real agent writes the poses the brief asks for, for its own bones)
MANNEQUIN_POSES = {
    "stand": {},
    "walk": {"thigh.L": [0, 0, -25], "thigh.R": [0, 0, 25], "shin.R": [0, 0, 20], "upper_arm.L": [0, 0, 20], "upper_arm.R": [0, 0, -20]},
    "sit": {"thigh.L": [0, 0, -90], "thigh.R": [0, 0, -90], "shin.L": [0, 0, 90], "shin.R": [0, 0, 90], "__lift__": -0.47},
    "kneel": {"shin.L": [0, 0, 90], "shin.R": [0, 0, 90], "__lift__": -0.44},
    "bow": {"spine": [0, 0, -50], "head": [0, 0, -15], "upper_arm.L": [0, 0, -15], "upper_arm.R": [0, 0, -15]},
    "touch_ground": {"shin.L": [0, 0, 90], "shin.R": [0, 0, 90], "spine": [0, 0, -75], "head": [0, 0, -10],
                     "upper_arm.L": [0, 0, -40], "upper_arm.R": [0, 0, -40], "__lift__": -0.44},
    "namaste": {"upper_arm.L": [0, 0, -25], "upper_arm.R": [0, 0, -25], "forearm.L": [-25, 0, -110], "forearm.R": [25, 0, -110]},
    "raise_hand": {"upper_arm.R": [0, 0, -150], "forearm.R": [0, 0, -10]},
    "reach": {"upper_arm.R": [0, 0, -80]},
}


def mannequin_script(brief: dict) -> str:
    """model.py for the offline stand-in figure, sized and coloured from the brief, with the poses it can do."""
    import re
    height = float(brief.get("height_m") or 1.75)
    colours = {k: v for k, v in (brief.get("colours") or {}).items() if re.fullmatch(r"#[0-9a-fA-F]{6}", str(v))}
    poses = dict(MANNEQUIN_POSES)
    s = height / 1.75
    for p in poses.values():
        if "__lift__" in p:
            p["__lift__"] = round(p["__lift__"] * s, 3)
    return (MANNEQUIN.replace("__HEIGHT__", repr(round(height, 3))).replace("__COLOURS__", repr(colours))
            .replace("__POSES__", json.dumps(poses)))


OBJECT = '''# A simple block object (the offline stand-in for a model Claude Code or Codex would build from the brief).
import bpy

W, D, H = __SIZE__
COLOUR = __COLOUR__
POSES = {}


def build(name):
    h = COLOUR.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    m = bpy.data.materials.new(name + "_colour")
    m.diffuse_color = (*rgb, 1)
    v = [(x * W / 2, y * D / 2, z * H) for x in (-1, 1) for y in (-1, 1) for z in (0, 1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob
'''


def object_script(brief: dict) -> str:
    size = (float(brief.get("width_m") or 0.5), float(brief.get("depth_m") or 0.5), float(brief.get("height_m") or 0.5))
    colour = next(iter((brief.get("colours") or {}).values()), "#8a6a4a")
    return OBJECT.replace("__SIZE__", repr(size)).replace("__COLOUR__", repr(colour))
