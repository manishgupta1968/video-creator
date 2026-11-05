"""Automatic photo search: only when the user supplied none, only for animals/objects/places, never for people."""
import asyncio
from pathlib import Path

import pytest

from video_generator import stock
from video_generator.models import ActorDetails, ContextItem, ContextRole, ContextType
from video_generator.stock import StockPhoto


def photo(title, lic="CC BY-SA 4.0", w=1600, h=1000, src="wikimedia"):
    return StockPhoto(src, title, "https://upload.wikimedia.org/t.jpg", "https://upload.wikimedia.org/x.jpg", w, h, "Jane Doe", lic, "https://commons.example/x")


@pytest.fixture
def web(monkeypatch, sample_photo):
    """Fake Wikimedia: records every search; downloads a local test photo."""
    calls = {"search": [], "download": 0}

    async def fake_search(q, source="wikimedia", limit=24, client=None):
        calls["search"].append(q)
        if calls.get("fail"):
            raise stock.StockError("network down")
        return calls.get("results", [photo("Lion male"), photo("Lion cub playing", w=900)])

    async def fake_download(url, dest_dir, name, client=None):
        calls["download"] += 1
        dest = Path(dest_dir) / "found.jpg"
        dest.write_bytes(sample_photo.read_bytes())
        return dest
    monkeypatch.setattr(stock, "search", fake_search)
    monkeypatch.setattr(stock, "download", fake_download)
    return calls


def project_with(svc, *items):
    p = svc.new_project("Add a lion that speaks", seconds=15)
    p.context.extend(items)
    svc.save(p)
    return svc.load(p.id)


def lion():
    return ContextItem(type=ContextType.actor, title="Kito the Lion", actor=ActorDetails(kind="animal", description="adult male African lion"))


def get(svc, pid, cid):
    return next(c for c in svc.load(pid).context if c.id == cid)


def test_animal_without_photo_gets_one_with_credit_and_reason(svc, web):
    p = project_with(svc, lion())
    cid = p.context[0].id
    assert asyncio.run(svc.auto_photos(p.id)) == 1
    item = get(svc, p.id, cid)
    assert len(item.files) == 1 and item.analysis["auto_photo"]["query"] == "male lion"
    assert item.analysis["auto_photo"]["photo"]["author"] == "Jane Doe"
    assert item.analysis["credits"][0]["license"] == "CC BY-SA 4.0"
    assert item.analysis["auto_photo"]["candidates"]                          # alternatives are kept for "Choose another"
    assert item.actor.kind == "animal" and not item.needs_consent


def test_a_photo_you_supplied_is_never_replaced_or_searched(svc, web, sample_photo):
    item = lion()
    p = project_with(svc, item)
    q = svc.load(p.id)
    svc.add_context_file(q, sample_photo, ctx_id=item.id)
    assert asyncio.run(svc.auto_photos(p.id)) == 0
    assert web["search"] == []
    assert get(svc, p.id, item.id).files and not get(svc, p.id, item.id).analysis.get("auto_photo")
    assert asyncio.run(svc.auto_photos(p.id, only=[item.id])) == 0              # even when asked for this item


@pytest.mark.parametrize("make", [
    lambda: ContextItem(type=ContextType.actor, title="Priya", actor=ActorDetails(kind="ai_person", description="woman")),
    lambda: ContextItem(type=ContextType.actor, title="Rahul", actor=ActorDetails(kind="real_person")),
    lambda: ContextItem(type=ContextType.actor, title="Our bag", actor=ActorDetails(kind="product", description="travel bag")),
    lambda: ContextItem(type=ContextType.entity, title="Our logo", role=ContextRole.must_appear),
    lambda: ContextItem(type=ContextType.text, title="Facts", text="400 g"),
    lambda: ContextItem(type=ContextType.object, title="Object"),                  # a generic, not-yet-described item
])
def test_never_searches_for_people_products_brands_or_unnamed_items(svc, web, make):
    p = project_with(svc, make())
    assert asyncio.run(svc.auto_photos(p.id)) == 0 and web["search"] == []


def test_objects_and_places_are_searched(svc, web):
    p = project_with(svc,
                     ContextItem(type=ContextType.object, title="Coffee cup", role=ContextRole.must_appear),
                     ContextItem(type=ContextType.location, title="Savannah at dawn", role=ContextRole.look_reference))
    assert asyncio.run(svc.auto_photos(p.id)) == 2


