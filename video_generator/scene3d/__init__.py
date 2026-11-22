"""The "3D camera reference" add-on: a rough 3D scene per clip whose camera path the video model follows.

Optional: a project uses it only when `settings.scene3d.enabled` is on; otherwise the tool works exactly as before.

    spec.py           the scene plan (shapes, camera path, light) and the checks, in plain Python
    render.py         turns a plan into reference.mp4 + pictures (Blender in the background, or a free sketch)
    blender_build.py  the script Blender runs (it imports bpy, so it is never imported by the tool itself)
    service.py        plan, check and build a clip's reference, and keep the result on the clip
"""
