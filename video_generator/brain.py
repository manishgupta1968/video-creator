"""The AI brain: vendor-neutral tasks built on the LLM plugin interface.

Every task sends the same prompt template to whichever LLM plugin is
configured (Anthropic, OpenAI, Gemini, or the offline rules engine) and
validates the answer against the same pydantic schema.
"""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Literal, Optional, Type

from pydantic import BaseModel, Field

from .context import effective_context, summarize_for_llm
from .models import (ActorInShot, ClipScript, ContextType, DialogueLine, Node, Project, ShotType)
from .plugins.base import PluginError, Usage
from .registry import Registry
from . import routes as routes_mod
from .tree import ancestors, numbering, outline, walk

SHOT_TYPES = [s.value for s in ShotType]


# =========================================================== response schemas
class ActorDraft(BaseModel):
    name: str
    kind: Literal["ai_person", "real_person", "digital_twin", "animal", "product"] = "ai_person"
    description: str = ""
    clothing: str = ""
    behaviour: str = ""
    voice_description: str = ""
    # voice profile for every speaker (people of any age, animals, mascots, robots, the narrator)
    voice_gender: str = ""            # male | female | neutral
    voice_age: str = ""               # child | teen | young | adult | older
    voice_pitch: str = ""             # low | medium | high
    voice_pace: str = ""              # slow | normal | fast
    voice_accent: str = ""


class ClipDraft(BaseModel):
    title: str
    goal: str
    seconds: float = 6


class PartDraft(BaseModel):
    title: str
    goal: str
    seconds: float = 20
    clips: list[ClipDraft] = Field(default_factory=list)


class StyleDraft(BaseModel):
    look: str = ""
    colour: str = ""
    mood: str = ""


class ProjectDraft(BaseModel):
    title: str
    style: StyleDraft = Field(default_factory=StyleDraft)
    actors: list[ActorDraft] = Field(default_factory=list)
    parts: list[PartDraft] = Field(default_factory=list)
    music_advice: str = ""            # "none", "subtle" or "full", then the mood/genre and where it should enter and leave


class ChildDraft(BaseModel):
    title: str
    goal: str
    seconds: float = 6
    kind: Literal["clip", "goal"] = "clip"


class Decomposition(BaseModel):
    children: list[ChildDraft]
    note: str = ""


class ShotActor(BaseModel):
    actor_name: str
    clothing: str = ""
    behaviour: str = ""


class Line(BaseModel):
    speaker_name: str
    text: str
    emotion: str = ""


class SplitPart(BaseModel):
    title: str
    goal: str = ""
    seconds: float = 4
    shot_type: str = "other"
    motion: str = ""                  # face | body | scene
    visual: str = ""
    action_beats: list[str] = Field(default_factory=list)
    dialogue: list[Line] = Field(default_factory=list)
    narration: str = ""
    sound_notes: str = ""
    start_state: str = ""
    end_state: str = ""


class ClipSplit(BaseModel):
    parts: list[SplitPart]
    note: str = ""


class ClipScriptDraft(BaseModel):
    shot_type: str = "other"
    visual: str
    action_beats: list[str] = Field(default_factory=list)
    camera: str = ""
    actors_in_shot: list[ShotActor] = Field(default_factory=list)
    dialogue: list[Line] = Field(default_factory=list)
    narration: str = ""
    on_camera_speech: bool = False
    sound_notes: str = ""
    motion: str = ""                  # face | body | scene: what must move in this clip
    start_state: str = ""
    end_state: str = ""
    negative: str = ""
    continues_from_previous: bool = False
    same_location_as_previous: bool = False
    change_summary: str = ""


class GoalRevision(BaseModel):
    title: str
    goal: str
    seconds: float = 0
    change_summary: str = ""


class DepDraft(BaseModel):
    from_number: str
    to_number: str
    type: Literal["continues_from", "same_location", "actor_state", "audio_carry", "reference"]
    note: str = ""


class DepList(BaseModel):
    dependencies: list[DepDraft] = Field(default_factory=list)


class PhotoQuery(BaseModel):
    query: str


class PhotoChoice(BaseModel):
    choice: int = 1        # 1-based; 0 = none acceptable
    reason: str = ""


class Explained(BaseModel):
    answer: str


class Op(BaseModel):
    op: Literal["set_title", "set_goal", "set_seconds", "set_script", "add_child", "remove",
                "set_actor", "set_style", "generate", "regenerate_scripts"]
    target: str = ""          # node number like "1.2", actor name, or "project"
    field: str = ""
    value: str = ""


class CommandPlan(BaseModel):
    summary: str
    ops: list[Op] = Field(default_factory=list)


class IssueDraft(BaseModel):
    check: str
    text: str
    at_s: Optional[float] = None
    severity: Literal["info", "minor", "major"] = "minor"


