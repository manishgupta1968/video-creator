"""Offline scene agent: a plain, predictable fix so the whole check-and-fix loop works (and is tested) with no agent
installed. As builder it points the camera at the middle of the figures from far enough back to see them all; as
checker it approves, unless `checker_problems` holds problems to report (tests use this)."""
from __future__ import annotations

import json

from ..base import AgentResult, AgentTask, SceneAgent


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
