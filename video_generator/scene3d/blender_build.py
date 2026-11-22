"""Runs INSIDE Blender (it imports bpy). Builds one clip's rough 3D scene from a scene plan and renders it.

    blender --background --factory-startup --python blender_build.py -- plan.json OUT_DIR ENGINE WIDTH HEIGHT

Writes, in OUT_DIR:
    scene.blend          the scene, to open in Blender and adjust by hand if wanted
    frames/0001.png ...  one picture per frame
    result.json          {"ok": true, "engine": ..., "blender": ..., "frames": N}

Nothing here needs the video-generator package: the plan arrives as JSON (see spec.py for its shape).
Movement between keys is straight and even (LINEAR), the same as the checks in spec.py assume.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector


def args():
    rest = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    plan_path, out_dir = rest[0], rest[1]
    engine = rest[2] if len(rest) > 2 else "BLENDER_WORKBENCH"
    width = int(rest[3]) if len(rest) > 3 else 1280
    height = int(rest[4]) if len(rest) > 4 else 720
    with open(plan_path) as f:
        return json.load(f), out_dir, engine, width, height


def hex_rgba(h, alpha=1.0):
    h = (h or "#888888").lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    # the picture colours are sRGB; Blender works in linear colour
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return (*lin, alpha)


_materials = {}


def material(colour):
    if colour in _materials:
        return _materials[colour]
    m = bpy.data.materials.new(f"flat_{colour.lstrip('#')}")
    m.use_nodes = True
    rgba = hex_rgba(colour)
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = 0.8
    m.diffuse_color = rgba                     # what the Workbench engine shows
    _materials[colour] = m
    return m


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def mesh(kind, name, size, colour, parent, offset=(0, 0, 0)):
    w, d, h = size
    if kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.5)
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.5, depth=1)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = (w, d, h)
    ob.location = (offset[0], offset[1], offset[2] + h / 2)
    ob.data.materials.append(material(colour))
    ob.parent = parent
    return ob


def build_thing(th):
    """A plain shape that stands for a character or object. Its origin is the centre of its base."""
    root = bpy.data.objects.new(th["id"], None)
    bpy.context.collection.objects.link(root)
    w, d, h = (list(th.get("size") or [0.5, 0.5, 1.8]) + [1, 1, 1])[:3]
    colour = th.get("colour") or "#888888"
    shape = th.get("shape", "box")
    if shape == "person":                       # body and head, so the camera can read which way up it is
        mesh("cylinder", th["id"] + "_body", (w, d, h * 0.82), colour, root)
        head = min(w, d, h * 0.18) * 1.05
        mesh("sphere", th["id"] + "_head", (head, head, head), colour, root, offset=(0, 0, h * 0.82))
    elif shape == "creature":                   # a long body with a head at the front (+X)
        mesh("cube", th["id"] + "_body", (w * 0.75, d, h * 0.7), colour, root, offset=(-w * 0.1, 0, 0))
        mesh("cube", th["id"] + "_head", (w * 0.3, d * 0.7, h * 0.45), colour, root, offset=(w * 0.38, 0, h * 0.45))
    else:
        mesh(shape, th["id"] + "_shape", (w, d, h), colour, root)
    return root


def yaw_for(keys, i):
    k = keys[i]
    if k.get("yaw_deg") is not None:
        return math.radians(k["yaw_deg"])
    nxt = keys[i + 1] if i + 1 < len(keys) else None
    prv = keys[i - 1] if i > 0 else None
    a, b = (k, nxt) if nxt else (prv, k) if prv else (None, None)
    if a and b:
        dx, dy = b["at"][0] - a["at"][0], b["at"][1] - a["at"][1]
        if abs(dx) + abs(dy) > 1e-3:
            return math.atan2(dy, dx)
    return None


def frame_of(t, fps):
    return 1 + int(round(t * fps))


def animate(ob, keys, fps):
    last_yaw = None
    for i, k in enumerate(sorted(keys, key=lambda k: k["t"])):
        f = frame_of(k["t"], fps)
        ob.location = Vector(k["at"])
        ob.keyframe_insert("location", frame=f)
        yaw = yaw_for(sorted(keys, key=lambda k: k["t"]), i)
        yaw = last_yaw if yaw is None else yaw
        if yaw is not None:
            ob.rotation_euler = (0, 0, yaw)
            ob.keyframe_insert("rotation_euler", frame=f)
            last_yaw = yaw


def build_set(s):
    lx, ly, lz = (list(s.get("size") or [20, 12, 6]) + [20, 12, 6])[:3]
    bpy.ops.mesh.primitive_plane_add(size=1)
    floor = bpy.context.active_object
    floor.name = "floor"
    floor.scale = (lx, ly, 1)
    floor.data.materials.append(material(s.get("floor_colour") or "#9a9a9a"))
    if s.get("walls"):
        wall = s.get("wall_colour") or "#bdbdbd"
        for name, loc, scale in (("wall_back", (0, ly / 2, lz / 2), (lx, 0.1, lz)),
                                 ("wall_left", (-lx / 2, 0, lz / 2), (0.1, ly, lz)),
                                 ("wall_right", (lx / 2, 0, lz / 2), (0.1, ly, lz))):
            bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
            ob = bpy.context.active_object
            ob.name = name
            ob.scale = scale
            ob.data.materials.append(material(wall))


def build_camera(cam, fps):
    data = bpy.data.cameras.new("camera")
    data.lens = float(cam.get("lens_mm") or 35)
    data.sensor_width = 36
    data.sensor_fit = "AUTO"
    ob = bpy.data.objects.new("camera", data)
    bpy.context.collection.objects.link(ob)
    target = bpy.data.objects.new("camera_target", None)
    bpy.context.collection.objects.link(target)
    c = ob.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    for k in sorted(cam.get("keys") or [], key=lambda k: k["t"]):
        f = frame_of(k["t"], fps)
        ob.location = Vector(k["at"])
        ob.keyframe_insert("location", frame=f)
        target.location = Vector(k["look_at"])
        target.keyframe_insert("location", frame=f)
        if k.get("lens_mm"):
            data.lens = float(k["lens_mm"])
            data.keyframe_insert("lens", frame=f)
    bpy.context.scene.camera = ob
    return ob


def build_lights(lights):
    for i, li in enumerate(lights or [{"kind": "sun", "at": [-6, -6, 10], "look_at": [0, 0, 0], "strength": 3}]):
        kind = {"sun": "SUN", "point": "POINT", "area": "AREA"}.get(li.get("kind", "sun"), "SUN")
        data = bpy.data.lights.new(f"light_{i}", kind)
        data.energy = float(li.get("strength", 3)) * (1 if kind == "SUN" else 300)
        ob = bpy.data.objects.new(f"light_{i}", data)
        bpy.context.collection.objects.link(ob)
        ob.location = Vector(li.get("at") or [-6, -6, 10])
        direction = Vector(li.get("look_at") or [0, 0, 0]) - ob.location
        ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_render(scene, engine, width, height, fps, frames, out_dir):
    scene.render.engine = engine
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.frame_start, scene.frame_end = 1, frames
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(out_dir, "frames", "")
    world = scene.world or bpy.data.worlds.new("world")
    scene.world = world
    world.color = (0.55, 0.62, 0.72)
    if engine == "BLENDER_WORKBENCH":
        sh = scene.display.shading
        sh.light = "STUDIO"
        sh.color_type = "MATERIAL"
        sh.show_shadows = True
        sh.shadow_intensity = 0.35
        sh.show_cavity = False
        scene.display.render_aa = "8"
    elif engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = 8
        scene.cycles.use_denoising = False
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = (0.55, 0.62, 0.72, 1)
            bg.inputs["Strength"].default_value = 0.6


def main():
    plan, out_dir, engine, width, height = args()
    os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"   # even movement, as the checks assume
    clear()
    scene = bpy.context.scene
    fps = int(plan.get("fps") or 24)
    frames = max(1, int(round(float(plan.get("seconds") or 5) * fps)))
    scene.unit_settings.system = "METRIC"
    build_set(plan.get("set") or {})
    for th in plan.get("things") or []:
        animate(build_thing(th), th.get("keys") or [{"t": 0, "at": [0, 0, 0]}], fps)
    build_camera(plan.get("camera") or {}, fps)
    build_lights(plan.get("lights"))
    setup_render(scene, engine, width, height, fps, frames, out_dir)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "scene.blend"))
    bpy.ops.render.render(animation=True)
    with open(os.path.join(out_dir, "result.json"), "w") as f:
        json.dump({"ok": True, "engine": engine, "blender": bpy.app.version_string, "frames": frames}, f)


try:
    main()
except Exception as exc:          # tell the caller what went wrong, then stop Blender with an error code
    import traceback
    traceback.print_exc()
    try:
        out = sys.argv[sys.argv.index("--") + 2]
        with open(os.path.join(out, "result.json"), "w") as f:
            json.dump({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}, f)
    except Exception:
        pass
    sys.exit(1)
