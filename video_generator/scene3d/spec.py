"""The scene plan: a rough 3D version of one clip (the "3D camera reference" add-on).

A scene plan says, in metres and seconds:
- the set (floor size, optional walls, colours);
- the things in it: people, animals and objects as plain coloured shapes, each with a path over time;
- the camera: where it is and what it looks at over time, and its lens;
- the light.

Blender (or the free sketch renderer when Blender is not installed) turns it into a reference video. The video model
then copies the camera and the movement, and takes the looks from the character and location pictures.

Coordinates: metres, Z is up, the floor is Z = 0, the set is centred on X = 0, Y = 0.
Example: a set 20 m long (X) and 10 m wide (Y) runs from X = -10 to 10 and Y = -5 to 5.

Everything here is plain Python (no Blender), so the checks run anywhere and in tests.
"""
from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, Field

Vec = list[float]

# Distinct flat colours for the stand-in shapes. The prompt names them ("the red figure is Dan in @Image1"), so the video
# model can tell the characters apart. Order matters: the first colours are the easiest to tell apart.
PALETTE: list[tuple[str, str]] = [
    ("red", "#d62828"), ("blue", "#1f6feb"), ("green", "#2a9d3f"), ("yellow", "#f2c500"), ("purple", "#8338ec"),
    ("orange", "#f77f00"), ("cyan", "#00b4d8"), ("pink", "#ff5d8f"), ("brown", "#8d5524"), ("white", "#f5f5f5"),
]
NEUTRAL = {"floor": "#9a9a9a", "wall": "#bdbdbd", "prop": "#7a7a7a"}


