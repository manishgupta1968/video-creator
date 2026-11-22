"""The free plan check an agent (or you) can run on a scene plan file:

    python -m video_generator.scene3d.check plan.json

It prints every measured problem in plain words, says where each figure is in the picture at the start, middle and
end, and draws three preview pictures (preview/start.png, middle.png, end.png) next to the plan with the free sketch
renderer. No Blender, no AI, no cost. Exit code 0 = no major problem, 1 = a major problem, 2 = the file is not a plan.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .spec import ScenePlan, camera_at, check, colour_name, normalise, visibility


def report(plan: ScenePlan) -> tuple[str, bool]:
    p = normalise(plan)
    issues = check(p)
    lines = []
    for name, t in (("start", 0.0), ("middle", p.seconds / 2), ("end", p.seconds)):
        eye, target, lens = camera_at(p.camera, t)
        seen = []
        for th in p.things:
            if th.kind != "figure":
                continue
            where, share = visibility(p, th, t)
            seen.append(f"{th.label or th.id} ({colour_name(th.colour)}): {where}" + (f" {share:.0%}" if where == "partly" else ""))
        lines.append(f"{name} ({t:g} s): camera at {[round(v, 2) for v in eye]} looking at {[round(v, 2) for v in target]}, "
                     f"lens {lens:g} mm. " + "; ".join(seen))
    major = any(i.severity == "major" for i in issues)
    lines.append("Problems:" if issues else "Problems: none.")
    lines += [f"- {i.severity}: {i.text}" for i in issues]
    return "\n".join(lines), major


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    path = Path(argv[0])
    try:
        plan = ScenePlan.model_validate(json.loads(path.read_text()))
    except (OSError, ValueError, ValidationError) as exc:
        print(f"{path} is not a valid scene plan: {exc}")
        return 2
    text, major = report(plan)
    print(text)
    if "--no-pictures" not in argv:
        from .render import sketch_frame
        out = path.parent / "preview"
        out.mkdir(exist_ok=True)
        p = normalise(plan)
        for name, t in (("start", 0.0), ("middle", p.seconds / 2), ("end", p.seconds)):
            sketch_frame(p, t, (640, 360)).save(out / f"{name}.png")
        print(f"Preview pictures: {out}/start.png, middle.png, end.png")
    return 1 if major else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
