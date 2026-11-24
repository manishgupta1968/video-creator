"""The AI brain through YOUR subscription: Claude Code or Codex, run on this computer through their command-line tools.

Planning, scripts, 3D plans and the Review Agent then use your Claude or ChatGPT subscription instead of a
pay-per-use API key. (Pictures, video clips and voices still need their own services, such as fal.ai.)

  claude_code_brain   claude -p (the question on standard input) --output-format json --json-schema <schema>
                      --system-prompt <the tool's own> --tools Read --no-session-persistence --strict-mcp-config
                      It may only READ files in a fresh work folder (the clip pictures for a review); no commands, no web.
  codex_brain         codex exec --skip-git-repo-check --sandbox read-only --cd <folder> --json [-i picture …] <question>
                      Codex's read-only sandbox lets it look but change nothing. These flags come from Codex's
                      documentation; check them with `codex exec --help` if a call fails.

Each call starts the program, so it takes a few seconds longer than an API call, and it counts against your plan's
usage limits. When a call fails (not signed in, a limit reached), the tool falls back to the next connected brain.
Set VG_CLAUDE or VG_CODEX to use a program that is not on the PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional, Type

from pydantic import BaseModel

from ..agent.cli_agents import _run
from ..base import LLM, PluginError, Usage
from .cli_models import codex_slug
from .common import MAX_IMAGES, extract_json, repair_prompt, schema_instruction

SIGN_IN_HINTS = ("not logged in", "please log in", "login", "log in", "authenticate", "unauthorized", "/login", "sign in")


def _work_folder() -> Path:
    from ...config import vg_home
    d = vg_home() / "brain_work" / uuid.uuid4().hex[:12]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pictures(images: Optional[list[Path]], folder: Path) -> list[Path]:
    """Copy the pictures into the work folder as picture_01.png …, in order (the order matters to the question)."""
    out = []
    for i, src in enumerate((images or [])[:MAX_IMAGES], 1):
        src = Path(src)
        if src.exists():
            dst = folder / f"picture_{i:02d}{src.suffix.lower() or '.png'}"
            shutil.copy(src, dst)
            out.append(dst)
    return out


def _question(user: str, schema: Type[BaseModel], pictures: list[Path]) -> str:
    q = user
    if pictures:
        names = ", ".join(p.name for p in pictures)
        q += (f"\n\nATTACHED PICTURES, in this order: {names}. They are files in your working folder: look at every one "
              "of them before you answer.")
    return q + schema_instruction(schema)


def _said(out: str) -> str:
    """The error messages in the program's json lines (not the echo of our own question)."""
    msgs = []
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        err = ev.get("error") if isinstance(ev.get("error"), dict) else None
        m = (err or {}).get("message") or (ev.get("message") if ev.get("type") == "error" else "") or \
            (ev.get("result") if ev.get("is_error") else "")
        if m and str(m) not in msgs:
            msgs.append(str(m))
    return " ".join(msgs)[:500]


