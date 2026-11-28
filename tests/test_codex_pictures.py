"""Pictures through Codex (your ChatGPT subscription): the picture model, the character and object pictures with
changes, the switch, and the first picture of a clip from the 3D layout. The real Codex is replaced by a stand-in that
"makes" a picture the two ways Codex can leave it: in the work folder, or in its own generated_images folder."""
import asyncio
import json
import sys

import pytest
from PIL import Image

from video_generator import pictures
from video_generator.models import ContextItem, ContextType
from video_generator.plugins.base import ImageRequest, PluginError
from video_generator.plugins.image.codex_image import CodexImage
from video_generator.tree import find

from .test_scene3d import two_shot_project

CODEX = """import json, os, sys, pathlib, time
from PIL import Image
args = sys.argv[1:]
pathlib.Path(os.environ["STAND_IN_LOG"]).write_text(json.dumps({"args": args, "cwd": os.getcwd(), "files": sorted(os.listdir("."))}))
mode = os.environ.get("STAND_IN_MODE", "home")
if mode == "home":       # Codex's image tool saves under $CODEX_HOME/generated_images
    d = pathlib.Path(os.environ["CODEX_HOME"]) / "generated_images" / "t1"
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 400), (200, 120, 40)).save(d / "img.png")
elif mode == "here":
    Image.new("RGB", (300, 400), (40, 120, 200)).save("output.png")
else:
    print(json.dumps({"type": "error", "message": "image generation is not available on your plan"})); sys.exit(1)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "A man in a saffron kurta."}}))
"""


@pytest.fixture
def codex(tmp_path, monkeypatch):
    exe = tmp_path / "codex"
    exe.write_text(f"#!{sys.executable}\n" + CODEX)
    exe.chmod(0o755)
    monkeypatch.setenv("VG_CODEX", str(exe))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
    monkeypatch.setenv("STAND_IN_LOG", str(tmp_path / "log.json"))
    return tmp_path / "log.json"


