"""The AI brain through your subscription: Claude Code or Codex run on this computer. Real programs are replaced by
small stand-ins, so the commands, the answers, the fall-back and the prices are tested without using a subscription."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel
from PIL import Image

from video_generator.models_list import price_text
from video_generator.plugins.base import PluginError
from video_generator.plugins.llm.cli_brain import ClaudeCodeBrain, CodexBrain
from video_generator.registry import BRAIN_ORDER


class Answer(BaseModel):
    title: str
    count: int


def stand_in(tmp_path, name, body):
    exe = tmp_path / name
    exe.write_text(f"#!{sys.executable}\n" + body)
    exe.chmod(0o755)
    return exe


CLAUDE = """import json, os, sys, pathlib
args = sys.argv[1:]
question = sys.stdin.read()
log = pathlib.Path(os.environ["STAND_IN_LOG"])
log.write_text(json.dumps({"args": args, "question": question, "cwd": os.getcwd(), "files": sorted(os.listdir("."))}))
mode = os.environ.get("STAND_IN_MODE", "structured")
if mode == "old" and "--json-schema" in args:
    print("error: unknown option '--json-schema'"); sys.exit(1)
if mode == "signed_out":
    print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"})); sys.exit(1)
out = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.03,
       "usage": {"input_tokens": 1200, "output_tokens": 80}}
if mode == "structured":
    out["structured_output"] = {"title": "Lion chase", "count": 3}
else:
    out["result"] = 'Here it is: {"title": "Lion chase", "count": 3}'
