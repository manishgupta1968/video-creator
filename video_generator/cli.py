"""Command line: `vg` — the same features as the GUI, for scripting."""
from __future__ import annotations

import asyncio
import json
import webbrowser
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from .catalog import load_vendors
from .config import Config, save_key, vg_home
from .project import ProjectStore
from .registry import plugin_classes
from .tree import find, leaves, numbering, walk

app = typer.Typer(help="video-generator: turn a goal into a finished video.", no_args_is_help=True)
tree_app = typer.Typer(help="Edit the goal tree")
actor_app = typer.Typer(help="Actors (faces, clothing, behaviour, voices)")
ctx_app = typer.Typer(help="Context: shared, per part, or per clip")
deps_app = typer.Typer(help="Links between clips")
config_app = typer.Typer(help="Settings")
app.add_typer(tree_app, name="tree")
app.add_typer(actor_app, name="actor")
app.add_typer(ctx_app, name="context")
app.add_typer(deps_app, name="deps")
app.add_typer(config_app, name="config")
con = Console()


def _svc():
    from .services import Service
    return Service()


def _pid(project: Optional[str]) -> str:
    if project:
        return project
    ProjectStore.init()
    items = ProjectStore.list()
    if not items:
        raise typer.BadParameter("no projects yet — run: vg new \"<goal>\"")
    return items[0]["id"]


def _node(svc, pid: str, ref: str) -> str:
    p = svc.load(pid)
    nums = {v: k for k, v in numbering(p).items()}
    if ref in nums:
        return nums[ref]
    find(p, ref)
    return ref


def _fmt(s: float) -> str:
    s = int(round(s or 0))
    return f"{s // 60}:{s % 60:02d}"


def _show(svc, pid: str) -> None:
    p = svc.load(pid)
    summ = svc.summary(p)
    nums = summ["numbers"]
    t = Tree(f"[bold]{p.name}[/]  ~{_fmt(summ['seconds'])} / target {_fmt(p.settings.target_seconds)}  "
             f"≈ ${summ['cost']:.2f}  ~{_fmt(summ['time_s'])} to make  (brain: {summ['brain']})")

    def add(branch, node):
        for c in node.children:
            badge = {"done": "[green]✓[/]", "needs_pick": "[yellow]pick[/]", "failed": "[red]✗[/]",
                     "stale": "[magenta]out of date[/]", "generating": "[cyan]…[/]"}.get(c.status.value, "")
            label = (f"[bold]{nums[c.id]}[/] {c.title} [dim]({c.kind.value})[/] ~{c.duration.likely_s:.0f}s "
                     f"≈${c.cost.likely_usd:.2f} {badge}")
            b = branch.add(label)
            if c.is_leaf and c.warnings:
                for w in c.warnings[:2]:
                    b.add(f"[yellow]! {w}[/]")
            add(b, c)
    add(t, p.root)
    con.print(t)
    for w in summ["warnings"]:
        con.print(f"[yellow]! {w}[/]")
    if p.dependencies:
        con.print("[bold]Links:[/] " + ", ".join(f"{nums.get(d.from_id)}→{nums.get(d.to_id)} ({d.type.value})"
                                                  for d in p.dependencies))


# ===================================================================== projects
@app.command()
def new(goal: str, length: float = typer.Option(60, help="target length in seconds"),
        aspect: str = "16:9", format: str = typer.Option("mp4", help="mp4 or mov"),
        add: List[Path] = typer.Option([], "--add", help="slides, clips, photos, voice samples, notes"),
        budget: Optional[float] = None, mode: str = typer.Option("", help="best | balanced | budget | free"),
        auto_length: bool = typer.Option(False, "--auto-length", help="no length asked for: as short as the story allows"),
        language: str = typer.Option("", help="spoken language code (en, hi …), or auto = the plan decides from the goal; default en"),
        no_draft: bool = typer.Option(False, help="create without the AI first draft")):
    """Create a project from a goal and draft the whole plan."""
    svc = _svc()
    p = svc.new_project(goal, seconds=length, aspect=aspect, fmt=format, files=add, budget=budget,
                        quality_mode=mode or None, length_mode="auto" if auto_length else None,
                        language=language or None)
    if not no_draft:
        with con.status("Drafting the plan…"):
            asyncio.run(svc.draft(p.id))
    con.print(f"Project [bold]{p.id}[/] created.")
    _show(svc, p.id)


@app.command("list")
def list_projects():
    """List projects (newest first)."""
    ProjectStore.init()
    for p in ProjectStore.list():
        con.print(f"[bold]{p['id']}[/]  {p['name']}  [dim]{p['updated_at']}[/]")


@app.command()
def show(project: Optional[str] = typer.Argument(None)):
    """Show the goal tree with length, cost and status."""
    svc = _svc()
    _show(svc, _pid(project))