def colour_name(hex_colour: str) -> str:
    """The plain name of one of our palette colours, or the nearest one."""
    h = (hex_colour or "").lower()
    for name, value in PALETTE:
        if value == h:
            return name
    try:
        r, g, b = (int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "grey"

    def dist(v: str) -> int:
        rr, gg, bb = (int(v[i:i + 2], 16) for i in (1, 3, 5))
        return (r - rr) ** 2 + (g - gg) ** 2 + (b - bb) ** 2
    return min(PALETTE, key=lambda p: dist(p[1]))[0]


class Key(BaseModel):
    """Where a thing is at a moment: the centre of its base on the floor (or in the air) at `t` seconds."""
    t: float = 0
    at: Vec = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    yaw_deg: Optional[float] = None     # which way it faces, 0 = towards +X; None = the way it moves
    pose: Optional[str] = None          # a pose its 3D model knows ("walk", "kneel", "bow" …); None = keep the pose before


class Thing(BaseModel):
    id: str
    label: str = ""                     # what it stands for, in words: "Dan, the man in the blue jacket"
    actor_id: str = ""                  # the project's actor (context item) it stands for, if any
    kind: Literal["figure", "prop"] = "figure"     # figure = a character the video model must recognise; prop = scenery
    shape: Literal["person", "creature", "box", "sphere", "cylinder"] = "box"
    size: Vec = Field(default_factory=lambda: [0.5, 0.5, 1.8])     # width (X), depth (Y), height (Z) in metres
    colour: str = ""                    # "" = given a distinct palette colour
    keys: list[Key] = Field(default_factory=lambda: [Key()])
    must_be_seen: bool = True           # figures: should be in the frame for most of the clip
    model: str = ""                     # the context item whose 3D model is used for this shape ("" = a plain shape)


class CameraKey(BaseModel):
    t: float = 0
    at: Vec = Field(default_factory=lambda: [0.0, -8.0, 1.6])
    look_at: Vec = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    lens_mm: Optional[float] = None     # None = the camera's lens


class Camera(BaseModel):
    lens_mm: float = 35                 # 24-35 mm wide, 50-85 mm close
    keys: list[CameraKey] = Field(default_factory=lambda: [CameraKey()])
    move: str = ""                      # the move in words, for the prompt: "comes down from above, then pans right to Bruiser"


class Light(BaseModel):
    kind: Literal["sun", "point", "area"] = "sun"
    at: Vec = Field(default_factory=lambda: [-6.0, -6.0, 10.0])
    look_at: Vec = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    strength: float = 3.0


class SetSpec(BaseModel):
    name: str = ""                      # "glass terrarium", "small apartment hallway"
    size: Vec = Field(default_factory=lambda: [20.0, 12.0, 6.0])      # length (X), width (Y), wall height (Z)
    walls: bool = False                 # back, left and right walls (the front stays open for the camera)
    floor_colour: str = NEUTRAL["floor"]
    wall_colour: str = NEUTRAL["wall"]


class ModelRef(BaseModel):
    """A built 3D model a scene can use: the script that builds it inside Blender, its size and the poses it knows."""
    script: str                         # absolute path of its model.py
    height: float = 1.7
    width: float = 0.5
    depth: float = 0.4
    poses: list[str] = Field(default_factory=list)
    pose_heights: dict[str, float] = Field(default_factory=dict)   # how tall it is in each pose
    version: str = ""                   # changes when the model is rebuilt (so scenes that use it go out of date)


class ScenePlan(BaseModel):
    set_id: str = ""
    models: dict[str, ModelRef] = Field(default_factory=dict)   # context id -> its 3D model (filled by the tool)                    # clips with the same set_id share one set (same place in every shot)
    set: SetSpec = Field(default_factory=SetSpec)
    things: list[Thing] = Field(default_factory=list)
    camera: Camera = Field(default_factory=Camera)
    lights: list[Light] = Field(default_factory=lambda: [Light()])
    seconds: float = 5
    fps: int = 24
    aspect: str = "16:9"
    notes: str = ""                     # anything the planner wants the builder to know


class Issue(BaseModel):
    severity: Literal["info", "minor", "major"] = "minor"
    text: str


# ----------------------------------------------------------------- maths
def _lerp(a: Vec, b: Vec, f: float) -> Vec:
    return [a[i] + (b[i] - a[i]) * f for i in range(3)]


def _at(keys, t: float, field: str) -> Vec:
    ks = sorted(keys, key=lambda k: k.t)
    if not ks:
        return [0.0, 0.0, 0.0]
    if t <= ks[0].t:
        return list(getattr(ks[0], field))
    for a, b in zip(ks, ks[1:]):
        if a.t <= t <= b.t:
            f = 0.0 if b.t == a.t else (t - a.t) / (b.t - a.t)
            return _lerp(getattr(a, field), getattr(b, field), f)
    return list(getattr(ks[-1], field))


def thing_at(thing: Thing, t: float) -> Vec:
    """Where a thing is at time t. Movement between keys is straight and even (the Blender builder uses the same)."""
    return _at(thing.keys, t, "at")


def camera_at(cam: Camera, t: float) -> tuple[Vec, Vec, float]:
    ks = sorted(cam.keys, key=lambda k: k.t)
    lens = cam.lens_mm
    before = [k for k in ks if k.t <= t and k.lens_mm]
    after = [k for k in ks if k.t >= t and k.lens_mm]
    if before and after and after[0].t > before[-1].t:
        f = (t - before[-1].t) / (after[0].t - before[-1].t)
        lens = before[-1].lens_mm + (after[0].lens_mm - before[-1].lens_mm) * f
    elif before:
        lens = before[-1].lens_mm
    elif after:
        lens = after[0].lens_mm
    return _at(ks, t, "at"), _at(ks, t, "look_at"), float(lens)


def aspect_ratio(aspect: str) -> float:
    try:
        a, b = (float(x) for x in aspect.split(":"))
        return a / b
    except ValueError:
        return 16 / 9


SENSOR_MM = 36.0     # Blender's default sensor; with "auto" fit it spans the longer side of the frame


def _basis(eye: Vec, target: Vec) -> tuple[Vec, Vec, Vec]:
    fwd = [target[i] - eye[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in fwd)) or 1.0
    fwd = [c / n for c in fwd]
    up = [0.0, 0.0, 1.0]
    if abs(fwd[2]) > 0.999:          # looking straight down or up: use +Y as "up" on the picture
        up = [0.0, 1.0, 0.0]
    right = [fwd[1] * up[2] - fwd[2] * up[1], fwd[2] * up[0] - fwd[0] * up[2], fwd[0] * up[1] - fwd[1] * up[0]]
    n = math.sqrt(sum(c * c for c in right)) or 1.0
    right = [c / n for c in right]
    true_up = [right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2], right[0] * fwd[1] - right[1] * fwd[0]]
    return fwd, right, true_up


