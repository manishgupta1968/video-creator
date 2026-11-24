"""Open a clip's 3D scene in your own Blender, to look around it (the 3D camera reference add-on).

The app runs on your computer, so it can start the Blender you installed. Blender opens the clip's scene.blend and
the 3D view looks through the camera, so pressing Play shows the shot the video model will follow.

It is for looking. The tool builds the reference from its own scene plan, so changes saved in Blender are not used:
ask for changes in the clip's "Change the 3D scene" box instead (they are applied, checked and rendered by themselves).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..project import ProjectStore
from ..tree import find
from . import service as s3
from .render import find_blender

# runs inside Blender once its window is up: every 3D view looks through the camera, in flat colours
LOOK_THROUGH_CAMERA = """
import bpy
def _look_through_camera():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.region_3d.view_perspective = "CAMERA"
                        space.shading.type = "SOLID"
                        space.shading.color_type = "MATERIAL"
    return None
bpy.app.timers.register(_look_through_camera, first_interval=1.0)
"""


def command(blender: str, blend: Path) -> list[str]:
    return [blender, str(blend), "--python-expr", LOOK_THROUGH_CAMERA]


def open_in_blender(svc, pid: str, nid: str) -> dict:
    """Start Blender on the clip's scene. Returns {path, note}; raises Scene3DError with the reason when it cannot."""
    p = svc.load(pid)
    n = find(p, nid)
    s = n.scene3d
    if not s or not s.plan:
        raise s3.Scene3DError(f"Clip '{n.title}' has no 3D scene yet. Make it first (describe it, or press \"Plan, check and render\").")
    if not s.blend:
        raise s3.Scene3DError("This 3D preview was drawn as a free sketch, so there is no Blender scene to open. "
                              "Install Blender (free, blender.org) and render the preview again.")
    blend = ProjectStore.path_for(pid) / s.blend
    if not blend.exists():
        raise s3.Scene3DError("The Blender file of this clip is missing. Render the preview again.")
    exe = find_blender(svc.config.blender_path)
    if not exe:
        raise s3.Scene3DError("Blender is not installed (or not found). Install it free from blender.org, or set its path "
                              "with `vg config set blender_path <path>`.")
    detach = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}    # Blender stays open on its own
    subprocess.Popen(command(exe, blend), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detach)
    note = ("Blender is opening this clip's scene, looking through the camera. Press Play (space bar) to watch the shot. "
            "Changes you save in Blender are not used: ask for changes in the \"Change the 3D scene\" box.")
    why = s3.stale_reason(n)
    if why:
        note = f"This Blender file is from before your last change ({why}); render the preview again to see it. " + note
    return {"path": str(blend), "note": note}


# runs inside Blender once its window is up: the largest area shows the video editor's preview, so Play shows the film
SHOW_FILM = """
import bpy
def _show_film():
    for window in bpy.context.window_manager.windows:
        areas = sorted(window.screen.areas, key=lambda a: a.width * a.height, reverse=True)
        if areas:
            area = areas[0]
            area.type = "SEQUENCE_EDITOR"
            for space in area.spaces:
                if space.type == "SEQUENCE_EDITOR":
                    space.view_type = "PREVIEW"
    return None
bpy.app.timers.register(_show_film, first_interval=1.0)
"""


def open_film(svc, pid: str) -> dict:
    """Start Blender on the whole 3D film (film.blend). Returns {path, note}; raises Scene3DError with the reason."""
    from .film import stale_reason
    p = svc.load(pid)
    f = p.scene3d_film
    if not f or not f.video:
        raise s3.Scene3DError("The whole 3D film has not been made yet. Press \"Make the whole 3D film\" first.")
    if not f.blend:
        raise s3.Scene3DError("The film has no Blender file (Blender was not installed when it was made). "
                              "Install Blender and make the film again; you can still watch it here.")
    blend = ProjectStore.path_for(pid) / f.blend
    exe = find_blender(svc.config.blender_path)
    if not exe or not blend.exists():
        raise s3.Scene3DError("Blender (or the film's Blender file) was not found. Make the film again.")
    detach = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([exe, str(blend), "--python-expr", SHOW_FILM], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detach)
    note = ("Blender is opening the whole 3D film in its video editor. Press Play (space bar) to watch every clip in "
            "order. It is for watching: ask for changes in each clip's \"Change the 3D scene\" box.")
    why = stale_reason(p)
    if why:
        note = f"This film is out of date ({why}); make it again to see the latest previews. " + note
    return {"path": str(blend), "note": note}