class Scores(BaseModel):
    """1-5 each. 0 means "cannot be checked from the evidence given" (never guess a high score)."""
    goal: int = 3
    script: int = 3
    actors: int = 3
    behaviour: int = 3
    realism: int = 3          # photoreal stills: skin, eyes, hands, fur/hair, no AI artifacts
    motion: int = 0           # real, natural, physically plausible movement (not a slideshow / zoom)
    consistency: int = 0      # same identity, clothing, lighting, background across frames (no morphing)
    fidelity: int = 0         # sharp, no blur / banding / compression blocks
    audio: int = 0            # voice natural, clear, right level, matches the mouth
    continuity: int = 3
    timing: int = 3
    lipsync: int = 3


class ReviewDraft(BaseModel):
    verdict: Literal["meets_goal", "minor_issues", "does_not_meet_goal"]
    scores: Scores = Field(default_factory=Scores)
    issues: list[IssueDraft] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str = ""


# =========================================================== prompt templates
def template(name: str) -> str:
    return resources.files("video_generator.prompts").joinpath(f"{name}.md").read_text()


def render(name: str, **values) -> str:
    text = template(name)
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


SYSTEM = None


def system_prompt() -> str:
    global SYSTEM
    if SYSTEM is None:
        SYSTEM = template("system")
    return SYSTEM


