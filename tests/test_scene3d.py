"""The 3D camera reference add-on, phases 1 and 2:
- a video model can be given a reference video (fal reference-to-video), and is only chosen when a clip has one;
- a scene plan (plain shapes, paths, camera path) is checked by measuring, rendered by Blender or the free sketch,
  and kept on the clip; nothing changes for a project that leaves the add-on off."""
import asyncio
import json
import py_compile
import shutil
from pathlib import Path

import pytest

from video_generator import media
from video_generator.models import DependencyType
from video_generator.models_list import abilities
from video_generator.plugins.base import VideoRequest
from video_generator.plugins.video import fal as fal_video
from video_generator.scene3d import render as R
from video_generator.scene3d import service as s3
from video_generator.scene3d.spec import (Camera, CameraKey, Key, ScenePlan, SetSpec, Thing, check, colour_name, continue_from,
                                          camera_at, legend, normalise, thing_at, visibility)
from video_generator.tree import find

from .conftest import requires_ffmpeg
from .test_scenarios import actor, build, clip


def chase(seconds=4.0) -> ScenePlan:
    """Two friends run along X; a giant lizard follows; the camera comes down from above."""
    return ScenePlan(set_id="terrarium", set=SetSpec(name="terrarium", size=[24, 12, 6]), seconds=seconds, things=[
        Thing(id="dan", label="Dan", shape="person", size=[0.5, 0.4, 1.8], keys=[Key(t=0, at=[0, 0, 0]), Key(t=seconds, at=[4, 0, 0])]),
        Thing(id="bruiser", label="Bruiser", shape="person", size=[0.5, 0.4, 1.7],
              keys=[Key(t=0, at=[0, 1.5, 0]), Key(t=seconds, at=[4, 1.5, 0])]),
        Thing(id="lizard", label="giant lizard", shape="creature", size=[8, 3, 4],
              keys=[Key(t=0, at=[-7, 0.5, 0]), Key(t=seconds, at=[-3, 0.5, 0])]),
        Thing(id="rock", kind="prop", shape="sphere", size=[2, 2, 1.5], keys=[Key(at=[6, -3, 0])])],
        camera=Camera(lens_mm=28, keys=[CameraKey(t=0, at=[0, -14, 12], look_at=[0, 0, 0]),
                                        CameraKey(t=seconds, at=[4, -8, 2], look_at=[1, 0, 1.5])]))


# ----------------------------------------------------------------- phase 1: reference video
def test_a_reference_model_gets_the_video_the_pictures_and_a_guide_to_what_each_one_is(svc, tmp_path):
    e = svc.catalog.get("seedance_2_reference")
    ref, pic = tmp_path / "ref.mp4", tmp_path / "dan.png"
    ref.write_bytes(b"video")
    pic.write_bytes(b"picture")
    req = VideoRequest(prompt="Two friends run from a giant lizard.", out=tmp_path / "o.mp4", model=e.model, seconds=4.2,
                       references=[pic], reference_labels=["Dan, the red figure"], reference_video=ref, params=dict(e.params))
    body = fal_video.build_payload(req)
    assert set(body) == {"prompt", "image_urls", "video_urls", "duration", "resolution", "aspect_ratio", "generate_audio"}
    assert len(body["video_urls"]) == 1 and body["video_urls"][0].startswith("data:video/mp4;base64,")
    assert len(body["image_urls"]) == 1
    assert body["duration"] == "5"                      # the next length the model accepts
    assert body["prompt"].startswith("@Video1 is the camera and movement reference")
    assert "Do not copy its look" in body["prompt"]
    assert "@Image1 is Dan, the red figure." in body["prompt"]
    assert body["prompt"].endswith("Two friends run from a giant lizard.")


def test_the_fast_reference_model_names_references_the_same_way(svc, tmp_path):
    e = svc.catalog.get("seedance_2_fast_reference")
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"video")
    req = VideoRequest(prompt="x", out=tmp_path / "o.mp4", references=[ref], reference_video=ref, params=dict(e.params))
    assert fal_video.reference_guide(req).startswith("@Video1 is the camera")
    assert "@Image1 is a reference picture." in fal_video.reference_guide(req)


