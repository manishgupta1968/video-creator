"""The models your Claude Code and Codex can use, read from the programs themselves (nothing is typed in by hand).

  Codex        `codex debug models` prints its model catalogue for your sign-in as JSON: each model's code name (slug),
               display name, description and whether it is listed. Only listed models are offered.
  Claude Code  has no list command. Its `--help` names the short model names it accepts (e.g. 'fable', 'opus',
               'sonnet') and the effort levels of --effort; those are offered. Each answer also says which full model
               answered (`modelUsage`).
  Codex's catalogue also gives each model's reasoning levels (supported_reasoning_levels) and its default level.

The lists are kept for ten minutes, so the Settings page does not start the programs on every visit.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from typing import Optional

_CACHE: dict[str, tuple[float, list[dict], str]] = {}
_KEEP_S = 600


def _exe(program: str, env: str) -> Optional[str]:
    return shutil.which(os.environ.get(env, "") or program)


async def _output(cmd: list[str], timeout_s: int = 60) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, (out or b"").decode(errors="replace")


def codex_slug(model: str) -> str:
    """Codex wants a model's code name ('gpt-6.2-sol'), not its display name ('GPT-6.2-Sol' or 'GPT-6.1 Terra')."""
    return re.sub(r"\s+", "-", (model or "").strip()).lower()


def parse_codex(text: str) -> list[dict]:
    data = json.loads(text[text.index("{"):] if "{" in text else text)
    rows = data.get("models", data) if isinstance(data, dict) else data
    out = []
    for m in sorted((r for r in rows if isinstance(r, dict) and r.get("slug")), key=lambda r: r.get("priority") or 999):
        if m.get("visibility", "list") != "list":
            continue
        efforts = [{"id": str(e.get("effort")), "note": str(e.get("description") or "")}
                   for e in (m.get("supported_reasoning_levels") or []) if isinstance(e, dict) and e.get("effort")]
        out.append({"id": m["slug"], "name": m.get("display_name") or m["slug"], "note": m.get("description") or "",
                    "efforts": efforts, "default_effort": str(m.get("default_reasoning_level") or "")})
    return out


def parse_claude_help(text: str) -> list[dict]:
    """The aliases Claude Code's own help names for --model, e.g. (e.g. 'fable', 'opus', or 'sonnet')."""
    block = re.search(r"--model <model>(.*?)(?:\n\s*-{1,2}[a-z])", text, re.S)
    names = re.findall(r"'([a-z][a-z0-9.\-]*)'", block.group(1) if block else "")
    eff = re.search(r"--effort <level>.*?\(([^)]*)\)", text, re.S)
    efforts = [{"id": e.strip(), "note": ""} for e in (eff.group(1).split(",") if eff else []) if e.strip()]
    seen, out = set(), []
    for n in names + ["haiku"]:          # haiku is accepted too, though the help names only a few examples
        if n not in seen:
            seen.add(n)
            out.append({"id": n, "name": n.title(), "note": "the latest model of this name", "efforts": efforts, "default_effort": ""})
    return out


def claude_efforts(text: str) -> list[dict]:
    """The effort levels Claude Code's own help names for --effort (e.g. low, medium, high, xhigh, max)."""
    return parse_claude_help(text)[0]["efforts"] if parse_claude_help(text) else []


async def list_models(which: str, fresh: bool = False) -> tuple[list[dict], str]:
    """(models, problem) for 'claude_code' or 'codex'. problem is '' when the list was read."""
    now = time.monotonic()
    if not fresh and which in _CACHE and now - _CACHE[which][0] < _KEEP_S:
        return _CACHE[which][1], _CACHE[which][2]
    models, why = [], ""
    try:
        if which == "codex":
            exe = _exe("codex", "VG_CODEX")
            if not exe:
                why = "Codex is not installed"
            else:
                code, out = await _output([exe, "debug", "models"])
                models = parse_codex(out) if code == 0 else []
                why = "" if models else f"`codex debug models` gave no list (exit {code}); update Codex with `codex update`"
        else:
            exe = _exe("claude", "VG_CLAUDE")
            if not exe:
                why = "Claude Code is not installed"
            else:
                code, out = await _output([exe, "--help"], 30)
                models = parse_claude_help(out)
    except (OSError, ValueError, asyncio.TimeoutError) as exc:
        why = f"could not read the model list: {exc}"
    _CACHE[which] = (now, models, why)
    return models, why
