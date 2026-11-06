"""Local web app: REST API + live WebSocket events + the built GUI."""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import traceback
from importlib import resources
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import media
from .. import stock
from ..brain import CommandPlan
from ..catalog import Catalog, load_vendors
from ..config import ENV_FILE_KEYS, Config, save_key
from ..context import effective_context
from ..project import ProjectStore
from ..registry import plugin_classes
from ..runner import Engine
from ..services import Service
from ..tree import find, numbering


class Hub:
    def __init__(self):
        self.clients: dict[str, set[WebSocket]] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def emit(self, pid: str, event: dict) -> None:
        if not self.loop:
            return
        event = {"project": pid, **event}
        for ws in list(self.clients.get(pid, set())) + list(self.clients.get("*", set())):
            self.loop.call_soon_threadsafe(asyncio.ensure_future, self._send(ws, pid, event))

    async def _send(self, ws: WebSocket, pid: str, event: dict) -> None:
        try:
            await ws.send_json(event)
        except Exception:
            for s in self.clients.values():
                s.discard(ws)


hub = Hub()
svc = Service()
engine = Engine(svc, emit=hub.emit)
app = FastAPI(title="video-generator", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
BACKGROUND: set[asyncio.Task] = set()


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(_app):
    hub.loop = asyncio.get_running_loop()
    engine.recover()
    yield

app.router.lifespan_context = lifespan


def bg(coro, pid: str, label: str) -> None:
    async def wrapper():
        hub.emit(pid, {"type": "busy", "label": label, "busy": True})
        try:
            await coro
            hub.emit(pid, {"type": "project"})
        except Exception as exc:
            traceback.print_exc()
            hub.emit(pid, {"type": "error", "message": f"{label} failed: {exc}"})
        finally:
            hub.emit(pid, {"type": "busy", "label": label, "busy": False})
    t = asyncio.create_task(wrapper())
    BACKGROUND.add(t)
    t.add_done_callback(BACKGROUND.discard)


def view(pid: str) -> dict:
    try:
        p = svc.load(pid)
    except FileNotFoundError:
        raise HTTPException(404, "project not found")
    summary = svc.summary(p)
    ProjectStore.save(p, snapshot=False)
    return {"project": p.model_dump(mode="json"), "summary": summary, "engine": engine.status(pid)}


def guard(fn):
    async def inner(*a, **k):
        try:
            r = fn(*a, **k)
            if asyncio.iscoroutine(r):
                r = await r
            return r
        except HTTPException:
            raise
        except (ValueError, KeyError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(500, str(exc))
    return inner


# ===================================================================== projects
@app.get("/api/health")
async def health():
    return {"ok": True, "ffmpeg": media.have_ffmpeg(), "brain": svc.reg.llm_plugin_name("default"),
            "default_budget": svc.config.budget_usd, "default_quality": svc.config.quality_mode}


@app.get("/api/languages")
async def get_languages():
    """The languages offered on the Start screen (data/languages.yaml)."""
    from .. import languages
    return [{"code": c, "name": n} for c, n in languages.names().items()]


@app.get("/api/ballpark")
async def get_ballpark(seconds: float = 0, quality: str = ""):
    """A rough price before any plan exists, from the catalogue prices of the models this quality would pick."""
    return svc.ballpark(seconds or None, quality or None)


@app.get("/api/projects")
async def list_projects():
    return ProjectStore.list()


@app.post("/api/projects")
async def create_project(goal: str = Form(...), seconds: float = Form(60), aspect: str = Form("16:9"),
                         format: str = Form("mp4"), quality_mode: str = Form(""), budget: float = Form(0),
                         length_mode: str = Form(""), language: str = Form(""),
                         files: list[UploadFile] = File(default=[])):
    tmp = Path(tempfile.mkdtemp())
    paths = []
    for f in files:
        if not f.filename:
            continue
        dest = tmp / Path(f.filename).name
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(dest)
    p = svc.new_project(goal, seconds=seconds, aspect=aspect, fmt=format, files=paths,
                        budget=budget or None, quality_mode=quality_mode or None,
                        length_mode=length_mode or None, language=language or None)
    shutil.rmtree(tmp, ignore_errors=True)
    bg(svc.draft(p.id), p.id, "Drafting your plan")
    return {"id": p.id}


@app.get("/api/projects/{pid}")
async def get_project(pid: str):
    return view(pid)


@app.patch("/api/projects/{pid}")
async def patch_project(pid: str, patch: dict = Body(...)):
    await guard(svc.update_project)(pid, patch)
    return view(pid)


@app.delete("/api/projects/{pid}")
async def delete_project(pid: str):
    ProjectStore.delete(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/draft")
async def redraft(pid: str):
    bg(svc.draft(pid), pid, "Drafting your plan")
    return {"ok": True}


@app.post("/api/projects/{pid}/undo")
async def undo(pid: str):
    ProjectStore.undo(pid)
    return view(pid)


@app.post("/api/projects/{pid}/redo")
async def redo(pid: str):
    ProjectStore.redo(pid)
    return view(pid)


@app.get("/api/projects/{pid}/budget")
async def budget(pid: str):
    return await guard(svc.budget_report)(pid)


@app.post("/api/projects/{pid}/explain")
async def explain(pid: str, body: dict = Body(...)):
    answer = await guard(svc.explain)(pid, body["question"], body.get("focus"))
    return {"answer": answer}


@app.get("/api/projects/{pid}/ledger")
async def ledger(pid: str):
    return ProjectStore.ledger(pid)


# ===================================================================== tree
@app.post("/api/projects/{pid}/nodes")
async def add_node(pid: str, body: dict = Body(...)):
    _, nid = await guard(svc.add_node)(pid, body["parent_id"], body.get("kind", "clip"), body.get("title", ""),
                                        body.get("goal", ""), body.get("index"))
    return {**view(pid), "new_id": nid}


@app.patch("/api/projects/{pid}/nodes/{nid}")
async def patch_node(pid: str, nid: str, patch: dict = Body(...)):
    await guard(svc.update_node)(pid, nid, patch)
    return view(pid)


@app.delete("/api/projects/{pid}/nodes/{nid}")
async def delete_node(pid: str, nid: str):
    await guard(svc.remove_node)(pid, nid)
    return view(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/move")
async def move_node(pid: str, nid: str, body: dict = Body(...)):
    await guard(svc.move_node)(pid, nid, body["parent_id"], int(body.get("index", 0)))
    return view(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/decompose")
async def decompose(pid: str, nid: str):
    await guard(svc.decompose)(pid, nid)
    return view(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/split")
async def split_clip(pid: str, nid: str):
    """Split one clip into consecutive clips that each need only what one route can do."""
    await guard(svc.split_clip)(pid, nid)
    return view(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/script")
async def write_script(pid: str, nid: str, body: dict = Body(default={})):
    await guard(svc.write_script)(pid, nid, body.get("feedback", ""))
    return view(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/revise")
async def revise(pid: str, nid: str, body: dict = Body(...)):
    await guard(svc.revise)(pid, nid, body["instruction"])
    return view(pid)


@app.post("/api/projects/{pid}/scripts")
async def write_scripts(pid: str, body: dict = Body(default={})):
    await guard(svc.write_all_scripts)(pid, body.get("under"), bool(body.get("overwrite")))
    return view(pid)


@app.get("/api/projects/{pid}/nodes/{nid}/context")
async def node_context(pid: str, nid: str):
    p = svc.load(pid)
    return [{"item": e.item.model_dump(mode="json"), "origin": e.origin, "overridden_from": e.overridden_from}
            for e in effective_context(p, nid)]


@app.post("/api/projects/{pid}/nodes/{nid}/context/{cid}/toggle")
async def toggle_context(pid: str, nid: str, cid: str, body: dict = Body(...)):
    await guard(svc.toggle_context)(pid, nid, cid, bool(body.get("off")))
    return view(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/context/{cid}/override")
async def override_context(pid: str, nid: str, cid: str, body: dict = Body(...)):
    await guard(svc.override_context)(pid, nid, cid, body.get("replacement"))
    return view(pid)


# ===================================================================== commands
@app.post("/api/projects/{pid}/command/plan")
async def command_plan(pid: str, body: dict = Body(...)):
    plan = await guard(svc.plan_command)(pid, body["text"], body.get("focus"))
    return plan.model_dump()


@app.post("/api/projects/{pid}/command/apply")
async def command_apply(pid: str, body: dict = Body(...)):
    plan = CommandPlan.model_validate(body["plan"])
    actions = await guard(svc.apply_command)(pid, plan)
    gen = actions.get("generate")
    run = None
    if gen:
        nums = {v: k for k, v in numbering(svc.load(pid)).items()}
        if gen in ("all", "next"):
            run = await engine.start(pid, gen)
        elif gen in nums:
            run = await engine.start(pid, "clip", [nums[gen]])
    return {**view(pid), "actions": actions, "run": run}


# ===================================================================== context
@app.post("/api/projects/{pid}/context")
async def add_context(pid: str, body: dict = Body(...)):
    _, item = await guard(svc.add_context)(pid, body)
    if svc.wants_auto_photo(item) and svc.load(pid).settings.auto_photo:
        bg(svc.auto_photos(pid, only=[item.id]), pid, f"Finding a photo of {item.title}")    # free; only when you gave none
    return {**view(pid), "new_id": item.id}


@app.post("/api/projects/{pid}/context/{cid}/auto-photo")
async def auto_photo(pid: str, cid: str):
    """The 'find one for me' button. Never replaces a photo you supplied unless you remove it first."""
    bg(svc.auto_photos(pid, only=[cid], force=True), pid, "Finding a photo")
    return {"ok": True}


@app.post("/api/projects/{pid}/context/upload")
async def upload_context(pid: str, files: list[UploadFile] = File(...), scope: str = Form("project"),
                         ctx_id: str = Form(""), hint: str = Form(""), as_node: str = Form("")):
    p = svc.load(pid)
    tmp = Path(tempfile.mkdtemp())
    ids = []
    try:
        for f in files:
            dest = tmp / Path(f.filename or "file").name
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)
            item = svc.add_context_file(p, dest, scope=scope, hint=hint, ctx_id=ctx_id or None, save=False)
            ids.append(item.id)
        if as_node:
            svc._attach_media_context(p)
        svc.save(p)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(400, str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {**view(pid), "new_ids": ids}


@app.post("/api/projects/{pid}/context/{cid}/voice-recording")
async def voice_recording(pid: str, cid: str, file: UploadFile = File(...), consent_self: str = Form("")):
    """A voice sample recorded in the browser. Used only to copy the voice; never placed in the video."""
    data = await file.read()
    await guard(svc.add_voice_recording)(pid, cid, data, file.filename or "", consent_self.lower() in ("1", "true", "yes"))
    return view(pid)


@app.get("/api/stock/search")
async def stock_search(q: str, source: str = "wikimedia"):
    try:
        found = await stock.search(q, source)
    except stock.StockError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Photo search failed: {exc}")
    return {"sources": stock.sources_available(), "results": [stock.to_dict(x) for x in found]}


@app.post("/api/projects/{pid}/context/{cid}/stock")
async def stock_add(pid: str, cid: str, body: dict = Body(...)):
    await guard(svc.add_stock_photo)(pid, cid, body["url"], body)
    return view(pid)


@app.patch("/api/projects/{pid}/context/{cid}")
async def patch_context(pid: str, cid: str, patch: dict = Body(...)):
    await guard(svc.update_context)(pid, cid, patch)
    return view(pid)


@app.delete("/api/projects/{pid}/context/{cid}")
async def delete_context(pid: str, cid: str):
    await guard(svc.remove_context)(pid, cid)
    return view(pid)


@app.post("/api/projects/{pid}/context/{cid}/consent")
async def consent(pid: str, cid: str, body: dict = Body(...)):
    await guard(svc.give_consent)(pid, cid, body["statement"], body.get("by", ""))
    return view(pid)


@app.post("/api/projects/{pid}/context/{cid}/voice-preview")
async def voice_preview(pid: str, cid: str):
    """Speak a short sample in this actor's voice (cloned if consented, else the voice chosen for their profile)."""
    from .. import casting
    from ..context import item_by_id
    p = svc.load(pid)
    item = item_by_id(p, cid)
    entry = svc.reg.choose("voice", mode=p.settings.quality_mode)
    plugin = svc.reg.plugin(entry.plugin)
    try:
        a = item.actor
        if a and not (a.voice_id and a.voice_provider == entry.plugin) and not entry.is_free:
            await engine._actor_voice(pid, cid, entry)          # clone (with consent) or choose from the profile
            p = svc.load(pid)
            item = item_by_id(p, cid)
            a = item.actor
        prof = casting.profile_for(item, p)
        vid = a.voice_id if a and a.voice_provider == entry.plugin else None
        out = ProjectStore.path_for(pid) / "cast" / cid / "preview.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        text = f"Hello, I am {item.title}. This is how I will sound in your video."
        await plugin.synthesize(text, casting.spec_from(prof, vid), out, entry.model)
        fitted, _, _ = await asyncio.to_thread(casting.fit_voice, out, prof, None)
        if fitted != out:
            shutil.move(str(fitted), str(out))
    except Exception as exc:
        raise HTTPException(400, f"voice preview failed: {exc}")
    import time as _t
    return {"url": f"/files/{pid}/cast/{cid}/preview.wav?t={int(_t.time())}", "voice": entry.id,
            "name": (item_by_id(svc.load(pid), cid).actor.voice_name if item.actor else "")}


@app.post("/api/projects/{pid}/context/{cid}/voice-next")
async def voice_next(pid: str, cid: str):
    """Try the next best voice for this actor. The voice you pick stays, even if you later edit the description."""
    from ..context import item_by_id
    p = svc.load(pid)
    entry = svc.reg.choose("voice", mode=p.settings.quality_mode)
    item = item_by_id(p, cid)
    if not item.actor:
        raise HTTPException(400, "Only actors have voices.")
    if not item.analysis.get("voice_alternatives"):
        await engine._actor_voice(pid, cid, entry)
        item = item_by_id(svc.load(pid), cid)
    alts = [x for x in (item.analysis.get("voice_alternatives") or []) if x.get("voice_id")]
    if len(alts) < 2:
        raise HTTPException(400, "No other voice is available for this speaker. Add or allow more voices at the voice service.")
    ids = [x["voice_id"] for x in alts]
    nxt = alts[(ids.index(item.actor.voice_id) + 1) % len(alts)] if item.actor.voice_id in ids else alts[0]
    await engine._store_voice(pid, cid, entry.plugin, nxt["voice_id"], nxt.get("name", ""), nxt.get("note", ""), alts, None)

    def mark(pr):
        item_by_id(pr, cid).analysis["voice_user_picked"] = True
    await engine.mutate(pid, mark)
    return view(pid)


# ===================================================================== dependencies
@app.post("/api/projects/{pid}/deps")
async def add_dep(pid: str, body: dict = Body(...)):
    await guard(svc.add_dependency)(pid, body["from_id"], body["to_id"], body.get("type", "continues_from"), body.get("note", ""))
    return view(pid)


@app.patch("/api/projects/{pid}/deps/{did}")
async def patch_dep(pid: str, did: str, body: dict = Body(...)):
    await guard(svc.update_dependency)(pid, did, body["type"])
    return view(pid)


@app.delete("/api/projects/{pid}/deps/{did}")
async def delete_dep(pid: str, did: str):
    await guard(svc.remove_dependency)(pid, did)
    return view(pid)


@app.post("/api/projects/{pid}/deps/suggest")
async def suggest_deps(pid: str):
    await guard(svc.suggest_dependencies)(pid)
    return view(pid)


@app.post("/api/projects/{pid}/unpin")
async def unpin(pid: str, body: dict = Body(default={})):
    """Clear the model chosen on clips (all clips pinned to a free model when no ids are given): the tool picks the best again."""
    await guard(svc.unpin)(pid, body.get("ids"))
    return view(pid)


# ===================================================================== estimate & run
@app.post("/api/projects/{pid}/estimate")
async def estimate(pid: str, body: dict = Body(default={})):
    p = svc.load(pid)
    targets = body.get("targets")
    mode = body.get("mode")
    if mode in ("all", "continue"):
        from ..tree import leaves
        targets = [n.id for n in leaves(p) if n.status.value != "done"]
    elif mode == "next":
        from ..deps import topo_order
        order = [n for n in topo_order(p) if find(p, n).status.value != "done"]
        targets = order[:1]
    return svc.estimate_targets(pid, targets or [])


@app.post("/api/projects/{pid}/run")
async def run(pid: str, body: dict = Body(...)):
    res = await guard(engine.start)(pid, body.get("mode", "all"), body.get("targets"), body.get("auto_pick"))
    return {**view(pid), "run": res}


@app.post("/api/projects/{pid}/pause")
async def pause(pid: str):
    await engine.pause(pid)
    return view(pid)


@app.post("/api/projects/{pid}/resume")
async def resume(pid: str):
    await engine.resume(pid)
    return view(pid)


@app.post("/api/projects/{pid}/stop")
async def stop(pid: str):
    await engine.stop(pid)
    return view(pid)


@app.post("/api/projects/{pid}/assemble")
async def assemble(pid: str, body: dict = Body(default={})):
    """Join the clips into the final video. body.music: auto | reuse | new | none (see Engine.assemble)."""
    music = body.get("music", "auto")
    if music not in ("auto", "reuse", "new", "none"):
        raise HTTPException(400, "music must be auto, reuse, new or none")
    bg(engine.assemble(pid, music), pid, "Stitching the final video")
    return {"ok": True}


@app.get("/api/projects/{pid}/music")
async def music_status(pid: str):
    """The saved music track, and what joining would cost for music (0 when the saved track is reused)."""
    return await guard(svc.music_status)(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/export")
async def export_node(pid: str, nid: str, body: dict = Body(default={})):
    """A finished video of one clip or part, ready to download. body.music: auto | new | none. When a new music track would cost
    money and you have not said so, the answer is {needs_music_choice: true, cost_usd, ...} and nothing is spent."""
    music = body.get("music", "auto")
    if music not in ("auto", "new", "none"):
        raise HTTPException(400, "music must be auto, new or none")
    res = await guard(engine.export_node)(pid, nid, music)
    if res.get("path"):
        from urllib.parse import quote
        res["url"] = f"/files/{pid}/{res['path']}?download={quote(res['filename'])}"
        if res.get("srt"):
            res["srt_url"] = f"/files/{pid}/{res['srt']}?download={quote(res['srt_filename'])}"
    return res


@app.post("/api/projects/{pid}/nodes/{nid}/pick")
async def pick(pid: str, nid: str, body: dict = Body(...)):
    await guard(engine.pick)(pid, nid, body["take_id"])
    return view(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/compare")
async def compare(pid: str, nid: str, body: dict = Body(...)):
    bg(engine.compare(pid, nid, body["models"]), pid, "Comparing models")
    return {"ok": True}


# ===================================================================== review & versions
@app.patch("/api/projects/{pid}/reviews/{rid}/suggestions/{sid}")
async def patch_suggestion(pid: str, rid: str, sid: str, body: dict = Body(...)):
    p = svc.load(pid)
    for r in p.reviews:
        if r.id == rid:
            for s in r.suggestions:
                if s.id == sid:
                    if "accepted" in body:
                        s.accepted = bool(body["accepted"])
                    if "text" in body:
                        s.text = body["text"]
    svc.save(p, snapshot=False)
    return view(pid)


@app.post("/api/projects/{pid}/nodes/{nid}/remake/preview")
async def remake_preview(pid: str, nid: str, body: dict = Body(...)):
    return await guard(svc.preview_remake)(pid, nid, body.get("accepted", []), body.get("feedback", ""))


@app.post("/api/projects/{pid}/nodes/{nid}/remake/apply")
async def remake_apply(pid: str, nid: str, body: dict = Body(...)):
    await guard(svc.apply_remake)(pid, nid, body["script"], body.get("feedback", ""))
    run = None
    if body.get("generate", True):
        run = await engine.start(pid, "clip", [nid])
    return {**view(pid), "run": run}


@app.post("/api/projects/{pid}/nodes/{nid}/revert")
async def revert(pid: str, nid: str, body: dict = Body(...)):
    await guard(svc.revert_version)(pid, nid, int(body["version"]))
    return view(pid)


# ===================================================================== files
@app.get("/files/{pid}/{path:path}")
async def files(pid: str, path: str, download: str = ""):
    try:
        base = ProjectStore.path_for(pid).resolve()
    except FileNotFoundError:
        raise HTTPException(404, "not found")
    target = (base / path).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(403, "outside project")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "not found")
    if download:                                      # save under a friendly name instead of the file's own
        return FileResponse(target, filename=Path(download).name or target.name)
    return FileResponse(target)


# ===================================================================== settings
def settings_view() -> dict:
    cfg = svc.config
    plugins = []
    for name, cls in sorted(plugin_classes().items()):
        try:
            ok, why = svc.reg.plugin(name).is_configured()
        except Exception as exc:
            ok, why = False, str(exc)
        plugins.append({"name": name, "job": getattr(cls, "job", ""), "description": getattr(cls, "description", ""),
                        "configured": ok, "status": why, "env": getattr(cls, "env_keys", [])})
    vendors = []
    for v in load_vendors():
        keys = [{"name": k, "set": bool(os.environ.get(k)), "from_file": k in ENV_FILE_KEYS} for k in v.get("env", [])]
        vendors.append({**v, "keys": keys, "configured": all(k["set"] for k in keys)})
    return {"config": cfg.model_dump(), "plugins": plugins, "vendors": vendors,
            "catalog": svc.model_rows(),
            "brain": svc.reg.llm_plugin_name("default"), "reviewer": svc.reg.llm_plugin_name("review")}


@app.get("/api/settings")
async def get_settings():
    return settings_view()


@app.patch("/api/settings")
async def patch_settings(patch: dict = Body(...)):
    cfg = svc.config
    data = cfg.model_dump()
    for k, v in patch.items():
        if k == "llm" and isinstance(v, dict):
            data["llm"] = {**data["llm"], **v}
        elif k in data:
            data[k] = v
    Config.model_validate(data).save()
    svc.reload()
    engine.svc = svc
    return settings_view()


@app.post("/api/models/llm/refresh")
async def refresh_llm_models():
    """Ask each connected AI vendor which models your key can use (free). Returns models, errors and skipped vendors."""
    return await svc.discover_models()


@app.post("/api/catalog/llm")
async def add_llm_model(body: dict = Body(...)):
    """Add an AI model found at the vendor to the catalogue, with its price per 1M tokens."""
    try:
        svc.add_model(body["plugin"], body["model"], float(body.get("usd_in", 0)), float(body.get("usd_out", 0)), body.get("note", ""))
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    engine.svc = svc
    return settings_view()


@app.post("/api/settings/keys")
async def set_key(body: dict = Body(...)):
    name = body["name"]
    allowed = {k for v in load_vendors() for k in v.get("env", [])}
    if name not in allowed:
        raise HTTPException(400, "unknown key name")
    save_key(name, body.get("value", "").strip())
    svc.reload()
    return settings_view()


@app.post("/api/settings/test")
async def test_plugin(body: dict = Body(...)):
    name = body["plugin"]
    plugin = svc.reg.plugin(name)
    ok, why = plugin.is_configured()
    if not ok:
        return {"ok": False, "message": why}
    if getattr(plugin, "job", "") == "llm":
        from pydantic import BaseModel

        class Ping(BaseModel):
            reply: str

        try:
            res, usage = await plugin.generate_json(system="Reply in JSON.", user='Say "ready".', schema=Ping,
                                                    model=svc.reg.llm_model("default", name), max_tokens=2000,
                                                    meta={"task": "ping"})
            return {"ok": True, "message": f"connected — replied “{getattr(res, 'reply', '')}”"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "key found (a real call is made on first use)"}


@app.patch("/api/catalog/{entry_id}")
async def patch_catalog(entry_id: str, patch: dict = Body(...)):
    e = svc.catalog.get(entry_id)
    data = e.model_dump()
    for k, v in patch.items():
        if k == "price" and isinstance(v, dict):
            data["price"] = {**data["price"], **v}
        elif k in data:
            data[k] = v
    new = type(e).model_validate(data)
    svc.catalog.save_user_override(new)
    svc.reload()
    engine.svc = svc
    return settings_view()


# ===================================================================== websocket
@app.websocket("/ws/{pid}")
async def ws(websocket: WebSocket, pid: str):
    await websocket.accept()
    hub.clients.setdefault(pid, set()).add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.get(pid, set()).discard(websocket)


# ===================================================================== GUI
STATIC = Path(str(resources.files("video_generator.web").joinpath("static")))
if (STATIC / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/{full_path:path}")
async def spa(full_path: str):
    if full_path.startswith(("api/", "files/", "ws/")):
        raise HTTPException(404, "not found")
    index = STATIC / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>video-generator</h1><p>The GUI is not built. Run <code>npm --prefix frontend run build</code>.</p>")
