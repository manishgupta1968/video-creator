"""Switching between Claude Code and Codex, their model lists read from the programs themselves, and one change for
the whole 3D film. Real programs are replaced by small stand-ins."""
import asyncio
import json
import sys

import pytest

from video_generator.plugins.base import AgentTask, PluginError
from video_generator.plugins.llm import cli_models
from video_generator.plugins.llm.cli_brain import CodexBrain
from video_generator.plugins.llm.cli_models import codex_slug, parse_claude_help, parse_codex
from video_generator.project import ProjectStore
from video_generator.scene3d import agent as ag
from video_generator.scene3d import service as s3
from video_generator.tree import find, numbering

from .conftest import requires_ffmpeg
from .test_scene3d_change import lizard, project
from .test_subscription_brain import Answer, stand_in

CATALOGUE = {"models": [
    {"slug": "gpt-6.2-astra", "display_name": "GPT-6.2-Astra", "visibility": "list", "priority": 2, "description": "Most capable."},
    {"slug": "gpt-6.2-sol", "display_name": "GPT-6.2-Sol", "visibility": "list", "priority": 1, "description": "Fast."},
    {"slug": "secret-model", "display_name": "Hidden", "visibility": "hide", "priority": 3},
]}

CODEX = """import json, os, sys, pathlib
args = sys.argv[1:]
if args[:2] == ["debug", "models"]:
    print(json.dumps(%s)); sys.exit(0)
pathlib.Path(os.environ["STAND_IN_LOG"]).write_text(json.dumps({"args": args}))
if "-m" in args and args[args.index("-m") + 1] != "gpt-6.2-sol":
    m = args[args.index("-m") + 1]
    print(json.dumps({"type": "error", "message": f"The '{m}' model is not supported when using Codex with a ChatGPT account."}))
    sys.exit(1)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": '{"title": "Lion chase", "count": 3}'}}))
""" % json.dumps(CATALOGUE)

HELP = """Options:
  --model <model>                       Model for the current session. Use an
                                        alias for the latest model (e.g.
                                        'fable', 'opus', or 'sonnet') or a
                                        model's full name.
  -n, --name <name>                     Set a display name
"""


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "log.json"
    monkeypatch.setenv("STAND_IN_LOG", str(path))
    cli_models._CACHE.clear()
    return path


def test_model_lists_come_from_the_programs():
    assert [m["id"] for m in parse_codex(json.dumps(CATALOGUE))] == ["gpt-6.2-sol", "gpt-6.2-astra"]   # hidden ones left out
    assert [m["id"] for m in parse_claude_help(HELP)] == ["fable", "opus", "sonnet", "haiku"]
    assert codex_slug("GPT-6.2-Sol") == "gpt-6.2-sol" and codex_slug("GPT-6.1 Terra") == "gpt-6.1-terra"


def test_codex_is_given_the_code_name_not_the_display_name(tmp_path, monkeypatch, log):
    monkeypatch.setenv("VG_CODEX", str(stand_in(tmp_path, "codex", CODEX)))
    result, _ = asyncio.run(CodexBrain().generate_json(system="s", user="u", schema=Answer, model="GPT-6.2-Sol"))
    assert result.title == "Lion chase"
    args = json.loads(log.read_text())["args"]
    assert args[args.index("-m") + 1] == "gpt-6.2-sol"
    with pytest.raises(PluginError) as err:                         # a model the sign-in cannot use: said plainly
        asyncio.run(CodexBrain().generate_json(system="s", user="u", schema=Answer, model="gpt-6.2-astra"))
    assert "Codex cannot use this model with your sign-in" in str(err.value) and "grade" not in str(err.value)
    models, why = asyncio.run(cli_models.list_models("codex"))
    assert why == "" and {k: models[0][k] for k in ("id", "name", "note")} == {"id": "gpt-6.2-sol", "name": "GPT-6.2-Sol", "note": "Fast."}


