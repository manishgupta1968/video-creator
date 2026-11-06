"""User configuration: ~/.video-generator (override with VG_HOME).

Files there:
  config.yaml   - preferences (AI brain, budget, routing)
  .env          - API keys (written by the GUI Settings page; chmod 600)
  catalog.yaml  - your edited copy of the model catalogue (optional)
  projects/     - one folder per project
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field

from . import policy as policy_mod
from .policy import Policy


def vg_home() -> Path:
    home = Path(os.environ.get("VG_HOME", Path.home() / ".video-generator"))
    home.mkdir(parents=True, exist_ok=True)
    return home


class LLMConfig(BaseModel):
    default: str = "auto"                 # auto | anthropic | openai | gemini | fake_llm
    models: dict[str, str] = Field(default_factory=lambda: {
        "anthropic": "claude-opus-5-5",
        "openai": "gpt-5",
        "gemini": "gemini-2.5-pro",
        "fake_llm": "rules",
    })
    per_task: dict[str, str] = Field(default_factory=dict)  # task -> plugin
    # the model chosen for a KIND of work, as "plugin:model" (for example "openai:gpt-5-mini"). Kinds: default (planning and
    # scripts), review (the Review Agent), simple (explain, photo choice, commands). Empty = the plugin's usual model.
    per_task_model: dict[str, str] = Field(default_factory=dict)
    reviewer: str = "same"                # same | anthropic | openai | gemini | fake_llm
    anthropic_effort: str = "medium"
    anthropic_fallbacks: bool = True


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    budget_usd: float = 50
    quality_mode: str = "balanced"        # best | balanced | budget | free
    disabled_models: list[str] = Field(default_factory=list)
    preferred_models: dict[str, str] = Field(default_factory=dict)  # shot_type/job -> catalog id
    projects_dir: str = ""
    max_parallel_jobs: int = 4
    user_name: str = ""
    policy: Policy = Field(default_factory=Policy)     # every quality threshold in one place: see `vg policy`

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls) -> "Config":
        path = vg_home() / "config.yaml"
        data: dict[str, Any] = {}
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
        cfg = cls.model_validate(data)
        policy_mod.use(cfg.policy)
        load_env()
        return cfg

    def save(self) -> None:
        (vg_home() / "config.yaml").write_text(yaml.safe_dump(self.model_dump(), sort_keys=False))

    @property
    def projects_path(self) -> Path:
        p = Path(self.projects_dir) if self.projects_dir else vg_home() / "projects"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def set_path(self, dotted: str, value: Any) -> None:
        obj: Any = self
        parts = dotted.split(".")
        for part in parts[:-1]:
            obj = getattr(obj, part) if not isinstance(obj, dict) else obj[part]
        last = parts[-1]
        if isinstance(obj, dict):
            obj[last] = value
        else:
            current = getattr(obj, last)
            if isinstance(current, bool):
                value = str(value).lower() in ("1", "true", "yes", "on")
            elif isinstance(current, (int, float)) and not isinstance(current, bool):
                value = type(current)(value)
            setattr(obj, last, value)


ENV_FILE_KEYS: set[str] = set()


def load_env() -> None:
    """Load ~/.video-generator/.env and ./.env without overriding real env vars."""
    for path in (vg_home() / ".env", Path.cwd() / ".env"):
        if path.exists():
            for k, v in dotenv_values(path).items():
                if v is not None and not os.environ.get(k):
                    os.environ[k] = v
                    ENV_FILE_KEYS.add(k)


def save_key(name: str, value: str) -> None:
    """Store an API key in ~/.video-generator/.env (owner-only permissions)."""
    path = vg_home() / ".env"
    lines: dict[str, str] = {}
    if path.exists():
        lines = {k: v for k, v in dotenv_values(path).items() if v is not None}
    if value:
        lines[name] = value
        os.environ[name] = value
    else:
        lines.pop(name, None)
        os.environ.pop(name, None)
    path.write_text("".join(f'{k}="{v}"\n' for k, v in lines.items()))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def has_env(*names: str) -> bool:
    return all(bool(os.environ.get(n)) for n in names)
