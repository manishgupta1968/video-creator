"""The 3D camera reference add-on, phase 4: Claude Code / Codex / the pair fix a clip's 3D plan until the checks pass.
Real agents are replaced by small stand-in programs, so the commands, the locked folder, the money cap and the
spending log are tested without paying for anything."""
import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from video_generator.plugins.agent.cli_agents import ClaudeCodeAgent, CodexAgent
from video_generator.plugins.base import AgentResult, AgentTask
from video_generator.project import ProjectStore
from video_generator.scene3d import agent as ag
from video_generator.scene3d import check as check_cli
from video_generator.scene3d import service as s3
from video_generator.scene3d.spec import CameraKey, ScenePlan, Thing, check, normalise
from video_generator.tree import find

from .conftest import requires_ffmpeg
from .test_scene3d import chase, two_shot_project


def broken_clip(svc):
    """A project whose first clip has a plan with the camera looking away from everyone (a major problem)."""
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    svc.save(p)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    plan = find(svc.load(p.id), ids[0]).scene3d.plan.model_copy(deep=True)
    plan.camera.keys = [CameraKey(t=0, at=[0, 30, 1.6], look_at=[0, 60, 1.6])]
    s3.set_plan(svc, p.id, ids[0], plan)
    assert any(i.severity == "major" for i in check(plan))
    return p, ids


def use(monkeypatch, builder, checker=None, notes=()):
    monkeypatch.setattr(ag, "pick_agents", lambda svc, choice: (builder, checker, list(notes)))


# ----------------------------------------------------------------- the loop
def test_the_agent_fixes_the_plan_and_what_must_not_change_is_kept(svc, monkeypatch):
    use(monkeypatch, "fake_agent")
    p, ids = broken_clip(svc)
    before = normalise(find(svc.load(p.id), ids[0]).scene3d.plan)
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0]))
    assert rep.fixed and rep.rounds == 1 and "Round 1: fake_agent" in rep.log[0] and "measured checks pass" in rep.log[0]
    n = find(svc.load(p.id), ids[0])
    after = n.scene3d.plan
    assert not [i for i in check(after) if i.severity == "major"]
    assert [(t.id, t.label, t.colour, t.actor_id) for t in after.things] == [(t.id, t.label, t.colour, t.actor_id) for t in before.things]
    assert after.seconds == before.seconds and n.scene3d.status == "planned"          # changed: it must be rendered again
    assert n.scene3d.agent_rounds == 1 and n.scene3d.agent_log
    task = svc.reg.plugin("fake_agent").runs[-1]
    assert task.role == "builder" and task.allowed_command == ag.check_command()
    assert "never in the camera's view" in (task.folder / "problems.txt").read_text()
    assert {f.name for f in (task.folder / "preview").iterdir()} == {"start.png", "middle.png", "end.png"}
    assert json.loads((task.folder / "clip.json").read_text())["characters"][0] == {"colour": "red", "is": "Dan"}


def test_a_plan_without_problems_is_not_sent_to_the_agent(svc, monkeypatch):
    use(monkeypatch, "fake_agent")
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    svc.save(p)
    asyncio.run(s3.plan_clip(svc, p.id, ids[0]))
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0]))
    assert rep.fixed and rep.rounds == 0 and svc.reg.plugin("fake_agent").runs == []


def test_in_pair_mode_the_checker_looks_and_its_problems_go_back_to_the_builder(svc, monkeypatch):
    use(monkeypatch, "fake_agent", "fake_agent")
    p, ids = broken_clip(svc)
    fake = svc.reg.plugin("fake_agent")
    fake.checker_problems = [["At the end the camera should be close to Dan."], []]
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0]))
    roles = [t.role for t in fake.runs]
    assert roles == ["builder", "checker", "builder", "checker"]
    assert "from the picture check: At the end the camera should be close to Dan." in fake.runs[2].instructions
    assert rep.fixed and any("the camera matches the script" in line for line in rep.log)


def test_when_no_agent_is_installed_the_problems_are_shown_and_nothing_changes(svc, monkeypatch):
    monkeypatch.setenv("VG_CLAUDE", "/no/such/claude")
    monkeypatch.setenv("VG_CODEX", "/no/such/codex")
    monkeypatch.setenv("PATH", "/nonexistent")
    p, ids = broken_clip(svc)
    builder, checker, notes = ag.pick_agents(svc, "pair")
    assert builder is None and checker is None and any("Neither Claude Code nor Codex is installed" in n for n in notes)
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0]))
    assert not rep.fixed and rep.rounds == 0 and any("never in the camera's view" in r for r in rep.remaining)


def test_a_missing_agent_is_replaced_by_the_one_that_is_installed(svc, monkeypatch, tmp_path):
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("VG_CLAUDE", "/no/such/claude")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setenv("VG_CODEX", str(fake))
    builder, checker, notes = ag.pick_agents(svc, "claude_code")
    assert builder == "codex" and checker is None and "claude_code is not installed, so codex fixes the plan instead." in notes