def test_an_ordinary_model_is_sent_exactly_what_it_was_sent_before(svc, tmp_path):
    e = svc.catalog.get("seedance_2")
    start, ref = tmp_path / "start.png", tmp_path / "ref.mp4"
    start.write_bytes(b"p")
    ref.write_bytes(b"v")
    req = VideoRequest(prompt="A lion walks.", out=tmp_path / "o.mp4", seconds=5, start_frame=start, reference_video=ref,
                       params=dict(e.params))
    body = fal_video.build_payload(req)
    assert body["prompt"] == "A lion walks."
    assert "video_urls" not in body and "image_url" in body


def test_reference_models_are_only_chosen_for_a_clip_that_has_a_reference_video(svc, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "test")
    svc.reg._instances.clear()
    for mode in ("best", "balanced", "budget"):
        ordinary = [e.id for e in svc.reg.candidates("video", "human_motion", None, mode)]
        assert not any(i.endswith("_reference") for i in ordinary)
        assert not any(i.endswith("_reference") for i in (e.id for e in svc.reg.candidates("video", "human_motion", {"start_frame": True}, mode)))
    with_ref = [e.id for e in svc.reg.candidates("video", "human_motion", {"reference_video": 1}, "best")]
    assert with_ref and all(i.endswith("_reference") for i in with_ref)
    assert "follows a 3D camera reference" in abilities(svc.catalog.get("seedance_2_reference"))


# ----------------------------------------------------------------- phase 2: the scene plan
def test_a_plan_is_tidied_keys_at_both_ends_and_every_figure_its_own_colour():
    p = ScenePlan(seconds=3, things=[Thing(id="a", keys=[Key(t=1, at=[0, 0, 0])]), Thing(id="b", colour="#d62828"),
                                     Thing(id="c", colour="#d62828"), Thing(id="wall", kind="prop")],
                  camera=Camera(keys=[CameraKey(t=9)]))
    n = normalise(p)
    assert [k.t for k in n.things[0].keys] == [0.0, 1.0, 3.0]
    assert [k.t for k in n.camera.keys] == [0.0, 3.0]        # a key past the end is moved to the end
    colours = [t.colour for t in n.things if t.kind == "figure"]
    assert len(set(colours)) == 3 and n.things[1].colour == "#d62828"    # the first red keeps red, the copy gets a new colour
    assert n.things[3].colour == "#7a7a7a"                   # scenery stays grey
    assert colour_name("#d62828") == "red" and colour_name("#2050f0") == "blue"


def test_the_checks_measure_what_the_camera_sees():
    p = normalise(chase())
    assert check(p) == []
    assert visibility(p, p.things[0], 0)[0] == "in"
    behind = p.model_copy(deep=True)
    behind.camera.keys = [CameraKey(t=0, at=[0, 10, 1.6], look_at=[0, 30, 1.6])]   # looking away from everyone
    texts = [i.text for i in check(behind)]
    assert any("'Dan' is never in the camera's view" in t for t in texts)
    inside = p.model_copy(deep=True)
    inside.camera.keys = [CameraKey(t=0, at=[-7, 0.5, 2], look_at=[0, 0, 1])]       # inside the lizard
    assert any(i.severity == "major" and "inside 'giant lizard'" in i.text for i in check(inside))
    assert legend(p) == [("red", "Dan"), ("blue", "Bruiser"), ("green", "giant lizard")]


def test_a_continuing_clip_starts_where_the_camera_and_figures_ended():
    first = normalise(chase(4))
    nxt = ScenePlan(seconds=3, things=[Thing(id="dan", keys=[Key(t=3, at=[9, 0, 0])])],
                    camera=Camera(keys=[CameraKey(t=0, at=[50, 50, 50]), CameraKey(t=3, at=[9, -6, 1.7], look_at=[9, 0, 1])]))
    joined = normalise(continue_from(first, nxt))
    eye, target, _ = camera_at(joined.camera, 0)
    assert eye == pytest.approx(camera_at(first.camera, 4)[0]) and target == pytest.approx(camera_at(first.camera, 4)[1])
    assert thing_at(joined.things[0], 0) == pytest.approx([4, 0, 0])
    assert joined.set_id == "terrarium"                     # the same place, not a new set


def test_the_blender_script_is_valid_python():
    py_compile.compile(str(R.build_script()), doraise=True)


