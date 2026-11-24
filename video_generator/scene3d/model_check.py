"""Check a 3D model script in Blender, render pictures of it, and save it (the 3D camera reference add-on).

    python -m video_generator.scene3d.model_check model.py [--name guru] [--needs kneel,bow,touch_ground]

Runs Blender in the background on blender_model.py: builds the model from model.py, measures it, checks every pose
uses bones that exist and that every pose the script needs is there, renders front / three-quarter / side / back
pictures and one picture per pose into the folder of model.py, and saves model.blend. Prints the problems in plain
words. Exit code 0 = no problem, 1 = problems, 2 = Blender is missing or model.py did not run.
Used by Claude Code / Codex while they build a model, and by the tool itself afterwards (it never trusts a model
it has not checked itself).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .render import DEFAULT_ENGINES, find_blender

SCRIPT = Path(__file__).with_name("blender_model.py")


def check_model(model_py: Path, name: str = "model", needs: Optional[list[str]] = None, blender: str = "",
                engines: Optional[list[str]] = None, timeout_s: int = 600) -> dict:
    """Run the check; returns result.json as a dict (ok, height, width, depth, bones, poses, missing, problems) plus
    'engine' and 'previews' ({view: path}). Raises RuntimeError when Blender is not installed."""
    exe = find_blender(blender)
    if not exe:
        raise RuntimeError("Blender is not installed (or not found), so 3D models cannot be built or checked.")
    out = Path(model_py).resolve().parent
    last: dict = {}
    for engine in engines or DEFAULT_ENGINES:
        (out / "result.json").unlink(missing_ok=True)
        try:
            proc = subprocess.run([exe, "--background", "--factory-startup", "-noaudio", "--python", str(SCRIPT), "--",
                                   str(Path(model_py).resolve()), str(out), name, engine, json.dumps(needs or [])],
                                  capture_output=True, text=True, timeout=timeout_s)
            log = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            last = {"ok": False, "problems": [f"Blender took longer than {timeout_s} s on this model"]}
            continue
        try:
            last = json.loads((out / "result.json").read_text())
        except (OSError, ValueError):
            last = {"ok": False, "problems": ["Blender stopped before checking the model: " + " ".join(log.split())[-300:]]}
        failed_to_draw = proc.returncode != 0 and not any(p.startswith("model.py failed") for p in last.get("problems", []))
        if failed_to_draw and engine != (engines or DEFAULT_ENGINES)[-1]:
            continue                       # this render engine cannot run here: try the next one
        last["engine"] = engine
        break
    last["previews"] = {p.stem: str(p) for p in sorted(out.glob("*.png"))
                        if p.stem in ("front", "side", "back", "three_quarter") or p.stem.startswith("pose_")}
    return last


def report(r: dict) -> str:
    lines = [f"Size: {r.get('height', 0):.2f} m high, {r.get('width', 0):.2f} m wide, {r.get('depth', 0):.2f} m deep."
             if r.get("height") else "Size: unknown (the model did not build)."]
    if r.get("bones"):
        lines.append(f"Bones: {', '.join(r['bones'])}")
    lines.append(f"Poses: {', '.join(r.get('poses') or []) or 'none'}")
    lines.append("Problems:" if r.get("problems") else "Problems: none.")
    lines += [f"- {p}" for p in r.get("problems") or []]
    if r.get("previews"):
        lines.append("Pictures: " + ", ".join(Path(v).name for v in r["previews"].values()))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    model = Path(argv[0])
    name = argv[argv.index("--name") + 1] if "--name" in argv else model.parent.name or "model"
    needs = [x for x in (argv[argv.index("--needs") + 1].split(",") if "--needs" in argv else []) if x]
    try:
        r = check_model(model, name, needs)
    except RuntimeError as exc:
        print(exc)
        return 2
    print(report(r))
    if any(str(p).startswith("model.py failed") for p in r.get("problems") or []):
        return 2
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