def test_a_broken_plan_from_the_agent_is_not_used(svc, monkeypatch):
    use(monkeypatch, "fake_agent")
    p, ids = broken_clip(svc)
    before = find(svc.load(p.id), ids[0]).scene3d.plan

    async def scribble(task):
        (task.folder / "plan.json").write_text("{not json")
        return AgentResult(ok=True, summary="done")
    monkeypatch.setattr(svc.reg.plugin("fake_agent"), "run", scribble)
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0]))
    assert not rep.fixed and "left plan.json broken" in rep.log[-1]
    assert find(svc.load(p.id), ids[0]).scene3d.plan == before


def test_the_money_cap_stops_the_fixing_and_every_cent_is_logged(svc, monkeypatch):
    use(monkeypatch, "fake_agent")
    p, ids = broken_clip(svc)
    q = svc.load(p.id)
    q.settings.scene3d.agent_max_usd = 0.6
    svc.save(q)
    caps = []

    async def costly(task):              # spends 0.5 each time and changes nothing
        caps.append(task.max_usd)
        return AgentResult(ok=True, summary="tried", cost_usd=0.5)
    monkeypatch.setattr(svc.reg.plugin("fake_agent"), "run", costly)
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0], rounds=5))
    assert caps[0] == pytest.approx(0.6) and len(caps) <= 2
    assert not rep.fixed and any("money cap" in line or "same problems" in line for line in rep.log)
    rows = [r for r in ProjectStore.ledger(p.id) if r["kind"] == "agent"]
    assert sum(r["actual_usd"] for r in rows) == pytest.approx(rep.cost_usd) and rows[0]["plugin"] == "fake_agent"
    assert find(svc.load(p.id), ids[0]).scene3d.agent_cost_usd == pytest.approx(rep.cost_usd)


def test_the_same_problems_twice_stop_the_loop(svc, monkeypatch):
    use(monkeypatch, "fake_agent")
    p, ids = broken_clip(svc)

    async def lazy(task):
        return AgentResult(ok=True, summary="looked, changed nothing")
    monkeypatch.setattr(svc.reg.plugin("fake_agent"), "run", lazy)
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0], rounds=5))
    assert rep.rounds == 1 and "same problems are left" in rep.log[-1]


def test_kept_puts_back_length_shape_and_who_is_who():
    before = normalise(chase(4))
    after = before.model_copy(deep=True)
    after.seconds, after.aspect = 9, "9:16"
    after.things = [t for t in after.things if t.id != "bruiser"]
    after.things[0].colour, after.things[0].label = "#000000", "someone"
    kept = ag._kept(before, after)
    assert kept.seconds == 4 and kept.aspect == "16:9"
    assert {t.id for t in kept.things} == {"dan", "bruiser", "lizard", "rock"}
    dan = next(t for t in kept.things if t.id == "dan")
    assert dan.colour == before.things[0].colour and dan.label == "Dan"


# ----------------------------------------------------------------- the free check command
def test_the_check_command_reports_and_draws_previews(tmp_path, capsys):
    good = tmp_path / "plan.json"
    good.write_text(normalise(chase(2)).model_dump_json())
    assert check_cli.main([str(good)]) == 0
    out = capsys.readouterr().out
    assert "Problems: none." in out and "Dan (red): in" in out
    assert (tmp_path / "preview" / "end.png").exists()
    bad = normalise(chase(2))
    bad.camera.keys = [CameraKey(t=0, at=[0, 30, 1.6], look_at=[0, 60, 1.6])]
    good.write_text(bad.model_dump_json())
    assert check_cli.main([str(good), "--no-pictures"]) == 1
    good.write_text("[]")
    assert check_cli.main([str(good)]) == 2


# ----------------------------------------------------------------- the real command-line agents (stand-in programs)
STAND_IN_CLAUDE = """#!{python}
import json, sys, pathlib
args = sys.argv[1:]
prompt = sys.stdin.read()
pathlib.Path("args.json").write_text(json.dumps(args))
plan = json.loads(pathlib.Path("plan.json").read_text())
xs = [t["keys"][0]["at"][0] for t in plan["things"] if t["kind"] == "figure"]
cx = sum(xs) / len(xs)
plan["camera"]["keys"] = [{{"t": 0, "at": [cx, -25, 3], "look_at": [cx, 0, 1]}}]
pathlib.Path("plan.json").write_text(json.dumps(plan))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "I moved the camera back.",
                  "total_cost_usd": 0.05, "num_turns": 3}}))
"""