# ----------------------------------------------------------------- phase 2: rendering
@requires_ffmpeg
def test_the_free_sketch_makes_a_reference_of_the_exact_length_and_shape(tmp_path):
    res = asyncio.run(R.render(chase(2), tmp_path / "out", (320, 180), use_blender=False))
    assert res.renderer == "sketch" and res.notes == ["Drawn by the free sketch renderer (the sketch was asked for)."]
    assert media.probe_duration(res.video) == pytest.approx(2.0, abs=0.1)
    assert media.video_size(res.video) == (320, 180)
    assert res.first.exists() and res.last.exists() and set(res.checks) == {"start", "middle", "end"}


@requires_ffmpeg
def test_when_blender_fails_the_sketch_is_used_and_the_reason_is_kept(tmp_path):
    fake = tmp_path / "blender"
    fake.write_text("#!/bin/sh\nexit 3\n")
    fake.chmod(0o755)
    res = asyncio.run(R.render(chase(1), tmp_path / "out", (160, 90), blender=str(fake), engines=["BLENDER_WORKBENCH"]))
    assert res.renderer == "sketch"
    assert "Blender could not render the scene" in res.notes[0] and "BLENDER_WORKBENCH did not work" in res.notes[0]


@requires_ffmpeg
@pytest.mark.skipif(not R.find_blender(), reason="Blender is not installed")
def test_real_blender_renders_the_plan_and_saves_the_scene(tmp_path):
    res = asyncio.run(R.render_blender(chase(0.5), tmp_path / "out", (160, 90), R.find_blender()))
    assert res.renderer == "blender" and res.blend and res.blend.exists()
    assert media.probe_duration(res.video) == pytest.approx(0.5, abs=0.1)
    assert json.loads((tmp_path / "out" / "result.json").read_text())["ok"] is True


# ----------------------------------------------------------------- phase 2: on a clip
def two_shot_project(svc, links=()):
    friends = [actor("Dan"), actor("Bruiser"), actor("Lizard", kind="animal")]
    return build(svc, "Two friends run from a giant lizard", friends, [
        clip("human_motion", "Dan and Bruiser run across the terrarium", actors=["Dan", "Bruiser", "Lizard"], seconds=4),
        clip("human_motion", "They hide behind a rock", actors=["Dan", "Bruiser"], seconds=4)], links=links)


@requires_ffmpeg
def test_a_clip_is_planned_built_and_approved_and_an_edit_makes_it_out_of_date(svc):
    p, ids = two_shot_project(svc)
    assert s3.enabled_for(p, find(p, ids[0])) is False           # off unless switched on: the tool works as before
    p.settings.scene3d.enabled = True
    svc.save(p)
    s = asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    assert s.status == "planned" and s.plan.seconds == pytest.approx(4, abs=0.5) and s.plan.aspect == "16:9"
    assert [lbl for _, lbl in legend(s.plan)] == ["Dan", "Bruiser", "Lizard"]
    assert not [i for i in s.issues if i.startswith("major")]
    s = asyncio.run(s3.build_clip(svc, p.id, ids[0], renderer="sketch"))
    assert s.status == "rendered" and s.approved_by == ""        # waits for you unless auto-approve is on
    q = svc.load(p.id)
    assert s3.ready_reference(q, find(q, ids[0])) is None
    s3.approve(svc, p.id, ids[0])
    q = svc.load(p.id)
    assert s3.ready_reference(q, find(q, ids[0])).approved_by == "you"
    edited = q.model_copy(deep=True)
    plan = find(edited, ids[0]).scene3d.plan
    plan.camera.lens_mm = 50
    s3.set_plan(svc, p.id, ids[0], plan)
    q = svc.load(p.id)
    assert not s3.is_current(find(q, ids[0])) and s3.ready_reference(q, find(q, ids[0])) is None
    with pytest.raises(s3.Scene3DError, match="no up-to-date 3D preview"):
        s3.approve(svc, p.id, ids[0])


@requires_ffmpeg
def test_auto_approve_approves_a_passing_preview_by_itself(svc):
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.auto_approve = True
    svc.save(p)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    s = asyncio.run(s3.build_clip(svc, p.id, ids[0], renderer="sketch"))
    assert s.status == "approved" and s.approved_by == "auto"


