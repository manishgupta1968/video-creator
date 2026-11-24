"""Offline scene agent: a plain, predictable fix so the whole check-and-fix loop works (and is tested) with no agent
installed. As builder it points the camera at the middle of the figures from far enough back to see them all; as
checker it approves, unless `checker_problems` holds problems to report (tests use this)."""
from __future__ import annotations

import json

from ..base import AgentResult, AgentTask, SceneAgent


def simple_change(plan: dict, request: str) -> tuple[dict, str]:
    """The offline way to apply a change asked in plain words: a few common requests, done plainly.
    "bigger" / "twice as big" / "smaller" (the shape named in the request, else every figure), "closer" / "further"
    (the camera), "slower" / "faster" (how far things move). Returns the plan and what was done ("" = nothing understood)."""
    import re
    p = json.loads(json.dumps(plan))
    words = request.lower()
    named = [t for t in p.get("things", []) if t.get("label") and any(w in words for w in re.findall(r"[a-z]{3,}", t["label"].lower()))]
    targets = named or [t for t in p.get("things", []) if t.get("kind") == "figure"]
    done = []
    factor = 2.0 if re.search(r"twice|double|2x|much bigger|huge", words) else 1.5 if "bigger" in words or "larger" in words else \
        0.5 if re.search(r"half|much smaller", words) else 0.7 if "smaller" in words else None
    if factor:
        for t in targets:
            t["size"] = [round(v * factor, 3) for v in t["size"]]
        done.append(f"made {', '.join(t.get('label') or t['id'] for t in targets)} {factor:g} times the size")
    cam = p.get("camera", {}).get("keys", [])
    if cam and re.search(r"closer|nearer|zoom in|push in", words):
        for k in cam[-1:] if "end" in words else cam:
            k["at"] = [a + (b - a) * 0.5 for a, b in zip(k["at"], k.get("look_at", k["at"]))]
        done.append("moved the camera halfway closer" + (" at the end" if "end" in words else ""))
    elif cam and re.search(r"further|farther|zoom out|pull back|wider", words):
        for k in cam:
            k["at"] = [b + (a - b) * 1.6 for a, b in zip(k["at"], k.get("look_at", k["at"]))]
        done.append("moved the camera further back")
    speed = 0.5 if "slower" in words else 1.5 if "faster" in words else None
    if speed:
        for t in p.get("things", []):
            ks = t.get("keys", [])
            if len(ks) > 1:
                x0 = ks[0]["at"]
                for k in ks[1:]:
                    k["at"] = [a + (b - a) * speed for a, b in zip(x0, k["at"])]
        done.append("made the movement " + ("slower" if speed < 1 else "faster"))
    return p, "; ".join(done)


class FakeAgent(SceneAgent):
    name = "fake_agent"
    env_keys: list[str] = []
    description = "Free offline fixer (simple camera fix, for trying the flow)"

    def __init__(self, config=None):
        super().__init__(config)
        self.checker_problems: list[list[str]] = []     # one list per checker run, used in order
        self.runs: list[AgentTask] = []

    async def run(self, task: AgentTask) -> AgentResult:
        from ...scene3d.spec import ScenePlan, normalise, thing_at
        self.runs.append(task)
        if task.role == "checker":
            problems = self.checker_problems.pop(0) if self.checker_problems else []
            (task.folder / "verdict.json").write_text(json.dumps({"ok": not problems, "problems": problems}))
            return AgentResult(ok=True, summary="looked at the pictures: " + ("; ".join(problems) or "the camera matches"))
        if task.role == "change":
            data, done = simple_change(json.loads((task.folder / "plan.json").read_text()), task.request)
            (task.folder / "plan.json").write_text(json.dumps(data, indent=1))
            return AgentResult(ok=True, summary=(done[:1].upper() + done[1:] + ".") if done else "I did not understand that change.")
        plan = normalise(ScenePlan.model_validate(json.loads((task.folder / "plan.json").read_text())))
        figures = [t for t in plan.things if t.kind == "figure"] or plan.things
        keys = []
        for t in (0.0, plan.seconds):
            pts = [thing_at(f, t) for f in figures]
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            spread = max([abs(p[0] - cx) + f.size[0] for p, f in zip(pts, figures)] + [max(f.size[2] for f in figures)])
            keys.append({"t": t, "at": [cx, cy - (spread * 2.2 + 6), 2.5], "look_at": [cx, cy, 1.0]})
        data = plan.model_dump()
        data["camera"]["keys"] = keys
        (task.folder / "plan.json").write_text(json.dumps(data, indent=1))
        return AgentResult(ok=True, summary="moved the camera back so every figure is in view")