@app.command()
def draft(project: Optional[str] = typer.Argument(None)):
    """Re-draft the whole plan from the goal (replaces the tree)."""
    svc = _svc()
    pid = _pid(project)
    with con.status("Drafting…"):
        asyncio.run(svc.draft(pid))
    _show(svc, pid)


@app.command()
def undo(project: Optional[str] = typer.Argument(None)):
    ProjectStore.init()
    con.print("undone" if ProjectStore.undo(_pid(project)) else "nothing to undo")


@app.command()
def redo(project: Optional[str] = typer.Argument(None)):
    ProjectStore.init()
    con.print("redone" if ProjectStore.redo(_pid(project)) else "nothing to redo")


# ===================================================================== tree
@tree_app.command("show")
def tree_show(project: Optional[str] = typer.Option(None, "-p")):
    show(project)


@tree_app.command("decompose")
def tree_decompose(node: str, project: Optional[str] = typer.Option(None, "-p")):
    """Break a node into sub-goals with AI (e.g. vg tree decompose 2)."""
    svc = _svc()
    pid = _pid(project)
    with con.status("Breaking down…"):
        asyncio.run(svc.decompose(pid, _node(svc, pid, node)))
    _show(svc, pid)


@tree_app.command("add")
def tree_add(parent: str, goal: str, kind: str = "clip", title: str = "", project: Optional[str] = typer.Option(None, "-p")):
    """Add a child under a node ('root' for top level)."""
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    parent_id = p.root.id if parent == "root" else _node(svc, pid, parent)
    svc.add_node(pid, parent_id, kind, title or goal[:40], goal)
    _show(svc, pid)