def test_a_part_can_switch_the_reference_on_or_off_for_its_clips(svc):
    p, ids = two_shot_project(svc)
    part = p.root.children[0]
    part.scene3d_enabled = True
    svc.save(p)
    q = svc.load(p.id)
    assert s3.enabled_for(q, find(q, ids[0])) and s3.enabled_for(q, find(q, ids[1]))
    find(q, ids[1]).scene3d_enabled = False
    assert not s3.enabled_for(q, find(q, ids[1]))


def test_the_next_clip_in_the_same_place_continues_the_camera(svc):
    p, ids = two_shot_project(svc, links=[(0, 1, DependencyType.continues_from.value)])
    p.settings.scene3d.enabled = True
    svc.save(p)
    first = asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    second = asyncio.run(s3.plan_clip(svc, p.id, ids[1]))
    end = camera_at(normalise(first.plan).camera, first.plan.seconds)
    start = camera_at(normalise(second.plan).camera, 0)
    assert start[0] == pytest.approx(end[0]) and start[1] == pytest.approx(end[1])
    assert second.plan.set_id == first.plan.set_id and second.plan.set == first.plan.set


def test_a_clip_without_a_script_is_told_to_write_one_first(svc):
    p, ids = two_shot_project(svc)
    find(p, ids[0]).script = None
    svc.save(p)
    with pytest.raises(s3.Scene3DError, match="no script yet"):
        asyncio.run(s3.plan_clip(svc, p.id, ids[0]))


# ----------------------------------------------------------------- phase 3: the reference is used when a clip is made
from video_generator import estimate as E  # noqa: E402

from .fake_vendors import Vendors  # noqa: E402
from .test_scenarios import run_all  # noqa: E402


def approved(svc, pid, nid, auto=False):
    """Plan, render (free sketch) and approve one clip's 3D reference."""
    asyncio.run(s3.plan_clip(svc, pid, nid))
    asyncio.run(s3.build_clip(svc, pid, nid, renderer="sketch"))
    return s3.approve(svc, pid, nid)


def keyframe_of(v, nid):
    """The first-picture request of one clip (character sheets are made before it)."""
    return next(r for r in v.calls["picture"] if nid in str(r.out) and "keyframe" in Path(r.out).name)


def reference_project(svc, monkeypatch, links=()):
    v = Vendors(svc, monkeypatch)
    p, ids = two_shot_project(svc, links=links)
    p.settings.scene3d.enabled = True
    svc.save(p)
    return v, p, ids


@requires_ffmpeg
def test_an_approved_reference_is_followed_and_the_first_picture_is_made_from_the_layout(svc, monkeypatch):
    v, p, ids = reference_project(svc, monkeypatch)
    approved(svc, p.id, ids[0])
    q = svc.load(p.id)
    plan = E.plan_clip(q, find(q, ids[0]), svc.reg)
    assert plan.reference and plan.video.id.endswith("_reference")
    run_all(svc, p.id)
    first_pic = keyframe_of(v, ids[0])
    assert first_pic.prompt.startswith("Picture 1 is a rough 3D layout made of plain coloured shapes.")
    assert "the red shape is Dan, the blue shape is Bruiser and the green shape is Lizard" in first_pic.prompt
    assert Path(first_pic.references[0]).name == "first.png"            # the layout's first picture leads
    call = next(c for c in v.calls["video"] if c.reference_video)
    assert call.model == svc.catalog.get(plan.video.id).model and call.start_frame is None
    assert Path(call.reference_video).name == "reference.mp4" and ids[0] in str(call.reference_video)
    assert call.reference_labels[0] == "the first picture of the clip: it starts exactly like this"
    assert Path(call.references[0]) == Path(first_pic.out)               # the realistic first picture, not the grey layout
    assert "In the camera reference, the red shape is Dan" in call.prompt
    body = fal_video.build_payload(call)
    assert body["prompt"].startswith("@Video1 is the camera and movement reference")
    assert "@Image1 is the first picture of the clip" in body["prompt"]
    # the second clip has no approved reference: it is made the usual way
    other = [c for c in v.calls["video"] if not c.reference_video]
    assert other and all(c.start_frame for c in other)


