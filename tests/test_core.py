"""Unit tests: tree, context scoping, dependencies, estimates, routing, plugins."""
import os

import pytest

from video_generator import deps as D
from video_generator import estimate as E
from video_generator.context import effective_context
from video_generator.models import (ActorDetails, ClipScript, ContextItem, ContextRole, ContextType, Dependency,
                                    DialogueLine, Node, NodeKind, NodeStatus, Project, ShotType)
from video_generator.tree import add_child, effective_style, leaves, move, numbering


def make_project() -> Project:
    p = Project(name="t", goal="advert")
    p.settings.target_seconds = 30
    hook = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Hook", goal="hook", style_overrides={"mood": "tense"}))
    c1 = add_child(p, hook.id, Node(kind=NodeKind.clip, title="Platform", goal="crowded platform"))
    c2 = add_child(p, hook.id, Node(kind=NodeKind.clip, title="Strap", goal="strap snaps"))
    part2 = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Product", goal="product"))
    c3 = add_child(p, part2.id, Node(kind=NodeKind.clip, title="Priya", goal="Priya presents"))
    return p


# ------------------------------------------------------------------ tree
def test_numbering_and_move():
    p = make_project()
    nums = numbering(p)
    assert sorted(nums.values())[1:] == ["1", "1.1", "1.2", "2", "2.1"]
    strap = leaves(p)[1]
    move(p, strap.id, p.root.children[1].id, 0)
    assert numbering(p)[strap.id] == "2.1"
    with pytest.raises(ValueError):
        move(p, p.root.children[0].id, p.root.children[0].id, 0)


def test_style_inheritance():
    p = make_project()
    p.style.look = "cinematic"
    clip = leaves(p)[0]
    clip.style_overrides = {"colour": "cool blue"}
    st = effective_style(p, clip.id)
    assert st == {"look": "cinematic", "mood": "tense", "colour": "cool blue"}


# ------------------------------------------------------------------ context
def test_effective_context_scopes_off_and_override():
    p = make_project()
    hook = p.root.children[0]
    c1, c2, c3 = leaves(p)
    logo = ContextItem(type=ContextType.entity, title="Logo", scope="project")
    platform = ContextItem(type=ContextType.location, title="Mumbai platform", scope=f"node:{hook.id}")
    horn = ContextItem(type=ContextType.audio, role=ContextRole.sound, title="Horn", scope=f"clip:{c1.id}")
    outfit2 = ContextItem(type=ContextType.text, title="Gym wear", scope=f"clip:{c3.id}")
    outfit1 = ContextItem(type=ContextType.text, title="Office wear", scope="project")
    p.context = [logo, platform, horn, outfit1, outfit2]
    names = lambda nid: {e.item.title: e.origin for e in effective_context(p, nid)}
    assert names(c1.id) == {"Logo": "shared", "Office wear": "shared", "Mumbai platform": "node:1", "Horn": "this"}
    assert "Horn" not in names(c2.id) and "Mumbai platform" in names(c2.id)
    assert "Mumbai platform" not in names(c3.id)
    c2.context_off = [logo.id]
    assert "Logo" not in names(c2.id)
    c3.context_override = {outfit1.id: outfit2.id}
    n3 = names(c3.id)
    assert "Gym wear" in n3 and "Office wear" not in n3


def test_text_only_context_item_is_fine():
    item = ContextItem(type=ContextType.text, text="Mention 400 g")
    assert item.files == [] and not item.needs_consent


def test_consent_needed_only_for_real_people():
    a = ContextItem(type=ContextType.actor, files=["inputs/p.jpg"], actor=ActorDetails(kind="real_person"))
    b = ContextItem(type=ContextType.actor, actor=ActorDetails(kind="ai_person", description="tall man"))
    assert a.needs_consent and not b.needs_consent


# ------------------------------------------------------------------ dependencies
def test_dependency_cycle_order_and_stale():
    p = make_project()
    c1, c2, c3 = leaves(p)
    D.add_dependency(p, Dependency(from_id=c2.id, to_id=c3.id, type="continues_from"))
    D.add_dependency(p, Dependency(from_id=c1.id, to_id=c2.id, type="same_location"))
    with pytest.raises(D.CycleError):
        D.add_dependency(p, Dependency(from_id=c3.id, to_id=c1.id, type="reference"))
    assert D.topo_order(p) == [c1.id, c2.id, c3.id]
    assert D.required_upstream(p, c3.id) == [c1.id, c2.id]
    for c in (c2, c3):
        c.status = NodeStatus.done
    stale = D.mark_downstream_stale(p, c1.id)
    assert stale == [c2.id, c3.id] and c3.status == NodeStatus.stale


def test_dependency_only_between_clips():
    p = make_project()
    with pytest.raises(ValueError):
        D.add_dependency(p, Dependency(from_id=p.root.children[0].id, to_id=leaves(p)[0].id))