def test_codex_makes_a_picture_from_its_own_folder_or_the_work_folder(codex, tmp_path, monkeypatch, svc):
    ref = tmp_path / "ref.png"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(ref)
    svc.config.llm.models["codex_brain"] = "GPT-6.2-Sol"
    svc.config.llm.efforts = {"codex_brain": "low"}
    plugin = CodexImage(svc.config)
    out, usage = asyncio.run(plugin.generate(ImageRequest(prompt="A guru in saffron", out=tmp_path / "a.png", references=[ref], aspect="3:4")))
    assert out.exists() and Image.open(out).getpixel((5, 5)) == (200, 120, 40) and usage.cost_usd == 0
    seen = json.loads(codex.read_text())
    args = seen["args"]
    assert args[:5] == ["exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "--cd"]
    assert args[args.index("-i") + 1].endswith("picture_01.png") and "picture_01.png" in seen["files"]
    assert args[args.index("-m") + 1] == "gpt-6.2-sol" and 'model_reasoning_effort="low"' in args
    assert "A guru in saffron" in args[-1] and "image generation tool" in args[-1] and "portrait" in args[-1]
    monkeypatch.setenv("STAND_IN_MODE", "here")
    out, _ = asyncio.run(plugin.generate(ImageRequest(prompt="x", out=tmp_path / "b.png")))
    assert Image.open(out).getpixel((5, 5)) == (40, 120, 200)
    monkeypatch.setenv("STAND_IN_MODE", "none")
    with pytest.raises(PluginError, match="Codex made no picture.*not available on your plan"):
        asyncio.run(plugin.generate(ImageRequest(prompt="x", out=tmp_path / "c.png")))


def test_codex_is_the_picture_maker_when_installed_and_can_be_switched_off(codex, svc):
    svc.reload()
    e, _ = pictures.picture_maker(svc)
    assert e.id == "codex_image_subscription" and pictures.maker_info(svc)["name"] == "Codex"
    assert pictures.maker_info(svc)["subscription"]
    svc.config.disabled_models = ["codex_image_subscription"]
    assert pictures.picture_maker(svc)[0] is None


def test_a_character_picture_becomes_its_look_and_can_be_changed(codex, svc, monkeypatch):
    svc.reload()
    p, ids = two_shot_project(svc)
    dan = next(c for c in p.context if c.title == "Dan")
    pic = asyncio.run(pictures.make_item_picture(svc, p.id, dan.id))
    item = next(c for c in svc.load(p.id).context if c.id == dan.id)
    assert item.actor.reference_sheet == [pic.file] and item.picture.by == "codex_image_subscription"
    first_prompt = json.loads(codex.read_text())["args"][-1]
    assert "full-body character reference picture of Dan" in first_prompt
    monkeypatch.setenv("STAND_IN_MODE", "here")
    pic2 = asyncio.run(pictures.make_item_picture(svc, p.id, dan.id, "a longer white beard"))
    seen = json.loads(codex.read_text())
    assert "Make the SAME picture with only this change: a longer white beard" in seen["args"][-1]
    assert seen["files"][0] == "picture_01.png"                         # the current picture is the starting point
    item = next(c for c in svc.load(p.id).context if c.id == dan.id)
    assert pic2.file != pic.file and item.actor.reference_sheet == [pic2.file] and item.picture.changes == ["a longer white beard"]


def test_an_object_picture_is_added_to_its_pictures(codex, svc):
    svc.reload()
    p, _ = two_shot_project(svc)
    p.context.append(ContextItem(type=ContextType.object, title="Takht", text="a low wooden seat"))
    svc.save(p)
    cid = p.context[-1].id
    pic = asyncio.run(pictures.make_item_picture(svc, p.id, cid))
    item = next(c for c in svc.load(p.id).context if c.id == cid)
    assert item.files[0] == pic.file and "reference picture of Takht: a low wooden seat" in item.picture.prompt


def test_without_any_picture_maker_the_reason_is_given(svc):
    p, _ = two_shot_project(svc)
    with pytest.raises(ValueError, match="install Codex"):
        asyncio.run(pictures.make_item_picture(svc, p.id, p.context[0].id))


def test_a_clips_first_picture_from_the_3d_layout_is_made_by_codex(codex, svc):
    from video_generator.estimate import plan_clip
    svc.reload()
    p, ids = two_shot_project(svc)
    p.settings.quality_mode = "balanced"
    svc.save(p)
    plan = plan_clip(svc.load(p.id), find(svc.load(p.id), ids[0]), svc.reg)
    assert plan.image is not None and plan.image.id == "codex_image_subscription"


def test_the_screen_shows_the_picture_maker_and_makes_a_picture(codex, svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    svc.reload()
    monkeypatch.setattr(appmod, "svc", svc)
    p, _ = two_shot_project(svc)
    with TestClient(appmod.app) as client:
        assert client.get("/api/pictures/maker").json()["name"] == "Codex"
        r = client.post(f"/api/projects/{p.id}/context/{p.context[0].id}/picture", json={}).json()
        assert r == {"ok": True, "by": "Codex"}
        for _ in range(100):
            if svc.load(p.id).context[0].picture:
                break
            asyncio.run(asyncio.sleep(0.1))
    assert svc.load(p.id).context[0].picture is not None


def test_a_place_gets_a_wide_picture_without_people(codex, svc):
    svc.reload()
    p, _ = two_shot_project(svc)
    p.context.append(ContextItem(type=ContextType.location, title="Village courtyard", text="mud houses, a big banyan tree"))
    svc.save(p)
    cid = p.context[-1].id
    pic = asyncio.run(pictures.make_item_picture(svc, p.id, cid))
    item = next(c for c in svc.load(p.id).context if c.id == cid)
    assert item.files[0] == pic.file
    prompt = json.loads(codex.read_text())["args"][-1]
    assert "wide establishing picture of the place Village courtyard: mud houses, a big banyan tree" in prompt and "no people" in prompt


def test_the_3d_planner_is_given_the_places_and_objects(svc):
    from video_generator.brain import render
    p, ids = two_shot_project(svc)
    p.context.append(ContextItem(type=ContextType.location, title="Village courtyard", text="mud houses, a banyan tree", scope="project"))
    p.context.append(ContextItem(type=ContextType.object, title="Takht", text="a low wooden seat", role="must_appear", scope="project"))
    svc.save(p)
    text = svc.brain._places(svc.load(p.id), ids[0])
    assert "PLACE: Village courtyard — mud houses, a banyan tree" in text and "OBJECT (must be seen): Takht — a low wooden seat" in text
    assert "THE PLACE AND THE OBJECTS THE USER DEFINED" in render("scene_plan", places=text) and text in render("scene_plan", places=text)


def test_place_pictures_are_labelled_as_the_place_not_as_a_style(svc, tmp_path):
    from video_generator.project import ProjectStore
    from video_generator.web import app as appmod
    p, ids = two_shot_project(svc)
    base = ProjectStore.path_for(p.id)
    (base / "inputs").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32)).save(base / "inputs" / "village.png")
    p.context.append(ContextItem(type=ContextType.location, title="Village", role="look_reference", files=["inputs/village.png"], scope="project"))
    svc.save(p)
    appmod.engine.svc = svc
    labels = [lbl for _, lbl in appmod.engine._labelled_references(svc.load(p.id), find(svc.load(p.id), ids[0]))]
    assert any(l.startswith("Village: the place where the clip happens") for l in labels)