# =========================================================== brain
class Brain:
    def __init__(self, reg: Registry):
        self.reg = reg
        self.last_usage = Usage()

    async def ask(self, task: str, prompt: str, schema: Type[BaseModel], meta: dict,
                  images: Optional[list[Path]] = None, video: Optional[Path] = None) -> BaseModel:
        errors = []
        for name in self.reg.llm_fallback_order(task):
            plugin = self.reg.plugin(name)
            model = self.reg.config.llm.models.get(name, "")
            try:
                result, usage = await plugin.generate_json(system=system_prompt(), user=prompt, schema=schema,
                                                           model=model, images=images, video=video, meta={"task": task, **meta})
                usage.cost_usd = self._cost(name, usage)
                usage.raw["plugin"] = name
                usage.raw["model"] = model
                self.last_usage = usage
                return result
            except PluginError as exc:
                errors.append(f"{name}: {exc}")
                continue
        raise PluginError("AI brain failed: " + " | ".join(errors))

    def _cost(self, plugin: str, usage: Usage) -> float:
        for e in self.reg.catalog.for_job("llm"):
            if e.plugin == plugin:
                return usage.input_tokens / 1e6 * e.price.usd_in + usage.output_tokens / 1e6 * e.price.usd_out
        return 0.0

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _context_block(project: Project, node_id: str) -> str:
        return summarize_for_llm(effective_context(project, node_id))

    @staticmethod
    def _actor_list(project: Project, node_id: Optional[str] = None) -> str:
        items = effective_context(project, node_id) if node_id else []
        actors = [e.item for e in items] if node_id else [c for c in project.context]
        lines = []
        for a in actors:
            if a.type == ContextType.actor and a.actor:
                lines.append(f"- {a.title} (id {a.id}, {a.actor.kind}): {a.actor.description}; clothing: {a.actor.clothing}; "
                             f"behaviour: {a.actor.behaviour}; voice: {a.actor.voice_description}"
                             + (f" [{', '.join(x for x in (a.actor.voice_gender, a.actor.voice_age, a.actor.voice_pitch + ' pitch' if a.actor.voice_pitch else '', a.actor.voice_pace + ' pace' if a.actor.voice_pace else '', a.actor.voice_accent) if x)}]"
                                if (a.actor.voice_gender or a.actor.voice_age or a.actor.voice_pitch or a.actor.voice_pace or a.actor.voice_accent) else "")
                             + ("; has photos" if a.files else "") + ("; has voice sample" if a.actor.voice_sample else ""))
        return "\n".join(lines) or "(no actors yet)"

    # ------------------------------------------------------------- tasks
    async def draft_project(self, project: Project) -> ProjectDraft:
        prompt = render("draft", goal=project.goal, seconds=project.settings.target_seconds, routes=routes_mod.describe(self.reg),
                        aspect=project.settings.aspect, context=summarize_for_llm(effective_context(project, project.root.id)))
        return await self.ask("draft", prompt, ProjectDraft,
                              {"goal": project.goal, "seconds": project.settings.target_seconds,
                               "context": [c.model_dump() for c in project.context]})

    async def decompose(self, project: Project, node: Node) -> Decomposition:
        nums = numbering(project)
        prompt = render("decompose", outline=outline(project), number=nums.get(node.id, ""), title=node.title, routes=routes_mod.describe(self.reg),
                        goal=node.goal, seconds=node.duration.likely_s or node.target_seconds or 20,
                        context=self._context_block(project, node.id), actors=self._actor_list(project, node.id))
        return await self.ask("decompose", prompt, Decomposition,
                              {"goal": node.goal, "title": node.title,
                               "seconds": node.duration.likely_s or node.target_seconds or 20})

    async def split_clip(self, project: Project, node: Node) -> ClipSplit:
        """Split one clip into consecutive clips that each need only what ONE route can do (the rule comes from the catalogue)."""
        nums = numbering(project)
        sc = node.script
        secs = node.target_seconds or (sc.target_seconds if sc else None) or node.duration.likely_s or 6
        prompt = render("split_clip", outline=outline(project), number=nums.get(node.id, ""), title=node.title, goal=node.goal,
                        seconds=f"{secs:g}", routes=routes_mod.describe(self.reg), actors=self._actor_list(project, node.id),
                        script=sc.model_dump_json(indent=1) if sc else "(none)", shot_types=", ".join(SHOT_TYPES))
        return await self.ask("split_clip", prompt, ClipSplit, {"title": node.title, "goal": node.goal, "seconds": secs,
                                                                  "script": sc.model_dump() if sc else {}})

    async def write_clip_script(self, project: Project, node: Node, feedback: str = "") -> ClipScriptDraft:
        nums = numbering(project)
        prev = _previous_leaf(project, node)
        parents = " > ".join(f"{a.title}: {a.goal}" for a in ancestors(project, node.id) if a.id != project.root.id)
        current = node.script.model_dump_json(indent=1) if node.script else "(none yet)"
        secs = node.target_seconds or (node.script.target_seconds if node.script else None) or node.duration.likely_s or 6
        prompt = render("clip_script", outline=outline(project), number=nums.get(node.id, ""), title=node.title, routes=routes_mod.describe(self.reg),
                        goal=node.goal, parents=parents or "(top level)", seconds=f"{secs:g}", max_beats=max(1, round(secs / 2.5)),
                        context=self._context_block(project, node.id), actors=self._actor_list(project, node.id),
                        previous=(f"{prev.title}: {prev.script.visual if prev.script else prev.goal}"
                                  + (f" | IT ENDS: {prev.script.end_state}" if prev and prev.script and prev.script.end_state else "")
                                  if prev else "(first clip)"),
                        current=current, feedback=feedback or "(none)", shot_types=", ".join(SHOT_TYPES),
                        style=json.dumps(_style(project, node)))
        return await self.ask("write_clip_script", prompt, ClipScriptDraft,
                              {"goal": node.goal, "title": node.title, "seconds": secs,
                               "actors": [a.model_dump() for a in project.context if a.type == ContextType.actor],
                               "feedback": feedback, "current": node.script.model_dump() if node.script else None,
                               "has_previous": prev is not None,
                               "previous_end_state": (prev.script.end_state if prev and prev.script else "")})

    async def revise_goal(self, project: Project, node: Node, instruction: str) -> GoalRevision:
        prompt = render("revise_goal", outline=outline(project), title=node.title, goal=node.goal,
                        seconds=node.duration.likely_s, instruction=instruction)
        return await self.ask("revise", prompt, GoalRevision,
                              {"title": node.title, "goal": node.goal, "instruction": instruction,
                               "seconds": node.target_seconds or node.duration.likely_s})

    async def suggest_dependencies(self, project: Project) -> DepList:
        lines = []
        nums = numbering(project)
        for n, _ in walk(project.root):
            if n.is_leaf:
                vis = n.script.visual if n.script else n.goal
                lines.append(f"{nums[n.id]} {n.title}: {vis}")
        prompt = render("dependencies", outline=outline(project), clips="\n".join(lines))
        return await self.ask("suggest_dependencies", prompt, DepList,
                              {"clips": [{"number": nums[n.id], "title": n.title,
                                          "visual": (n.script.visual if n.script else n.goal)}
                                         for n, _ in walk(project.root) if n.is_leaf]})

    async def photo_query(self, title: str, description: str) -> PhotoQuery:
        prompt = render("photo_query", title=title, description=description or title)
        return await self.ask("photo_query", prompt, PhotoQuery, {"title": title, "description": description})

    async def pick_photo(self, project: Project, description: str, titles: list[str], images: list[Path]) -> PhotoChoice:
        prompt = render("pick_photo", description=description, style=json.dumps({k: v for k, v in project.style.model_dump().items() if v}),
                        candidates="\n".join(f"{i}: {t}" for i, t in enumerate(titles, start=1)))
        return await self.ask("pick_photo", prompt, PhotoChoice, {"titles": titles}, images=images)

    async def explain(self, question: str, facts: str) -> Explained:
        prompt = render("explain", question=question, facts=facts)
        return await self.ask("explain", prompt, Explained, {"question": question, "facts": facts})

    async def command(self, project: Project, instruction: str, focus: Optional[Node] = None) -> CommandPlan:
        nums = numbering(project)
        prompt = render("command", outline=outline(project), actors=self._actor_list(project),
                        instruction=instruction, focus=(f"{nums.get(focus.id, '')} {focus.title}" if focus else "(whole project)"))
        return await self.ask("command", prompt, CommandPlan, {"instruction": instruction,
                                                                "focus": nums.get(focus.id, "") if focus else "",
                                                                "numbers": {v: k for k, v in nums.items()}})

    async def review_take(self, project: Project, node: Node, frames: list[tuple[float, Path]],
                          transcript: str, measurements: dict, take_seconds: float,
                          video: Optional[Path] = None, history: str = "", pair_times: Optional[list[float]] = None) -> ReviewDraft:
        nums = numbering(project)
        script = node.script.model_dump_json(indent=1) if node.script else "{}"
        prompt = render("review", number=nums.get(node.id, ""), title=node.title, goal=node.goal,
                        parents=" > ".join(a.goal for a in ancestors(project, node.id) if a.id != project.root.id),
                        script=script, context=self._context_block(project, node.id),
                        transcript=transcript or "(no speech detected)", measurements=json.dumps(measurements),
                        target=node.duration.likely_s, actual=take_seconds,
                        frame_times=_frame_description(frames, pair_times or []), history=history or "(first review)")
        return await self.ask("review", prompt, ReviewDraft,
                              {"script": node.script.model_dump() if node.script else {}, "transcript": transcript,
                               "measurements": measurements, "target": node.duration.likely_s,
                               "actual": take_seconds},
                              images=[p for _, p in frames], video=video)

    async def review_node(self, project: Project, node: Node, summaries: str, actual_seconds: float,
                          frames: list[tuple[float, Path]], boundaries: str = "", boundary_images: Optional[list[Path]] = None) -> ReviewDraft:
        prompt = render("node_review", title=node.title or "Whole video", goal=node.goal or project.goal,
                        summaries=summaries, target=node.target_seconds or node.duration.likely_s,
                        actual=actual_seconds, context=self._context_block(project, node.id),
                        boundaries=boundaries or "(none: these clips are separate scenes)")
        return await self.ask("review", prompt, ReviewDraft,
                              {"node_review": True, "target": node.target_seconds or node.duration.likely_s,
                               "actual": actual_seconds, "summaries": summaries, "boundaries": boundaries},
                              images=[p for _, p in frames] + list(boundary_images or []))