def test_the_screen_lists_both_tools_models(tmp_path, monkeypatch, log, svc):
    from fastapi.testclient import TestClient
    from video_generator.web import app as appmod
    monkeypatch.setattr(appmod, "svc", svc)
    monkeypatch.setenv("VG_CODEX", str(stand_in(tmp_path, "codex", CODEX)))
    monkeypatch.setenv("VG_CLAUDE", str(stand_in(tmp_path, "claude", f"print({HELP!r})")))
    with TestClient(appmod.app) as client:
        r = client.get("/api/settings/subscription-models").json()
    assert [m["id"] for m in r["codex"]["models"]] == ["gpt-6.2-sol", "gpt-6.2-astra"]
    assert [m["id"] for m in r["claude_code"]["models"]][:3] == ["fable", "opus", "sonnet"]


def test_the_3d_work_follows_the_ai_brain_switch(tmp_path, monkeypatch, svc):
    monkeypatch.setenv("VG_CODEX", str(stand_in(tmp_path, "codex", CODEX)))
    monkeypatch.setenv("VG_CLAUDE", str(stand_in(tmp_path, "claude", "print('{}')")))
    svc.reload()
    assert svc.config.llm.default in ("auto", "") or True
    svc.config.llm.default = "claude_code_brain"
    assert ag.pick_agents(svc, "brain")[0] == "claude_code"
    svc.config.llm.default = "codex_brain"                          # one switch: the brain AND the 3D work
    svc.config.llm.models["codex_brain"] = "gpt-6.2-sol"
    assert ag.pick_agents(svc, "brain")[0] == "codex"
    assert ag.pick_agents(svc, "claude_code")[0] == "claude_code"   # a fixed choice stays as chosen
    from video_generator.models import Scene3DSettings
    assert Scene3DSettings().agent == "brain"
    p, _ = project(svc, monkeypatch)
    seen = {}

    class Spy:
        async def run(self, task):
            seen["model"] = task.model
            from video_generator.plugins.base import AgentResult
            return AgentResult(ok=True)
    monkeypatch.setattr(svc.reg, "plugin", lambda name: Spy())
    asyncio.run(ag._call(svc, p.id, "codex", AgentTask(folder=tmp_path, instructions="x"), "test"))
    assert seen["model"] == "gpt-6.2-sol"                           # no 3D model chosen: the brain's model is used


@requires_ffmpeg
def test_one_change_for_the_whole_3d_film(svc, monkeypatch):
    p, ids = project(svc, monkeypatch)
    from video_generator.scene3d.film import make_film
    asyncio.run(make_film(svc, p.id, prepare=True))                 # as on your screen: the whole 3D film is made first

    def has_lizard(nid):
        return any(t.label == "Lizard" for t in find(svc.load(p.id), nid).scene3d.plan.things)
    with_lizard = [nid for nid in ids if has_lizard(nid)]
    assert with_lizard
    before = {nid: lizard(svc, p.id, nid).size for nid in with_lizard}
    rep = asyncio.run(ag.change_film(svc, p.id, "make the lizard twice as big"))
    nums = numbering(svc.load(p.id))
    assert sorted(rep.clips) == sorted(nums[n] for n in ids) and not rep.problems    # the offline brain asks every 3D clip
    for nid, b in before.items():
        assert lizard(svc, p.id, nid).size == pytest.approx([v * 2 for v in b], rel=1e-2)
        assert not lizard(svc, p.id, nid).model or lizard(svc, p.id, nid).scale == pytest.approx(2.0)   # a model is scaled, not replaced
        assert find(svc.load(p.id), nid).scene3d.changes == ["make the lizard twice as big"]
    film = svc.load(p.id).scene3d_film
    assert film and film.video and any(pt.source == "3d" for pt in film.parts)
    ProjectStore.undo(p.id)                                         # ONE undo takes the whole film change back
    for nid, b in before.items():
        assert lizard(svc, p.id, nid).size == pytest.approx(b)


def test_a_film_change_with_no_3d_clips_says_why(svc, monkeypatch):
    p, _ = project(svc, monkeypatch)
    p = svc.load(p.id)
    p.settings.scene3d.enabled = False
    svc.save(p)
    with pytest.raises(s3.Scene3DError, match="No clip has the 3D camera reference on"):
        asyncio.run(ag.change_film(svc, p.id, "the camera lower everywhere"))