print(json.dumps(out))
"""

CODEX = """import json, os, sys, pathlib
args = sys.argv[1:]
log = pathlib.Path(os.environ["STAND_IN_LOG"])
log.write_text(json.dumps({"args": args}))
print(json.dumps({"type": "thread.started"}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": '{"title": "Lion chase", "count": 3}'}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 900, "output_tokens": 40}}))
"""


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "stand_in_log.json"
    monkeypatch.setenv("STAND_IN_LOG", str(path))
    return path


def picture(tmp_path, name="frame.png"):
    p = tmp_path / name
    Image.new("RGB", (32, 18), (200, 30, 30)).save(p)
    return p


def test_claude_code_answers_in_the_fixed_format_and_may_only_read(tmp_path, monkeypatch, log):
    monkeypatch.setenv("VG_CLAUDE", str(stand_in(tmp_path, "claude", CLAUDE)))
    brain = ClaudeCodeBrain()
    assert brain.is_configured() == (True, "ok")
    result, usage = asyncio.run(brain.generate_json(system="You plan videos.", user="Plan a lion chase.", schema=Answer,
                                                    model="sonnet", images=[picture(tmp_path)]))
    assert result == Answer(title="Lion chase", count=3) and usage.input_tokens == 1200
    seen = json.loads(log.read_text())
    args = seen["args"]
    assert args[:3] == ["-p", "--output-format", "json"]
    assert json.loads(args[args.index("--json-schema") + 1])["properties"]["count"]["type"] == "integer"
    assert args[args.index("--system-prompt") + 1] == "You plan videos."
    assert args[args.index("--tools") + 1] == "Read" and "Bash" in args and "WebFetch" in args
    assert args[args.index("--model") + 1] == "sonnet"
    assert seen["files"] == ["picture_01.png"] and "picture_01.png" in seen["question"]
    assert not Path(seen["cwd"]).exists()                       # the work folder is cleaned up


def test_a_plain_text_answer_and_an_older_claude_code_both_work(tmp_path, monkeypatch, log):
    monkeypatch.setenv("VG_CLAUDE", str(stand_in(tmp_path, "claude", CLAUDE)))
    monkeypatch.setenv("STAND_IN_MODE", "text")
    assert asyncio.run(ClaudeCodeBrain().generate_json(system="s", user="u", schema=Answer, model=""))[0].count == 3
    monkeypatch.setenv("STAND_IN_MODE", "old")
    result, _ = asyncio.run(ClaudeCodeBrain().generate_json(system="You plan videos.", user="u", schema=Answer, model=""))
    assert result.title == "Lion chase"
    seen = json.loads(log.read_text())
    assert "--json-schema" not in seen["args"] and seen["question"].startswith("You plan videos.")


def test_a_signed_out_claude_code_steps_aside_for_the_next_brain(tmp_path, monkeypatch, log, svc):
    monkeypatch.setenv("VG_CLAUDE", str(stand_in(tmp_path, "claude", CLAUDE)))
    monkeypatch.setenv("STAND_IN_MODE", "signed_out")
    svc.reload()
    assert svc.reg.llm_plugin_name("default") == "claude_code_brain"
    brain = svc.reg.plugin("claude_code_brain")
    with pytest.raises(PluginError, match="not signed in"):
        asyncio.run(brain.generate_json(system="s", user="u", schema=Answer, model=""))
    ok, why = brain.is_configured()
    assert not ok and "run `claude` once" in why
    assert svc.reg.llm_plugin_name("default") != "claude_code_brain"    # the next connected brain answers at once


def test_codex_answers_with_pictures_in_a_read_only_sandbox(tmp_path, monkeypatch, log):
    monkeypatch.setenv("VG_CODEX", str(stand_in(tmp_path, "codex", CODEX)))
    result, usage = asyncio.run(CodexBrain().generate_json(system="You plan videos.", user="Plan it.", schema=Answer,
                                                          model="", images=[picture(tmp_path)]))
    assert result.count == 3 and usage.output_tokens == 40
    args = json.loads(log.read_text())["args"]
    assert args[:5] == ["exec", "--skip-git-repo-check", "--sandbox", "read-only", "--cd"] and "--json" in args
    assert Path(args[args.index("-i") + 1]).name == "picture_01.png"
    assert args[-1].startswith("You plan videos.") and "Respond with ONLY a JSON object" in args[-1]


def test_automatic_brain_prefers_your_subscriptions_claude_code_first(tmp_path, monkeypatch, svc):
    assert BRAIN_ORDER[:2] == ("claude_code_brain", "codex_brain")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    svc.reload()
    assert svc.reg.llm_plugin_name("default") == "anthropic"           # no subscription tool installed
    monkeypatch.setenv("VG_CODEX", str(stand_in(tmp_path, "codex", CODEX)))
    svc.reload()
    assert svc.reg.llm_plugin_name("default") == "codex_brain"
    monkeypatch.setenv("VG_CLAUDE", str(stand_in(tmp_path, "claude", CLAUDE)))
    svc.reload()
    assert svc.reg.llm_plugin_name("default") == "claude_code_brain"
    assert svc.reg.llm_fallback_order("default")[:3] == ["claude_code_brain", "codex_brain", "anthropic"]
    svc.config.llm.default = "codex_brain"                             # you can choose Codex instead
    assert svc.reg.llm_plugin_name("default") == "codex_brain"


def test_subscription_brains_cost_nothing_per_call(svc, monkeypatch, tmp_path, log):
    monkeypatch.setenv("VG_CLAUDE", str(stand_in(tmp_path, "claude", CLAUDE)))
    svc.reload()
    row = svc.catalog.get("claude_code_subscription")
    assert price_text(row) == "your subscription (no per-call cost)"
    assert svc.reg.llm_entry("default").id == "claude_code_subscription"
    asyncio.run(svc.brain.ask("photo_query", "Find a lion photo.", Answer, {}))
    assert svc.brain.last_usage.cost_usd == 0 and svc.brain.last_usage.raw["plugin"] == "claude_code_brain"
    rows = {r["id"]: r for r in svc.model_rows()}
    assert rows["claude_code_subscription"]["usable"] and rows["claude_code_subscription"]["draft_cost_usd"] == 0
    assert not rows["codex_subscription"]["usable"] and "install the `codex` command" in rows["codex_subscription"]["why_not"]
