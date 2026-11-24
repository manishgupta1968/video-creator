"""Runs INSIDE Blender (it imports bpy). Builds ONE 3D model from its model.py, checks it, renders pictures of it and
saves it as model.blend.

    blender --background --factory-startup --python blender_model.py -- model.py OUT_DIR NAME ENGINE '["kneel","bow"]'

The model.py contract (what Claude Code / Codex writes; nothing about the model itself is fixed by the tool):
    POSES = {"stand": {}, "kneel": {"thigh.L": [90, 0, 0], ...}, ...}
        pose name -> {bone name: [x, y, z] rotation in degrees, relative to the rest pose}; an optional "__lift__"
        moves the whole body up or down in metres (kneeling, sitting). A model without bones
        (most objects) has POSES = {} or only {"rest": {}}.
    def build(name): -> the root object (an armature for a character, else an empty or a mesh).
        Builds the model at the world origin, standing on the floor (Z = 0), facing +X, at real size in metres.

Writes, in OUT_DIR: model.blend, front.png, side.png, back.png, three_quarter.png, pose_<name>.png, result.json
    result.json: {"ok", "height", "width", "depth", "bones", "poses", "missing", "problems", "blender"}
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector


def args():
    rest = sys.argv[sys.argv.index("--") + 1:]
    return rest[0], rest[1], rest[2], (rest[3] if len(rest) > 3 else "BLENDER_WORKBENCH"), json.loads(rest[4] if len(rest) > 4 else "[]")


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def family(root):
    out, todo = [], [root]
    while todo:
        ob = todo.pop()
        out.append(ob)
        todo.extend(ob.children)
    return out


def bounds(objs):
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    lo, hi = Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
    found = False
    for ob in objs:
        if ob.type != "MESH":
            continue
        ev = ob.evaluated_get(deps)
        for c in ev.bound_box:
            w = ev.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
            found = True
    return (lo, hi) if found else (Vector((0, 0, 0)), Vector((0, 0, 0)))


def apply_pose(arm, pose):
    if not arm or arm.type != "ARMATURE":
        return []
    bad = []
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, 0, 0)
    arm.location.z = float((pose or {}).get("__lift__", 0) or 0)       # the whole body up or down (kneeling, sitting)
    for bone, rot in (pose or {}).items():
        if bone.startswith("__"):
            continue
        pb = arm.pose.bones.get(bone)
        if pb is None:
            bad.append(bone)
            continue
        pb.rotation_euler = tuple(math.radians(float(v)) for v in (list(rot) + [0, 0, 0])[:3])
    bpy.context.view_layer.update()
    return bad


def setup_render(engine, out_dir):
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    world = scene.world or bpy.data.worlds.new("world")
    scene.world = world
    world.color = (0.62, 0.66, 0.72)
    if engine == "BLENDER_WORKBENCH":
        sh = scene.display.shading
        sh.light, sh.color_type, sh.show_shadows = "STUDIO", "MATERIAL", False
    elif engine == "CYCLES":
        scene.cycles.device, scene.cycles.samples, scene.cycles.use_denoising = "CPU", 8, False
    sun = bpy.data.objects.new("preview_sun", bpy.data.lights.new("preview_sun", "SUN"))
    sun.data.energy = 3
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    bpy.context.collection.objects.link(sun)
    cam = bpy.data.objects.new("preview_camera", bpy.data.cameras.new("preview_camera"))
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    return cam


def shoot(cam, lo, hi, angle_deg, path):
    centre = (lo + hi) / 2
    size = max((hi - lo).length, 0.5)
    a = math.radians(angle_deg)
    cam.data.lens = 50
    cam.location = centre + Vector((math.cos(a), math.sin(a), 0.25)) * size * 2.0
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    script, out_dir, name, engine, needed = args()
    os.makedirs(out_dir, exist_ok=True)
    result = {"ok": False, "problems": [], "blender": bpy.app.version_string}
    clear()
    ns = {"__name__": "model", "bpy": bpy}
    with open(script) as f:
        exec(compile(f.read(), script, "exec"), ns)
    poses = ns.get("POSES") or {}
    if not callable(ns.get("build")):
        raise RuntimeError("model.py has no build(name) function")
    root = ns["build"](name)
    if root is None or not hasattr(root, "name"):
        raise RuntimeError("build(name) did not return the model's root object")
    objs = family(root)
    arm = next((o for o in objs if o.type == "ARMATURE"), None)
    apply_pose(arm, poses.get("stand") or poses.get("rest") or {})
    lo, hi = bounds(objs)
    size = hi - lo
    result.update({"height": round(size.z, 3), "width": round(size.x, 3), "depth": round(size.y, 3),
                   "bones": [b.name for b in arm.data.bones] if arm else [], "poses": sorted(poses)})
    if size.z <= 0.01:
        result["problems"].append("the model has no visible parts (no meshes, or they are flat)")
    if lo.z < -0.05 or lo.z > 0.05:
        result["problems"].append(f"the model should stand on the floor (Z = 0), but its lowest point is at Z = {lo.z:.2f}")
    for pose_name, pose in poses.items():
        bad = apply_pose(arm, pose) if arm else list((pose or {}).keys())
        if bad:
            result["problems"].append(f"pose '{pose_name}' moves bones that do not exist: {', '.join(bad[:6])}")
    result["missing"] = [p for p in needed if p not in poses]
    if result["missing"]:
        result["problems"].append("poses the script needs but the model does not have: " + ", ".join(result["missing"]))
    cam = setup_render(engine, out_dir)
    apply_pose(arm, poses.get("stand") or poses.get("rest") or {})
    for view, angle in (("front", 0), ("three_quarter", 40), ("side", 90), ("back", 180)):
        shoot(cam, lo, hi, angle, os.path.join(out_dir, f"{view}.png"))
    result["pose_heights"] = {}
    for pose_name, pose in poses.items():
        apply_pose(arm, pose)
        plo, phi = bounds(objs)
        result["pose_heights"][pose_name] = round(max(phi.z, 0.05), 3)     # how tall it is in this pose (for the camera)
        shoot(cam, plo, phi, 40, os.path.join(out_dir, f"pose_{pose_name}.png"))
    apply_pose(arm, poses.get("stand") or poses.get("rest") or {})
    for ob in (bpy.data.objects.get("preview_sun"), bpy.data.objects.get("preview_camera")):
        if ob:
            bpy.data.objects.remove(ob, do_unlink=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "model.blend"))
    result["ok"] = not result["problems"]
    with open(os.path.join(out_dir, "result.json"), "w") as f:
        json.dump(result, f)


try:
    main()
except Exception as exc:
    import traceback
    traceback.print_exc()
    try:
        out = sys.argv[sys.argv.index("--") + 2]
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "result.json"), "w") as f:
            json.dump({"ok": False, "problems": [f"model.py failed: {exc.__class__.__name__}: {exc}"]}, f)
    except Exception:
        pass
    sys.exit(1)
