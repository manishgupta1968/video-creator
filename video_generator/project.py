"""Project storage: one folder per project, with autosave and undo history.

projects/<id>/
  project.json        current state
  history/NNNN.json   snapshots for undo/redo
  inputs/             files the user added
  cast/<actor>/       reference sheets, cleaned voice samples
  clips/<node>/       voice, keyframes, takes, outputs, review frames
  output/             final video, subtitles
  ledger.jsonl        every paid call: estimated vs actual cost and time
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path
from typing import Optional

from .config import Config
from .models import Project, now_iso

_LOCK = threading.RLock()
MAX_HISTORY = 100
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")


def slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "project"


class ProjectStore:
    root: Path = Path()

    @classmethod
    def init(cls, config: Optional[Config] = None) -> None:
        cls.root = (config or Config.load()).projects_path

    @classmethod
    def path_for(cls, project_id: str) -> Path:
        if not SAFE_ID.match(project_id or ""):
            raise FileNotFoundError(f"invalid project id: {project_id!r}")
        if not cls.root or str(cls.root) == ".":
            cls.init()
        return cls.root / project_id

    # ------------------------------------------------------------- crud
    @classmethod
    def create(cls, project: Project) -> Project:
        base = slug(project.name or project.goal)
        pid = base
        i = 2
        while cls.path_for(pid).exists():
            pid = f"{base}-{i}"
            i += 1
        project.id = pid
        d = cls.path_for(pid)
        for sub in ("inputs", "cast", "clips", "output", "history"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        cls.save(project, snapshot=True)
        return project

    @classmethod
    def load(cls, project_id: str) -> Project:
        p = cls.path_for(project_id) / "project.json"
        if not p.exists():
            raise FileNotFoundError(f"project not found: {project_id}")
        return Project.model_validate_json(p.read_text())

    @classmethod
    def save(cls, project: Project, snapshot: bool = True) -> None:
        with _LOCK:
            project.updated_at = now_iso()
            d = cls.path_for(project.id)
            d.mkdir(parents=True, exist_ok=True)
            data = project.model_dump_json(indent=1)
            tmp = d / "project.json.tmp"
            tmp.write_text(data)
            tmp.replace(d / "project.json")
            if snapshot:
                cls._snapshot(project.id, data)

    @classmethod
    def list(cls) -> list[dict]:
        if not cls.root or str(cls.root) == ".":
            cls.init()
        out = []
        for d in sorted(cls.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True) if cls.root.exists() else []:
            pj = d / "project.json"
            if pj.exists():
                try:
                    data = json.loads(pj.read_text())
                    out.append({"id": data["id"], "name": data.get("name", ""), "goal": data.get("goal", ""),
                                "updated_at": data.get("updated_at", ""),
                                "final_output": data.get("final_output")})
                except Exception:
                    continue
        return out

    @classmethod
    def delete(cls, project_id: str) -> None:
        shutil.rmtree(cls.path_for(project_id), ignore_errors=True)

    # ------------------------------------------------------------- undo / redo
    @classmethod
    def _hist(cls, project_id: str) -> Path:
        h = cls.path_for(project_id) / "history"
        h.mkdir(parents=True, exist_ok=True)
        return h

    @classmethod
    def _pointer(cls, project_id: str) -> int:
        f = cls._hist(project_id) / "pointer"
        return int(f.read_text()) if f.exists() else -1

    @classmethod
    def _set_pointer(cls, project_id: str, i: int) -> None:
        (cls._hist(project_id) / "pointer").write_text(str(i))

    @classmethod
    def _snapshot(cls, project_id: str, data: str) -> None:
        h = cls._hist(project_id)
        ptr = cls._pointer(project_id)
        snaps = sorted(h.glob("*.json"))
        # drop redo branch
        for s in snaps:
            if int(s.stem) > ptr:
                s.unlink()
        last = h / f"{ptr:05d}.json"
        if last.exists() and last.read_text() == data:
            return
        ptr += 1
        (h / f"{ptr:05d}.json").write_text(data)
        cls._set_pointer(project_id, ptr)
        snaps = sorted(h.glob("*.json"))
        for s in snaps[:-MAX_HISTORY]:
            s.unlink()

    @classmethod
    def undo(cls, project_id: str) -> Optional[Project]:
        return cls._step(project_id, -1)

    @classmethod
    def redo(cls, project_id: str) -> Optional[Project]:
        return cls._step(project_id, +1)

    @classmethod
    def _step(cls, project_id: str, delta: int) -> Optional[Project]:
        with _LOCK:
            ptr = cls._pointer(project_id) + delta
            f = cls._hist(project_id) / f"{ptr:05d}.json"
            if ptr < 0 or not f.exists():
                return None
            cls._set_pointer(project_id, ptr)
            project = Project.model_validate_json(f.read_text())
            current = cls.load(project_id)
            # never undo money already spent or files already produced
            project.run = current.run
            cls.save(project, snapshot=False)
            return project

    # ------------------------------------------------------------- ledger
    @classmethod
    def ledger_add(cls, project_id: str, row: dict) -> None:
        with _LOCK:
            row = {"at": now_iso(), **row}
            with open(cls.path_for(project_id) / "ledger.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")

    @classmethod
    def ledger(cls, project_id: str) -> list[dict]:
        p = cls.path_for(project_id) / "ledger.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