# ------------------------------------------------------------------ estimates
def test_duration_from_script_and_speaking_rate():
    p = make_project()
    c3 = leaves(p)[2]
    priya = ContextItem(type=ContextType.actor, title="Priya", actor=ActorDetails(behaviour="calm and slow"))
    p.context.append(priya)
    words = " ".join(["word"] * 80)
    c3.script = ClipScript(shot_type=ShotType.talking_head, visual="Priya at desk",
                           dialogue=[DialogueLine(speaker=priya.id, text=words)])
    d = E.estimate_duration(p, c3)
    # 80 words at 150*0.88=132 wpm = 36.4 s + 1 s edge padding
    assert d.basis.value == "script" and 36 < d.likely_s < 39
    assert "80 words" in d.explain
    c3.voice_seconds = 30.0
    d2 = E.estimate_duration(p, c3)
    assert d2.basis.value == "actual" and abs(d2.likely_s - 30.5) < 0.01


def test_goal_stage_estimates_share_parent_target():
    from video_generator.config import Config
    from video_generator.registry import Registry
    p = make_project()
    est = E.refresh(p, Registry(Config()))
    assert abs(est.seconds - 30) < 0.5
    assert p.root.children[0].duration.basis.value == "goal"


def test_costs_with_paid_routing_and_rollup(monkeypatch):
    for k in ("FAL_KEY", "ELEVENLABS_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "test")
    from video_generator.config import Config
    from video_generator.registry import Registry
    p = make_project()
    c1, c2, c3 = leaves(p)
    c2.script = ClipScript(shot_type=ShotType.human_motion, visual="strap snaps", action_beats=["walks", "strap snaps"],
                           narration="Heavy bags slow you down.")
    reg = Registry(Config())
    E.refresh(p, reg)
    items = {l.item.split(" (")[0]: l for l in c2.cost.lines}
    assert "Video" in items and "Keyframe images" in items and "Voice" in items
    assert "3 take(s)" in items["Video"].calc           # people shot -> 3 takes
    assert c2.cost.likely_usd > 1
    hook = p.root.children[0]
    assert abs(hook.cost.likely_usd - (c1.cost.likely_usd + c2.cost.likely_usd)) < 0.02
    # what-if: fewer takes lowers the cost
    before = c2.cost.likely_usd
    c2.takes_override = 1
    E.refresh(p, reg)
    assert c2.cost.likely_usd < before


def test_continues_from_requires_start_frame_model(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "test")
    monkeypatch.setenv("RUNWAYML_API_SECRET", "test")
    from video_generator.config import Config
    from video_generator.registry import Registry
    p = make_project()
    c1, c2, _ = leaves(p)
    c2.script = ClipScript(shot_type=ShotType.product, visual="bag")
    D.add_dependency(p, Dependency(from_id=c1.id, to_id=c2.id, type="continues_from"))
    plan = E.plan_clip(p, c2, Registry(Config()))
    assert plan.needs_start_frame and plan.video.capabilities.get("start_frame")
    assert plan.takes >= 1


def test_budget_warning():
    from video_generator.config import Config
    from video_generator.registry import Registry
    p = make_project()
    p.settings.budget_usd = 0
    p.run.spent_usd = 1.0
    est = E.refresh(p, Registry(Config()))
    assert any("budget" in w for w in est.warnings)


def test_free_mode_makes_one_take():
    from video_generator.config import Config
    from video_generator.registry import Registry
    p = make_project()
    c = leaves(p)[1]
    c.script = ClipScript(shot_type=ShotType.human_motion, visual="x")
    assert E.plan_clip(p, c, Registry(Config())).takes == 1


# ------------------------------------------------------------------ registry & plugins
def test_plugin_discovery_and_routing_fallback(monkeypatch):
    from video_generator.config import Config
    from video_generator.registry import Registry, plugin_classes
    names = plugin_classes()
    for n in ("anthropic", "openai", "fal", "veo", "elevenlabs", "heygen", "fake_video", "ffmpeg"):
        assert n in names
    reg = Registry(Config())
    assert reg.choose("video", "wildlife").is_free          # no keys -> free preview
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("FAL_KEY", "x")
    reg = Registry(Config())
    assert reg.choose("video", "wildlife", mode="best").plugin == "veo"
    assert reg.choose("video", "human_motion", mode="best").plugin == "fal"


def test_llm_switch_is_one_setting(monkeypatch):
    from video_generator.config import Config
    from video_generator.registry import Registry
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    cfg = Config()
    assert Registry(cfg).llm_plugin_name() == "anthropic"
    cfg.llm.default = "openai"
    assert Registry(cfg).llm_plugin_name() == "openai"
    cfg.llm.per_task = {"decompose": "anthropic"}
    assert Registry(cfg).llm_plugin_name("decompose") == "anthropic"
    assert Registry(cfg).llm_fallback_order("write_clip_script")[:2] == ["openai", "anthropic"]


def test_entry_point_plugin_is_found(monkeypatch):
    import importlib.metadata as md
    from video_generator import registry

    class EP:
        name = "example_video"
        value = "video_generator.plugins.fake.fake_media:FakeVideo"

    real = md.entry_points
    monkeypatch.setattr(registry, "entry_points", lambda group=None: [EP()] if group == registry.GROUP else real(group=group))
    registry.plugin_classes.cache_clear()
    try:
        assert "example_video" in registry.plugin_classes()
    finally:
        registry.plugin_classes.cache_clear()


def test_catalog_user_override(tmp_path):
    from video_generator.catalog import Catalog
    c = Catalog.load()
    e = c.get("kling_3")
    e.price.usd = 0.5
    c.save_user_override(e)
    assert Catalog.load().get("kling_3").price.usd == 0.5
