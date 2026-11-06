"""Model catalogue: packaged defaults merged with the user's edited copy."""
from __future__ import annotations

from datetime import date
from importlib import resources
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from .config import vg_home

JOBS = ("video", "image", "voice", "avatar", "lipsync", "music", "sfx", "llm", "transcribe")


class Price(BaseModel):
    unit: str = "second"     # second | image | 1k_chars | minute | request | 1m_tokens
    usd: float = 0
    usd_in: float = 0
    usd_out: float = 0


class Timing(BaseModel):
    queue_s: float = 0
    per_output_s: float = 1


class CatalogEntry(BaseModel):
    id: str
    job: str = ""
    plugin: str
    model: str = ""
    vendor: str = ""
    enabled: bool = True
    strengths: dict[str, int] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    quality: int = 3
    price: Price = Field(default_factory=Price)
    time: Timing = Field(default_factory=Timing)
    licence: str = ""
    note: str = ""                          # one line shown beside the model in a list of choices
    pricing_url: str = ""
    last_checked: str = ""
    live_price: Optional[float] = None     # filled by price_lookup when available
    # model-specific API details so a fix needs no code: image_field, end_image_field, durations, fields, resolution
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def unit_price(self) -> float:
        return self.live_price if self.live_price is not None else self.price.usd

    @property
    def is_free(self) -> bool:
        return self.vendor == "local"

    def billed_seconds(self, seconds: float) -> float:
        """The length the vendor really makes (and charges for): the next length the model accepts.
        A 4 s clip on a model that only makes 5 / 10 / 15 s is billed as 5 s; the final file is still cut to 4 s."""
        allowed = sorted(float(d) for d in (self.params.get("durations") or []))
        if not allowed:
            return seconds
        return next((d for d in allowed if d >= seconds - 1e-6), allowed[-1])

    def strength(self, shot_type: str) -> int:
        return self.strengths.get(shot_type, self.strengths.get("other", self.quality))

    def days_since_checked(self) -> int:
        try:
            return (date.today() - date.fromisoformat(self.last_checked)).days
        except ValueError:
            return 9999


class Catalog(BaseModel):
    entries: list[CatalogEntry] = Field(default_factory=list)

    @classmethod
    def load(cls) -> "Catalog":
        base = yaml.safe_load(resources.files("video_generator.data").joinpath("catalog.yaml").read_text())
        user_path = vg_home() / "catalog.yaml"
        user = yaml.safe_load(user_path.read_text()) if user_path.exists() else {}
        merged: dict[str, dict] = {}
        for src in (base or {}, user or {}):
            for job, items in src.items():
                for it in items or []:
                    it = dict(it)
                    it["job"] = job
                    merged[it["id"]] = {**merged.get(it["id"], {}), **it}
        return cls(entries=[CatalogEntry.model_validate(v) for v in merged.values()])

    def save_user_override(self, entry: CatalogEntry) -> None:
        path = vg_home() / "catalog.yaml"
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        data = data or {}
        items = [i for i in data.get(entry.job, []) if i.get("id") != entry.id]
        items.append(entry.model_dump(exclude={"job", "live_price"}))
        data[entry.job] = items
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def get(self, entry_id: str) -> CatalogEntry:
        for e in self.entries:
            if e.id == entry_id:
                return e
        raise KeyError(entry_id)

    def for_job(self, job: str) -> list[CatalogEntry]:
        return [e for e in self.entries if e.job == job]

    def stale(self, days: int = 30) -> list[CatalogEntry]:
        return [e for e in self.entries if not e.is_free and e.days_since_checked() > days]


def load_vendors() -> list[dict]:
    return yaml.safe_load(resources.files("video_generator.data").joinpath("vendors.yaml").read_text())
