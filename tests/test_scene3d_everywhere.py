"""The 3D scene in every clip, the run that makes missing previews first, and the whole 3D film."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from video_generator import estimate as E
from video_generator import media
from video_generator.models import DependencyType
from video_generator.project import ProjectStore
from video_generator.scene3d import film as film_mod
from video_generator.scene3d import render as R
from video_generator.scene3d import service as s3
from video_generator.scene3d import viewer
from video_generator.scene3d.spec import CameraKey, camera_words
from video_generator.tree import find

from .conftest import requires_ffmpeg
from .fake_vendors import Vendors
from .test_scenarios import run_all
from .test_scene3d import approved, chase, keyframe_of, two_shot_project


# ----------------------------------------------------------------- the camera move in words
def test_the_camera_move_is_written_out_from_the_plan():
    words = camera_words(chase(4))
    assert words.startswith("Camera (from the 3D plan): starts far above the scene (12.0 m) looking down")
    assert "comes down to eye level" in words and "moves in from 18 m to 9 m away" in words and "wide lens (28 mm)" in words
    p = chase(4)
    p.camera.keys = [CameraKey(t=0, at=[0, -9, 1.7], look_at=[-6, 0, 1]), CameraKey(t=4, at=[0, -9, 1.7], look_at=[6, 0, 1])]
    assert "turns to the right" in camera_words(p)
    p.camera.keys = [CameraKey(t=0, at=[0, -9, 0.5], look_at=[0, 0, 0.5])]
    assert camera_words(p) == "Camera (from the 3D plan): starts at knee height (0.5 m), holds still; wide lens (28 mm)."


# ----------------------------------------------------------------- every clip uses its 3D scene
def setup(svc, monkeypatch, links=(), second_on=True):
    v = Vendors(svc, monkeypatch)
    p, ids = two_shot_project(svc, links=links)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.renderer = "sketch"
    if not second_on:
        find(p, ids[1]).scene3d_enabled = False
    svc.save(p)
    return v, p, ids


@requires_ffmpeg
def test_with_a_reference_model_the_clip_uses_the_video_the_first_picture_and_the_camera_words(svc, monkeypatch):
    v, p, ids = setup(svc, monkeypatch, second_on=False)
    approved(svc, p.id, ids[0])
    q = svc.load(p.id)
    uses = E.plan_clip(q, find(q, ids[0]), svc.reg).uses3d
    assert uses == ["the reference video (camera path and movement)", "the first picture is made from the 3D layout",
                    "the camera move, written out from the 3D plan"]
    run_all(svc, p.id)
    call = next(c for c in v.calls["video"] if c.reference_video)
    assert "Camera (from the 3D plan):" in call.prompt


@requires_ffmpeg
def test_without_a_reference_model_the_clip_still_ends_as_the_layout_ends(svc, monkeypatch):
    v, p, ids = setup(svc, monkeypatch, second_on=False)
    svc.config.disabled_models += ["seedance_2_reference", "seedance_2_fast_reference"]
    approved(svc, p.id, ids[0])
    q = svc.load(p.id)
    plan = E.plan_clip(q, find(q, ids[0]), svc.reg)
    assert plan.end_picture and "the last picture is made from the 3D layout" in plan.uses3d
    run_all(svc, p.id)
    end = next(r for r in v.calls["picture"] if ids[0] in str(r.out) and Path(r.out).name.endswith("_end.png"))
    assert Path(end.references[0]).name == "last.png" and "This is the LAST picture of the clip" in end.prompt
    call = next(c for c in v.calls["video"] if ids[0] in str(c.out))
    assert call.end_frame and Path(call.end_frame).name.endswith("_end.png") and "Camera (from the 3D plan):" in call.prompt


@requires_ffmpeg
def test_a_continuing_clip_starts_from_the_clip_before_and_ends_on_its_layout(svc, monkeypatch):
    v, p, ids = setup(svc, monkeypatch, links=[(0, 1, DependencyType.continues_from.value)])
    approved(svc, p.id, ids[0])
    approved(svc, p.id, ids[1])
    q = svc.load(p.id)
    uses = E.plan_clip(q, find(q, ids[1]), svc.reg).uses3d
    assert "it starts from the clip before (smooth join)" in uses and "the last picture is made from the 3D layout" in uses
    run_all(svc, p.id)
    second = [c for c in v.calls["video"] if ids[1] in str(c.out)][-1]
    assert Path(second.start_frame).name.startswith("handoff_from_") and second.end_frame


# ----------------------------------------------------------------- the run makes missing previews first
@requires_ffmpeg
def test_generate_makes_missing_previews_first_and_waits_for_your_approval(svc, monkeypatch):
    v, p, ids = setup(svc, monkeypatch)
    run_all(svc, p.id)
    q = svc.load(p.id)
    assert all(find(q, i).scene3d and find(q, i).scene3d.status == "rendered" for i in ids)
    assert q.run.status == "paused" and "2 3D preview(s) wait for your approval" in q.run.message
    assert v.calls["video"] == []                                     # nothing was paid for
    assert sorted(q.run.scene3d_asked) == sorted(ids)
    run_all(svc, p.id)                                                # asked once: now they are made the usual way
    q = svc.load(p.id)
    assert all(find(q, i).status.value == "done" for i in ids) and not any(c.reference_video for c in v.calls["video"])


@requires_ffmpeg
def test_with_auto_approve_the_run_makes_previews_and_carries_on(svc, monkeypatch):
    v, p, ids = setup(svc, monkeypatch)
    q = svc.load(p.id)
    q.settings.scene3d.auto_approve = True
    svc.save(q)
    run_all(svc, p.id)
    q = svc.load(p.id)
    assert all(find(q, i).status.value == "done" for i in ids)
    assert sum(1 for c in v.calls["video"] if c.reference_video) == 2


# ----------------------------------------------------------------- the whole 3D film
@requires_ffmpeg
def test_the_whole_film_joins_every_clip_and_says_why_a_clip_has_no_preview(svc, monkeypatch):
    monkeypatch.setattr(film_mod, "find_blender", lambda configured="": None)       # as on a computer without Blender
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.renderer = "sketch"
    find(p, ids[1]).scene3d_enabled = False
    svc.save(p)
    q = svc.load(p.id)
    assert film_mod.stale_reason(q) == "the whole 3D film has not been made yet"
    with pytest.raises(s3.Scene3DError, match="has not been made yet"):
        viewer.open_film(svc, p.id)
    f = asyncio.run(film_mod.make_film(svc, p.id))
    assert [(pt.source, pt.why) for pt in f.parts] == [("3d", ""), ("card", "3D camera reference off for this clip")]
    total = sum(find(q, i).duration.likely_s for i in ids)
    assert media.probe_duration(ProjectStore.path_for(p.id) / f.video) == pytest.approx(total, abs=0.2)
    assert f.blend is None and "can be watched here but not opened in Blender" in f.notes[0]
    assert film_mod.stale_reason(svc.load(p.id)) == ""
    plan = find(svc.load(p.id), ids[0]).scene3d.plan
    plan.camera.lens_mm = 60
    s3.set_plan(svc, p.id, ids[0], plan)
    assert "changed after the film was made" in film_mod.stale_reason(svc.load(p.id))


@requires_ffmpeg
@pytest.mark.skipif(not R.find_blender(), reason="Blender is not installed")
def test_the_whole_film_opens_in_blender_one_clip_after_another(svc, monkeypatch, tmp_path):
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.renderer = "sketch"
    svc.save(p)
    f = asyncio.run(film_mod.make_film(svc, p.id))
    blend = ProjectStore.path_for(p.id) / f.blend
    out = subprocess.run([R.find_blender(), "-b", str(blend), "--python-expr",
                          "import bpy; se=bpy.context.scene.sequence_editor; st=se.strips if hasattr(se,'strips') else se.sequences; "
                          "print('STRIPS', sorted((s.type, s.frame_final_start) for s in st))"],
                         capture_output=True, text=True, timeout=180).stdout
    line = next(l for l in out.splitlines() if l.startswith("STRIPS"))
    assert line.count("'MOVIE'") == 2 and line.count("'TEXT'") == 2
    log = tmp_path / "args.json"
    exe = tmp_path / "blender"
    import sys
    exe.write_text(f"#!{sys.executable}\nimport json, sys\nopen({str(log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n")
    exe.chmod(0o755)
    monkeypatch.setenv("VG_BLENDER", str(exe))
    r = viewer.open_film(svc, p.id)
    assert "video editor" in r["note"]
    for _ in range(50):
        if log.exists():
            break
        asyncio.run(asyncio.sleep(0.1))
    args = json.loads(log.read_text())
    assert args[0] == str(blend) and 'view_type = "SEQUENCER_PREVIEW"' in args[2] and "sequencer_scene" in args[2]
    compile(viewer.SHOW_FILM, "film", "exec")


@requires_ffmpeg
def test_the_screen_makes_and_shows_the_film(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    monkeypatch.setattr(film_mod, "find_blender", lambda configured="": None)
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.renderer = "sketch"
    svc.save(p)
    with TestClient(appmod.app) as client:
        base = f"/api/projects/{p.id}/scene3d/film"
        assert client.get(base).json() == {"film": None, "stale": "the whole 3D film has not been made yet"}
        assert client.post(base, json={}).json() == {"ok": True}
        for _ in range(300):
            d = client.get(base).json()
            if d["film"]:
                break
            asyncio.run(asyncio.sleep(0.1))
        assert [pt["source"] for pt in d["film"]["parts"]] == ["3d", "3d"] and d["stale"] == ""
        r = client.post(f"{base}/open")
        assert r.status_code == 400 and "no Blender file" in r.json()["detail"]
        info = client.get(f"/api/projects/{p.id}/nodes/{ids[0]}/scene3d").json()
        assert info["uses"] == []                                     # rendered but not approved yet: nothing is used


def _film_helpers():
    """strips_of, length_of and add_title from the Blender film script, without Blender (they only use what they are given)."""
    import ast
    src = Path(R.__file__).with_name("blender_film.py").read_text()
    tree = ast.parse(src)
    code = {n.name: ast.get_source_segment(src, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    ns: dict = {}
    for name in ("strips_of", "length_of", "add_title"):
        exec(code[name], ns)
    return ns


def test_the_film_script_works_with_blender_5_and_older():
    h = _film_helpers()

    class Empty(list):          # an empty strips collection is "false", as in Blender
        pass

    class Blender5Editor:       # Blender 5: only `strips`, and it starts empty
        strips = Empty()

    class Blender4Editor:       # Blender 4.0: only `sequences`
        sequences = Empty()
    assert h["strips_of"](Blender5Editor()) is Blender5Editor.strips
    assert h["strips_of"](Blender4Editor()) is Blender4Editor.sequences

    class Strips5:              # Blender 5 takes `length`
        def new_effect(self, name, type, channel, frame_start, length):
            return ("length", frame_start, length)

    class Strips4:              # older versions take `frame_end`
        def new_effect(self, name, type, channel, frame_start, frame_end):
            return ("frame_end", frame_start, frame_end)
    assert h["add_title"](Strips5(), "t", 61, 60) == ("length", 61, 60)
    assert h["add_title"](Strips4(), "t", 61, 60) == ("frame_end", 61, 121)

    class NoLength:
        pass
    assert h["length_of"](NoLength(), 48) == 48