@tree_app.command("remove")
def tree_remove(node: str, project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    pid = _pid(project)
    svc.remove_node(pid, _node(svc, pid, node))
    _show(svc, pid)


@tree_app.command("move")
def tree_move(node: str, parent: str, index: int = 0, project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    parent_id = p.root.id if parent == "root" else _node(svc, pid, parent)
    svc.move_node(pid, _node(svc, pid, node), parent_id, index)
    _show(svc, pid)


@app.command()
def script(node: str, project: Optional[str] = typer.Option(None, "-p"), show_only: bool = False):
    """Write (or show) the detailed script of a clip."""
    svc = _svc()
    pid = _pid(project)
    nid = _node(svc, pid, node)
    if not show_only:
        with con.status("Writing script…"):
            asyncio.run(svc.write_script(pid, nid))
    n = find(svc.load(pid), nid)
    con.print_json(n.script.model_dump_json() if n.script else "{}")


@app.command()
def revise(node: str, instruction: str, project: Optional[str] = typer.Option(None, "-p")):
    """Revise a node with plain instructions (e.g. vg revise 1.2 "make Rahul look frustrated")."""
    svc = _svc()
    pid = _pid(project)
    with con.status("Revising…"):
        asyncio.run(svc.revise(pid, _node(svc, pid, node), instruction))
    _show(svc, pid)


@app.command()
def ask(text: str, project: Optional[str] = typer.Option(None, "-p"), yes: bool = False):
    """Natural-language command for the whole project (shows what will change first)."""
    svc = _svc()
    pid = _pid(project)
    plan = asyncio.run(svc.plan_command(pid, text))
    con.print(f"[bold]{plan.summary}[/]")
    for op in plan.ops:
        con.print(f"  • {op.op} {op.target} {op.field} {op.value}")
    if yes or typer.confirm("Apply?"):
        actions = asyncio.run(svc.apply_command(pid, plan))
        if actions.get("generate"):
            con.print(f"Run: vg render --{actions['generate'] if actions['generate'] in ('all', 'next') else 'clip ' + actions['generate']}")
        _show(svc, pid)


# ===================================================================== actors & context
@actor_app.command("add")
def actor_add(name: str, description: str = "", photos: List[Path] = typer.Option([], "--photo"),
              voice: Optional[Path] = None, voice_description: str = "", clothing: str = "", behaviour: str = "",
              scope: str = "project", project: Optional[str] = typer.Option(None, "-p")):
    """Add an actor by photos and/or text, with clothing, behaviour and voice."""
    svc = _svc()
    pid = _pid(project)
    _, item = svc.add_context(pid, {"type": "actor", "title": name, "role": "must_appear", "scope": scope,
                                    "actor": {"description": description, "clothing": clothing, "behaviour": behaviour,
                                              "voice_description": voice_description}})
    p = svc.load(pid)
    for f in photos + ([voice] if voice else []):
        svc.add_context_file(p, f, ctx_id=item.id, save=False)
    svc.save(p)
    p = svc.load(pid)
    it = next(c for c in p.context if c.id == item.id)
    con.print(f"Actor [bold]{name}[/] added ({item.id}).")
    for k, v in it.analysis.items():
        con.print(f"  {k}: {v}")
    if it.needs_consent:
        con.print("[yellow]Real photos/voice: confirm consent with[/] vg actor consent " + item.id + " self|permission")


@actor_app.command("consent")
def actor_consent(ctx_id: str, statement: str = typer.Argument(..., help="self | permission"),
                  project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    svc.give_consent(_pid(project), ctx_id, statement)
    con.print("Consent recorded.")


@actor_app.command("list")
def actor_list(project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    p = svc.load(_pid(project))
    for c in p.context:
        if c.type.value == "actor" and c.actor:
            con.print(f"[bold]{c.title}[/] ({c.id}) {c.actor.kind} — {c.actor.description} | clothing: {c.actor.clothing} | "
                      f"behaviour: {c.actor.behaviour} | voice: {c.actor.voice_description or c.actor.voice_sample or '-'} "
                      f"| consent: {'yes' if c.consent.confirmed else 'no'}")


@ctx_app.command("add")
def ctx_add(files: List[Path] = typer.Argument(None), text: str = "", title: str = "",
            type: str = typer.Option("", help="actor|object|entity|location|style|audio|text|media"),
            role: str = typer.Option("", help="must_appear|look_reference|start_frame|end_frame|voice|sound|music_reference|knowledge|include"),
            scope: str = typer.Option("project", help="project | node:<number> | clip:<number>"),
            project: Optional[str] = typer.Option(None, "-p")):
    """Add context (files and/or text). Example: vg context add logo.png --scope project"""
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    if scope.startswith(("node:", "clip:")):
        kind, ref = scope.split(":", 1)
        scope = f"{kind}:{_node(svc, pid, ref)}"
    ids = []
    for f in files or []:
        item = svc.add_context_file(p, f, scope=scope, hint=title, save=False)
        if type:
            item.type = type
        if role:
            item.role = role
        if title:
            item.title = title
        ids.append(item.id)
    svc.save(p)
    if text or not files:
        data = {"type": type or "text", "role": role or "knowledge", "title": title or text[:40], "text": text, "scope": scope}
        _, item = svc.add_context(pid, data)
        ids.append(item.id)
    con.print(f"Added: {', '.join(ids)}")


@ctx_app.command("list")
def ctx_list(node: Optional[str] = typer.Argument(None), project: Optional[str] = typer.Option(None, "-p")):
    """List context; with a node number, show its effective context."""
    from .context import effective_context
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    if node:
        for e in effective_context(p, _node(svc, pid, node)):
            con.print(f"[{e.origin}] {e.item.type.value}/{e.item.role.value} {e.item.title} ({e.item.id})")
    else:
        for c in p.context:
            con.print(f"{c.scope:>14}  {c.type.value}/{c.role.value}  {c.title} ({c.id})  {len(c.files)} file(s)")


@ctx_app.command("off")
def ctx_off(node: str, ctx_id: str, project: Optional[str] = typer.Option(None, "-p")):
    """Switch an inherited context item off for one node."""
    svc = _svc()
    pid = _pid(project)
    svc.toggle_context(pid, _node(svc, pid, node), ctx_id, True)
    con.print("switched off")


# ===================================================================== dependencies
@deps_app.command("show")
def deps_show(project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    p = svc.load(_pid(project))
    nums = numbering(p)
    for d in p.dependencies:
        con.print(f"{d.id}: {nums.get(d.from_id)} → {nums.get(d.to_id)}  {d.type.value}  [{d.source}] {d.note}")


@deps_app.command("add")
def deps_add(from_node: str, to_node: str, type: str = "continues_from", project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    pid = _pid(project)
    svc.add_dependency(pid, _node(svc, pid, from_node), _node(svc, pid, to_node), type)
    deps_show(pid)


@deps_app.command("remove")
def deps_remove(dep_id: str, project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    svc.remove_dependency(_pid(project), dep_id)


@deps_app.command("suggest")
def deps_suggest(project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    pid = _pid(project)
    asyncio.run(svc.suggest_dependencies(pid))
    deps_show(pid)


# ===================================================================== estimate, cost, render
@app.command()
def estimate(node: Optional[str] = typer.Argument(None), project: Optional[str] = typer.Option(None, "-p")):
    """Cost and time BEFORE making anything (whole video or one node)."""
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    svc.refresh(p)
    if node:
        n = find(p, _node(svc, pid, node))
        con.print(f"[bold]{numbering(p)[n.id]} {n.title}[/]  ~{n.duration.likely_s:.0f}s ({n.duration.basis.value}: {n.duration.explain})")
        con.print(f"  cost ≈ ${n.cost.likely_usd:.2f} (range ${n.cost.min_usd:.2f}–${n.cost.max_usd:.2f}), time ≈ {_fmt(n.time.likely_s)}")
        for line in n.cost.lines:
            con.print(f"    {line.item}: {line.calc} = ${line.cost:.3f}")
    else:
        _show(svc, pid)


@app.command()
def cost(project: Optional[str] = typer.Option(None, "-p")):
    """Estimated vs actual cost per clip, and spending so far."""
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    svc.refresh(p)
    t = Table("clip", "title", "estimate", "actual", "status")
    nums = numbering(p)
    for n in leaves(p):
        t.add_row(nums[n.id], n.title[:40], f"${n.cost.likely_usd:.2f}",
                  f"${n.cost.actual_usd:.2f}" if n.cost.actual_usd is not None else "-", n.status.value)
    con.print(t)
    con.print(f"Spent so far: ${p.run.spent_usd:.2f} of budget ${p.settings.budget_usd:.2f}")


@app.command()
def render(clip: Optional[str] = typer.Argument(None, help="clip number to make (with anything it needs first)"),
           all: bool = typer.Option(False, "--all", help="make the entire video"),
           next: bool = typer.Option(False, "--next", help="make the next clip"),
           cont: bool = typer.Option(False, "--continue", help="make all remaining clips and stitch"),
           yes: bool = typer.Option(False, "--yes", "-y", help="skip the cost confirmation"),
           auto_pick: bool = typer.Option(True, help="pick the best take automatically (use --no-auto-pick to choose)"),
           project: Optional[str] = typer.Option(None, "-p")):
    """Generate clips. Shows cost and time and asks before spending."""
    from .runner import Engine
    svc = _svc()
    pid = _pid(project)
    mode = "clip" if clip else ("next" if next else ("continue" if cont else "all"))
    targets = [_node(svc, pid, clip)] if clip else None
    est = svc.estimate_targets(pid, targets or ([] if mode != "all" else [n.id for n in leaves(svc.load(pid))]))
    if mode in ("all", "continue"):
        p = svc.load(pid)
        est = svc.estimate_targets(pid, [n.id for n in leaves(p) if n.status.value != "done"])
    con.print(f"This will make {len(est['clips'])} clip(s): ≈ ${est['cost_usd']:.2f}, about {_fmt(est['time_s'])}. "
              f"Spent so far ${est['spent_usd']:.2f} of ${est['budget_usd']:.2f}.")
    if est["extra_upstream"]:
        con.print(f"  (includes {len(est['extra_upstream'])} earlier clip(s) it depends on)")
    if not yes and est["cost_usd"] > 0 and not typer.confirm("Go ahead?"):
        raise typer.Exit()
    eng = Engine(svc, emit=lambda p, e: con.print(f"[dim]{e.get('type')} {e.get('node', '')} {e.get('step', '') or e.get('status', '')}[/]")
                 if e.get("type") in ("clip", "assemble", "final") else None, stop_when_waiting=True)

    async def go():
        await eng.start(pid, mode, targets, auto_pick=auto_pick)
        await eng.runs[pid].task
    asyncio.run(go())
    p = svc.load(pid)
    con.print(f"[bold]{p.run.message}[/]")
    if p.final_output:
        con.print(f"Final video: {ProjectStore.path_for(pid) / p.final_output}")
    picks = [numbering(p)[n.id] for n in leaves(p) if n.status.value == "needs_pick"]
    if picks:
        con.print(f"Pick takes with: vg pick <clip> <take-number>   (waiting: {', '.join(picks)})")


@app.command()
def join(node: str = typer.Argument(..., help="clip number, for example 1.2"),
         how: str = typer.Argument(..., help="continues | same_scene | cut: how this clip joins the clip before it"),
         project: Optional[str] = typer.Option(None, "-p")):
    """Say how a clip joins the one before it. continues = starts on its last picture; same_scene = same place, new angle; cut = new place or time."""
    svc = _svc()
    pid = _pid(project)
    try:
        p = svc.set_join(pid, _node(svc, pid, node), how)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
    c = find(p, _node(svc, pid, node)).continuity
    con.print(f"Clip {node} now joins the clip before it as: [bold]{c.join}[/] ({c.join_reason}).")


@app.command()
def optimize(scope: str = typer.Option("", "--scope", help="a part number such as 2 (default: the whole video)"),
             length: Optional[float] = typer.Option(None, "--length", help="the length you want, in seconds"),
             cost: Optional[float] = typer.Option(None, "--cost", help="the most you want to still spend, in dollars"),
             lowest: bool = typer.Option(False, "--lowest", help="as short and cheap as possible without losing quality"),
             max_level: Optional[int] = typer.Option(None, "--max-level", help="the deepest level it may use: 1 no visible change, 2 small, 3 noticeable"),
             ai: bool = typer.Option(False, "--ai", help="also ask the AI to tighten the script (it shows the cost first)"),
             replan: bool = typer.Option(False, "--replan", help="ask the AI to rewrite the Goal a little and re-plan the parts (it shows the cost first)"),
             cut: List[str] = typer.Option([], "--cut", help="a clip or part number that may be cut (repeat for more), for example --cut 2.3"),
             keep: List[str] = typer.Option([], "--keep", help="a clip or part number that must stay (repeat for more)"),
             reuse: bool = typer.Option(True, "--reuse/--no-reuse", help="with --replan: reuse the videos already made where the new plan keeps a clip (default), or make new ones"),
             apply_it: bool = typer.Option(False, "--apply", help="apply the proposal (otherwise it only shows it)"),
             yes: bool = typer.Option(False, "--yes", "-y", help="do not ask before spending on the AI or applying"),
             project: Optional[str] = typer.Option(None, "-p")):
    """Propose a shorter and cheaper video (nothing changes until --apply). Levels: 1 no visible change, 2 small change, 3 noticeable, 4 AI script change,
    5 (--replan) a lightly reworded Goal and a new breakdown."""
    svc = _svc()
    pid = _pid(project)
    body = {"scope": _node(svc, pid, scope) if scope else None, "length": length, "cost": cost, "lowest": lowest, "max_level": max_level,
            "answers": {**{n: "cut" for n in cut}, **{n: "keep" for n in keep}}}
    if replan:
        return _replan_cli(svc, pid, body, apply_it, yes, reuse)
    try:
        prop = svc.optimize_propose(pid, body)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
    if ai:
        info = prop["ai"]
        if not info["available"]:
            con.print(info["why"])
        else:
            con.print(f"Asking the AI to tighten {info['clips']} clip(s) costs about ${info['cost_low']:.2f} to ${info['cost_high']:.2f} ({info['model']}).")
            if yes or typer.confirm("Ask the AI?"):
                got = asyncio.run(svc.optimize_ai(pid, body))
                for why in got["skipped"]:
                    con.print(f"[yellow]ignored[/] {why}")
                body["ai_edits"] = got["edits"]
                prop = svc.optimize_propose(pid, body)
    _show_proposal(prop)
    if apply_it:
        if prop["after"]["seconds"] == prop["before"]["seconds"] and prop["after"]["cost"] == prop["before"]["cost"]:
            con.print("Nothing to apply.")
            return
        if yes or typer.confirm("Apply the ticked changes? (one undo step)"):
            body["ticked"] = [e["id"] for e in prop["edits"] if e["checked"]]
            svc.optimize_apply(pid, body)
            con.print("[green]Applied.[/] Undo with: vg undo")


def _replan_cli(svc, pid: str, body: dict, apply_it: bool, yes: bool, reuse: bool) -> None:
    """`vg optimize --replan`: the cost first, then the proposed Goal change and the new plan beside the current one; nothing changes without --apply."""
    est_ = svc.replan_estimate(pid, body)
    free = est_["call_high"] == 0
    con.print(f"Asking the AI to re-plan costs about " + ("nothing (the offline helper)." if free else f"${est_['call_low']:.2f} to ${est_['call_high']:.2f} ({est_['model']}).")
              + (f" Writing the scripts of the new clips afterwards: about ${est_['scripts_low']:.2f} to ${est_['scripts_high']:.2f}." if not free else ""))
    if not (yes or typer.confirm("Ask the AI?")):
        return
    body["question_answers"] = []
    try:
        res = asyncio.run(svc.replan_preview(pid, body))
        while res["plan"] is None and res["questions"]:                                     # the planner could not choose: you answer, it is asked again
            for q in res["questions"]:
                answer = typer.prompt(q["text"] + ("  [" + " / ".join(q["options"]) + "]" if q["options"] else ""))
                body["question_answers"].append({"id": q["id"], "text": q["text"], "answer": answer})
            res = asyncio.run(svc.replan_preview(pid, body))
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
    plan = res["plan"]
    if plan is None:
        con.print("The AI returned no plan.")
        return
    g = plan["goal"]
    con.print("[bold]Goal[/]" + (": unchanged." if g["new"] == g["old"] else f":\n  before: {g['old']}\n  after:  {g['new']}"))
    if plan["part_goal"]["new"] != plan["part_goal"]["old"]:
        con.print(f"[bold]Part Goal[/]:\n  before: {plan['part_goal']['old']}\n  after:  {plan['part_goal']['new']}")
    b, a = res["before"], res["after"]
    con.print(f"[bold]New plan[/]: length {b['seconds']:.0f} s to {a['seconds']:.0f} s · still to spend ${b['cost']:.2f} to ${a['cost']:.2f} (new clips have no script yet, so this is a range)")
    for part in res["outline"]:
        con.print(f"  part {part['number']} {part['title']}: {part['seconds']:.0f} s")
        for c in part["clips"]:
            con.print(f"    {c['number']} {c['title']} ({c['seconds']:.0f} s){'  (reuses its video)' if c['reused'] and c['made'] else '  (kept)' if c['reused'] else '  (new)'}")
    for u in plan["unused_made"]:
        con.print(f"  [yellow]clip {u['number']} is made but not in the new plan[/]: its video stays on disk (vg undo brings it back); it is not reused")
    for f in plan["forced"]:
        con.print(f"  [dim]clip {f['number']} stays: {f['why']}[/]")
    for w in plan["warnings"]:
        con.print(f"[yellow]{w}[/]")
    if plan["note"]:
        con.print(f"[dim]{plan['note']}[/]")
    if not apply_it:
        con.print("Nothing was changed. Add --apply to make this the plan.")
        return
    if yes or typer.confirm("Apply this plan? (one undo step)"):
        choose = {} if reuse else {u: False for u in {c["reuse_id"] for p_ in plan["parts"] for c in p_["clips"] if c["reuse_id"] and not c["forced"]}}
        svc.replan_apply(pid, {"plan": plan, "reuse": choose})
        con.print("[green]Applied.[/] Write the scripts of the new clips when you are ready (vg script <clip>, or the Write the scripts step in the app), or undo with: vg undo")


def _show_proposal(prop: dict) -> None:
    b, a = prop["before"], prop["after"]
    con.print(f"[bold]{'The whole video' if prop['scope']['is_whole_video'] else 'Part ' + prop['scope']['number']}[/]: "
              f"length {b['seconds']:.0f} s to {a['seconds']:.0f} s · still to spend ${b['cost']:.2f} to ${a['cost']:.2f} · making time about {b['time_s'] / 60:.0f} to {a['time_s'] / 60:.0f} min")
    for lv in prop["levels"]:
        if lv["level"] == 4 and not any(e["level"] == 4 for e in prop["edits"]):
            continue
        con.print(f"  level {lv['level']} {lv['name']}: {lv['after']['seconds']:.0f} s, ${lv['after']['cost']:.2f}" + ("  [green]meets the goal[/]" if lv["meets_goal"] else ""))
    for e in prop["edits"]:
        con.print(f"   [{'x' if e['checked'] else ' '}] L{e['level']} {e['label']}  ({e['effect']['seconds']:+.1f} s, {e['effect']['cost']:+.2f} $)" + (f"\n        you lose: {e['loses']}" if e["loses"] else ""))
    j = prop["joins"]
    if j["of"]:
        con.print(f"Joins kept: {j['kept']} of {j['of']}")
        for x in j["broken"]:
            con.print(f"   [yellow]{x}[/]")
    for n in prop["notes"]:
        con.print(f"[dim]{n}[/]")
    if prop["reason"]:
        con.print(f"[yellow]The goal cannot be met.[/] {prop['reason']}")
    elif prop["met"]:
        con.print("[green]The goal is met.[/]")


@app.command()
def continuity(project: Optional[str] = typer.Option(None, "-p")):
    """List what would make the clips feel like different videos (plain rules, no AI, no cost)."""
    svc = _svc()
    pid = _pid(project)
    found = svc.summary(svc.load(pid))["continuity"]
    if not found:
        con.print("Everything fits together.")
    for f in found:
        con.print(f"[{'red' if f['severity'] == 'problem' else 'yellow'}]{f['severity'].upper()}[/] {('clip ' + f['number'] + ': ') if f['number'] else ''}{f['text']}")
        for fx in f["fixes"]:
            if fx["action"] in ("copy_start", "set_join", "joins_as_cuts"):
                con.print(f"    fix: {fx['label']}" + (f"  (vg join {f['number']} {fx['join']})" if fx["action"] == "set_join" else ""))


@app.command()
def export(node: str = typer.Argument(..., help="clip or part number, for example 2 or 2.1"),
           output: Optional[Path] = typer.Option(None, "-o", help="where to save the video (default: the current folder)"),
           music: str = typer.Option("auto", help="auto | new | none: auto uses the saved music and asks before a new track is paid for"),
           yes: bool = typer.Option(False, "--yes", "-y", help="do not ask before paying for new music"),
           project: Optional[str] = typer.Option(None, "-p")):
    """Save the finished video of one clip or part (every clip under it must be made)."""
    import shutil
    from .runner import Engine
    svc = _svc()
    pid = _pid(project)
    nid = _node(svc, pid, node)
    eng = Engine(svc)
    res = asyncio.run(eng.export_node(pid, nid, music))
    if res.get("needs_music_choice"):
        con.print(f"This part would need new background music for the whole video: ≈ ${res['cost_usd']:.2f} ({res['model']}); every part and "
                  "the final video then reuse it.")
        if yes or typer.confirm("Make the music now?"):
            res = asyncio.run(eng.export_node(pid, nid, "new"))
        else:
            res = asyncio.run(eng.export_node(pid, nid, "none"))
    src = ProjectStore.path_for(pid) / res["path"]
    dest = (output or Path.cwd() / res["filename"])
    if dest.is_dir():
        dest = dest / res["filename"]
    shutil.copy(src, dest)
    con.print(f"Saved {dest} ({res['seconds']:.0f} s{', with music' if res['with_music'] else ', no music'})")
    if res.get("srt"):
        shutil.copy(ProjectStore.path_for(pid) / res["srt"], dest.with_suffix(".srt"))
        con.print(f"Subtitles: {dest.with_suffix('.srt')}")
    for note in res.get("notes", []):
        con.print(f"[dim]{note}[/]")


@app.command()
def pick(clip: str, take: int, project: Optional[str] = typer.Option(None, "-p")):
    """Choose a take for a clip (1, 2, 3 …)."""
    from .runner import Engine
    svc = _svc()
    pid = _pid(project)
    nid = _node(svc, pid, clip)
    n = find(svc.load(pid), nid)
    takes = [t for t in n.takes if t.version == n.version] or n.takes
    asyncio.run(Engine(svc).pick(pid, nid, takes[take - 1].id))
    con.print("picked")


@app.command()
def takes(clip: str, project: Optional[str] = typer.Option(None, "-p")):
    """Show the takes and the Review Agent's findings for a clip."""
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    n = find(p, _node(svc, pid, clip))
    reviews = {r.id: r for r in p.reviews}
    for i, t in enumerate([t for t in n.takes if t.version == n.version] or n.takes, start=1):
        r = reviews.get(t.review_id or "")
        con.print(f"[bold]take {i}[/] {t.model} {t.seconds:.1f}s  {ProjectStore.path_for(pid) / (t.video or '')}"
                  + ("  [green]chosen[/]" if t.id == n.chosen_take else ""))
        if r:
            con.print(f"   verdict: {r.verdict}  scores: {r.scores}")
            for iss in r.issues:
                con.print(f"   ! {iss.check}: {iss.text}" + (f" at {iss.at_s:.1f}s" if iss.at_s is not None else ""))
            for s in r.suggestions:
                con.print(f"   → {s.text}")


@app.command()
def remake(clip: str, feedback: str = typer.Option("", help="your own feedback (wins over the agent's)"),
           accept_all: bool = typer.Option(True, help="include the Review Agent's suggestions"),
           yes: bool = False, project: Optional[str] = typer.Option(None, "-p")):
    """Re-make a clip with the agent's suggestions plus your feedback (you confirm first)."""
    svc = _svc()
    pid = _pid(project)
    nid = _node(svc, pid, clip)
    p = svc.load(pid)
    n = find(p, nid)
    accepted = [s.id for r in p.reviews if r.target in {t.id for t in n.takes} for s in r.suggestions] if accept_all else []
    prev = asyncio.run(svc.preview_remake(pid, nid, accepted, feedback))
    con.print("[bold]Old visual:[/] " + ((prev["old"] or {}).get("visual", "")[:300]))
    con.print("[bold]New visual:[/] " + prev["new"]["visual"][:300])
    con.print(f"Change: {prev['change_summary']}  — new estimate ≈ ${prev['cost']['likely_usd']:.2f}")
    if yes or typer.confirm("Apply and re-make?"):
        svc.apply_remake(pid, nid, prev["new"], prev["feedback"])
        render(clip, yes=True, project=pid)


@app.command()
def compare(clip: str, models: str = typer.Option(..., help="comma-separated catalogue ids, e.g. veo_3_1,kling_3"),
            project: Optional[str] = typer.Option(None, "-p")):
    """Make the same clip with several models, side by side."""
    from .runner import Engine
    svc = _svc()
    pid = _pid(project)
    asyncio.run(Engine(svc).compare(pid, _node(svc, pid, clip), [m.strip() for m in models.split(",")]))
    takes(clip, project=pid)


@app.command()
def budget(project: Optional[str] = typer.Option(None, "-p")):
    """Where the money went: every paid call, grouped, with the arithmetic."""
    svc = _svc()
    r = svc.budget_report(_pid(project))
    con.print(f"Budget ${r['budget']:.2f} · spent ${r['spent']:.2f} · still to spend ≈ ${r['remaining_estimate']:.2f} · left ≈ ${r['left_in_budget']:.2f}")
    for line in r["explain"]:
        con.print(f"  • {line}")
    for g in r["groups"]:
        con.print(f"[bold]{g['label']}[/]: ${g['actual']:.4f} in {g['calls']} call(s)")
        for row in g["rows"]:
            con.print(f"    {row['what']}  {row['vendor']} {row['model']}  {row['how']}  = ${row['actual']:.4f}")


@app.command()
def explain(question: str, project: Optional[str] = typer.Option(None, "-p")):
    """Ask a question about your project in plain words (cost, time, length, why a model was chosen …)."""
    svc = _svc()
    con.print(asyncio.run(svc.explain(_pid(project), question)))


@app.command()
def doctor():
    """Check your keys with free calls (nothing is charged): OpenAI, ElevenLabs and fal.ai."""
    from . import doctor as dr
    from .catalog import Catalog
    from .config import load_env
    load_env()                       # keys saved in the GUI live in ~/.video-generator/.env
    marks = {dr.OK: "[green]✓[/]", dr.WARN: "[yellow]![/]", dr.BAD: "[red]✗[/]", dr.SKIP: "[dim]-[/]"}
    checks = asyncio.run(dr.run_checks(catalog=Catalog.load()))
    for c in checks:
        con.print(f"{marks[c.status]} [bold]{c.name}[/]: {c.message}", highlight=False)
    bad = [c for c in checks if c.status == dr.BAD]
    con.print("\n[red]Fix the ✗ lines before you generate.[/]" if bad else "\n[green]No problems found with your keys.[/] A real clip is the final test.")


@app.command("smoke-test")
def smoke_test(max_usd: float = typer.Option(1.0, "--max-usd", help="never spend more than this many dollars"),
               yes: bool = typer.Option(False, "--yes", help="do not ask before spending"),
               all_video_models: bool = typer.Option(False, "--all-video-models", help="test up to 3 video models (costs more)")):
    """A tiny REAL test of voice, picture, video and a talking picture with your own keys (about $1 at most). Asks first."""
    from . import smoketest
    svc = _svc()
    rep = asyncio.run(smoketest.run(svc, max_usd, None if yes else (lambda q: typer.confirm(q)),
                                    say=lambda s: con.print(s, highlight=False), all_video=all_video_models))
    con.print("\n" + rep.text(), highlight=False)


@app.command()
def policy():
    """Show every quality rule and its value. Change one in ~/.video-generator/config.yaml under `policy:`."""
    from . import policy as pol
    from .config import Config
    Config.load()
    for name, value, why in pol.describe():
        con.print(f"[bold]{name}[/] = {value}", highlight=False)
        con.print(f"    {why}", highlight=False)


@app.command("photo-test")
def photo_test(words: str = typer.Argument("wild animal portrait", help="what to search for, e.g. 'red fox winter'")):
    """Check the automatic photo search on this computer, step by step. Saves the first photo it can download here."""
    from . import stock
    from .config import load_env
    load_env()
    lines, saved = asyncio.run(stock.diagnose(words, Path.cwd()))
    for line in lines:
        con.print(line, highlight=False)
    con.print("[green]Photo search works.[/]" if saved else "[yellow]No photo was saved.[/]")


@app.command()
def pause(project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    p.run.status = "paused"
    ProjectStore.save(p, snapshot=False)
    con.print("paused (running jobs will finish)")


@app.command()
def stop(project: Optional[str] = typer.Option(None, "-p")):
    svc = _svc()
    pid = _pid(project)
    p = svc.load(pid)
    p.run.status = "stopping"
    ProjectStore.save(p, snapshot=False)
    con.print("stopping")


@app.command()
def resume(project: Optional[str] = typer.Option(None, "-p")):
    """Continue a paused or interrupted run."""
    render(cont=True, yes=True, project=project)


# ===================================================================== plugins, catalog, vendors, settings
@app.command()
def plugins():
    """List every plugin found (built-in and installed), and whether it is configured."""
    svc = _svc()
    t = Table("plugin", "job", "configured", "description")
    for name, cls in sorted(plugin_classes().items()):
        ok, why = svc.reg.plugin(name).is_configured()
        t.add_row(name, getattr(cls, "job", ""), "[green]yes[/]" if ok else f"[dim]{why}[/]", getattr(cls, "description", ""))
    con.print(t)


@app.command()
def catalog(check: bool = typer.Option(False, help="list prices older than 30 days")):
    """Show the model catalogue (prices, strengths, last checked)."""
    svc = _svc()
    rows = svc.catalog.stale() if check else svc.catalog.entries
    t = Table("id", "job", "plugin", "price", "usable", "checked", "pricing page")
    for e in rows:
        price = f"${e.price.usd}/{e.price.unit}" if e.price.unit != "1m_tokens" else f"${e.price.usd_in}/${e.price.usd_out} per 1M"
        t.add_row(e.id, e.job, e.plugin, price, "yes" if svc.reg.entry_usable(e) else "-", e.last_checked, e.pricing_url)
    con.print(t)
    if check and not rows:
        con.print("All prices were checked in the last 30 days.")


@app.command()
def vendors():
    """Vendors, sign-up/pricing links, and which keys are set."""
    import os
    t = Table("vendor", "used for", "key(s)", "sign up", "need")
    for v in load_vendors():
        keys = ", ".join(f"{k} {'✓' if os.environ.get(k) else '✗'}" for k in v.get("env", [])) or "-"
        t.add_row(v["name"], v["used_for"], keys, v.get("signup_url", ""), v.get("need", ""))
    Config.load()
    con.print(t)


@config_app.command("set")
def config_set(key: str, value: str):
    """Example: vg config set llm.default openai"""
    cfg = Config.load()
    cfg.set_path(key, value)
    cfg.save()
    con.print(f"{key} = {value}")


@config_app.command("show")
def config_show():
    con.print_json(Config.load().model_dump_json())
    con.print(f"[dim]config folder: {vg_home()}[/]")


@config_app.command("key")
def config_key(name: str, value: str):
    """Store an API key in ~/.video-generator/.env (e.g. vg config key FAL_KEY ...)."""
    save_key(name, value)
    con.print(f"{name} saved")


@app.command()
def gui(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    """Open the GUI in your browser."""
    import threading
    import uvicorn
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    con.print(f"video-generator is running at [bold]{url}[/]  (Ctrl+C to stop)")
    uvicorn.run("video_generator.web.app:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