class _CLIBrain(LLM):
    program = ""
    env_override = ""
    who = ""

    def __init__(self, config=None):
        super().__init__(config)
        self.blocked = ""          # set when the program says it is not signed in: then the next brain is used straight away

    def exe(self) -> Optional[str]:
        return shutil.which(os.environ.get(self.env_override, "") or self.program)

    def is_configured(self):
        if self.blocked:
            return False, self.blocked
        if self.exe():
            return True, "ok"
        return False, f"install the `{self.program}` command and sign in (or set {self.env_override} to its path)"

    def _fail(self, code: int, out: str) -> PluginError:
        low = out.lower()
        if any(h in low for h in SIGN_IN_HINTS):
            self.blocked = f"{self.who} is not signed in: run `{self.program}` once in a terminal and sign in"
            return PluginError(self.blocked)
        said = _said(out)
        if self.name == "codex_brain" and "not supported" in said.lower() and "model" in said.lower():
            return PluginError(f"Codex cannot use this model with your sign-in: {said} Choose another in Settings → AI brain "
                               "(the list there comes from Codex itself).")
        return PluginError(f"{self.who} stopped with exit {code}: {said or ' '.join(out.split())[-300:]}")

    async def ask_once(self, question: str, system: str, schema: Type[BaseModel], model: str, folder: Path,
                       pictures: list[Path]) -> tuple[str, Usage]:
        raise NotImplementedError

    async def generate_json(self, *, system: str, user: str, schema: Type[BaseModel], model: str,
                            images: Optional[list[Path]] = None, video: Optional[Path] = None,
                            max_tokens: int = 16000, meta: Optional[dict] = None):
        folder = _work_folder()
        try:
            pictures = _pictures(images, folder)
            question = _question(user, schema, pictures)
            usage = Usage()
            last = ""
            for attempt in range(2):
                text, u = await self.ask_once(question if attempt == 0 else question + "\n\n" + repair_prompt(last),
                                              system, schema, model, folder, pictures)
                usage.input_tokens += u.input_tokens
                usage.output_tokens += u.output_tokens
                usage.raw.update(u.raw)
                try:
                    return schema.model_validate(extract_json(text) if isinstance(text, str) else text), usage
                except Exception as exc:          # one more try, telling it what was wrong
                    last = str(exc)[:300]
            raise PluginError(f"{self.who}: the reply did not match the expected format: {last}")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class ClaudeCodeBrain(_CLIBrain):
    name = "claude_code_brain"
    program = "claude"
    env_override = "VG_CLAUDE"
    who = "Claude Code"
    description = "AI brain through your Claude subscription (the claude command on this computer)"
    licence = "your Claude plan's terms"

    def command(self, schema: Type[BaseModel], model: str, system: str, minimal: bool = False) -> list[str]:
        cmd = [self.exe() or self.program, "-p", "--output-format", "json"]
        if not minimal:
            cmd += ["--json-schema", json.dumps(schema.model_json_schema(), separators=(",", ":")),
                    "--system-prompt", system, "--tools", "Read", "--disallowedTools", "Bash", "Edit", "Write", "WebFetch",
                    "WebSearch", "--no-session-persistence", "--strict-mcp-config"]
        if model:
            cmd += ["--model", model]
        return cmd

    async def ask_once(self, question, system, schema, model, folder, pictures):
        cmd = self.command(schema, model, system)
        code, out = await _run(cmd, folder, question, 900)
        if code != 0 and ("unknown option" in out.lower() or "unexpected argument" in out.lower()):
            # an older Claude Code: ask again with only the basic options (the format is then asked for in the question)
            code, out = await _run(self.command(schema, model, system, minimal=True), folder,
                                   f"{system}\n\n{question}", 900)
        data: dict = {}
        for line in reversed(out.strip().splitlines()):
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    break
            except ValueError:
                continue
        if code != 0 or not data or data.get("is_error"):
            raise self._fail(code, out if not data else str(data.get("result") or out))
        u = data.get("usage") or {}
        usage = Usage(input_tokens=int(u.get("input_tokens") or 0), output_tokens=int(u.get("output_tokens") or 0),
                      raw={"subscription": "claude", "reported_usd": data.get("total_cost_usd"),
                           "model_used": ", ".join((data.get("modelUsage") or {}).keys())})
        answer = data.get("structured_output")
        return (answer if isinstance(answer, dict) else str(data.get("result") or "")), usage


class CodexBrain(_CLIBrain):
    name = "codex_brain"
    program = "codex"
    env_override = "VG_CODEX"
    who = "Codex"
    description = "AI brain through your ChatGPT subscription (the codex command on this computer)"
    licence = "your ChatGPT plan's terms"

    def command(self, folder: Path, model: str, pictures: list[Path], question: str) -> list[str]:
        cmd = [self.exe() or self.program, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--cd", str(folder), "--json"]
        for p in pictures:
            cmd += ["-i", str(p)]
        if model:
            cmd += ["-m", codex_slug(model)]
        return cmd + [question]

    async def ask_once(self, question, system, schema, model, folder, pictures):
        code, out = await _run(self.command(folder, model, pictures, f"{system}\n\n{question}"), folder, None, 900)
        last, usage = "", Usage(raw={"subscription": "chatgpt"})
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            item = ev.get("item") if isinstance(ev.get("item"), dict) else ev.get("msg") if isinstance(ev.get("msg"), dict) else {}
            if item.get("type") == "agent_message":
                last = str(item.get("text") or item.get("message") or last)
            u = ev.get("usage") if isinstance(ev.get("usage"), dict) else None
            if u:
                usage.input_tokens = int(u.get("input_tokens") or usage.input_tokens)
                usage.output_tokens = int(u.get("output_tokens") or usage.output_tokens)
        if code != 0 or not last:
            raise self._fail(code, out)
        return last, usage