def project(eye: Vec, target: Vec, lens_mm: float, aspect: str, point: Vec) -> Optional[tuple[float, float, float]]:
    """Where a 3D point lands in the picture: (x, y, depth) with x and y from 0 to 1 (0,0 = top left).
    None when the point is behind the camera."""
    fwd, right, up = _basis(eye, target)
    d = [point[i] - eye[i] for i in range(3)]
    z = sum(d[i] * fwd[i] for i in range(3))
    if z <= 0.05:
        return None
    x = sum(d[i] * right[i] for i in range(3))
    y = sum(d[i] * up[i] for i in range(3))
    ar = aspect_ratio(aspect)
    half_long = SENSOR_MM / 2 / lens_mm          # tan of half the angle across the longer side
    half_w, half_h = (half_long, half_long / ar) if ar >= 1 else (half_long * ar, half_long)
    return 0.5 + x / z / half_w / 2, 0.5 - y / z / half_h / 2, z


def pose_at(thing: Thing, t: float) -> Optional[str]:
    """The pose a shape is in at time t: the last key at or before t that names one."""
    pose = None
    for k in sorted(thing.keys, key=lambda k: k.t):
        if k.t <= t + 1e-6 and k.pose:
            pose = k.pose
    return pose


def corners(thing: Thing, t: float, plan: Optional["ScenePlan"] = None) -> list[Vec]:
    cx, cy, cz = thing_at(thing, t)
    w, dpt, h = (list(thing.size) + [1, 1, 1])[:3]
    ref = plan.models.get(thing.model) if plan is not None and thing.model else None
    if ref:                                    # a 3D model in a pose is as tall as that pose (kneeling is lower)
        h = ref.pose_heights.get(pose_at(thing, t) or "stand", h)
    return [[cx + sx * w / 2, cy + sy * dpt / 2, cz + sz * h] for sx in (-1, 1) for sy in (-1, 1) for sz in (0, 1)]


def visibility(plan: ScenePlan, thing: Thing, t: float) -> tuple[str, float]:
    """How much of a thing the camera sees at time t: ('in' | 'partly' | 'out' | 'behind', share of its box in frame)."""
    eye, target, lens = camera_at(plan.camera, t)
    pts = [project(eye, target, lens, plan.aspect, c) for c in corners(thing, t, plan)]
    front = [p for p in pts if p]
    if not front:
        return "behind", 0.0
    inside = [p for p in front if 0 <= p[0] <= 1 and 0 <= p[1] <= 1]
    share = len(inside) / len(pts)
    if share == 1:
        return "in", 1.0
    xs, ys = [p[0] for p in front], [p[1] for p in front]
    overlaps = max(xs) >= 0 and min(xs) <= 1 and max(ys) >= 0 and min(ys) <= 1
    return ("partly", max(share, 0.01)) if overlaps else ("out", 0.0)