def _frame_description(frames: list[tuple[float, Path]], pair_times: list[float]) -> str:
    singles = frames[: len(frames) - len(pair_times)] if pair_times else frames
    pairs = frames[len(frames) - len(pair_times):] if pair_times else []
    text = "single frames at " + ", ".join(f"{t:.1f}s" for t, _ in singles)
    if pairs:
        text += ("; then ADJACENT PAIRS (images come two by two, 0.25 s apart; compare the two images of each pair with each other) at "
                 + ", ".join(f"{pairs[i][0]:.1f}s→{pairs[i + 1][0]:.1f}s" for i in range(0, len(pairs) - 1, 2)))
    return text


# =========================================================== conversions
def _style(project: Project, node: Node) -> dict:
    from .tree import effective_style
    return effective_style(project, node.id)


def _previous_leaf(project: Project, node: Node) -> Optional[Node]:
    prev = None
    for n, _ in walk(project.root):
        if n.id == node.id:
            return prev
        if n.is_leaf:
            prev = n
    return None


def draft_to_script(project: Project, d: ClipScriptDraft) -> ClipScript:
    by_name = {}
    for c in project.context:
        if c.type == ContextType.actor:
            by_name[c.title.lower()] = c.id
            by_name[c.id] = c.id

    def resolve(name: str) -> str:
        if not name:
            return "narrator"
        key = name.lower().strip()
        if key in ("narrator", "voice over", "voiceover", "vo"):
            return "narrator"
        if key in by_name:
            return by_name[key]
        for n, cid in by_name.items():
            if key and (key in n or n in key):
                return cid
        return name

    shot = d.shot_type if d.shot_type in SHOT_TYPES else "other"
    return ClipScript(
        shot_type=ShotType(shot), visual=d.visual, action_beats=d.action_beats, camera=d.camera,
        actors_in_shot=[ActorInShot(actor_id=resolve(a.actor_name), clothing=a.clothing, behaviour=a.behaviour)
                        for a in d.actors_in_shot],
        dialogue=[DialogueLine(speaker=resolve(l.speaker_name), text=l.text, emotion=l.emotion) for l in d.dialogue],
        narration=d.narration, on_camera_speech=d.on_camera_speech and bool(d.dialogue),
        sound_notes=d.sound_notes, motion=d.motion if d.motion in ("face", "body", "scene") else "",
        start_state=d.start_state, end_state=d.end_state, negative=d.negative)
