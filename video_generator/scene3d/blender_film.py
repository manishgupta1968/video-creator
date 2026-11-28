"""Runs INSIDE Blender (it imports bpy). Puts the whole 3D film together in Blender's video editor (the Sequencer):
every clip's preview one after another, with its number and title written on top, saved as film.blend.

    blender --background --factory-startup --python blender_film.py -- film.json OUT.blend

film.json: {"fps": 24, "width": 854, "height": 480,
            "clips": [{"path": "/abs/clip.mp4", "label": "1.1 · The arrival", "audio": "/abs/voice.wav" or ""}, …]}
"""
import json
import sys

import bpy


def strips_of(se):
    """The editor's strips. Blender 4.4+ calls them `strips` (and Blender 5 removed the old name `sequences`).
    An empty collection counts as false in Python, so test for the attribute, never for its contents."""
    return se.strips if hasattr(se, "strips") else se.sequences


def length_of(strip, fallback):
    for name in ("frame_final_duration", "frame_duration"):
        value = getattr(strip, name, None)
        if value:
            return int(value)
    return int(fallback)


def add_title(strips, name, frame, length):
    """A text strip over [frame, frame + length). Blender 5 takes `length`; older versions take `frame_end`."""
    try:
        return strips.new_effect(name=name, type="TEXT", channel=2, frame_start=frame, length=length)
    except TypeError:
        return strips.new_effect(name=name, type="TEXT", channel=2, frame_start=frame, frame_end=frame + length)


def main():
    rest = sys.argv[sys.argv.index("--") + 1:]
    with open(rest[0]) as f:
        film = json.load(f)
    out = rest[1]
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    scene = bpy.context.scene
    scene.render.fps = int(film.get("fps") or 24)
    scene.render.resolution_x = int(film.get("width") or 854)
    scene.render.resolution_y = int(film.get("height") or 480)
    scene.render.resolution_percentage = 100
    se = scene.sequence_editor_create()
    strips = strips_of(se)
    frame = 1
    for i, clip in enumerate(film.get("clips") or []):
        movie = strips.new_movie(name=f"clip_{i + 1:02d}", filepath=clip["path"], channel=1, frame_start=frame)
        length = length_of(movie, clip.get("frames") or 1)
        try:                                     # the clip's number and title, small, at the bottom
            text = add_title(strips, f"label_{i + 1:02d}", frame, length)
            text.text = clip.get("label", "")
            text.font_size = 28
            text.location = (0.5, 0.06)
            text.use_shadow = True
        except Exception:
            pass                                 # a Blender without text strips still gets the clips
        if clip.get("audio"):                    # the clip's spoken words, so the film plays with sound in Blender too
            try:
                strips.new_sound(name=f"voice_{i + 1:02d}", filepath=clip["audio"], channel=3, frame_start=frame)
            except Exception as exc:
                print("SOUND_SKIPPED", i + 1, exc)
        frame += length
    scene.frame_start, scene.frame_end = 1, max(frame - 1, 1)
    scene.frame_current = 1
    for ws in bpy.data.workspaces:          # Blender 5: each workspace's video editor shows its own "sequencer scene"
        if hasattr(ws, "sequencer_scene"):
            ws.sequencer_scene = scene
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print("FILM_OK", frame - 1)


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
