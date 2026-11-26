"""Coding agents through their command-line tools, for the 3D camera reference add-on.

Each run happens inside ONE locked work folder. The agent may read and edit files there and run ONE command (the free
plan check). It cannot fetch web pages or use other tools. The tool checks the result itself afterwards.

  claude_code   Claude Code:  claude -p (instructions on standard input) --output-format json
                --permission-mode acceptEdits --allowedTools Read Edit Write Glob Grep "Bash(<check command>:*)"
                --max-budget-usd <cap> --no-session-persistence --strict-mcp-config
                It reports what it spent (total_cost_usd), and stops at the cap.
  codex         Codex:        codex exec --skip-git-repo-check --sandbox workspace-write --cd <folder> --json <instructions>
                The sandbox lets it write only inside the folder. Codex does not report a price.
                These flags are from Codex's documentation as known when this was written; check them with
                `codex exec --help` if a run fails.

Set VG_CLAUDE or VG_CODEX to use a program that is not on the PATH.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Optional

from ..llm.cli_models import codex_slug
from ..base import AgentResult, AgentTask, PluginError, SceneAgent


async def _run(cmd: list[str], cwd, stdin: Optional[str], timeout_s: int) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(cwd), stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        raise PluginError(f"{cmd[0]} could not start: {exc}") from exc
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin is not None else None), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        raise PluginError(f"{os.path.basename(cmd[0])} took longer than {timeout_s} s and was stopped")
    return proc.returncode or 0, (out or b"").decode(errors="replace")


class _CLIAgent(SceneAgent):
    program = ""
    env_override = ""

    def exe(self) -> Optional[str]:
        return shutil.which(os.environ.get(self.env_override, "") or self.program)

    def is_configured(self):
        if self.exe():
            return True, "ok"
        return False, f"install the `{self.program}` command (or set {self.env_override} to its path)"


class ClaudeCodeAgent(_CLIAgent):
    name = "claude_code"
    program = "claude"
    env_override = "VG_CLAUDE"
    description = "Claude Code (the claude command) fixes 3D plans in a locked folder"
    licence = "commercial (Anthropic terms)"

    def command(self, task: AgentTask) -> list[str]:
        tools = ["Read", "Glob", "Grep", "Edit", "Write"]
        if task.allowed_command:
            tools.append(f"Bash({task.allowed_command}:*)")
        return [self.exe() or self.program, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                "--allowedTools", *tools, "--disallowedTools", "WebFetch", "WebSearch",
                "--max-budget-usd", f"{max(task.max_usd, 0.01):.2f}", "--no-session-persistence", "--strict-mcp-config"] + \
            (["--model", task.model] if task.model else []) + (["--effort", task.effort] if task.effort else [])

    async def run(self, task: AgentTask) -> AgentResult:
        code, out = await _run(self.command(task), task.folder, task.instructions, task.timeout_s)
        data: dict = {}
        for line in reversed(out.strip().splitlines()):           # the json result is the last line
            try:
                data = json.loads(line)
                break
            except ValueError:
                continue
        cost = float(data.get("total_cost_usd") or 0)
        if not data:
            raise PluginError(f"Claude Code gave no result (exit {code}): {out.strip()[-300:]}")
        ok = code == 0 and not data.get("is_error") and data.get("subtype", "success") == "success"
        summary = str(data.get("result") or data.get("subtype") or "")
        return AgentResult(ok=ok, summary=summary.strip()[:1500], cost_usd=cost, raw={k: data.get(k) for k in ("subtype", "num_turns", "duration_ms")})


class CodexAgent(_CLIAgent):
    name = "codex"
    program = "codex"
    env_override = "VG_CODEX"
    description = "Codex (the codex command) fixes or checks 3D plans in a locked folder"
    licence = "commercial (OpenAI terms)"

    def command(self, task: AgentTask) -> list[str]:
        return [self.exe() or self.program, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
                "--cd", str(task.folder), "--json"] + (["-m", codex_slug(task.model)] if task.model else []) + \
            (["-c", f'model_reasoning_effort="{task.effort}"'] if task.effort else []) + [task.instructions]

    async def run(self, task: AgentTask) -> AgentResult:
        code, out = await _run(self.command(task), task.folder, None, task.timeout_s)
        last = ""
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            item = ev.get("item") if isinstance(ev.get("item"), dict) else ev.get("msg") if isinstance(ev.get("msg"), dict) else {}
            if item.get("type") == "agent_message":
                last = str(item.get("text") or item.get("message") or last)
        if code != 0 and not last:
            raise PluginError(f"Codex stopped with exit {code}: {out.strip()[-300:]}")
        return AgentResult(ok=code == 0, summary=last.strip()[:1500], cost_usd=0.0, raw={"note": "Codex does not report a price"})
