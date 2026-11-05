"""Automatic photo search: only when the user supplied none, only for animals/objects/places, never for people."""
import asyncio
from pathlib import Path

import httpx
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


# ------------------------------------------------------------------ round 3: downloads that fail must not end the search
JPEG = b"\xff\xd8abc"


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("raw,clean", [
    ("//upload.wikimedia.org/x.jpg", "https://upload.wikimedia.org/x.jpg"),
    ("http://upload.wikimedia.org/x.jpg", "https://upload.wikimedia.org/x.jpg"),
    ("  https://upload.wikimedia.org/x.jpg \n", "https://upload.wikimedia.org/x.jpg"),
    ("http://evil.example/x.jpg", "http://evil.example/x.jpg"),          # never upgraded: it is refused instead
])
def test_addresses_are_cleaned_before_they_are_checked(raw, clean):
    assert stock.clean_url(raw) == clean


@pytest.mark.parametrize("host,ok", [
    ("upload.wikimedia.org", True), ("commons.wikimedia.org", True), ("images.pexels.com", True), ("wikimedia.org", True),
    ("evil.example", False), ("wikimedia.org.evil.example", False), ("notwikimedia.org", False), ("pexels.com.evil.io", False), ("", False),
])
def test_allowed_sites_need_the_dot_in_front(host, ok):
    assert stock.host_allowed(host) is ok


def test_download_accepts_clean_scheme_less_and_http_forms(tmp_path):
    client = mock_client(lambda r: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=JPEG))
    for url in ("//upload.wikimedia.org/a.jpg", "http://upload.wikimedia.org/a.jpg", "https://commons.wikimedia.org/a.jpg"):
        assert asyncio.run(stock.download(url, tmp_path, "lion", client=client)).read_bytes() == JPEG


def test_refusal_names_the_host(tmp_path):
    with pytest.raises(stock.StockError, match=r"host: evil\.example"):
        asyncio.run(stock.download("https://evil.example/x.jpg", tmp_path, "x"))
    with pytest.raises(stock.StockError, match="no web address"):
        asyncio.run(stock.download("", tmp_path, "x"))


def test_redirects_are_followed_only_between_allowed_sites(tmp_path):
    def handler(request: httpx.Request):
        if request.url.path == "/old.jpg":
            return httpx.Response(302, headers={"location": "https://upload.wikimedia.org/new.jpg"})
        if request.url.path == "/new.jpg":
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=JPEG)
        if request.url.path == "/evil.jpg":
            return httpx.Response(302, headers={"location": "https://evil.example/x.jpg"})
        if request.url.path == "/loop.jpg":
            return httpx.Response(302, headers={"location": "/loop.jpg"})
        return httpx.Response(404)
    client = mock_client(handler)
    assert asyncio.run(stock.download("https://upload.wikimedia.org/old.jpg", tmp_path, "a", client=client)).exists()
    with pytest.raises(stock.StockError, match="evil.example"):
        asyncio.run(stock.download("https://upload.wikimedia.org/evil.jpg", tmp_path, "b", client=client))
    with pytest.raises(stock.StockError, match="too many times"):
        asyncio.run(stock.download("https://upload.wikimedia.org/loop.jpg", tmp_path, "c", client=client))


