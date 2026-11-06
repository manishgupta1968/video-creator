"""Core data model for video-generator.

Hierarchy:  Project -> Node tree (goal nodes, clip leaves) -> Takes / Reviews
Context:    ContextItems scoped to project / node subtree / single clip
Links:      Dependencies between clips (continues_from, same_location, ...)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- enums
class NodeKind(str, Enum):
    goal = "goal"            # has children
    clip = "clip"            # AI-generated clip (leaf)
    slides = "slides"        # user slides (leaf)
    user_clip = "user_clip"  # user's own footage (leaf)


class ShotType(str, Enum):
    talking_head = "talking_head"          # presenter / digital twin to camera
    dialogue_scene = "dialogue_scene"      # people speaking inside a scene
    human_motion = "human_motion"          # people moving, hands, objects
    wildlife = "wildlife"                  # animals, nature
    landscape = "landscape"                # scenery, establishing, effects
    product = "product"                    # product hero shot
    other = "other"


class NodeStatus(str, Enum):
    draft = "draft"            # being planned
    ready = "ready"            # script ready, not generated
    waiting = "waiting"        # waiting for an upstream clip
    queued = "queued"
    generating = "generating"
    needs_pick = "needs_pick"  # takes ready, user must pick
    done = "done"
    stale = "stale"            # upstream changed; needs re-make
    failed = "failed"


class ContextType(str, Enum):
    actor = "actor"
    object = "object"
    entity = "entity"      # brand, logo, mascot, product name
    location = "location"
    style = "style"
    audio = "audio"
    text = "text"
    media = "media"        # slides / footage to include


class ContextRole(str, Enum):
    must_appear = "must_appear"
    look_reference = "look_reference"
    start_frame = "start_frame"
    end_frame = "end_frame"
    voice = "voice"
    sound = "sound"
    music_reference = "music_reference"
    knowledge = "knowledge"
    include = "include"


class DependencyType(str, Enum):
    continues_from = "continues_from"
    same_location = "same_location"
    actor_state = "actor_state"
    audio_carry = "audio_carry"
    reference = "reference"
    order_only = "order_only"


class EstimateBasis(str, Enum):
    goal = "goal"
    script = "script"
    actual = "actual"


# --------------------------------------------------------------------------- context
class Consent(BaseModel):
    confirmed: bool = False
    statement: Literal["self", "permission", ""] = ""
    confirmed_by: str = ""
    confirmed_at: str = ""
    files: list[str] = Field(default_factory=list)


class ActorDetails(BaseModel):
    kind: Literal["ai_person", "real_person", "digital_twin", "animal", "product"] = "ai_person"
    description: str = ""          # appearance in words
    clothing: str = ""             # default outfit
    behaviour: str = ""            # mannerisms, body language, speaking style
    voice_description: str = ""    # e.g. "deep, warm, Indian English, slow"
    # voice profile: the planner fills it, the user can edit it; "" = not decided (guessed from the description)
    voice_gender: str = ""         # male | female | neutral
    voice_age: str = ""            # child | teen | young | adult | older
    voice_pitch: str = ""          # low | medium | high
    voice_pace: str = ""           # slow | normal | fast
    voice_accent: str = ""         # e.g. "Indian English"; defaults to the project language
    voice_name: str = ""           # the vendor's name for the chosen voice (shown to the user)
    voice_note: str = ""           # why this voice was chosen / a warning when the match is weak
    voice_sample: Optional[str] = None
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None
    speaking_wpm: Optional[int] = None
    props: str = ""
    reference_sheet: list[str] = Field(default_factory=list)  # generated images
    avatar_id: Optional[str] = None


class ContextItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ctx_"))
    type: ContextType = ContextType.text
    title: str = ""
    text: str = ""
    files: list[str] = Field(default_factory=list)   # project-relative paths
    role: ContextRole = ContextRole.knowledge
    scope: str = "project"                            # project | node:<id> | clip:<id>
    actor: Optional[ActorDetails] = None
    consent: Consent = Field(default_factory=Consent)
    analysis: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)

    @property
    def needs_consent(self) -> bool:
        if self.type != ContextType.actor or not self.actor:
            return False
        has_real = bool(self.files) or bool(self.actor.voice_sample)
        return has_real and self.actor.kind in ("real_person", "digital_twin")


# --------------------------------------------------------------------------- script
class ActorInShot(BaseModel):
    actor_id: str
    clothing: str = ""
    behaviour: str = ""


class DialogueLine(BaseModel):
    speaker: str = ""      # actor id or "narrator"
    text: str = ""
    emotion: str = ""
    fixed: bool = False    # must be spoken exactly as written: a quote, a slogan, text given in the goal. Never cut or reworded.


class ClipScript(BaseModel):
    shot_type: ShotType = ShotType.other
    visual: str = ""                    # what we see (prompt basis)
    action_beats: list[str] = Field(default_factory=list)
    camera: str = ""
    actors_in_shot: list[ActorInShot] = Field(default_factory=list)
    dialogue: list[DialogueLine] = Field(default_factory=list)
    narration: str = ""
    narration_fixed: bool = False       # the narration must be spoken exactly as written
    on_camera_speech: bool = False
    sound_notes: str = ""               # sound design: ambience, effects tied to the action, or "silence"
    motion: str = ""                    # what must move: face (only face and head) | body | scene; "" = not decided
    start_state: str = ""               # how the clip begins: pose, place, time of day, framing, clothing, light
    end_state: str = ""                 # how it ends (the next clip that continues starts from this)
    negative: str = ""
    target_seconds: Optional[float] = None


# --------------------------------------------------------------------------- estimates
class DurationEstimate(BaseModel):
    min_s: float = 0
    likely_s: float = 0
    max_s: float = 0
    basis: EstimateBasis = EstimateBasis.goal
    explain: str = ""


class CostLine(BaseModel):
    item: str
    calc: str
    cost: float


class CostEstimate(BaseModel):
    min_usd: float = 0
    likely_usd: float = 0
    max_usd: float = 0
    lines: list[CostLine] = Field(default_factory=list)
    model: str = ""
    basis: EstimateBasis = EstimateBasis.goal
    actual_usd: Optional[float] = None


class TimeEstimate(BaseModel):
    likely_s: float = 0
    explain: str = ""


# --------------------------------------------------------------------------- takes & reviews
class ReviewIssue(BaseModel):
    check: str
    text: str
    at_s: Optional[float] = None
    frame: Optional[str] = None
    severity: Literal["info", "minor", "major"] = "minor"


class ReviewSuggestion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sg_"))
    text: str
    accepted: bool = True


class Review(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rv_"))
    target: str                        # take id or node id
    verdict: Literal["meets_goal", "minor_issues", "does_not_meet_goal"] = "minor_issues"
    scores: dict[str, int] = Field(default_factory=dict)
    issues: list[ReviewIssue] = Field(default_factory=list)
    suggestions: list[ReviewSuggestion] = Field(default_factory=list)
    summary: str = ""
    reviewer_model: str = ""
    cost_usd: float = 0
    measurements: dict[str, float] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class Take(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tk_"))
    version: int = 1
    index: int = 1
    video: Optional[str] = None
    keyframe: Optional[str] = None
    model: str = ""
    cost_usd: float = 0
    seconds: float = 0
    quality: dict[str, float] = Field(default_factory=dict)
    review_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class ClipVersion(BaseModel):
    version: int
    script: ClipScript
    feedback: str = ""                  # merged feedback that produced it
    created_at: str = Field(default_factory=now_iso)


# --------------------------------------------------------------------------- tree
class Node(BaseModel):
    id: str = Field(default_factory=lambda: new_id("n_"))
    kind: NodeKind = NodeKind.goal
    title: str = ""
    goal: str = ""
    children: list["Node"] = Field(default_factory=list)
    target_seconds: Optional[float] = None
    style_overrides: dict[str, str] = Field(default_factory=dict)
    context_add: list[str] = Field(default_factory=list)       # context ids scoped here
    context_off: list[str] = Field(default_factory=list)       # inherited ids switched off
    context_override: dict[str, str] = Field(default_factory=dict)  # inherited id -> replacement id
    script: Optional[ClipScript] = None
    media: Optional[str] = None                 # slides/user clip path
    provider_override: Optional[str] = None
    takes_override: Optional[int] = None
    transition_in: str = "cut"
    status: NodeStatus = NodeStatus.draft
    duration: DurationEstimate = Field(default_factory=DurationEstimate)
    cost: CostEstimate = Field(default_factory=CostEstimate)
    time: TimeEstimate = Field(default_factory=TimeEstimate)
    version: int = 1
    versions: list[ClipVersion] = Field(default_factory=list)
    takes: list[Take] = Field(default_factory=list)
    chosen_take: Optional[str] = None
    voice_audio: Optional[str] = None
    voice_seconds: Optional[float] = None
    output: Optional[str] = None                # assembled clip / node video
    input_hash: str = ""
    warnings: list[str] = Field(default_factory=list)
    needs_split: bool = False       # computed: the clip needs more than any single route can do (see estimate.plan_clip)
    review_enabled: bool = True
    locked: bool = False            # "keep this clip as it is": its length is never changed by resizing or optimizing
    quality_mode: Optional[Literal["best", "balanced", "budget", "free"]] = None   # this part's own quality; None = the part above, then the video

    @property
    def is_leaf(self) -> bool:
        return self.kind != NodeKind.goal


Node.model_rebuild()


class Dependency(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dp_"))
    from_id: str
    to_id: str
    type: DependencyType = DependencyType.order_only
    source: Literal["ai", "rule", "user"] = "user"
    note: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- project
class Settings(BaseModel):
    # auto = no length was asked for: the plan is as short as the story allows (target_seconds then follows the plan);
    # fixed = target_seconds is the length asked for. Projects made before this setting existed are "fixed".
    length_mode: Literal["auto", "fixed"] = "fixed"
    target_seconds: float = 60
    aspect: str = "16:9"
    resolution: str = "1080p"
    fps: int = 24
    format: Literal["mp4", "mov"] = "mp4"
    budget_usd: float = 50
    takes_people: int = 3
    takes_other: int = 1
    language: str = "en"
    default_wpm: int = 150
    subtitles: bool = True
    auto_pick: bool = False
    review_enabled: bool = True
    music: bool = True
    ambience: bool = True         # natural sound (wind, room tone, footsteps...) for clips that have none of their own
    fill: Literal["blur", "black", "crop"] = "blur"   # what to put around a picture that is not the video's shape
    auto_photo: bool = True       # find a real photo by itself when none is supplied (animals, objects, places)
    quality_mode: Literal["best", "balanced", "budget", "free"] = "balanced"


class Style(BaseModel):
    look: str = ""
    colour: str = ""
    mood: str = ""
    notes: str = ""


class RunState(BaseModel):
    mode: Literal["idle", "all", "clip", "next", "continue"] = "idle"
    status: Literal["idle", "running", "paused", "stopping", "finished", "failed"] = "idle"
    targets: list[str] = Field(default_factory=list)
    message: str = ""
    started_at: str = ""
    spent_usd: float = 0


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("p_"))
    name: str = "Untitled video"
    goal: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    settings: Settings = Field(default_factory=Settings)
    style: Style = Field(default_factory=Style)
    root: Node = Field(default_factory=lambda: Node(kind=NodeKind.goal, title="Video"))
    context: list[ContextItem] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    run: RunState = Field(default_factory=RunState)
    music_advice: str = ""        # the planner's suggestion: none | subtle | full, mood, genre
    final_output: Optional[str] = None
    final_hash: str = ""
    final_notes: list[str] = Field(default_factory=list)   # what could not be added to the final video, and why (shown to the user)
    final_review_id: Optional[str] = None