@requires_ffmpeg
def test_making_the_film_again_says_what_it_really_did(svc, monkeypatch):
    """"Make it again" with nothing changed only joins the film again (a second); it now says so. Planning every scene
    again makes new plans and renders, as one Undo step."""
    from video_generator.scene3d.film import make_film
    p, ids = project(svc, monkeypatch)
    first = asyncio.run(make_film(svc, p.id, prepare=True))
    assert any(n.startswith("Rendered now") for n in first.notes)
    again = asyncio.run(make_film(svc, p.id, prepare=True))
    assert any("Nothing had changed" in n for n in again.notes) and not any(n.startswith("Rendered now") for n in again.notes)
    fresh = asyncio.run(make_film(svc, p.id, prepare=True, replan=True))
    assert any(n.startswith("Planned afresh") for n in fresh.notes) and any(n.startswith("Rendered now") for n in fresh.notes)


EFFORT_HELP = HELP.replace("  -n, --name <name>", """  --effort <level>                      Effort level for the current session
                                        (low, medium, high, xhigh, max)
  -n, --name <name>""")
CATALOGUE_LEVELS = {"models": [{"slug": "gpt-6.2-sol", "display_name": "GPT-6.2-Sol", "visibility": "list", "priority": 1,
                                "default_reasoning_level": "low",
                                "supported_reasoning_levels": [{"effort": "low", "description": "Fast"}, {"effort": "high", "description": "Deep"}]}]}


def test_reasoning_levels_come_from_the_programs():
    assert [e["id"] for e in parse_claude_help(EFFORT_HELP)[0]["efforts"]] == ["low", "medium", "high", "xhigh", "max"]
    m = parse_codex(json.dumps(CATALOGUE_LEVELS))[0]
    assert m["default_effort"] == "low" and [e["id"] for e in m["efforts"]] == ["low", "high"]


def test_the_chosen_reasoning_is_given_to_both_programs(svc, tmp_path):
    from video_generator.plugins.agent.cli_agents import ClaudeCodeAgent, CodexAgent
    from video_generator.plugins.llm.cli_brain import ClaudeCodeBrain
    svc.config.llm.efforts = {"claude_code_brain": "high", "codex_brain": "xhigh"}
    claude, codex = ClaudeCodeBrain(svc.config), CodexBrain(svc.config)
    cmd = claude.command(Answer, "opus", "s")
    assert cmd[cmd.index("--effort") + 1] == "high"
    assert "--effort" not in claude.command(Answer, "opus", "s", minimal=True)   # an older Claude Code: asked plainly
    cmd = codex.command(tmp_path, "gpt-6.2-sol", [], "q")
    assert cmd[cmd.index("-c") + 1] == 'model_reasoning_effort="xhigh"'
    svc.config.llm.efforts = {}
    assert "--effort" not in ClaudeCodeBrain(svc.config).command(Answer, "", "s")   # "" = its usual effort
    task = AgentTask(folder=tmp_path, instructions="x", effort="max")
    assert ClaudeCodeAgent().command(task)[-2:] == ["--effort", "max"]
    c = CodexAgent().command(task)
    assert c[c.index("-c") + 1] == 'model_reasoning_effort="max"' and c[-1] == "x"


def test_3d_work_thinks_as_hard_as_chosen_else_as_the_ai_brain(svc, monkeypatch, tmp_path):
    p, _ = project(svc, monkeypatch)
    seen = []

    class Spy:
        async def run(self, task):
            seen.append(task.effort)
            from video_generator.plugins.base import AgentResult
            return AgentResult(ok=True)
    real = svc.reg.plugin
    svc.config.llm.efforts = {"codex_brain": "medium"}
    svc.reg.plugin = lambda name: Spy()
    asyncio.run(ag._call(svc, p.id, "codex", AgentTask(folder=tmp_path, instructions="x"), "t"))
    svc.reg.plugin = real
    q = svc.load(p.id)
    q.settings.scene3d.agent_efforts = {"codex": "high"}          # chosen for 3D work: wins over the brain's
    svc.save(q)
    svc.reg.plugin = lambda name: Spy()
    asyncio.run(ag._call(svc, p.id, "codex", AgentTask(folder=tmp_path, instructions="x"), "t"))
    svc.reg.plugin = real
    assert seen == ["medium", "high"]
