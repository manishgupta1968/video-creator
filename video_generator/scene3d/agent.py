"""The check-and-fix loop: a coding agent repairs a clip's 3D plan until the checks pass (the 3D camera reference add-on).

Who fixes (Settings → 3D camera reference → agent):
  claude_code   Claude Code fixes the plan.
  codex         Codex fixes the plan.
  pair          Claude Code fixes the plan; then Codex LOOKS at the preview pictures and says whether the camera does
                what the script says. Its problems go back to Claude Code in the next round.
When the chosen agent is not installed, the other one is used and the clip says so. With none installed, nothing is
fixed and the problems are shown to you.

One round:
1. A locked work folder is made: plan.json (the ONLY file the builder may change), clip.json (what the clip must show),
   problems.txt, and preview pictures drawn by the free sketch renderer.
2. The builder fixes plan.json. It can run the free check (`python -m video_generator.scene3d.check plan.json`) as
   often as it likes to measure its own fix.
3. The tool reads plan.json back, checks that it is still a valid plan, keeps what must not change (length, frame
   shape, the characters' ids, labels and colours), and measures it again.
4. In pair mode, when the measured checks pass, the checker looks at the new preview pictures.
The loop stops when nothing is wrong, after `max_fix_rounds` rounds, or when the money cap for the clip is reached.
Every cent an agent reports is written to the spending log.
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from ..models import now_iso
from ..plugins.base import AgentResult, AgentTask, PluginError
from ..project import ProjectStore
from ..tree import find
from . import service as s3
from .render import sketch_frame
from .spec import ScenePlan, check, legend, normalise

CHECK_MODULE = "video_generator.scene3d.check"


@dataclass
class FixReport:
    fixed: bool                       # no major problem (and, in pair mode, the checker is happy)
    rounds: int = 0
    cost_usd: float = 0.0
    log: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    builder: str = ""
    checker: str = ""


def check_command() -> str:
    """The one command an agent may run: the free plan check, with the same Python the tool runs on."""
    return f"{sys.executable} -m {CHECK_MODULE}"


def pick_agents(svc, choice: str) -> tuple[Optional[str], Optional[str], list[str]]:
    """(builder, checker, notes) for a setting. A missing agent is replaced by one that is installed, and the notes say so."""
    def ready(name: str) -> bool:
        return svc.reg.configured(name)
    notes: list[str] = []
    if choice == "fake_agent":
        return "fake_agent", None, notes
    wanted_builder = "codex" if choice == "codex" else "claude_code"
    other = "claude_code" if wanted_builder == "codex" else "codex"
    builder = wanted_builder if ready(wanted_builder) else other if ready(other) else None
    if builder and builder != wanted_builder:
        notes.append(f"{wanted_builder} is not installed, so {builder} fixes the plan instead.")
    checker = None
    if choice == "pair":
        checker = "codex" if builder == "claude_code" else "claude_code"
        if not ready(checker) or checker == builder:
            notes.append(f"Pair mode needs both Claude Code and Codex; {checker} is not installed, so nothing checks the pictures.")
            checker = None
    if not builder:
        notes.append("Neither Claude Code nor Codex is installed, so the plan cannot be fixed automatically. "
                     "Install one (the `claude` or `codex` command), or fix the plan yourself.")
    return builder, checker, notes


def _clip_brief(project, node) -> dict:
    sc = node.script
    return {"title": node.title, "goal": node.goal, "seconds": node.scene3d.plan.seconds if node.scene3d and node.scene3d.plan else None,
            "frame_shape": project.settings.aspect, "camera": sc.camera if sc else "", "what_we_see": sc.visual if sc else "",
            "action_steps": sc.action_beats if sc else [], "starts": sc.start_state if sc else "", "ends": sc.end_state if sc else "",
            "characters": [{"colour": c, "is": label} for c, label in legend(node.scene3d.plan)] if node.scene3d and node.scene3d.plan else []}


BUILDER_TASK = """You fix the rough 3D plan of ONE shot of a video. Work only in this folder.

Files:
- plan.json: the plan. This is the ONLY file you may change.
- clip.json: what the shot must show (goal, camera words, action, length, frame shape, which colour is which character).
- problems.txt: what is wrong now.
- preview/start.png, middle.png, end.png: what the camera sees now (plain coloured shapes).

The plan, in short: metres and seconds, Z is up, the floor is Z = 0, the set is centred on X = 0, Y = 0.
things[] are plain shapes; keys[] = where each one's base is over time {{t, at:[x,y,z]}}; movement between keys is
straight and even. camera.keys[] = {{t, at:[x,y,z], look_at:[x,y,z], lens_mm}}; camera.lens_mm is the usual lens
(24-35 wide, 50-85 close).