# ----------------------------------------------------------------- tidy + check
def normalise(plan: ScenePlan) -> ScenePlan:
    """A copy that is safe to build: keys sorted and inside the clip, a key at the start and end, distinct colours."""
    p = plan.model_copy(deep=True)
    p.seconds = max(float(p.seconds or 0), 0.5)
    p.fps = int(p.fps or 24)

    def tidy(keys, make):
        ks = sorted(keys or [make()], key=lambda k: k.t)
        for k in ks:
            k.t = min(max(float(k.t), 0.0), p.seconds)
        if ks[0].t > 0:
            first = ks[0].model_copy(deep=True)
            first.t = 0.0
            ks.insert(0, first)
        if ks[-1].t < p.seconds:
            last = ks[-1].model_copy(deep=True)
            last.t = p.seconds
            ks.append(last)
        return ks

    used: set[str] = set()
    for th in p.things:
        th.keys = tidy(th.keys, Key)
        th.size = [max(float(v), 0.05) for v in (list(th.size) + [1, 1, 1])[:3]]
    for th in p.things:                     # keep the colours the planner chose when they are distinct
        if th.kind == "figure" and th.colour and th.colour.lower() not in used:
            used.add(th.colour.lower())
        elif th.kind == "figure":
            th.colour = ""
    free = [v for _, v in PALETTE if v not in used]
    for th in p.things:
        if th.kind == "figure" and not th.colour:
            th.colour = free.pop(0) if free else PALETTE[0][1]
        elif th.kind == "prop" and not th.colour:
            th.colour = NEUTRAL["prop"]
    p.camera.keys = tidy(p.camera.keys, CameraKey)
    p.camera.lens_mm = min(max(float(p.camera.lens_mm or 35), 8.0), 300.0)
    return p


def check(plan: ScenePlan) -> list[Issue]:
    """Plain-words problems with a plan, found by measuring (no AI, no Blender). Major issues should be fixed before
    a reference is rendered; minor ones are shown to the user."""
    p = normalise(plan)
    out: list[Issue] = []
    lx, ly, lz = (list(p.set.size) + [10, 10, 5])[:3]
    if not p.things:
        out.append(Issue(severity="major", text="The scene has nothing in it. Add the characters as shapes."))
    ids = [t.id for t in p.things]
    if len(ids) != len(set(ids)):
        out.append(Issue(severity="major", text="Two shapes have the same id. Every shape needs its own id."))
    for th in p.things:
        for k in th.keys:
            if abs(k.at[0]) > lx / 2 + 0.01 or abs(k.at[1]) > ly / 2 + 0.01:
                out.append(Issue(severity="minor", text=f"'{th.label or th.id}' goes outside the set at {k.t:g} s "
                                                        f"(the set is {lx:g} m by {ly:g} m)."))
                break
    for k in p.camera.keys:
        for th in p.things:
            c = thing_at(th, k.t)
            w, d, h = th.size
            if abs(k.at[0] - c[0]) < w / 2 and abs(k.at[1] - c[1]) < d / 2 and c[2] <= k.at[2] <= c[2] + h:
                out.append(Issue(severity="major", text=f"At {k.t:g} s the camera is inside '{th.label or th.id}'."))
    times = [0.0, p.seconds / 2, p.seconds]
    words = {0: "start", 1: "middle", 2: "end"}
    for th in p.things:
        if th.kind != "figure" or not th.must_be_seen:
            continue
        missing = [words[i] for i, t in enumerate(times) if visibility(p, th, t)[0] in ("out", "behind")]
        if len(missing) == 3:
            out.append(Issue(severity="major", text=f"'{th.label or th.id}' is never in the camera's view."))
        elif missing:
            out.append(Issue(severity="minor", text=f"'{th.label or th.id}' is out of the camera's view at the {', '.join(missing)}."))
    return out


def continue_from(previous: ScenePlan, plan: ScenePlan) -> ScenePlan:
    """For a clip that continues the one before: its camera starts exactly where the previous camera ended, and every
    shape that is in both clips starts where it ended. This is what makes the join between the two clips smooth."""
    prev = normalise(previous)
    p = plan.model_copy(deep=True)
    eye, target, lens = camera_at(prev.camera, prev.seconds)
    first = CameraKey(t=0.0, at=eye, look_at=target, lens_mm=lens)
    p.camera.keys = [first] + [k for k in p.camera.keys if k.t > 0]
    ends = {th.id: (thing_at(th, prev.seconds), pose_at(th, prev.seconds)) for th in prev.things}
    for th in p.things:
        if th.id in ends:
            at, pose = ends[th.id]
            th.keys = [Key(t=0.0, at=at, pose=pose)] + [k for k in th.keys if k.t > 0]   # same place, same pose
    p.set_id, p.set = prev.set_id, prev.set.model_copy(deep=True)     # a continuing shot is always in the same place
    return p