def test_find_what_is_missing_and_add_the_ticked_ones(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.scene3d import service as s3
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    svc.save(p)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    q = svc.load(p.id)
    plan = find(q, ids[0]).scene3d.plan
    from video_generator.scene3d.spec import Thing
    plan.things.append(Thing(id="mat1", label="Prayer mat", kind="prop", shape="box", size=[1, 0.6, 0.02]))
    svc.save(q)
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/context/missing").json()
        kinds = {(i["type"], i["title"]) for i in r["items"]}
        place = next(i["title"] for i in r["items"] if i["type"] == "location")
        assert ("object", "Prayer mat") in kinds
        mat = next(i for i in r["items"] if i["title"] == "Prayer mat")
        assert mat["clips"] == ["1.1"]
        v = client.post(f"/api/projects/{p.id}/context/missing/add", json={"items": r["items"]}).json()
        assert sorted(v["added"]) == sorted(["Prayer mat", place])
        again = client.post(f"/api/projects/{p.id}/context/missing/add", json={"items": r["items"]}).json()
        assert again["added"] == []                                     # already defined: not added twice
    ctx = {c.title: c for c in svc.load(p.id).context}
    assert ctx["Prayer mat"].scope == f"node:{ids[0]}" and ctx["Prayer mat"].role.value == "must_appear"
    assert ctx[place].scope == "project" and ctx[place].type == ContextType.location
    r2 = asyncio.run(svc.brain.find_missing(svc.load(p.id)))
    assert all(i.title not in ("Prayer mat", place) for i in r2.items)


def test_the_chosen_ai_brain_describes_and_codex_draws(codex, svc, monkeypatch):
    from video_generator.brain import PictureBrief
    svc.reload()
    p, _ = two_shot_project(svc)
    dan = next(c for c in p.context if c.title == "Dan")
    seen = {}

    async def brief(project, item, draft):
        seen["draft"] = draft
        return PictureBrief(prompt="Dan, a lean man in his twenties, white kurta, standing, plain grey background.")
    monkeypatch.setattr(svc.brain, "picture_brief", brief)
    monkeypatch.setattr(svc.reg, "llm_plugin_name", lambda task="default": "claude_code_brain")
    pic = asyncio.run(pictures.make_item_picture(svc, p.id, dan.id))
    assert "full-body character reference picture of Dan" in seen["draft"]              # the rules are its first draft
    assert "Dan, a lean man in his twenties, white kurta" in json.loads(codex.read_text())["args"][-1]
    assert pic.described_by == "claude_code_brain" and pic.by == "codex_image_subscription"
    info = pictures.maker_info(svc)
    assert info["brain_name"] == "Claude Code" and "Claude Code cannot draw pictures" in info["note"]

    async def fails(project, item, draft):
        raise PluginError("not signed in")
    monkeypatch.setattr(svc.brain, "picture_brief", fails)
    pic = asyncio.run(pictures.make_item_picture(svc, p.id, next(c for c in p.context if c.title == "Bruiser").id))
    assert pic.described_by == "" and "full-body character reference picture of Bruiser" in json.loads(codex.read_text())["args"][-1]


def test_find_missing_reads_the_whole_plan_the_3d_sets_and_the_rendered_pictures(svc, monkeypatch):
    from video_generator.project import ProjectStore
    from video_generator.scene3d import service as s3
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.renderer = "sketch"
    svc.save(p)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    q = svc.load(p.id)
    find(q, ids[0]).scene3d.plan.set.name = "village courtyard"
    svc.save(q)
    asyncio.run(s3.build_clip(svc, p.id, ids[0], renderer="sketch"))
    seen = {}
    real = svc.brain.ask

    async def spy(task, prompt, schema, meta, images=None, video=None):
        if task == "missing_context":
            seen.update(prompt=prompt, images=images, meta=meta)
        return await real(task, prompt, schema, meta, images=images, video=video)
    monkeypatch.setattr(svc.brain, "ask", spy)
    r = asyncio.run(svc.brain.find_missing(svc.load(p.id), ProjectStore.path_for(p.id)))
    assert "its 3D set: village courtyard" in seen["prompt"] and "THE PLAN (the whole video and every part" in seen["prompt"]
    assert seen["images"] and seen["images"][0].exists() and "its rendered 3D preview is picture 1" in seen["prompt"]
    assert any(i.type == "location" and i.title == "Village Courtyard" for i in r.items)      # named after the 3D set


def test_an_empty_card_counts_as_missing_and_gets_its_description(svc):
    p, _ = two_shot_project(svc)
    p.context.append(ContextItem(type=ContextType.location, title="Location", scope="project"))
    svc.save(p)
    r = asyncio.run(svc.brain.find_missing(svc.load(p.id)))
    item = next(i for i in r.items if i.title == "Location")
    added = pictures.add_missing(svc, p.id, [item.model_dump()])
    loc = [c for c in svc.load(p.id).context if c.type == ContextType.location]
    assert added == ["Location"] and len(loc) == 1 and loc[0].text           # filled in, not added twice
    pictures.add_missing(svc, p.id, [{**item.model_dump(), "description": "something else"}])
    assert [c for c in svc.load(p.id).context if c.type == ContextType.location][0].text == loc[0].text   # yours is kept
