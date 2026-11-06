"""Step 1 (v3.9): the screen says the REAL reason a clip is only a placeholder.

A clip pinned to a free model with a key present must never be blamed on a missing key."""
import pytest

from video_generator import estimate as E
from video_generator.models import ClipScript, Node, NodeKind, NodeStatus, ShotType, Take
from video_generator.tree import add_child, leaves

from .fake_vendors import Vendors


def project(svc, n_clips=3, **settings):
    p = svc.new_project("Cause test", seconds=4 * n_clips, quality_mode="balanced")
    p.settings.budget_usd = 20
    for k, v in settings.items():
        setattr(p.settings, k, v)
    part = add_child(p, p.root.id, Node(kind=NodeKind.goal, title="Story", goal="story", target_seconds=4.0 * n_clips))
    for i in range(n_clips):
        c = add_child(p, part.id, Node(kind=NodeKind.clip, title=f"Shot {i + 1}", goal="hills", target_seconds=4.0))
        c.script = ClipScript(shot_type=ShotType.landscape, visual="hills", sound_notes="wind")
    svc.save(p)
    return svc.load(p.id)


def pin(svc, p, *indexes, model="free_preview"):
    ls = leaves(p)
    for i in indexes:
        ls[i].provider_override = model
    svc.save(p)
    return svc.load(p.id), [ls[i].id for i in indexes]


def test_without_keys_the_cause_is_a_missing_key_and_the_hint_is_shown(svc):
    p = project(svc)
    info = svc.summary(p)["preview"]
    assert all(c["video"] == "no_key" for c in info["causes"].values())
    assert "video" in info["jobs"] and "FAL_KEY" in info["jobs"]["video"]
    assert info["all_preview"] and info["pinned"] == []


def test_a_clip_pinned_to_a_free_model_is_not_blamed_on_a_missing_key(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p = project(svc)
    p, ids = pin(svc, p, 0, 1)
    info = svc.summary(p)["preview"]
    assert set(info["pinned"]) == set(ids)
    assert all(info["causes"][i]["video"] == "pinned" for i in ids)
    assert "video" not in info["jobs"]                       # no "add FAL_KEY" hint: the key is there
    assert not info["all_preview"]
    assert leaves(p)[2].id not in info["clips"]              # the clip that was not pinned gets a real model


def test_the_guide_does_not_ask_for_keys_when_clips_are_only_pinned(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    monkeypatch.setattr(svc.reg, "llm_plugin_name", lambda task="default": "openai")
    p = project(svc)
    p, ids = pin(svc, p, 0, 1, 2)
    g = svc.summary(p)["guide"]
    services = next(s for s in g["steps"] if s["id"] == "services")
    assert services["state"] == "done"
    issue = next(i for i in g["issues"] if i["action"]["kind"] == "unpin")
    assert "not a missing key" in issue["text"] and set(issue["action"]["ids"]) == set(ids)


def test_free_preview_quality_is_its_own_cause(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p = project(svc, quality_mode="free")
    info = svc.summary(p)["preview"]
    assert info["chosen_free_mode"] and all(c["video"] == "free_mode" for c in info["causes"].values())
    assert info["jobs"] == {} and info["pinned"] == []


def test_unpin_gives_the_clips_a_real_model_again(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p = project(svc)
    p, ids = pin(svc, p, 0, 1)
    assert E.plan_clip(p, leaves(p)[0], svc.reg).video.is_free
    p = svc.unpin(p.id)
    assert all(l.provider_override is None for l in leaves(p))
    assert not E.plan_clip(p, leaves(p)[0], svc.reg).video.is_free
    assert svc.summary(p)["preview"]["clips"] == {}


def test_unpin_marks_a_clip_made_as_a_placeholder_out_of_date_but_keeps_real_clips(svc, monkeypatch):
    Vendors(svc, monkeypatch)
    p = project(svc)
    ls = leaves(p)
    ls[0].provider_override = "free_preview"
    ls[0].takes = [Take(model="free_preview", video="x.mp4")]
    ls[0].chosen_take = ls[0].takes[0].id
    ls[0].status = NodeStatus.done
    ls[1].provider_override = "kling_3"                       # a real model that the user chose on purpose: stays as it is
    ls[1].takes = [Take(model="kling_3", video="y.mp4")]
    ls[1].chosen_take = ls[1].takes[0].id
    ls[1].status = NodeStatus.done
    svc.save(p)
    p = svc.unpin(p.id)                                       # no ids: only clips pinned to a FREE model
    a, b = leaves(p)[0], leaves(p)[1]
    assert a.provider_override is None and a.status == NodeStatus.stale
    assert b.provider_override == "kling_3" and b.status == NodeStatus.done


def test_unpin_api_returns_the_new_view(svc, monkeypatch):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    Vendors(svc, monkeypatch)
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setattr(appmod.engine, "svc", svc)
    p = project(svc)
    p, ids = pin(svc, p, 0)
    with TestClient(appmod.app) as client:
        r = client.post(f"/api/projects/{p.id}/unpin", json={})
        assert r.status_code == 200
        assert r.json()["summary"]["preview"]["pinned"] == []
        assert next(n for n in r.json()["project"]["root"]["children"][0]["children"] if n["id"] == ids[0])["provider_override"] is None