def legend(plan: ScenePlan) -> list[tuple[str, str]]:
    """(colour name, what it stands for) for every figure: the words the video prompt uses."""
    p = normalise(plan)
    return [(colour_name(th.colour), th.label or th.id) for th in p.things if th.kind == "figure"]


def legend_sentence(plan: ScenePlan, where: str = "the camera reference") -> str:
    """'In the camera reference, the red shape is Dan, the blue shape is Bruiser and the green shape is the lizard;
    grey shapes are scenery.' The words that tell a picture or video model which plain shape is which character."""
    parts = [f"the {colour} shape is {label}" for colour, label in legend(plan)]
    if not parts:
        return ""
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    props = any(t.kind == "prop" for t in plan.things)
    return f"In {where}, {joined}" + ("; grey shapes are scenery." if props else ".")


def layout_words(plan: ScenePlan) -> str:
    """The instruction that turns the first picture of a 3D layout into a realistic first picture of the clip."""
    return ("Picture 1 is a rough 3D layout made of plain coloured shapes. Make a realistic, cinematic still with exactly the "
            "same framing, camera angle, lens and positions as picture 1, and none of its plain look. "
            + legend_sentence(plan, "picture 1") + " The other pictures show how they really look.")


def _h(v: Vec) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2)


def camera_words(plan: ScenePlan) -> str:
    """The planned camera move in plain words, measured from the plan, for ANY video model (also those that cannot take
    a reference video). Example: "Camera (from the 3D plan): starts far above the scene (12.0 m) looking down, comes
    down to knee height (0.5 m), moves in from 14 m to 6 m away; wide lens (28 mm)." """
    p = normalise(plan)
    (e0, t0, l0), (e1, t1, l1) = camera_at(p.camera, 0.0), camera_at(p.camera, p.seconds)

    def height(z: float) -> str:
        return ("at ground level" if z < 0.3 else "at knee height" if z < 0.8 else "at waist height" if z < 1.3 else
                "at eye level" if z < 2.1 else "just above eye level" if z < 4 else "high up" if z < 10 else "far above the scene")

    def to(z: float) -> str:
        return height(z).removeprefix("at ")
    d0 = math.dist(e0, t0)
    d1 = math.dist(e1, t1)
    parts = [f"starts {height(e0[2])} ({e0[2]:.1f} m)" + (" looking down" if t0[2] < e0[2] - 1 else "")]
    if abs(e1[2] - e0[2]) > 0.4:
        parts.append(f"{'comes down' if e1[2] < e0[2] else 'rises'} to {to(e1[2])} ({e1[2]:.1f} m)")
    if abs(d1 - d0) > max(0.5, 0.15 * d0):
        parts.append(f"moves {'in' if d1 < d0 else 'back'} from {d0:.0f} m to {d1:.0f} m away")
    a0 = math.atan2(t0[1] - e0[1], t0[0] - e0[0])
    a1 = math.atan2(t1[1] - e1[1], t1[0] - e1[0])
    turn = (math.degrees(a1 - a0) + 180) % 360 - 180
    if abs(turn) > 8:
        parts.append(f"turns to the {'left' if turn > 0 else 'right'} (about {abs(turn):.0f}°)")
    side = [e1[i] - e0[i] for i in range(2)]
    if _h(side) > 0.8 and abs(d1 - d0) <= max(0.5, 0.15 * d0):
        parts.append(f"travels {_h(side):.0f} m alongside the action")
    if len(parts) == 1:
        parts.append("holds still")
    lens = l1 if abs(l1 - l0) < 1 else None
    lens_text = (f"{'wide' if lens < 35 else 'normal' if lens < 50 else 'long'} lens ({lens:.0f} mm)" if lens
                 else f"zooms from {l0:.0f} mm to {l1:.0f} mm")
    return "Camera (from the 3D plan): " + ", ".join(parts) + f"; {lens_text}."