def test_removing_the_found_photo_switches_search_off_for_that_item(svc, web):
    item = lion()
    p = project_with(svc, item)
    asyncio.run(svc.auto_photos(p.id))
    svc.update_context(p.id, item.id, {"files": []})                            # the user removes it
    got = get(svc, p.id, item.id)
    assert got.files == [] and got.analysis["auto_photo_off"] and "credits" not in got.analysis
    web["search"].clear()
    assert asyncio.run(svc.auto_photos(p.id)) == 0 and web["search"] == []      # not searched again by itself
    assert asyncio.run(svc.auto_photos(p.id, only=[item.id], force=True)) == 1  # ...but the "find one for me" button works
    assert not get(svc, p.id, item.id).analysis.get("auto_photo_off")


def test_failures_never_break_planning_and_are_not_retried_every_time(svc, web):
    web["fail"] = True
    item = lion()
    p = project_with(svc, item)
    assert asyncio.run(svc.auto_photos(p.id)) == 0                              # no exception
    got = get(svc, p.id, item.id)
    assert got.analysis["auto_photo_tried"] and "no suitable photo" in got.analysis["auto_photo_error"]
    web["search"].clear()
    asyncio.run(svc.auto_photos(p.id))
    assert web["search"] == []


def test_switched_off_in_settings(svc, web):
    p = project_with(svc, lion())
    svc.update_project(p.id, {"settings": {"auto_photo": False}})
    assert asyncio.run(svc.auto_photos(p.id)) == 0 and web["search"] == []


def test_licence_rules_and_ranking():
    ok = [photo("Lion male"), photo("Lion", lic="CC0"), photo("Lion", lic="Public domain"), photo("Lion", lic="Pexels License", src="pexels")]
    assert len(stock.rank(ok, "lion")) == 4
    bad = [photo("Lion", lic="CC BY-NC 4.0"), photo("Lion", lic="CC BY-ND 2.0"), photo("Lion", lic="see source"), photo("Lion", lic="All rights reserved")]
    assert stock.rank(bad, "lion") == []                                          # we animate and may sell: no NC / ND
    ranked = stock.rank([photo("Map of lion range"), photo("Lion skeleton"), photo("Male lion portrait"), photo("Sunset")], "male lion")
    assert ranked[0].title == "Male lion portrait" and all("map" not in r.title.lower() for r in ranked)


def test_vision_pick_is_used_when_a_real_brain_is_connected(svc, web, monkeypatch):
    from video_generator.brain import PhotoChoice
    web["results"] = [photo("Lion male"), photo("Lion portrait"), photo("Lion at rest")]
    item = lion()
    p = project_with(svc, item)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    svc.reload()

    async def fake_pick(project, subject, titles, images):
        return PhotoChoice(choice=2, reason="faces the camera")
    monkeypatch.setattr(svc.brain, "pick_photo", fake_pick)
    asyncio.run(svc.auto_photos(p.id))
    assert get(svc, p.id, item.id).analysis["auto_photo"]["photo"]["title"] != ""
    assert get(svc, p.id, item.id).files


def test_draft_finds_the_photo_before_any_money_is_spent(svc, web):
    p = svc.new_project("Add a lion that speaks says hello", seconds=15, quality_mode="free")
    p = asyncio.run(svc.draft(p.id))
    lion_item = next(c for c in p.context if c.type == ContextType.actor and c.actor.kind == "animal")
    assert lion_item.files and lion_item.analysis["auto_photo"]


def test_clip_generation_searches_first_when_nothing_was_found_yet(svc, web):
    from video_generator.runner import Engine
    item = lion()
    p = project_with(svc, item)
    from video_generator.models import ActorInShot, ClipScript, DialogueLine, Node, NodeKind, ShotType
    from video_generator.tree import add_child
    q = svc.load(p.id)
    c = add_child(q, q.root.id, Node(kind=NodeKind.clip, title="c", goal="g", target_seconds=4))
    c.script = ClipScript(shot_type=ShotType.talking_head, visual="close-up", on_camera_speech=True,
                          actors_in_shot=[ActorInShot(actor_id=item.id)], dialogue=[DialogueLine(speaker=item.id, text="hello")])
    svc.save(q)
    eng = Engine(svc)
    asyncio.run(eng._prepare_actors(p.id, c.id))
    got = get(svc, p.id, item.id)
    assert got.files and got.actor.reference_sheet                                # photo found, then used exactly as the reference


def test_unreachable_photo_sites_give_a_friendly_message(svc, monkeypatch):
    async def offline(q, source="wikimedia", limit=24, client=None):
        raise ConnectionError("All connection attempts failed")
    monkeypatch.setattr(stock, "search", offline)
    item = lion()
    p = project_with(svc, item)
    assert asyncio.run(svc.auto_photos(p.id)) == 0
    assert "internet connection" in get(svc, p.id, item.id).analysis["auto_photo_error"]