def test_search_results_with_odd_addresses_are_cleaned():
    page = {"query": {"pages": {"1": {"index": 1, "title": "File:Lion male.jpg", "imageinfo": [{
        "mime": "image/jpeg", "width": 4000, "height": 3000, "thumburl": "//upload.wikimedia.org/b.jpg",
        "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]}}}}
    client = mock_client(lambda r: httpx.Response(200, json=page))
    res = asyncio.run(stock.search("lion", "wikimedia", client=client))
    assert res[0].url == "https://upload.wikimedia.org/b.jpg"


def test_when_the_first_photo_cannot_be_downloaded_the_next_one_is_used(svc, monkeypatch, sample_photo):
    bad = StockPhoto("wikimedia", "Lion male", "https://x.example/t.jpg", "https://x.example/bad.jpg", 1600, 1000, "Bad Author", "CC0", "https://c/1")
    good = StockPhoto("wikimedia", "Lion portrait", "https://upload.wikimedia.org/t.jpg", "https://upload.wikimedia.org/good.jpg",
                      1600, 1000, "Good Author", "CC BY 4.0", "https://c/2")

    async def fake_search(q, source="wikimedia", limit=24, client=None):
        return [bad, good]
    real_download = stock.download

    async def fake_download(url, dest_dir, name, client=None):
        if "good" in url:
            dest = Path(dest_dir) / "found.jpg"
            dest.write_bytes(sample_photo.read_bytes())
            return dest
        return await real_download(url, dest_dir, name)          # the real check refuses the bad address
    monkeypatch.setattr(stock, "search", fake_search)
    monkeypatch.setattr(stock, "download", fake_download)
    p = project_with(svc, lion())
    cid = p.context[0].id
    assert asyncio.run(svc.auto_photos(p.id)) == 1
    item = get(svc, p.id, cid)
    assert item.files and item.analysis["auto_photo"]["photo"]["author"] == "Good Author"
    assert "auto_photo_error" not in item.analysis


def test_when_no_photo_can_be_downloaded_the_reason_says_how_many_and_why(svc, monkeypatch):
    photos = [StockPhoto("wikimedia", f"Lion {i}", "https://x.example/t.jpg", f"https://x.example/{i}.jpg", 1600, 1000, "A", "CC0", "https://c") for i in range(3)]

    async def fake_search(q, source="wikimedia", limit=24, client=None):
        return photos
    monkeypatch.setattr(stock, "search", fake_search)
    p = project_with(svc, lion())
    cid = p.context[0].id
    assert asyncio.run(svc.auto_photos(p.id)) == 0                              # no exception reaches the caller
    err = get(svc, p.id, cid).analysis["auto_photo_error"]
    assert "found 3 photo(s)" in err and "none could be downloaded" in err and "host: x.example" in err
    assert not err.endswith(".")


def test_photo_test_command_describes_every_step(tmp_path, monkeypatch):
    wiki = {"query": {"pages": {
        "1": {"index": 1, "title": "File:Male lion portrait.jpg", "imageinfo": [{
            "mime": "image/jpeg", "width": 4000, "height": 3000, "thumburl": "https://upload.wikimedia.org/a.jpg",
            "extmetadata": {"Artist": {"value": "Jane"}, "LicenseShortName": {"value": "CC BY 4.0"}}}]},
        "2": {"index": 2, "title": "File:Lion map.jpg", "imageinfo": [{
            "mime": "image/jpeg", "width": 4000, "height": 3000, "thumburl": "https://upload.wikimedia.org/b.jpg",
            "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]}}}}

    def handler(request: httpx.Request):
        if "commons.wikimedia.org" in request.url.host:
            return httpx.Response(200, json=wiki)
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=JPEG)
    lines, saved = asyncio.run(stock.diagnose("male lion", tmp_path, client=mock_client(handler), download_client=mock_client(handler)))
    text = "\n".join(lines)
    assert "2 photo(s) came back" in text and "1 left" in text and "removed: “Lion map”" in text
    assert "address host: upload.wikimedia.org; allowed: yes" in text and "downloaded OK" in text
    assert saved and saved.exists()

    from typer.testing import CliRunner
    from video_generator.cli import app
    monkeypatch.setattr(stock, "diagnose", lambda words, dest: _fake_diag(tmp_path))
    out = CliRunner().invoke(app, ["photo-test", "male lion"])
    assert out.exit_code == 0 and "Photo search works" in out.output


async def _fake_diag(tmp_path):
    p = tmp_path / "x.jpg"
    p.write_bytes(JPEG)
    return ["1. Search on wikimedia for “male lion”: 3 photo(s) came back."], p