@requires_ffmpeg
def test_a_reference_that_is_only_rendered_or_switched_off_is_not_used(svc, monkeypatch):
    v, p, ids = reference_project(svc, monkeypatch)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    asyncio.run(s3.build_clip(svc, p.id, ids[0], renderer="sketch"))      # rendered, not approved
    q = svc.load(p.id)
    assert not E.plan_clip(q, find(q, ids[0]), svc.reg).reference
    s3.approve(svc, p.id, ids[0])
    q = svc.load(p.id)
    q.settings.scene3d.enabled = False                                    # approved, but the add-on is off
    svc.save(q)
    q = svc.load(p.id)
    plan = E.plan_clip(q, find(q, ids[0]), svc.reg)
    assert not plan.reference and not plan.layout
    run_all(svc, p.id)
    assert not any(c.reference_video for c in v.calls["video"])
    assert not any(r.prompt.startswith("Picture 1 is a rough 3D layout") for r in v.calls["picture"])


@requires_ffmpeg
def test_without_a_reference_model_the_first_picture_still_comes_from_the_layout(svc, monkeypatch):
    v, p, ids = reference_project(svc, monkeypatch)
    svc.config.disabled_models += ["seedance_2_reference", "seedance_2_fast_reference"]
    approved(svc, p.id, ids[0])
    q = svc.load(p.id)
    plan = E.plan_clip(q, find(q, ids[0]), svc.reg)
    assert plan.layout and not plan.reference
    assert any("no connected video model can follow a reference video" in w for w in plan.warnings)
    run_all(svc, p.id)
    assert not any(c.reference_video for c in v.calls["video"])
    assert keyframe_of(v, ids[0]).prompt.startswith("Picture 1 is a rough 3D layout")


@requires_ffmpeg
def test_a_continuing_clip_keeps_its_hand_over_picture_over_the_reference(svc, monkeypatch):
    v, p, ids = reference_project(svc, monkeypatch, links=[(0, 1, DependencyType.continues_from.value)])
    approved(svc, p.id, ids[0])
    approved(svc, p.id, ids[1])
    q = svc.load(p.id)
    plan = E.plan_clip(q, find(q, ids[1]), svc.reg)
    assert not plan.reference
    assert any("it continues the clip before" in w for w in plan.warnings)
    run_all(svc, p.id)
    second = [c for c in v.calls["video"] if not c.reference_video]
    assert second and Path(second[-1].start_frame).name.startswith("handoff_from_")


def test_a_reference_of_the_wrong_length_is_out_of_date(svc):
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    svc.save(p)
    approved(svc, p.id, ids[0])
    q = svc.load(p.id)
    n = find(q, ids[0])
    assert s3.ready_reference(q, n) is not None
    n.duration.likely_s = n.scene3d.plan.seconds + 2
    assert s3.ready_reference(q, n) is None and "plan it again" in s3.stale_reason(n)


@requires_ffmpeg
def test_approving_a_reference_for_a_made_clip_marks_it_out_of_date(svc, monkeypatch):
    v, p, ids = reference_project(svc, monkeypatch)
    run_all(svc, p.id)
    q = svc.load(p.id)
    assert find(q, ids[0]).status.value == "done"
    approved(svc, p.id, ids[0])
    q = svc.load(p.id)
    assert find(q, ids[0]).status.value == "stale"
    assert any("3D camera reference was approved" in w for w in find(q, ids[0]).warnings)


@requires_ffmpeg
def test_a_clip_made_in_parts_gives_each_part_its_own_stretch_of_the_reference(svc, monkeypatch, tmp_path):
    from video_generator.runner import Engine
    v, p, ids = reference_project(svc, monkeypatch)
    entry = svc.catalog.get("seedance_2_reference").model_copy(deep=True)
    entry.capabilities["max_seconds"] = 2
    ref = tmp_path / "reference.mp4"
    media.ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=24", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(ref))
    pic = tmp_path / "first.png"
    from PIL import Image
    Image.new("RGB", (320, 180), (200, 40, 40)).save(pic)
    req = VideoRequest(prompt="run", out=tmp_path / "out.mp4", model=entry.model, seconds=4, references=[pic],
                       reference_video=ref, params=dict(entry.params))
    asyncio.run(Engine(svc)._video_parts(p.id, entry, req, "t1", (), ids[0]))
    parts = [c.reference_video for c in v.calls["video"]]
    assert len(parts) == 2 and len(set(parts)) == 2 and ref not in parts
    assert all(media.probe_duration(x) == pytest.approx(2.0, abs=0.15) for x in parts)