STAND_IN_CODEX = """#!{python}
import json, sys, pathlib
pathlib.Path(sys.argv[sys.argv.index("--cd") + 1], "args.json").write_text(json.dumps(sys.argv[1:]))
folder = pathlib.Path(sys.argv[sys.argv.index("--cd") + 1])
plan = json.loads((folder / "plan.json").read_text())
plan["camera"]["keys"] = [{{"t": 0, "at": [0, -25, 3], "look_at": [0, 0, 1]}}]
(folder / "plan.json").write_text(json.dumps(plan))
print(json.dumps({{"type": "thread.started"}}))
print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": "Camera pulled back."}}}}))
"""


def stand_in(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body.format(python=sys.executable)))
    path.chmod(0o755)
    return path


def test_claude_code_is_run_in_the_locked_folder_with_a_cap_and_its_cost_is_logged(svc, monkeypatch, tmp_path):
    monkeypatch.setenv("VG_CLAUDE", str(stand_in(tmp_path, "claude", STAND_IN_CLAUDE)))
    p, ids = broken_clip(svc)
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0], agent="claude_code"))
    assert rep.builder == "claude_code" and rep.fixed and rep.cost_usd == pytest.approx(0.05)
    assert "I moved the camera back." in rep.log[-1]
    folder = ProjectStore.path_for(p.id) / "clips" / ids[0] / "scene3d" / "agent" / "round_1"
    args = json.loads((folder / "args.json").read_text())
    assert args[:3] == ["-p", "--output-format", "json"] and "--max-budget-usd" in args
    assert args[args.index("--max-budget-usd") + 1] == "2.00"
    assert f"Bash({ag.check_command()}:*)" in args and "WebFetch" in args[args.index("--disallowedTools"):]
    assert [r["actual_usd"] for r in ProjectStore.ledger(p.id) if r["kind"] == "agent"] == [0.05]


def test_codex_is_run_in_a_write_sandbox_on_the_folder(svc, monkeypatch, tmp_path):
    monkeypatch.setenv("VG_CODEX", str(stand_in(tmp_path, "codex", STAND_IN_CODEX)))
    p, ids = broken_clip(svc)
    rep = asyncio.run(ag.fix_clip(svc, p.id, ids[0], agent="codex"))
    assert rep.builder == "codex" and rep.fixed and rep.cost_usd == 0 and "Camera pulled back." in rep.log[-1]
    folder = ProjectStore.path_for(p.id) / "clips" / ids[0] / "scene3d" / "agent" / "round_1"
    args = json.loads((folder / "args.json").read_text())
    assert args[:5] == ["exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "--cd"] and "--json" in args


def test_an_agent_that_gives_no_result_is_reported(tmp_path):
    folder = tmp_path / "w"
    folder.mkdir()
    silent = stand_in(tmp_path, "claude", "#!{python}\nimport sys; sys.stdin.read(); print('oops'); sys.exit(1)\n")
    os.environ["VG_CLAUDE"] = str(silent)
    try:
        with pytest.raises(Exception, match="Claude Code gave no result"):
            asyncio.run(ClaudeCodeAgent().run(AgentTask(folder=folder, instructions="x")))
    finally:
        del os.environ["VG_CLAUDE"]


# ----------------------------------------------------------------- the whole automatic chain
@requires_ffmpeg
def test_prepare_plans_fixes_renders_and_approves_by_itself(svc, monkeypatch):
    use(monkeypatch, "fake_agent")
    p, ids = two_shot_project(svc)
    p.settings.scene3d.enabled = True
    p.settings.scene3d.auto_approve = True
    p.settings.scene3d.renderer = "sketch"
    svc.save(p)
    real_plan = s3.plan_clip

    async def bad_plan(svc_, pid, nid):                 # the planner makes a plan with a major problem
        s = await real_plan(svc_, pid, nid)
        plan = s.plan.model_copy(deep=True)
        plan.camera.keys = [CameraKey(t=0, at=[0, 30, 1.6], look_at=[0, 60, 1.6])]
        return s3.set_plan(svc_, pid, nid, plan)
    monkeypatch.setattr(s3, "plan_clip", bad_plan)
    reports = asyncio.run(ag.prepare_all(svc, p.id))
    assert [r.nid for r in reports] == ids
    assert all(r.planned and r.fix and r.fix.fixed and r.status == "approved" for r in reports)
    q = svc.load(p.id)
    assert all(s3.ready_reference(q, find(q, i)) for i in ids)
    # running it again changes nothing and calls no agent
    runs = len(svc.reg.plugin("fake_agent").runs)
    again = asyncio.run(ag.prepare_all(svc, p.id))
    assert all(not r.planned and r.fix is None and r.status == "approved" for r in again)
    assert len(svc.reg.plugin("fake_agent").runs) == runs


def test_prepare_all_skips_clips_that_have_it_switched_off(svc):
    p, ids = two_shot_project(svc)
    assert asyncio.run(ag.prepare_all(svc, p.id)) == []
