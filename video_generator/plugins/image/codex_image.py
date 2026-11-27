"""Pictures through YOUR ChatGPT subscription: Codex's built-in image generation tool, run on this computer.

  codex exec --skip-git-repo-check --sandbox workspace-write --cd <folder> --json [-i picture …] [-m model]
             [-c model_reasoning_effort="…"] <instructions>

Codex has an image generation tool (its feature list calls it `image_generation`, stable and on by default). It saves
each picture it makes under its own folder ($CODEX_HOME/generated_images/…, CODEX_HOME is ~/.codex unless set). Codex
is asked to copy the picture into the work folder as output.png; when it does not, the newest picture it saved since
the run started is taken from its folder. There is no per-picture cost: it counts against your plan's usage limits.

Claude Code has no image tool, so pictures come from Codex (or from a picture service such as fal.ai).
Set VG_CODEX to use a codex program that is not on the PATH, and CODEX_HOME if Codex keeps its files elsewhere.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from ..agent.cli_agents import _run
from ..base import ImageGenerator, ImageRequest, PluginError, Usage
from ..llm.cli_brain import SIGN_IN_HINTS, _said
from ..llm.cli_models import codex_slug

PICTURE_EXT = (".png", ".jpg", ".jpeg", ".webp")

TASK = """Make ONE picture with your built-in image generation tool, then save it here. Work only in this folder.

THE PICTURE:
{prompt}

Frame shape: {aspect} ({shape}).{avoid}
{refs}
Steps:
1. Use your image generation tool once to make the picture. Do not draw it with code, and do not use the internet.
2. Copy the picture it made into this folder as output.png (your tool saves it under $CODEX_HOME/generated_images/).
3. Do not create or change any other file. Reply with one sentence describing the picture.
"""


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _shape(aspect: str) -> str:
    try:
        a, b = (float(x) for x in aspect.split(":"))
    except ValueError:
        return "landscape"
    return "landscape, wider than tall" if a > b * 1.1 else "portrait, taller than wide" if b > a * 1.1 else "square"


def pictures_in(*roots: Path) -> dict[Path, float]:
    """Every picture under these folders, with when it was last written."""
    found: dict[Path, float] = {}
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            try:
                if f.suffix.lower() in PICTURE_EXT and f.is_file():
                    found[f] = f.stat().st_mtime
            except OSError:
                continue
    return found


def new_picture(before: dict[Path, float], *roots: Path) -> Optional[Path]:
    """The newest picture that was not there (or was written again) since `before`: never one left from an earlier run."""
    fresh = [(t, f) for f, t in pictures_in(*roots).items() if f not in before or t > before[f]]
    return max(fresh)[1] if fresh else None


def _paths_in(out: str) -> list[Path]:
    """Picture paths Codex mentions in its json events (for example where its image tool saved the picture)."""
    found = []
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        stack = [ev]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                stack += list(x.values())
            elif isinstance(x, list):
                stack += x
            elif isinstance(x, str) and x.lower().endswith(PICTURE_EXT) and os.path.isabs(x) and os.path.exists(x):
                found.append(Path(x))
    return found


class CodexImage(ImageGenerator):
    name = "codex_image"
    description = "Pictures through your ChatGPT subscription (Codex's image generation tool on this computer)"
    licence = "your ChatGPT plan's terms"
    program = "codex"
    env_override = "VG_CODEX"

    def __init__(self, config=None):
        super().__init__(config)
        self.blocked = ""

    def exe(self) -> Optional[str]:
        return shutil.which(os.environ.get(self.env_override, "") or self.program)

    def is_configured(self):
        if self.blocked:
            return False, self.blocked
        if self.exe():
            return True, "ok"
        return False, "install the `codex` command and sign in with your ChatGPT account (or set VG_CODEX to its path)"

    def _choice(self, key: str) -> str:
        llm = getattr(self.config, "llm", None)
        return str(((getattr(llm, key, None) or {}).get("codex_brain", "")) or "")

    def command(self, folder: Path, pictures: list[Path], instructions: str) -> list[str]:
        cmd = [self.exe() or self.program, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
               "--cd", str(folder), "--json"]
        for p in pictures:
            cmd += ["-i", str(p)]
        model, effort = self._choice("models"), self._choice("efforts")
        if model:
            cmd += ["-m", codex_slug(model)]
        if effort:
            cmd += ["-c", f'model_reasoning_effort="{effort}"']
        return cmd + [instructions]

    async def generate(self, req: ImageRequest) -> tuple[Path, Usage]:
        from ...config import vg_home
        folder = vg_home() / "picture_work" / uuid.uuid4().hex[:12]
        folder.mkdir(parents=True, exist_ok=True)
        try:
            pictures = []
            for i, src in enumerate(req.references[:6], 1):
                src = Path(src)
                if src.exists():
                    dst = folder / f"picture_{i:02d}{src.suffix.lower() or '.png'}"
                    shutil.copy(src, dst)
                    pictures.append(dst)
            refs = ""
            if pictures:
                refs = ("\nATTACHED PICTURES, in this order (the description calls them picture 1, picture 2 …): "
                        + ", ".join(p.name for p in pictures) + ". Look at every one before you make the picture; "
                        "keep the people's and things' looks from them, and the framing of picture 1 when the "
                        "description says it is a layout.\n")
            avoid = f"\nAvoid: {req.negative}." if req.negative else ""
            task = TASK.format(prompt=req.prompt.strip(), aspect=req.aspect, shape=_shape(req.aspect), avoid=avoid, refs=refs)
            started = time.time()
            home = codex_home() / "generated_images"
            before = pictures_in(home)
            code, out = await _run(self.command(folder, pictures, task), folder, None, 900)
            low = out.lower()
            if code != 0 and any(h in low for h in SIGN_IN_HINTS):
                self.blocked = "Codex is not signed in: run `codex` once in a terminal and sign in"
                raise PluginError(self.blocked)
            made: Optional[Path] = folder / "output.png"
            if not made.exists():
                found = [p for p in _paths_in(out) if p.stat().st_mtime >= started - 1 and (p not in before or p.stat().st_mtime > before[p])]
                made = found[-1] if found else (new_picture(before, home) or new_picture({p: 0 for p in pictures}, folder))
                if made is not None and made in pictures:
                    made = None
            if made is None or not made.exists():
                said = _said(out) or " ".join(out.split())[-300:]
                raise PluginError(f"Codex made no picture (exit {code}): {said} — check that `codex features list` shows "
                                  "image_generation as true, and that your ChatGPT plan includes pictures.")
            req.out.parent.mkdir(parents=True, exist_ok=True)
            if made.suffix.lower() == req.out.suffix.lower():
                shutil.copy(made, req.out)
            else:
                from PIL import Image
                Image.open(made).convert("RGB").save(req.out)
            return req.out, Usage(cost_usd=0.0, raw={"subscription": "chatgpt", "source": str(made)})
        finally:
            shutil.rmtree(folder, ignore_errors=True)