Rules:
- Fix the problems below and make the camera do what clip.json says. Change as little as you can.
- Keep seconds, fps and aspect. Keep every thing's id, label, actor_id, kind and colour.
- Every character must be in the frame at the start, middle and end unless clip.json says it enters or leaves.
- The camera must never be inside a shape.
- Check your work with:  {check} plan.json
  It lists the problems and redraws the preview pictures. Stop when it reports no major problem and the pictures
  match clip.json.
- Do not create, change or delete any other file. Do not use the internet.
- When you finish, reply with one or two plain sentences saying what you changed.

Problems now:
{problems}
"""

CHECKER_TASK = """You check the rough 3D plan of ONE shot of a video. Do not change any file except verdict.json.

Look at preview/start.png, preview/middle.png and preview/end.png (what the camera sees, as plain coloured shapes),
plan.json (the plan) and clip.json (what the shot must show, and which colour is which character).

Decide: does the camera do what clip.json says (its move, framing and timing), and is every character where the story
needs it? Small looks do not matter: the shapes are only stand-ins.

Write verdict.json as {{"ok": true, "problems": []}} or {{"ok": false, "problems": ["one plain sentence per problem"]}}.
Write at most 4 problems, each saying what to change (for example "At the end the camera should be close to Dan;
it is still far away."). Then reply with one sentence.
"""


def _folder(pid: str, nid: str, round_no: int) -> Path:
    d = ProjectStore.path_for(pid) / "clips" / nid / "scene3d" / "agent" / f"round_{round_no}"
    shutil.rmtree(d, ignore_errors=True)
    (d / "preview").mkdir(parents=True)
    return d


def _previews(plan: ScenePlan, folder: Path) -> None:
    p = normalise(plan)
    for name, t in (("start", 0.0), ("middle", p.seconds / 2), ("end", p.seconds)):
        sketch_frame(p, t, (640, 360)).save(folder / "preview" / f"{name}.png")


def _kept(before: ScenePlan, after: ScenePlan, strict: bool = True) -> ScenePlan:
    """The agent's plan with what must not change put back: length, fps, frame shape, and (strict, for fixes) who each
    shape is and every character. A change YOU asked for (strict=False) may rename, recolour, add or remove shapes."""
    a = after.model_copy(deep=True)
    a.seconds, a.fps, a.aspect = before.seconds, before.fps, before.aspect
    a.set_id = before.set_id or a.set_id
    if not strict:
        return normalise(a)
    old = {t.id: t for t in before.things}
    for t in a.things:
        if t.id in old:
            t.label, t.actor_id, t.kind, t.colour = old[t.id].label, old[t.id].actor_id, old[t.id].kind, old[t.id].colour
    missing = [t for t in before.things if t.id not in {x.id for x in a.things} and t.kind == "figure"]
    a.things += [m.model_copy(deep=True) for m in missing]        # a character the agent dropped comes back as it was
    return normalise(a)


async def _call(svc, pid: str, name: str, task: AgentTask, what: str) -> AgentResult:
    plugin = svc.reg.plugin(name)
    result = await plugin.run(task)
    if result.cost_usd:
        ProjectStore.ledger_add(pid, {"kind": "agent", "what": what, "plugin": name, "model": name,
                                      "estimated_usd": round(task.max_usd, 4), "actual_usd": round(result.cost_usd, 4)})
    return result


async def fix_clip(svc, pid: str, nid: str, rounds: Optional[int] = None, agent: Optional[str] = None) -> FixReport:
    """Run the check-and-fix loop on one clip's plan, and keep the result on the clip (it must be rendered again)."""
    p = svc.load(pid)
    n = find(p, nid)
    if not n.scene3d or not n.scene3d.plan:
        raise s3.Scene3DError(f"Clip '{n.title}' has no 3D plan yet. Make the plan first.")
    st = p.settings.scene3d
    builder, checker, notes = pick_agents(svc, agent or st.agent)
    report = FixReport(fixed=False, log=list(notes), builder=builder or "", checker=checker or "")
    limit = rounds if rounds is not None else st.max_fix_rounds
    budget = max(st.agent_max_usd - (n.scene3d.agent_cost_usd or 0), 0.0)
    plan = normalise(n.scene3d.plan)
    brief = _clip_brief(p, n)
    seen_problems: list[str] = []
    for r in range(1, limit + 1):
        issues = check(plan)
        problems = [f"{i.severity}: {i.text}" for i in issues if i.severity in ("major", "minor")]
        major = [i for i in issues if i.severity == "major"]
        folder = _folder(pid, nid, n.scene3d.agent_rounds + r)
        (folder / "plan.json").write_text(plan.model_dump_json(indent=1))
        (folder / "clip.json").write_text(json.dumps(brief, indent=1))
        _previews(plan, folder)
        looked: list[str] = []
        if not major and checker and budget > 0:
            # the measured checks pass: in pair mode the second agent looks at the pictures
            res = await _call(svc, pid, checker, AgentTask(folder=folder, instructions=CHECKER_TASK, role="checker",
                                                           max_usd=min(budget, 0.5)), f"3D check {nid} round {r}")
            report.cost_usd += res.cost_usd
            budget -= res.cost_usd
            try:
                verdict = json.loads((folder / "verdict.json").read_text())
                looked = [str(x) for x in verdict.get("problems") or []][:4] if not verdict.get("ok") else []
            except (OSError, ValueError):
                looked = []
                report.log.append(f"Round {r}: {checker} wrote no verdict, so its look is skipped.")
            report.log.append(f"Round {r}: {checker} looked at the pictures: " + ("; ".join(looked) if looked else "the camera matches the script."))
        if not major and not looked:
            report.fixed = True
            report.remaining = problems
            break
        if not builder:
            report.remaining = problems + looked
            break
        if budget <= 0:
            report.log.append(f"The money cap for this clip (${st.agent_max_usd:.2f}) is reached, so the fixing stops here.")
            report.remaining = problems + looked
            break
        todo = problems + [f"from the picture check: {x}" for x in looked]
        if todo == seen_problems and r > 1:
            report.log.append(f"Round {r}: the same problems are left as in the round before, so the fixing stops here.")
            report.remaining = todo
            break
        seen_problems = todo
        (folder / "problems.txt").write_text("\n".join(todo) + "\n")
        task = AgentTask(folder=folder, instructions=BUILDER_TASK.format(check=check_command(), problems="\n".join(todo)),
                         role="builder", allowed_command=check_command(), max_usd=budget)
        try:
            res = await _call(svc, pid, builder, task, f"3D fix {nid} round {r}")
        except PluginError as exc:
            report.log.append(f"Round {r}: {builder} failed: {exc}")
            report.remaining = todo
            break
        report.cost_usd += res.cost_usd
        budget -= res.cost_usd
        report.rounds = r
        try:
            new = ScenePlan.model_validate(json.loads((folder / "plan.json").read_text()))
        except (OSError, ValueError, ValidationError) as exc:
            report.log.append(f"Round {r}: {builder} left plan.json broken ({str(exc)[:160]}), so its change is not used.")
            report.remaining = todo
            break
        plan = _kept(plan, new)
        left = [i for i in check(plan) if i.severity == "major"]
        report.log.append(f"Round {r}: {builder} — {res.summary or 'no reply'}"
                          + (f" (${res.cost_usd:.2f})" if res.cost_usd else "")
                          + (f" Still wrong: {'; '.join(i.text for i in left)}" if left else " The measured checks pass now."))
    else:
        issues = check(plan)
        report.remaining = [f"{i.severity}: {i.text}" for i in issues]
        report.fixed = not any(i.severity == "major" for i in issues) and not checker
        if checker and not report.fixed:
            report.log.append(f"After {limit} round(s) the picture check was not run again; build and look at the preview yourself.")
    # keep the result on the clip
    p = svc.load(pid)
    n = find(p, nid)
    changed = n.scene3d.plan is None or normalise(n.scene3d.plan).model_dump() != plan.model_dump()
    if changed:
        s3.set_plan(svc, pid, nid, plan)
        p = svc.load(pid)
        n = find(p, nid)
    n.scene3d.agent_rounds += report.rounds
    n.scene3d.agent_cost_usd = round(n.scene3d.agent_cost_usd + report.cost_usd, 4)
    n.scene3d.agent_log = (n.scene3d.agent_log + [f"{now_iso()[:16]} " + line for line in report.log])[-40:]
    svc.save(p)
    return report


@dataclass
class PrepareReport:
    nid: str
    planned: bool = False
    fix: Optional[FixReport] = None
    status: str = ""
    error: str = ""


def _needs_fix(project, node) -> bool:
    """Fix when a measured check finds a major problem, or always in pair mode (the checker looks at the pictures)."""
    s = node.scene3d
    if not s or not s.plan:
        return False
    if project.settings.scene3d.agent == "pair":
        return True
    return any(i.severity == "major" for i in check(s.plan))


async def prepare_clip(svc, pid: str, nid: str, fix: bool = True, renderer: Optional[str] = None,
                       replan: bool = False) -> PrepareReport:
    """The whole automatic chain for one clip: plan (when there is none, or the clip's length changed), fix (when the
    checks find a problem), render, and approve by itself when auto-approve is on and nothing major is left."""
    rep = PrepareReport(nid=nid)
    p = svc.load(pid)
    n = find(p, nid)
    why = s3.stale_reason(n) if n.scene3d else ""
    if replan or not n.scene3d or not n.scene3d.plan or "plan it again" in why:
        await s3.plan_clip(svc, pid, nid)
        rep.planned = True
    p = svc.load(pid)
    n = find(p, nid)
    fresh = rep.planned or bool(s3.stale_reason(n)) or n.scene3d.status in ("planned", "failed")
    if fix and fresh and _needs_fix(p, n):           # a plan already rendered and unchanged is not fixed (or paid for) again
        rep.fix = await fix_clip(svc, pid, nid)
    p = svc.load(pid)
    n = find(p, nid)
    if s3.stale_reason(n) or n.scene3d.status in ("planned", "failed"):
        s = await s3.build_clip(svc, pid, nid, renderer)
        rep.status = s.status
    else:
        rep.status = n.scene3d.status
    return rep


async def prepare_all(svc, pid: str, fix: bool = True, renderer: Optional[str] = None) -> list[PrepareReport]:
    """prepare_clip for every clip that has the 3D camera reference switched on, in story order (so a clip that
    continues another is planned after it). A clip that fails is reported and the others still go on."""
    from ..models import NodeKind
    from ..tree import leaves
    out = []
    p = svc.load(pid)
    for leaf in leaves(p):
        if leaf.kind != NodeKind.clip or not s3.enabled_for(p, leaf) or not leaf.script:
            continue
        try:
            out.append(await prepare_clip(svc, pid, leaf.id, fix=fix, renderer=renderer))
        except (s3.Scene3DError, PluginError) as exc:
            out.append(PrepareReport(nid=leaf.id, error=str(exc)))
    return out


# =========================================================== changes you ask for in plain words
CHANGE_TASK = """You change the rough 3D plan of ONE shot of a video, exactly as the user asks. Work only in this folder.

Files:
- plan.json: the plan. This is the ONLY file you may change.
- clip.json: what the shot is about (goal, camera words, action, length, frame shape, which colour is which character).
- preview/start.png, middle.png, end.png: what the camera sees now (plain coloured shapes).

The plan, in short: metres and seconds, Z is up, the floor is Z = 0, the set is centred on X = 0, Y = 0.
things[] are plain shapes (kind figure = a character, prop = scenery); keys[] = where each one's base is over time
{{t, at:[x,y,z]}}; movement between keys is straight and even. camera.keys[] = {{t, at:[x,y,z], look_at:[x,y,z], lens_mm}}.

THE USER ASKS:
{request}

Rules:
- Do what the user asks, and change nothing else.
- Keep seconds, fps and aspect. Keep every shape's id. Keep labels, colours and actor_id unless the user asks otherwise.
- A new character is a figure with a colour no other figure has (red, blue, green, yellow, purple, orange, cyan, pink).
- The camera must never be inside a shape. Every character must stay in the frame unless the user asks otherwise.
- If the change affects the camera, update camera.move to describe the camera in one plain sentence.
- Check your work with:  {check} plan.json
  It lists problems and redraws the preview pictures. Stop when the pictures show the change and nothing major is wrong.
- Do not create, change or delete any other file. Do not use the internet.
- When you finish, reply with one or two plain sentences saying what you changed.
"""


@dataclass
class ChangeReport:
    request: str
    changed: bool = False             # the plan is different from before
    summary: str = ""                 # what was done, in plain words
    by: str = ""                      # claude_code | codex | the AI brain
    cost_usd: float = 0.0
    planned: bool = False             # there was no scene yet: it was planned from your words
    fix: Optional[FixReport] = None   # the automatic check-and-fix after the change, if a check found a problem
    status: str = ""                  # the 3D preview's status at the end (rendered / approved / planned / failed)


async def change_clip(svc, pid: str, nid: str, request: str, render: bool = True, agent: Optional[str] = None) -> ChangeReport:
    """The video's way of working, automated: you say what you want, and the scene follows.

    - No 3D scene yet: it is planned from the script AND your words ("a big empty kitchen, the chef at the far end").
    - A scene exists: Claude Code (or Codex) changes it as you ask and nothing else, in the locked work folder, measuring
      its own work with the free check. With no agent installed, the AI brain makes the change.
    Then, by itself: the checks run (and the fixer repairs a major problem), and Blender renders the new preview.
    One Undo takes the change back."""
    request = (request or "").strip()
    if not request:
        raise s3.Scene3DError("Say what you want to see or change, for example: \"make the lizard twice as big\".")
    rep = ChangeReport(request=request)
    p = svc.load(pid)
    mark = ProjectStore.history_mark(p)          # the whole change (plan, check, fix, render) becomes ONE undo step
    try:
        return await _change(svc, pid, nid, request, render, agent, rep)
    finally:
        ProjectStore.collapse_history(pid, mark)


async def _change(svc, pid: str, nid: str, request: str, render: bool, agent: Optional[str], rep: ChangeReport) -> ChangeReport:
    p = svc.load(pid)
    n = find(p, nid)
    if not n.scene3d or not n.scene3d.plan:
        await s3.plan_clip(svc, pid, nid, wishes=request)
        rep.planned, rep.changed, rep.by = True, True, "the AI brain"
        rep.summary = "Planned the 3D scene from the script and your words."
    else:
        before = normalise(n.scene3d.plan)
        builder, _, notes = pick_agents(svc, agent or p.settings.scene3d.agent)
        st = p.settings.scene3d
        budget = max(st.agent_max_usd - (n.scene3d.agent_cost_usd or 0), 0.0)
        new: Optional[ScenePlan] = None
        if builder and budget > 0:
            folder = _folder(pid, nid, n.scene3d.agent_rounds + 1)
            (folder / "plan.json").write_text(before.model_dump_json(indent=1))
            (folder / "clip.json").write_text(json.dumps(_clip_brief(p, n), indent=1))
            _previews(before, folder)
            task = AgentTask(folder=folder, instructions=CHANGE_TASK.format(request=request, check=check_command()),
                             role="change", request=request, allowed_command=check_command(), max_usd=budget)
            try:
                res = await _call(svc, pid, builder, task, f"3D change {nid}")
                rep.cost_usd += res.cost_usd
                rep.summary, rep.by = res.summary, builder
                new = ScenePlan.model_validate(json.loads((folder / "plan.json").read_text()))
            except PluginError as exc:
                rep.summary = f"{builder} could not make the change ({exc}); the AI brain made it instead."
            except (OSError, ValueError, ValidationError) as exc:
                rep.summary = f"{builder} left plan.json broken ({str(exc)[:120]}); the AI brain made the change instead."
        elif builder and budget <= 0:
            rep.summary = f"The money cap for this clip's agent (${st.agent_max_usd:.2f}) is used up, so the AI brain made the change."
        if new is None:                     # no agent (or it failed): the AI brain makes the change
            new = await svc.brain.scene_change(p, n, before, request)
            p = svc.load(pid)
            svc._ledger_llm(p, f"3D change {nid}")
            svc.save(p, snapshot=False)
            rep.by = "the AI brain"
            rep.summary = rep.summary or "The AI brain changed the plan."     # (or the reason the agent did not)
        plan = _kept(before, new, strict=False)
        rep.changed = plan.model_dump() != before.model_dump()
        if rep.changed:
            s3.set_plan(svc, pid, nid, plan)
        elif not rep.summary.lower().startswith("i did not"):
            rep.summary = (rep.summary + " " if rep.summary else "") + "The plan did not change."
        p = svc.load(pid)
        n = find(p, nid)
        n.scene3d.changes = (n.scene3d.changes + [request])[-30:]
        n.scene3d.agent_cost_usd = round(n.scene3d.agent_cost_usd + rep.cost_usd, 4)
        line = f"Change \"{request[:80]}\" by {rep.by}: {rep.summary}" + (f" (${rep.cost_usd:.2f})" if rep.cost_usd else "")
        n.scene3d.agent_log = (n.scene3d.agent_log + [f"{now_iso()[:16]} " + line] + [f"{now_iso()[:16]} {x}" for x in notes])[-40:]
        svc.save(p)
    # then by itself: check (and fix a major problem), render, approve when that is switched on
    p = svc.load(pid)
    n = find(p, nid)
    if any(i.severity == "major" for i in check(n.scene3d.plan)):
        rep.fix = await fix_clip(svc, pid, nid)
    if render:
        p = svc.load(pid)
        n = find(p, nid)
        if s3.stale_reason(n) or n.scene3d.status in ("planned", "failed"):
            rep.status = (await s3.build_clip(svc, pid, nid)).status
        else:
            rep.status = n.scene3d.status
    return rep
